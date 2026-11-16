"""Phase 15.6 — Validate AIMW_GROQ_API_KEY integration.

Run this script once you have set AIMW_GROQ_API_KEY in your .env file.
It sends one minimal request to the Groq API and reports success/failure.

Usage:
    python scripts/validate_groq.py

Exit codes:
    0  Key is valid and API is reachable
    1  Key is missing, invalid, or API returned an error
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def _validate() -> bool:
    """Return True if the Groq key is valid and the API responds."""
    from aimw.core.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    if settings.groq_api_key is None:
        print("[FAIL] AIMW_GROQ_API_KEY is not set.")
        print("       Add it to your .env file:  AIMW_GROQ_API_KEY=gsk_...")
        return False

    key = settings.groq_api_key.get_secret_value()
    masked = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
    print(f"[INFO] Key loaded: {masked}")
    print(f"[INFO] Model: {settings.groq_model}")
    print(f"[INFO] Base URL: {settings.groq_base_url}")
    print("[INFO] Sending test request …")

    import httpx

    payload = {
        "model": settings.groq_model,
        "temperature": 0.0,
        "max_tokens": 16,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return ONLY a JSON object."},
            {"role": "user", "content": 'Return {"ok": true}'},
        ],
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    url = f"{settings.groq_base_url}/chat/completions"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:200]
            print(f"[FAIL] HTTP {exc.response.status_code}: {body}")
            return False
        except Exception as exc:
            print(f"[FAIL] Network error: {exc}")
            return False

    body = resp.json()
    content = body["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if parsed.get("ok") is True:
        tokens = body.get("usage", {}).get("total_tokens", "?")
        print(f"[OK  ] API call succeeded. Response: {parsed}  tokens_used={tokens}")
        print()
        print("Next step: run the full 95-case corpus with LLM active:")
        print("  .venv/Scripts/python.exe -c \"")
        print("    from aimw.cli import app")
        print("    app(['validation', 'run', '--force'])\"")
        return True

    print(f"[FAIL] Unexpected response body: {content[:200]}")
    return False


if __name__ == "__main__":
    ok = asyncio.run(_validate())
    sys.exit(0 if ok else 1)
