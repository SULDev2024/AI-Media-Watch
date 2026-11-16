"""Phase 15.6A — Referee activation verification script.

Checks:
  1. AIMW_GROQ_API_KEY is present in settings / .env
  2. The Groq API endpoint is reachable and returns a valid model response
  3. reasoning.referee.run() returns a non-fallback result (no status_note)

Output (on success):
  REFEREE_STATUS=ACTIVE
  MODEL=<name>
  TOKENS=<count>
  FALLBACK=false

Exits with code 1 and REFEREE_STATUS=INACTIVE if any check fails.
"""
from __future__ import annotations

import asyncio
import json
import sys


def _print(key: str, value: object) -> None:
    print(f"{key}={value}", flush=True)


async def _check_groq_key() -> str:
    """Return the key value or raise RuntimeError."""
    from aimw.core.config import get_settings

    s = get_settings()
    if s.groq_api_key is None or not s.groq_api_key.get_secret_value():
        raise RuntimeError("AIMW_GROQ_API_KEY is not set in environment or .env")
    key = s.groq_api_key.get_secret_value()
    _print("KEY_PRESENT", "true")
    return key


async def _check_groq_endpoint(api_key: str) -> tuple[str, int]:
    """Hit the Groq models endpoint to confirm reachability.

    Returns (model_id, estimated_cap_remaining).
    """
    import httpx

    from aimw.core.config import get_settings

    s = get_settings()
    url = f"{s.groq_base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Groq endpoint unreachable: {exc}") from exc

    models = [m["id"] for m in body.get("data", []) if isinstance(m, dict)]
    chosen = s.groq_model if s.groq_model in models else (models[0] if models else s.groq_model)
    _print("ENDPOINT_REACHABLE", "true")
    _print("AVAILABLE_MODELS", len(models))
    return chosen, s.groq_daily_token_cap


async def _check_minimal_completion(api_key: str, model: str) -> int:
    """Send a minimal chat completion to verify the key grants inference.

    Returns the token count used.
    """
    import httpx

    from aimw.core.config import get_settings

    s = get_settings()
    url = f"{s.groq_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": 'Reply with {"ok":true}'}],
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Minimal completion failed: {exc}") from exc

    usage = body.get("usage", {})
    tokens = int(usage.get("total_tokens", 0))
    content = body["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if not parsed.get("ok"):
        raise RuntimeError(f"Unexpected completion response: {content!r}")
    _print("COMPLETION_OK", "true")
    return tokens


async def _check_referee_nonfallback() -> None:
    """Run referee with a stub and assert status_note is None."""
    import datetime as dt

    from aimw.confidence.models import BriefShape
    from aimw.core.schema.evidence import EvidencePackage, EvidencePiece, ExtractedEntities
    from aimw.reasoning.referee import run as referee_run
    from aimw.reasoning.stub import ReasoningStub

    pkg = EvidencePackage(
        report_id="rpt-verify-0000000000000001",
        video_id="verify-referee-test",
        platform="test",
        url="file:///verify",
        collected_at=dt.datetime.now(dt.UTC),
        processed_at=dt.datetime.now(dt.UTC),
        evidence=[
            EvidencePiece(
                source="transcript",
                polarity="incriminating",
                strength="strong",
                indicator_type="guaranteed_return",
                raw_value="guaranteed 5% daily return",
                regulation_ref="art_217_kz",
            ),
            EvidencePiece(
                source="description",
                polarity="incriminating",
                strength="medium",
                indicator_type="pyramid_recruit",
                raw_value="invite friends earn bonuses",
                regulation_ref="art_217_kz",
            ),
        ],
        entities=ExtractedEntities(),
    )
    stub = ReasoningStub()
    result = await referee_run(pkg, briefs_provider=stub)

    is_fallback = result.status_note == "token_budget_exhausted"
    _print("REFEREE_FALLBACK", str(is_fallback).lower())

    if is_fallback:
        raise RuntimeError("Referee used fallback path — stub activation failed")

    has_confidence = result.confidence is not None
    has_briefs = result.prosecutor is not None and result.defense is not None
    if not has_confidence or not has_briefs:
        raise RuntimeError("Referee returned incomplete result (no confidence or briefs)")

    _print("CONFIDENCE", result.confidence.confidence)  # type: ignore[union-attr]
    _print("ACTION", result.action)


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    print("=== AI Media Watch — Referee Activation Verification ===", flush=True)
    print("", flush=True)

    try:
        # Step 1: key present
        api_key = await _check_groq_key()

        # Step 2: endpoint reachable
        model, _cap = await _check_groq_endpoint(api_key)
        _print("MODEL", model)

        # Step 3: minimal completion (burns a few tokens)
        tokens = await _check_minimal_completion(api_key, model)
        _print("TOKENS", tokens)

        # Step 4: referee non-fallback (uses stub, no Groq call)
        await _check_referee_nonfallback()

        print("", flush=True)
        _print("REFEREE_STATUS", "ACTIVE")

    except Exception as exc:
        print("", flush=True)
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        _print("REFEREE_STATUS", "INACTIVE")
        print(
            "\nTo activate the referee:\n"
            "  1. Add to .env:  AIMW_GROQ_API_KEY=gsk_...\n"
            "  2. Re-run:       python scripts/verify_referee.py",
            flush=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
