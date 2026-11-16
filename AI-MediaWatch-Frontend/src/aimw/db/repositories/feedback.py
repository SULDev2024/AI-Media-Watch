"""Analyst-feedback repository (Phase 15 builds on this)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aimw.db.models import AnalystFeedbackRow, EvidencePackageRow, RegressionCaseRow
from aimw.db.session import writer_lock

Verdict = Literal["confirmed", "dismissed", "escalated"]


class FeedbackRepository:
    """Persistence for analyst verdicts and frozen regression cases."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def record(
        self,
        report_id: str,
        verdict: Verdict,
        notes: str | None = None,
        analyst_id: str | None = None,
    ) -> int:
        """Record an analyst verdict; returns the feedback row id."""
        async with writer_lock(), self._sm() as session, session.begin():
            row = AnalystFeedbackRow(
                report_id=report_id,
                verdict=verdict,
                notes=notes,
                created_by=analyst_id,
                created_at=dt.datetime.now(dt.UTC),
            )
            session.add(row)
            await session.flush()
            return row.id

    async def list_recent(self, limit: int = 100) -> list[dict]:
        """Return the most recent feedback entries as dicts."""
        async with self._sm() as session:
            stmt = (
                select(AnalystFeedbackRow)
                .order_by(AnalystFeedbackRow.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "feedback_id": r.id,
                    "report_id": r.report_id,
                    "verdict": r.verdict,
                    "notes": r.notes,
                    "created_at": r.created_at,
                    "regression_case_id": None,
                }
                for r in rows
            ]

    async def freeze_as_regression(self, feedback_id: int) -> int:
        """Freeze the report behind a feedback row as a regression case.

        ``expected_level`` is left NULL: the scoring engine (Phase 8) does not
        exist yet, so the repository does not fabricate a level here.
        """
        async with writer_lock(), self._sm() as session, session.begin():
            feedback = await session.get(AnalystFeedbackRow, feedback_id)
            if feedback is None:
                raise ValueError(f"no analyst_feedback row with id {feedback_id}")

            pkg = await session.get(EvidencePackageRow, feedback.report_id)
            input_url = None
            if pkg is not None:
                # Read the URL from the canonical blob (authoritative source).
                from aimw.core.schema import from_json

                input_url = from_json(pkg.package_json).url

            case = RegressionCaseRow(
                name=f"regression-{feedback.report_id}-{feedback_id}",
                input_url=input_url,
                expected_level=None,
                frozen_at=dt.datetime.now(dt.UTC),
                frozen_from_report=feedback.report_id,
            )
            session.add(case)
            await session.flush()
            return case.id
