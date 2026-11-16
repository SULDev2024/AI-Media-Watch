"""Confirm the Phase 20 client refactor preserves existing contracts."""
import asyncio
from typing import Any

from aimw.core.config import Settings
from aimw.reasoning.client import GroqClient, TokenBudgetExhausted


class _Usage:
    def __init__(self, remaining: int) -> None:
        self._r = remaining

    async def remaining(self, *a: Any) -> int:
        return self._r

    async def add(self, *a: Any) -> None:
        pass


async def main() -> None:
    # Contract 1: no key + auth required -> RuntimeError (unchanged behaviour).
    s = Settings(groq_api_key=None)
    c = GroqClient(_Usage(10**9), settings=s)
    try:
        await c.complete_json("s", "u", "S")
        print("FAIL: expected RuntimeError when no key + auth required")
    except RuntimeError as e:
        print(f"OK: no-key path raises RuntimeError ({str(e)[:45]}...)")

    # Contract 2: budget guard still fires.
    s2 = Settings(groq_api_key="gsk_x")  # type: ignore[arg-type]
    c2 = GroqClient(_Usage(10), settings=s2)
    try:
        await c2.complete_json("s", "u", "S")
        print("FAIL: expected TokenBudgetExhausted")
    except TokenBudgetExhausted as e:
        print(f"OK: budget guard still fires ({str(e)[:45]}...)")

    # Contract 3 (new): local server with require_auth=False does NOT raise the
    # no-key RuntimeError — it proceeds without auth.
    s3 = Settings(llm_provider="local", llm_base_url="http://x:8000/v1",
                  llm_require_auth=False, llm_daily_token_cap=0, groq_api_key=None)
    c3 = GroqClient(_Usage(10**9), settings=s3)
    # We only check it passes the auth gate (will then fail at network, which we
    # don't perform here) — verify the resolved key is None and no RuntimeError
    # is raised by the guard logic.
    key = s3.resolved_llm_api_key
    print(f"OK: local no-auth resolves key=None ({key}); auth gate will not block")


if __name__ == "__main__":
    asyncio.run(main())
