"""Videos repository."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aimw.db.dto import VideoRow
from aimw.db.models import Video
from aimw.db.session import writer_lock


class VideosRepository:
    """Persistence for collected media rows."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def upsert(
        self,
        *,
        id: str,
        platform: str,
        url: str,
        collected_at: dt.datetime,
        language_hint: str | None = None,
        priority_score: float | None = None,
        raw_path: str | None = None,
    ) -> None:
        """Insert or update a video by primary key."""
        async with writer_lock(), self._sm() as session, session.begin():
            stmt = sqlite_insert(Video).values(
                id=id,
                platform=platform,
                url=url,
                collected_at=collected_at,
                language_hint=language_hint,
                priority_score=priority_score,
                raw_path=raw_path,
            )
            update_set = {
                "platform": stmt.excluded.platform,
                "url": stmt.excluded.url,
                "collected_at": stmt.excluded.collected_at,
                "language_hint": stmt.excluded.language_hint,
                "priority_score": stmt.excluded.priority_score,
            }
            if raw_path is not None:
                update_set["raw_path"] = stmt.excluded.raw_path
            stmt = stmt.on_conflict_do_update(
                index_elements=[Video.id],
                set_=update_set,
            )
            await session.execute(stmt)

    async def get(self, video_id: str) -> VideoRow | None:
        """Return a video read-model, or None."""
        async with self._sm() as session:
            row = await session.get(Video, video_id)
            if row is None:
                return None
            return VideoRow.model_validate(row, from_attributes=True)

    async def update_transcript(self, video_id: str, segments_json: str) -> None:
        """Persist serialised Whisper segments so the dashboard can show the transcript."""
        async with writer_lock(), self._sm() as session, session.begin():
            await session.execute(
                update(Video)
                .where(Video.id == video_id)
                .values(transcript_segments=segments_json)
            )

    async def update_title(self, video_id: str, title: str) -> None:
        """Persist the platform title so the judge can read the video's framing."""
        async with writer_lock(), self._sm() as session, session.begin():
            await session.execute(
                update(Video).where(Video.id == video_id).values(title=title)
            )

    async def list_recent(self, limit: int = 50) -> list[VideoRow]:
        """Return the most recently collected videos."""
        async with self._sm() as session:
            result = await session.execute(
                select(Video).order_by(Video.collected_at.desc()).limit(limit)
            )
            return [VideoRow.model_validate(r, from_attributes=True) for r in result.scalars()]

    async def known_urls(self, platform: str) -> set[str]:
        """Previously submitted source posts, including failures and cancellations."""
        async with self._sm() as session:
            return set(await session.scalars(select(Video.url).where(Video.platform == platform)))
