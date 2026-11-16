"""Auto-detect a remote LLM server's capabilities and print the exact AIMW config.

Usage:
    python scripts/probe_llm_server.py https://<live-tunnel>.trycloudflare.com

It figures out, with zero prior knowledge of the server:
  * Reachability (is the tunnel actually up?)
  * API flavor: OpenAI-compatible (/v1/...) vs Ollama (/api/...) vs unknown
  * The correct base_url to use (root, /v1, etc.)
  * Available model name(s)
  * Whether auth is required (401/403 without a key)
  * Whether the model supports VISION (image input) — the capability that lets
    us skip slow local OCR and analyze frames remotely in seconds
  * A round-trip latency sample for one tiny chat completion

Then it prints the exact env vars to paste into .env.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from typing import Any

import httpx

# A 1x1 red PNG — smallest possible image to test vision intake without bandwidth.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _try(method: str, url: str, **kw: Any) -> httpx.Response | None:
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as c:
            return c.request(method, url, **kw)
    except Exception as exc:  # noqa: BLE001
        print(f"    ! {method} {url} -> {type(exc).__name__}: {str(exc)[:80]}")
        return None


def _norm(base: str) -> str:
    return base.rstrip("/")


def probe(base: str) -> None:
    base = _norm(base)
    print(f"\n=== Probing {base} ===\n")

    # 1. Reachability ---------------------------------------------------------
    root = _try("GET", base + "/")
    if root is None:
        print("UNREACHABLE. The tunnel is down or the URL is wrong.")
        print("On the server host, restart cloudflared and use the NEW url it prints.")
        return
    print(f"[reachable] GET / -> {root.status_code}")

    # 2. Discover API flavor + models ----------------------------------------
    openai_models: list[str] = []
    ollama_models: list[str] = []
    base_url_for_chat = base

    for candidate in (base, base + "/v1"):
        r = _try("GET", candidate + "/models")
        if r is not None and r.status_code == 200:
            try:
                data = r.json().get("data", [])
                openai_models = [m.get("id") for m in data if m.get("id")]
                base_url_for_chat = candidate
                print(f"[openai] {candidate}/models -> {openai_models}")
                break
            except Exception:  # noqa: BLE001
                pass

    r = _try("GET", base + "/api/tags")
    if r is not None and r.status_code == 200:
        try:
            ollama_models = [m.get("name") for m in r.json().get("models", [])]
            print(f"[ollama] {base}/api/tags -> {ollama_models}")
        except Exception:  # noqa: BLE001
            pass

    models = openai_models or ollama_models
    if not models:
        print("\nNo model list found via /v1/models or /api/tags.")
        print("Server may use a custom API — paste me the GET / body or its docs.")
        # still try a blind chat below using 'default'
        models = ["default"]

    model = models[0]
    chat_url = base_url_for_chat + "/chat/completions"

    # 3. Auth probe -----------------------------------------------------------
    auth_required = False
    test_payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word OK."}],
        "max_tokens": 8,
        "temperature": 0,
    }
    t0 = time.perf_counter()
    r = _try("POST", chat_url, json=test_payload, headers={"Content-Type": "application/json"})
    dt_ms = (time.perf_counter() - t0) * 1000
    if r is not None and r.status_code in (401, 403):
        auth_required = True
        print(f"[auth] {chat_url} -> {r.status_code} (API KEY REQUIRED)")
    elif r is not None and r.status_code == 200:
        try:
            content = r.json()["choices"][0]["message"]["content"]
            print(f"[chat OK] no-auth text completion in {dt_ms:.0f}ms -> {content!r}")
        except Exception:  # noqa: BLE001
            print(f"[chat] 200 but unexpected body: {r.text[:200]}")
    elif r is not None:
        print(f"[chat] {chat_url} -> {r.status_code}: {r.text[:200]}")

    # 4. Vision probe (the big one) ------------------------------------------
    vision = False
    if not auth_required:
        vision_payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What color is this image? One word."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{_TINY_PNG_B64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 16,
            "temperature": 0,
        }
        tv = time.perf_counter()
        rv = _try("POST", chat_url, json=vision_payload,
                  headers={"Content-Type": "application/json"})
        vdt = (time.perf_counter() - tv) * 1000
        if rv is not None and rv.status_code == 200:
            try:
                ans = rv.json()["choices"][0]["message"]["content"]
                vision = True
                print(f"[VISION OK] image input accepted in {vdt:.0f}ms -> {ans!r}")
            except Exception:  # noqa: BLE001
                print(f"[vision] 200 but unexpected body: {rv.text[:200]}")
        elif rv is not None:
            print(f"[vision] not supported ({rv.status_code}): {rv.text[:160]}")

    # 5. Verdict + config -----------------------------------------------------
    print("\n" + "=" * 60)
    print("DETECTED CONFIG — add these to .env:")
    print("=" * 60)
    print("AIMW_LLM_PROVIDER=local")
    print(f"AIMW_LLM_BASE_URL={base_url_for_chat}")
    print(f"AIMW_LLM_MODEL={model}")
    print(f"AIMW_LLM_REQUIRE_AUTH={'true' if auth_required else 'false'}")
    if auth_required:
        print("AIMW_LLM_API_KEY=<paste-your-key-here>")
    print("AIMW_LLM_DAILY_TOKEN_CAP=100000000   # effectively unlimited for on-prem")
    print("=" * 60)
    print(f"Vision (image input) supported: {'YES' if vision else 'NO'}")
    if vision:
        print(" -> We can send video frames directly and SKIP local OCR. Big speedup.")
    else:
        print(" -> Text-only. Speeds up the judge step; local extraction still runs.")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/probe_llm_server.py https://<live-url>")
        sys.exit(1)
    probe(sys.argv[1])
