"""Candidate discovery — turn an admin search term into video URLs.

The collector does NOT download anything here. It uses yt-dlp's flat
extraction (``extract_flat``) against a ``ytsearchN:`` query to pull a page
of result metadata cheaply, then normalises each entry to a canonical
``watch?v=`` URL. The heavy work (download → transcribe → OCR → score) only
happens later, once :mod:`aimw.workers.enqueue` hands each URL to the
pipeline worker.

Keeping discovery and analysis separate means the crawl is fast and the
admin's Start click feels instant: one search per query per tick, a handful
of URLs enqueued, the worker drains them at its own pace.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from aimw.collection.prescreen import score_text
from aimw.core.logging import get_logger

log = get_logger("aimw.collection.collector")

_WATCH = "https://www.youtube.com/watch?v="


@dataclass(frozen=True)
class _Candidate:
    url: str
    score: int
    order: int


def _normalize_entry(entry: dict[str, Any]) -> str | None:
    """Return a canonical YouTube watch URL for one flat-search entry.

    yt-dlp's flat entries vary by version: some carry a full ``url``, others
    only an ``id`` (the 11-char video id) or a ``url`` that is just the id.
    We resolve all three to ``https://www.youtube.com/watch?v=<id>``.
    """
    url = entry.get("url") or ""
    if url.startswith("http"):
        # Already a full URL — keep it only if it points at a real video.
        host = (urlsplit(url).hostname or "").lower()
        if host.endswith("youtube.com") or host == "youtu.be":
            return url
        return None
    vid = entry.get("id") or url
    if vid and isinstance(vid, str) and len(vid) >= 6:
        return f"{_WATCH}{vid}"
    return None


def _entry_text(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "description", "channel", "uploader"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    tags = entry.get("tags")
    if isinstance(tags, list):
        parts.extend(str(tag) for tag in tags if tag)
    return " ".join(parts)


def search_candidates(query: str, limit: int = 5) -> list[str]:
    """Return up to ``limit`` candidate watch URLs for ``query``.

    Errors (network blip, yt-dlp extractor change) are swallowed and logged:
    a failed search for one term must never take the whole collector down.
    """
    import yt_dlp  # lazy: keeps module import cheap where yt-dlp isn't needed

    limit = max(1, min(limit, 25))
    fetch_limit = min(50, max(limit * 4, limit))
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{fetch_limit}:{query}", download=False)
    except Exception as exc:
        log.warning("collector_search_failed", query=query, error=str(exc))
        return []

    entries = (info or {}).get("entries") or []
    ranked: list[_Candidate] = []
    seen: set[str] = set()
    for order, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        url = _normalize_entry(entry)
        if not url or url in seen:
            continue
        text = _entry_text(entry)
        if text.strip():
            screen = score_text(text, query=query)
            if screen.score <= -3:
                continue
            score = screen.score
        else:
            score = 1
        if score < 1:
            continue
        seen.add(url)
        ranked.append(_Candidate(url=url, score=score, order=order))

    ranked.sort(key=lambda candidate: (-candidate.score, candidate.order))
    urls = [candidate.url for candidate in ranked[:limit]]
    log.info("collector_search", query=query, found=len(urls), scanned=len(entries))
    return urls


__all__ = ["search_candidates"]
