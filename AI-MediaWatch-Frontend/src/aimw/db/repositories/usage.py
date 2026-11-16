"""Daily token-usage repository for the Groq budget guard (Phase 10/13)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aimw.db.models import DailyTokenUsageRow
from aimw.db.session import writer_lock


class UsageRepository:
    """Per-(date, model) token accounting."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def add(self, date: dt.date, model: str, tokens: int) -> None:
        """Add ``tokens`` to the running total for (date, model)."""
        async with writer_lock(), self._sm() as session, session.begin():
            stmt = sqlite_insert(DailyTokenUsageRow).values(
                date=date, model=model, tokens_used=tokens
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[DailyTokenUsageRow.date, DailyTokenUsageRow.model],
                set_={"tokens_used": DailyTokenUsageRow.tokens_used + stmt.excluded.tokens_used},
            )
            await session.execute(stmt)

    async def used(self, date: dt.date, model: str) -> int:
        """Tokens used so far for (date, model); 0 if no row."""
        async with self._sm() as session:
            result = await session.execute(
                select(DailyTokenUsageRow.tokens_used).where(
                    DailyTokenUsageRow.date == date, DailyTokenUsageRow.model == model
                )
            )
            value = result.scalar_one_or_none()
            return int(value) if value is not None else 0

    async def remaining(self, date: dt.date, model: str, daily_cap: int) -> int:
        """Remaining tokens under ``daily_cap`` (never negative)."""
        return max(daily_cap - await self.used(date, model), 0)
