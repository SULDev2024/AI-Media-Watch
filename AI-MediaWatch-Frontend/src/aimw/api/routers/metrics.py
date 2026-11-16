"""Metrics router — GET /metrics.

H1 mitigation: the graph view served here uses the same TTL cache as
``GET /campaigns``.  A rate limit (token bucket) protects the DB
count query path on cache misses.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from aimw.api.dependencies import AuthDep, SessionmakerDep
from aimw.api.graph_cache import campaign_graph_cache
from aimw.api.models import MetricsSnapshot
from aimw.api.throttling import metrics_bucket
from aimw.core.config import get_settings
from aimw.db.models import EvidencePackageRow
from aimw.db.repositories.usage import UsageRepository

router = APIRouter(tags=["observability"])


@router.get("/metrics", response_model=MetricsSnapshot)
async def get_metrics(
    sm: SessionmakerDep,
    _auth: AuthDep,
) -> MetricsSnapshot:
    """Return a real-time operational metrics snapshot.

    Counts are derived from the live database; the campaign view is
    served from the same TTL cache as ``GET /campaigns``.

    ``packages_by_level`` will show all zeros until Phase 13 populates
    the ``risk_level`` DB column (currently the column is always NULL
    because the scoring engine is in-memory only).
    """
    if not metrics_bucket.try_consume("metrics"):
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate limit exceeded",
                "code": "RATE_LIMITED",
                "endpoint": "metrics",
            },
        )

    today = dt.date.today()
    settings = get_settings()

    async with sm() as session:
        total_result = await session.execute(
            select(func.count(EvidencePackageRow.report_id))
        )
        total_packages: int = total_result.scalar_one() or 0

        level_rows = await session.execute(
            select(EvidencePackageRow.risk_level, func.count())
            .where(EvidencePackageRow.risk_level.is_not(None))
            .group_by(EvidencePackageRow.risk_level)
        )
        packages_by_level: dict[str, int] = {
            level: count for level, count in level_rows.all()
        }

    campaigns, _ = await campaign_graph_cache.get(sm)
    campaigns_by_strength: dict[str, int] = {}
    for c in campaigns:
        campaigns_by_strength[c.strength] = campaigns_by_strength.get(c.strength, 0) + 1

    usage_repo = UsageRepository(sm)
    token_used = await usage_repo.used(today, settings.resolved_llm_model)

    return MetricsSnapshot(
        total_packages=total_packages,
        packages_by_level=packages_by_level,
        total_campaigns=len(campaigns),
        campaigns_by_strength=campaigns_by_strength,
        token_usage_today=token_used,
        token_cap_today=settings.resolved_llm_daily_token_cap,
    )
