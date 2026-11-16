"""Collector run-state control — a single shared flag in Redis.

The collector is a beat-driven crawler that the admin turns on and off from
the dashboard. Its run-state lives in Redis (not the DB) because:

* Redis is already the broker, shared by the API process (which flips the
  flag) and the worker process (which reads it every tick) — no new table,
  no Alembic migration, no writer-lock contention for a high-frequency poll.
* The flag is operational state, not analytical data; losing it on a flush
  just means the collector defaults to ``stopped`` (fail-safe).

State shape (JSON under key ``aimw:collector``)::

    {
      "status": "running" | "stopped",
      "queries": ["crypto scam", "..."],   # search terms the crawler cycles
      "per_query": 5,                       # candidates pulled per query/tick
      "last_run": "2026-06-18T12:00:00+00:00" | None,
      "last_enqueued": 3,                   # new candidates from the last tick
      "enqueued_total": 42                  # cumulative since last start
    }

Access is synchronous redis-py. The API touches it on rare admin clicks and
the worker once per tick, so a sub-millisecond localhost round-trip on the
event loop is acceptable and keeps both processes on one code path.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
import threading
from typing import Any

import redis

from aimw.core.config import get_settings
from aimw.core.logging import get_logger

log = get_logger("aimw.collection.control")

_KEY = "aimw:collector"
_TICK_LOCK_KEY = "aimw:collector:tick_lock"
_LOCAL_LOCK = threading.RLock()
_LOCAL_TICK_TOKEN: str | None = None


def _state_path():
    return get_settings().resolved_data_dir / "collector-state.json"

# Platforms the admin can target. Only those in SUPPORTED_PLATFORMS have a
# working keyword searcher today (YouTube via yt-dlp). The others are accepted
# and stored so the UI can show intent, but the tick skips them until their
# platform API is wired (see the Telegram bot / channel work).
ALWAYS_SUPPORTED = ("youtube",)
KNOWN_PLATFORMS = ("youtube", "telegram", "instagram", "tiktok")

# Content kinds the admin can choose to collect. The tick only keeps items whose
# kind is selected — e.g. a Telegram channel can be mined for photos only, or
# YouTube (always video) is skipped entirely when "video" is deselected.
CONTENT_TYPES = ("video", "photo", "text")


def _normalise_selection(
    platforms: list[str] | None,
    content_types: list[str] | None,
) -> tuple[list[str], list[str]]:
    """Return a collector selection that can actually enqueue work."""
    chosen = [p for p in (platforms or ["youtube"]) if p in KNOWN_PLATFORMS] or ["youtube"]
    kinds = [t for t in (content_types or list(CONTENT_TYPES)) if t in CONTENT_TYPES]
    if not kinds:
        kinds = list(CONTENT_TYPES)

    # YouTube keyword collection only yields videos. Keep "video" enabled when
    # YouTube is active so the collector cannot look running while doing no work.
    if "youtube" in chosen and "video" not in kinds:
        kinds = ["video", *kinds]

    return chosen, list(dict.fromkeys(kinds))


def supported_platforms() -> tuple[str, ...]:
    """Platforms that have a working keyword searcher right now.

    YouTube is always supported (yt-dlp, no key needed).  Telegram is
    supported when the session credentials are configured.  TikTok and
    Instagram remain URL-only (no keyword search).
    """
    from aimw.collection.telegram_search import is_telegram_configured

    platforms = list(ALWAYS_SUPPORTED)
    if is_telegram_configured():
        platforms.append("telegram")
    return tuple(platforms)

_DEFAULT_STATE: dict[str, Any] = {
    "status": "stopped",
    "queries": [],
    "platforms": ["youtube"],
    "content_types": list(CONTENT_TYPES),
    "region_focus": "global",
    "per_query": 5,
    "last_run": None,
    "last_enqueued": 0,
    "enqueued_total": 0,
}


def _client() -> redis.Redis:
    """Return a decode-on-read Redis client bound to the configured URL."""
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True,
                               socket_connect_timeout=0.5, socket_timeout=0.5)


def get_state() -> dict[str, Any]:
    """Return the current collector state, or the fail-safe default."""
    try:
        if get_settings().eager:
            with _LOCAL_LOCK:
                path = _state_path()
                raw = path.read_text(encoding="utf-8") if path.exists() else None
        else:
            raw = _client().get(_KEY)
    except Exception as exc:  # Redis down → report stopped rather than crash.
        log.warning("collector_state_read_failed", error=str(exc))
        return dict(_DEFAULT_STATE)
    if not raw:
        return dict(_DEFAULT_STATE)
    try:
        state = json.loads(raw)
    except (TypeError, ValueError):
        return dict(_DEFAULT_STATE)
    # Merge over defaults so older/partial payloads gain new keys.
    merged = dict(_DEFAULT_STATE)
    merged.update(state)
    platforms, content_types = _normalise_selection(
        merged.get("platforms"),
        merged.get("content_types"),
    )
    merged["platforms"] = platforms
    merged["content_types"] = content_types
    return merged


def set_state(**changes: Any) -> dict[str, Any]:
    """Apply ``changes`` to the stored state and return the new state.

    Degrades gracefully when Redis is unreachable: the new state is still
    returned (best-effort, in-memory) so the API responds 200 instead of 500.
    Persistence is lost until Redis is back — acceptable for a fail-safe flag.
    """
    if get_settings().eager:
        with _LOCAL_LOCK:
            state = get_state()
            state.update(changes)
            path = _state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            pending = path.with_suffix(".tmp")
            pending.write_text(json.dumps(state), encoding="utf-8")
            pending.replace(path)
            return state
    state = get_state()
    state.update(changes)
    try:
        _client().set(_KEY, json.dumps(state))
    except Exception as exc:  # Redis down → return the computed state anyway.
        log.warning("collector_state_write_failed", error=str(exc))
        raise RuntimeError("Collector storage is unavailable; start Redis or use AIMW_EAGER=1") from exc
    return state


def start(
    queries: list[str],
    per_query: int = 5,
    platforms: list[str] | None = None,
    content_types: list[str] | None = None,
    region_focus: str | None = None,
) -> dict[str, Any]:
    """Switch the collector on with a fresh query set; resets the counter."""
    cleaned = [q.strip() for q in queries if q and q.strip()]
    chosen, kinds = _normalise_selection(platforms, content_types)
    region = (region_focus or "global").strip().lower() or "global"
    return set_state(
        status="running",
        queries=cleaned,
        platforms=chosen,
        content_types=kinds,
        region_focus=region,
        per_query=max(1, min(per_query, 25)),
        enqueued_total=0,
        last_enqueued=0,
    )


def stop() -> dict[str, Any]:
    """Switch the collector off; queries are kept so a restart is one click."""
    return set_state(status="stopped")


def record_run(enqueued: int) -> dict[str, Any]:
    """Stamp ``last_run`` and fold ``enqueued`` into the running totals."""
    state = get_state()
    return set_state(
        last_run=dt.datetime.now(dt.UTC).isoformat(),
        last_enqueued=enqueued,
        enqueued_total=int(state.get("enqueued_total", 0)) + enqueued,
    )


def acquire_tick_lock(ttl_seconds: int = 600) -> str | None:
    """Best-effort distributed lock so only one collector tick runs at a time."""
    token = uuid.uuid4().hex
    if get_settings().eager:
        global _LOCAL_TICK_TOKEN
        with _LOCAL_LOCK:
            if _LOCAL_TICK_TOKEN is not None:
                return None
            _LOCAL_TICK_TOKEN = token
            return token
    try:
        ok = _client().set(_TICK_LOCK_KEY, token, nx=True, ex=max(60, int(ttl_seconds)))
    except Exception as exc:
        log.warning("collector_tick_lock_failed", error=str(exc))
        return None
    return token if ok else None


def release_tick_lock(token: str) -> None:
    """Release the collector tick lock if we still own it."""
    if get_settings().eager:
        global _LOCAL_TICK_TOKEN
        with _LOCAL_LOCK:
            if _LOCAL_TICK_TOKEN == token:
                _LOCAL_TICK_TOKEN = None
        return
    try:
        client = _client()
        if client.get(_TICK_LOCK_KEY) == token:
            client.delete(_TICK_LOCK_KEY)
    except Exception as exc:
        log.warning("collector_tick_unlock_failed", error=str(exc))


def is_running() -> bool:
    """True when the collector flag is set to ``running``."""
    return get_state().get("status") == "running"


__all__ = [
    "acquire_tick_lock",
    "get_state",
    "is_running",
    "record_run",
    "release_tick_lock",
    "set_state",
    "start",
    "stop",
]
