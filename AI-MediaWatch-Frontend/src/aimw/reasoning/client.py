"""Groq client with token-budget guard -- Phase 10.

Wraps the Groq OpenAI-compatible API. Key invariants:

* All chat completions go through ``complete_json`` with ``temperature=0.1``
  and ``response_format={"type":"json_object"}`` -- deterministic enough that
  re-running the same prompt with the same fixture yields a stable shape.
* Before every call, the daily token usage is checked against
  ``settings.groq_daily_token_cap``. If less than ``2 *
  settings.groq_request_token_budget`` tokens remain (the 90%-used threshold
  per the acceptance criteria), ``TokenBudgetExhausted`` is raised and the
  referee falls back to ``analyst_review`` without calling the network.
* Token counts are estimated with ``tiktoken cl100k_base`` (the OpenAI base
  encoding; Groq uses an OpenAI-compatible tokenizer for ``openai/gpt-oss-*``).
* Usage is added to ``daily_token_usage`` after the response is received,
  using the actual ``usage`` block from Groq when available and falling back
  to the local estimate otherwise.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Any, Protocol

import httpx
import tiktoken

_LOG = logging.getLogger("aimw.reasoning.client")

from aimw.core.config import Settings, get_settings


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header value (delta-seconds) into float seconds.

    Groq returns a numeric seconds value (often fractional). HTTP-date form is
    not used by Groq, so we only handle the numeric form and return None for
    anything unparseable.
    """
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


class TokenBudgetExhausted(RuntimeError):
    """Raised when the daily Groq token cap is too close to call again."""


class UsageTracker(Protocol):
    """Minimal usage-repository interface the reasoning layer depends on.

    The aimw.db ``UsageRepository`` satisfies this Protocol structurally;
    declaring it here keeps ``aimw.reasoning`` free of any ``aimw.db`` import
    (import-linter contract ``reasoning-no-direct-writes``). Tests pass an
    in-memory fake implementing the same two methods.
    """

    async def remaining(self, date: dt.date, model: str, daily_cap: int) -> int: ...
    async def add(self, date: dt.date, model: str, tokens: int) -> None: ...


_ENCODING = tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    """Approximate token count for *text* using cl100k_base."""
    return len(_ENCODING.encode(text))


# Process-global gate that serialises outbound chat-completion requests. The
# free Groq tier rejects concurrent requests with 429; agents that fan out via
# asyncio.gather would otherwise burst and trigger backoff storms. Serialising
# to one in-flight call avoids the 429s entirely and is dramatically faster than
# parallel-with-backoff. Lazily created on the running loop so it binds to the
# correct event loop in tests and in the API server.
_REQUEST_GATE: "asyncio.Semaphore | None" = None


def _request_gate() -> "asyncio.Semaphore":
    global _REQUEST_GATE
    if _REQUEST_GATE is None:
        _REQUEST_GATE = asyncio.Semaphore(1)
    return _REQUEST_GATE


class GroqClient:
    """Token-budgeted Groq chat-completions client.

    Parameters
    ----------
    usage_tracker:
        Object satisfying the ``UsageTracker`` Protocol -- the production wiring
        passes the ``aimw.db.repositories.usage.UsageRepository``; tests pass a
        fake.
    settings:
        Optional override; defaults to ``get_settings()``.
    http_client:
        Optional injected ``httpx.AsyncClient`` (tests pass a mock transport).
    """

    def __init__(
        self,
        usage_tracker: UsageTracker,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._usage = usage_tracker
        self._settings = settings or get_settings()
        self._http = http_client

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> httpx.Response:
        """POST with bounded retry on 429.

        Free-tier limits are tokens-per-minute (TPM); a burst exhausts the
        bucket and the rest of the minute returns 429. We honour ``Retry-After``
        when present, otherwise a capped linear backoff. The total wait is
        bounded so an interactive request (Scam Check / Investigate) never hangs
        for minutes — it falls through to the deterministic engine instead.
        ``AIMW_LLM_MAX_RETRIES`` / ``AIMW_LLM_MAX_RETRY_WAIT`` override the
        defaults (bulk collection can raise them for TPM patience).
        """
        import os
        max_retries = int(os.environ.get("AIMW_LLM_MAX_RETRIES", "3"))
        max_wait = float(os.environ.get("AIMW_LLM_MAX_RETRY_WAIT", "10"))
        response = await client.post(url, json=payload, headers=headers)
        for _attempt in range(max_retries):
            if response.status_code != 429:
                break
            wait = _parse_retry_after(response.headers.get("retry-after"))
            if wait is None:
                wait = _parse_retry_after(response.headers.get("x-ratelimit-reset-tokens"))
            if wait is None:
                wait = 4.0 * (_attempt + 1)
            wait = min(max(wait, 2.0), max_wait)
            _LOG.warning("rate_limited (429), retrying in %.1fs", wait)
            await asyncio.sleep(wait)
            response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response

    async def _check_budget(self, estimated_in: int, max_out: int) -> None:
        """Raise TokenBudgetExhausted if the daily cap is too close."""
        today = dt.date.today()
        model = self._settings.resolved_llm_model
        cap = self._settings.resolved_llm_daily_token_cap
        remaining = await self._usage.remaining(today, model, cap)
        # Refuse if remaining is below 2 * request budget (~90% used).
        # Spec wording: "remaining < settings.groq_request_token_budget * 2".
        floor = self._settings.groq_request_token_budget * 2
        needed = estimated_in + max_out
        if remaining < max(floor, needed):
            raise TokenBudgetExhausted(
                f"daily_cap={cap}, remaining={remaining}, floor={floor}, needed={needed}"
            )

    async def complete_json(
        self,
        system: str,
        user: str,
        schema_name: str,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Send a JSON-mode chat completion and return the parsed dict.

        Provider-agnostic (Phase 20): reads the *resolved* LLM config so the
        same code path serves Groq cloud or a self-hosted OpenAI-compatible
        server (vLLM/Ollama/TGI). For local servers with ``llm_require_auth``
        false, no Authorization header is sent.

        Raises
        ------
        TokenBudgetExhausted
            If the daily token cap leaves insufficient headroom.
        httpx.HTTPError
            For network/HTTP errors -- the caller decides whether to retry.
        ValueError
            If the response body is not valid JSON.
        """
        settings = self._settings
        api_key = settings.resolved_llm_api_key
        if api_key is None and settings.llm_require_auth:
            raise RuntimeError(
                "no LLM api key resolved and auth required -- set AIMW_LLM_API_KEY / "
                "AIMW_GROQ_API_KEY, or AIMW_LLM_REQUIRE_AUTH=false for a local server, "
                "or use ReasoningStub for offline runs"
            )

        model = settings.resolved_llm_model
        full_system = (
            f"{system}\n\n"
            f"Return ONLY a JSON object matching the schema named '{schema_name}'. "
            "No prose outside JSON."
        )
        estimated_in = _count_tokens(full_system) + _count_tokens(user)
        await self._check_budget(estimated_in, max_tokens)

        payload: dict[str, Any] = {
            "model": model,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": full_system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key.get_secret_value()}"
        url = f"{settings.resolved_llm_base_url}/chat/completions"

        own_client = self._http is None
        client = self._http or httpx.AsyncClient(timeout=settings.llm_request_timeout_s)
        try:
            # Serialise outbound calls through the process gate so fan-out agents
            # don't burst into the free-tier concurrency limit and trigger 429s.
            async with _request_gate():
                response = await self._post_with_retry(client, url, payload, headers)
            body: dict[str, Any] = response.json()
        finally:
            if own_client:
                await client.aclose()

        usage = body.get("usage", {})
        tokens_used = int(usage.get("total_tokens", estimated_in + max_tokens))
        await self._usage.add(dt.date.today(), model, tokens_used)

        content = body["choices"][0]["message"]["content"]
        parsed: dict[str, Any] = json.loads(content)
        # Some models (e.g. llama3) wrap the response in the schema name key:
        # {"FraudVerdict": {"intent": ...}} instead of {"intent": ...}.
        # Unwrap it so callers always get the flat dict.
        if schema_name in parsed and isinstance(parsed[schema_name], dict) and len(parsed) == 1:
            parsed = parsed[schema_name]
        return parsed

    async def complete_vision(
        self,
        system: str,
        content: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> str:
        """Multimodal (text + image) chat completion — returns raw text.

        Used by the vision extraction pipeline to send sampled video frames
        to a multimodal model (qwen2.5vl, llava) for OCR + visual analysis.
        No JSON mode — vision models return free text.
        """
        settings = self._settings
        api_key = settings.resolved_llm_api_key
        model = settings.resolved_llm_model

        payload: dict[str, Any] = {
            "model": model,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key.get_secret_value()}"
        url = f"{settings.resolved_llm_base_url}/chat/completions"

        own_client = self._http is None
        client = self._http or httpx.AsyncClient(timeout=max(settings.llm_request_timeout_s, 180.0))
        try:
            async with _request_gate():
                response = await self._post_with_retry(client, url, payload, headers)
            body: dict[str, Any] = response.json()
        finally:
            if own_client:
                await client.aclose()

        usage = body.get("usage", {})
        tokens_used = int(usage.get("total_tokens", 0))
        if tokens_used:
            await self._usage.add(dt.date.today(), model, tokens_used)

        return body["choices"][0]["message"]["content"]


class ChatClient(Protocol):
    """Structural type for any JSON-mode chat client the reasoning layer uses.

    Both the cloud (Groq) and self-hosted (vLLM/Ollama/TGI) paths are the same
    concrete class today (``GroqClient`` is provider-agnostic after Phase 20),
    but callers should type against this Protocol so a future bespoke client
    (e.g. a gRPC local backend) drops in without touching judge/briefs.
    """

    async def complete_json(
        self, system: str, user: str, schema_name: str, max_tokens: int = ...
    ) -> dict[str, Any]: ...


def build_chat_client(
    usage_tracker: UsageTracker,
    settings: Settings | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> GroqClient:
    """Construct the configured chat client (cloud Groq or sovereign on-prem).

    The returned object speaks the OpenAI-compatible protocol and reads the
    resolved LLM settings, so switching to on-prem inference is purely a config
    change (``AIMW_LLM_PROVIDER`` / ``AIMW_LLM_BASE_URL`` / ``AIMW_LLM_MODEL``).
    Callers in ``aimw.workers``/``aimw.api`` own the usage tracker because the
    reasoning layer may not import ``aimw.db``.
    """
    s = settings or get_settings()
    return GroqClient(usage_tracker, settings=s, http_client=http_client)
