"""Prove the chat client builds correct requests for BOTH backends.

Uses httpx.MockTransport so no live server is needed. Verifies:
  - Cloud (Groq): Authorization header present, Groq URL + model.
  - On-prem (local): NO Authorization header, local URL + model.
Same GroqClient code path for both — only config differs.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from aimw.core.config import Settings
from aimw.reasoning.client import GroqClient, build_chat_client


class _FakeUsage:
    def __init__(self) -> None:
        self.total = 0

    async def remaining(self, *a: Any) -> int:
        return 10**9

    async def add(self, *a: Any) -> None:
        self.total += 0


captured: dict[str, Any] = {}


def _handler(request: httpx.Request) -> httpx.Response:
    captured["url"] = str(request.url)
    captured["auth"] = request.headers.get("Authorization")
    captured["body"] = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps({"ok": True})}}],
            "usage": {"total_tokens": 123},
        },
    )


async def _call(settings: Settings) -> dict[str, Any]:
    transport = httpx.MockTransport(_handler)
    http = httpx.AsyncClient(transport=transport)
    client = build_chat_client(_FakeUsage(), settings=settings, http_client=http)
    out = await client.complete_json("sys", "user", "Schema", max_tokens=64)
    await http.aclose()
    return out


async def main() -> None:
    # Cloud (Groq)
    cloud = Settings(groq_api_key="gsk_test_cloudkey")  # type: ignore[arg-type]
    await _call(cloud)
    print("=== CLOUD (Groq) ===")
    print("  url  :", captured["url"])
    print("  model:", captured["body"]["model"])
    print("  auth :", captured["auth"])
    assert captured["url"].endswith("api.groq.com/openai/v1/chat/completions")
    assert captured["auth"] == "Bearer gsk_test_cloudkey"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    print("  PASS: cloud sends auth header to Groq endpoint")

    # On-prem (local, no auth)
    local = Settings(
        llm_provider="local",
        llm_base_url="http://vllm:8000/v1",
        llm_model="qwen2.5-72b-instruct",
        llm_require_auth=False,
        llm_daily_token_cap=0,
    )
    await _call(local)
    print("\n=== ON-PREM (local vLLM) ===")
    print("  url  :", captured["url"])
    print("  model:", captured["body"]["model"])
    print("  auth :", captured["auth"])
    assert captured["url"] == "http://vllm:8000/v1/chat/completions"
    assert captured["auth"] is None, "local server must NOT receive an Authorization header"
    assert captured["body"]["model"] == "qwen2.5-72b-instruct"
    print("  PASS: on-prem sends NO auth header to local endpoint, citizen data stays local")

    print("\nSOVEREIGN-INFERENCE ABSTRACTION VERIFIED — same client, two backends.")


if __name__ == "__main__":
    asyncio.run(main())
