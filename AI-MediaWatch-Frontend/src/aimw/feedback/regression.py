"""Regression freeze — §14 of AI_MediaWatch_v4.md.

``freeze(feedback_id, *, packages_repo, db_sessionmaker)`` snapshots a
confirmed (or escalated) evidence package into a deterministic YAML fixture
under ``tests/regression/cases/<name>.yaml`` and inserts / updates a
``regression_cases`` row so the dashboard counter reflects the growing suite.

The frozen YAML is entirely self-contained: it carries the canonical package
JSON plus the expected level so ``tests/regression/test_frozen.py`` can
re-run the deterministic scoring pipeline without any DB or network access.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from aimw.core.schema import to_json
from aimw.feedback import audit
from aimw.scoring.registry import register as _register_scoring

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from aimw.db.repositories.packages import PackagesRepository

_CASES_DIR = Path("tests/regression/cases")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(report_id: str) -> str:
    """Stable, filesystem-safe slug from a report id."""
    clean = _SLUG_RE.sub("-", report_id.lower()).strip("-")
    return clean[:60] or "case"


async def freeze(
    feedback_id: int,
    *,
    packages_repo: PackagesRepository,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    user_id: str = "system",
) -> Path:
    """Freeze the evidence package behind *feedback_id* as a YAML regression case.

    Steps
    -----
    1. Load the feedback row → report_id.
    2. Load the ``EvidencePackage`` for that report.
    3. Register the scoring engine and compute ``expected_level``.
    4. Write a YAML fixture to ``tests/regression/cases/<slug>.yaml``.
    5. Upsert the ``regression_cases`` row with ``expected_level`` populated.
    6. Audit-log the freeze.

    Returns
    -------
    Path
        Absolute path to the written YAML fixture.

    Raises
    ------
    ValueError
        No analyst feedback row found for *feedback_id*.
    LookupError
        The evidence package referenced by the feedback row is missing from DB.
    """
    from aimw.db.models import AnalystFeedbackRow, RegressionCaseRow
    from aimw.db.session import writer_lock

    async with db_sessionmaker() as session:
        feedback = await session.get(AnalystFeedbackRow, feedback_id)
        if feedback is None:
            raise ValueError(f"no analyst_feedback row with id {feedback_id}")
        report_id: str = feedback.report_id

    pkg = await packages_repo.get(report_id)
    if pkg is None:
        raise LookupError(f"evidence package {report_id!r} not found in DB")

    # Compute expected_level using the deterministic scoring engine.
    _register_scoring()
    expected_level: str = str(pkg.risk_level)

    # Serialise the canonical package to a round-trippable JSON string.
    package_json: str = to_json(pkg)

    name = f"regression-{_slug(report_id)}-{feedback_id}"
    frozen_at = dt.datetime.now(dt.UTC)

    fixture: dict[str, str] = {
        "name": name,
        "frozen_at": frozen_at.isoformat(),
        "frozen_from_report": report_id,
        "expected_level": expected_level,
        "package": package_json,
    }

    _CASES_DIR.mkdir(parents=True, exist_ok=True)
    yaml_path = _CASES_DIR / f"{name}.yaml"
    yaml_path.write_text(yaml.dump(fixture, allow_unicode=True, sort_keys=True), encoding="utf-8")

    # Upsert the regression_cases row (insert if absent, update expected_level).
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    async with writer_lock(), db_sessionmaker() as session, session.begin():
        stmt = sqlite_insert(RegressionCaseRow).values(
            name=name,
            input_url=pkg.url,
            expected_level=expected_level,
            frozen_at=frozen_at,
            frozen_from_report=report_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[RegressionCaseRow.name],
            set_={
                "expected_level": stmt.excluded.expected_level,
                "frozen_at": stmt.excluded.frozen_at,
            },
        )
        await session.execute(stmt)

    audit.append(
        "regression_freeze",
        before=None,
        after={
            "feedback_id": feedback_id,
            "report_id": report_id,
            "expected_level": expected_level,
            "yaml_path": str(yaml_path),
        },
        user_id=user_id,
    )

    return yaml_path
