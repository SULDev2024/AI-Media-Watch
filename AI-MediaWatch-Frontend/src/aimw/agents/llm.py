"""Graceful LLM wrapper for agents.

Wraps the provider-agnostic :class:`aimw.reasoning.client.GroqClient` (Groq cloud
or sovereign on-prem) so an agent can ``ask`` for a JSON object and ALWAYS get a
usable answer or ``None`` — never an exception that would abort the cell.

If no API key is configured, the daily budget is exhausted, or the network
fails, ``ask`` returns ``None`` and the agent falls back to its deterministic
reasoning. This is what makes the whole 9-agent cell demo-reliable with or
without a live LLM.
"""
from __future__ import annotations

from typing import Any

from aimw.reasoning.client import GroqClient, TokenBudgetExhausted


class AgentLLM:
    """Thin, fail-soft adapter over a JSON-mode chat client."""

    def __init__(self, client: GroqClient | None) -> None:
        self._client = client
        self.available = client is not None
        self.calls = 0
        self.failures = 0

    @classmethod
    def disabled(cls) -> "AgentLLM":
        """An LLM wrapper that always falls back (no client)."""
        return cls(None)

    async def ask(
        self,
        system: str,
        user: str,
        schema_name: str,
        max_tokens: int = 800,
    ) -> dict[str, Any] | None:
        """Return a parsed JSON object, or ``None`` to signal 'use the fallback'.

        Catches budget exhaustion, network errors, and malformed JSON. The agent
        treats ``None`` as "the LLM is unavailable; reason deterministically".
        """
        if self._client is None:
            return None
        self.calls += 1
        try:
            return await self._client.complete_json(
                system=system,
                user=user,
                schema_name=schema_name,
                max_tokens=max_tokens,
            )
        except TokenBudgetExhausted:
            self.failures += 1
            return None
        except Exception:
            # Network/HTTP/JSON errors → fall back rather than crash the cell.
            self.failures += 1
            return None


__all__ = ["AgentLLM"]
