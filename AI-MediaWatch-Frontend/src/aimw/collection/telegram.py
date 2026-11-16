"""Telethon channel watcher — downloads video messages, records videos rows.

Side-effect only (constraint #5): it reads Telegram and writes the ``videos``
table via the repository interface (constraint #7 — the only DB access allowed
here). It never constructs or reads an ``EvidencePackage``; package creation is
Phase 5+.

Resilience (constraint #8): a failure on one message or one channel logs a
structured error and continues — it never crashes the ingestion loop.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import random
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from telethon.errors import FloodWaitError

from aimw.collection import priority
from aimw.collection.language_detect import detect as detect_language
from aimw.collection.offsets import Offsets
from aimw.core.logging import get_logger

log = get_logger("aimw.collection.telegram")

_CHUNK = 1 << 20


@dataclass(frozen=True)
class ChannelSpec:
    """A curated public channel to watch."""

    name: str  # used for the t.me URL and offset key
    entity: Any  # what Telethon resolves (username string or id)


class _VideosRepo(Protocol):
    """The only DB surface the watcher is allowed to touch (constraint #7)."""

    async def upsert(
        self,
        *,
        id: str,
        platform: str,
        url: str,
        collected_at: dt.datetime,
        language_hint: str | None = ...,
        priority_score: float | None = ...,
        raw_path: str | None = ...,
    ) -> None: ...


def _sha16(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _message_datetime(msg: Any) -> dt.datetime:
    when = getattr(msg, "date", None)
    if isinstance(when, dt.datetime):
        return when if when.tzinfo else when.replace(tzinfo=dt.UTC)
    return dt.datetime.now(dt.UTC)


class ChannelWatcher:
    """Polls curated channels and persists new video messages as videos rows."""

    def __init__(
        self,
        client: Any,
        videos_repo: _VideosRepo,
        offsets: Offsets,
        media_dir: Path,
        *,
        concurrency: int = 3,
    ) -> None:
        self._client = client
        self._videos = videos_repo
        self._offsets = offsets
        self._media_dir = media_dir
        self._sem = asyncio.Semaphore(concurrency)

    async def poll_channel(self, channel: ChannelSpec) -> int:
        """Process new video messages for one channel; return count ingested.

        Never raises: FloodWait sleeps and returns; any other error is logged.
        """
        last_id = self._offsets.get(channel.name) or 0
        try:
            messages = [
                msg
                async for msg in self._client.iter_messages(channel.entity, min_id=last_id)
                if self._is_video(msg)
            ]
        except FloodWaitError as exc:
            await self._handle_flood_wait(exc, channel.name)
            return 0
        except Exception as exc:  # must not crash the loop (constraint #8)
            log.error("collection_poll_failed", channel=channel.name, error=str(exc))
            return 0

        results = await asyncio.gather(
            *(self._process(channel, msg) for msg in messages),
            return_exceptions=True,
        )
        processed = 0
        for result in results:
            if isinstance(result, Exception):
                log.error("collection_item_failed", channel=channel.name, error=str(result))
            elif result:
                processed += 1
        return processed

    async def _process(self, channel: ChannelSpec, msg: Any) -> bool:
        async with self._sem:
            try:
                path, video_id = await self._download(msg)
            except FloodWaitError as exc:
                await self._handle_flood_wait(exc, channel.name)
                return False
            except Exception as exc:  # must not crash the loop (constraint #8)
                log.error(
                    "collection_download_failed",
                    channel=channel.name,
                    msg_id=getattr(msg, "id", None),
                    error=str(exc),
                )
                return False

            caption = getattr(msg, "message", None) or ""
            prio = priority.score(caption)
            await self._videos.upsert(
                id=video_id,
                platform="telegram",
                url=f"https://t.me/{channel.name}/{msg.id}",
                collected_at=_message_datetime(msg),
                language_hint=detect_language(caption),
                priority_score=prio,
                raw_path=str(path),
            )
            current = self._offsets.get(channel.name) or 0
            if msg.id > current:
                self._offsets.set(channel.name, msg.id)
            log.info(
                "collection_ingested",
                channel=channel.name,
                video_id=video_id,
                msg_id=msg.id,
                priority=prio,
            )
            return True

    async def _download(self, msg: Any) -> tuple[Path, str]:
        self._media_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / f"{msg.id}.bin"
            await self._client.download_media(msg, file=str(tmp_path))
            video_id = _sha16(tmp_path)
            final = self._media_dir / f"{video_id}.mp4"
            if not final.exists():
                shutil.move(str(tmp_path), str(final))
        return final, video_id

    @staticmethod
    def _is_video(msg: Any) -> bool:
        if getattr(msg, "video", None):
            return True
        document = getattr(msg, "document", None)
        mime = getattr(document, "mime_type", "") if document else ""
        return bool(mime and mime.startswith("video"))

    async def _handle_flood_wait(self, exc: FloodWaitError, channel_name: str) -> None:
        delay = exc.seconds + random.uniform(1, 5)
        log.warning("flood_wait", seconds=exc.seconds, channel=channel_name, sleep=delay)
        await asyncio.sleep(delay)
