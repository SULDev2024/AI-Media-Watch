"""Shared enqueue path for a single video URL.

Both the manual ingest route (``POST /api/v1/ingest/url``) and the
beat-driven collector funnel through :func:`enqueue_video_url` so there is
exactly one place that:

1. derives the stable ``video_id`` from the URL,
2. upserts the ``videos`` row,
3. writes the ``ingest_queue`` row, and
4. best-effort kicks ``process_video.delay``.

Input validation (SSRF allow-list, scheme checks) stays in the route — the
collector only ever feeds URLs it built itself from trusted search results,
so it skips that layer deliberately.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
import os
from typing import Any
from urllib.parse import urlsplit, urlencode, parse_qsl

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import update

from aimw.db.models import IngestQueueRow, EvidencePackageRow
from aimw.db.repositories.videos import VideosRepository
from aimw.db.session import writer_lock, get_sessionmaker
from aimw.workers.cancellation import CANCEL_MESSAGE, JobCancelled, reset_job, track_task

_LOG = logging.getLogger("aimw.workers.enqueue")

_EAGER = os.environ.get("AIMW_EAGER") == "1"


async def _eager_pipeline_task(video_id: str) -> None:
    """Non-blocking asyncio task for EAGER mode pipeline execution.

    Running the pipeline as an asyncio.create_task means the HTTP response
    is sent immediately and the frontend can poll for results, instead of
    blocking the uvicorn event loop for the entire pipeline duration.
    """
    from aimw.workers.pipeline import run_pipeline
    from aimw.db.repositories.packages import PackagesRepository

    try:
        # A cancellation can commit before a newly queued task gets CPU time.
        # Respect its durable marker even if no live task existed to cancel.
        if await PackagesRepository(get_sessionmaker()).latest_failure(video_id) == CANCEL_MESSAGE:
            return
        await run_pipeline(video_id)
    except JobCancelled:
        _LOG.info('eager_pipeline_cancelled', extra={'video_id': video_id})
    except Exception:
        _LOG.error(
            "eager_pipeline_failed", extra={"video_id": video_id}, exc_info=True
        )


_TRACKING_PARAMS = frozenset({
    "si", "feature", "pp", "ref",           # YouTube share params
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "msclkid",           # ad-click IDs
})


def _normalize_url(url: str) -> str:
    """Strip tracking-only query params so the same video always gets the same id.

    YouTube ?si= is a per-share tracking token — two people sharing the same
    video get different si= values. Without normalization each share link would
    create a duplicate DB row and be analysed again from scratch.
    """
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query) if k not in _TRACKING_PARAMS]
    clean_query = urlencode(kept)
    return parts._replace(query=clean_query).geturl()


def derive_video_id(url: str) -> str:
    """Stable id derived from the canonical URL so a re-submission collapses."""
    canonical = _normalize_url(url)
    h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"vid-{h}"


def classify_platform(url: str) -> str:
    """Map a URL to a known platform string for the queue payload."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.endswith("t.me") or host.endswith("telegram.org") or host == "telegram.me":
        return "telegram"
    if host.endswith("youtube.com") or host == "youtu.be":
        return "youtube"
    if host.endswith("tiktok.com") or host == "vm.tiktok.com":
        return "tiktok"
    if host.endswith("instagram.com") or host == "instagr.am":
        return "instagram"
    if (parts.scheme or "").lower() == "file":
        return "local"
    return "unknown"


async def _write_queue_and_kick(
    sm: async_sessionmaker[AsyncSession],
    *,
    video_id: str,
    url: str,
    platform: str,
    now: dt.datetime,
) -> int:
    """Write the ingest_queue row and best-effort kick the worker."""
    payload: dict[str, Any] = {"url": url, "platform": platform, "video_id": video_id}
    async with writer_lock(), sm() as session, session.begin():
        await session.execute(update(EvidencePackageRow).where(
            EvidencePackageRow.video_id == video_id,
            EvidencePackageRow.schema_version == 'failed',
        ).values(action='retrying'))
        row = IngestQueueRow(
            kind="video_url", payload=payload, created_at=now, status="pending"
        )
        session.add(row)
        await session.flush()
        queue_id: int = row.id

    if _EAGER:
        try:
            # Non-blocking: schedule as asyncio task so the HTTP 202 response
            # returns immediately and the frontend can poll for results.
            reset_job(video_id)
            task = asyncio.get_running_loop().create_task(_eager_pipeline_task(video_id))
            track_task(video_id, task)
        except RuntimeError:
            # No running event loop (CLI / beat context) — run synchronously
            from aimw.workers.tasks import process_video

            try:
                process_video.delay(video_id)
            except Exception:
                _LOG.warning(
                    "broker enqueue failed; row stays pending",
                    extra={"video_id": video_id, "queue_id": queue_id},
                )
    else:
        try:
            from aimw.workers.tasks import process_video

            process_video.delay(video_id)
        except Exception:
            _LOG.warning(
                "broker enqueue failed; row stays pending",
                extra={"video_id": video_id, "queue_id": queue_id},
            )
    return queue_id


async def enqueue_video_url(
    sm: async_sessionmaker[AsyncSession],
    url: str,
    *,
    skip_if_exists: bool = False,
) -> tuple[str, int | None]:
    """Upsert the video, write a queue row, and kick the worker.

    Returns ``(video_id, queue_id)``. When ``skip_if_exists`` is set and a
    ``videos`` row for the derived id already exists, returns
    ``(video_id, None)`` without enqueuing — the collector uses this to avoid
    re-processing videos it has already seen.
    """
    video_id = derive_video_id(url)
    platform = classify_platform(url)
    repo = VideosRepository(sm)

    if skip_if_exists and await repo.get(video_id) is not None:
        return video_id, None

    now = dt.datetime.now(dt.UTC)
    await repo.upsert(id=video_id, platform=platform, url=url, collected_at=now)
    queue_id = await _write_queue_and_kick(
        sm, video_id=video_id, url=url, platform=platform, now=now
    )
    return video_id, queue_id


async def enqueue_prepared(
    sm: async_sessionmaker[AsyncSession],
    *,
    video_id: str,
    url: str,
    platform: str,
    raw_path: str,
) -> tuple[str, int]:
    """Enqueue a manual job whose media already sits on disk at ``raw_path``.

    Used for pasted text, uploaded images, and uploaded video files: the
    worker skips the download step (the file exists) and the extraction stage
    branches on the file's suffix. ``url`` is a human-readable label shown in
    the queue, not something fetched.
    """
    now = dt.datetime.now(dt.UTC)
    await VideosRepository(sm).upsert(
        id=video_id, platform=platform, url=url, collected_at=now, raw_path=raw_path
    )
    queue_id = await _write_queue_and_kick(
        sm, video_id=video_id, url=url, platform=platform, now=now
    )
    return video_id, queue_id


__all__ = [
    "derive_video_id",
    "classify_platform",
    "enqueue_video_url",
    "enqueue_prepared",
]
