"""Campaigns router — GET /campaigns, GET /campaigns/{entity_value}.

H1 mitigation: the (graph, campaigns) tuple is served from a TTL cache
(``campaign_graph_cache``).  The cache eliminates the per-request
graph rebuild that made these endpoints a DoS amplifier in Phase 12.
A token bucket caps burst rate per process so a malicious client cannot
saturate the rebuild path on cache misses.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aimw.api.dependencies import AuthDep, SessionmakerDep
from aimw.api.graph_cache import campaign_graph_cache
from aimw.api.models import CampaignSummary
from aimw.api.throttling import campaigns_bucket
from aimw.graph.models import Campaign

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _to_summary(c: Campaign) -> CampaignSummary:
    return CampaignSummary(
        campaign_id=c.shared_entities[0],
        shared_entities=list(c.shared_entities),
        strength=c.strength,
        n_videos=len(c.videos),
        videos=list(c.videos),
    )


async def _all_campaigns(
    sm: async_sessionmaker[AsyncSession],
) -> list[CampaignSummary]:
    campaigns, _ = await campaign_graph_cache.get(sm)
    return [_to_summary(c) for c in campaigns]


def _check_rate_limit() -> None:
    if not campaigns_bucket.try_consume("campaigns"):
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate limit exceeded",
                "code": "RATE_LIMITED",
                "endpoint": "campaigns",
            },
        )


@router.get("", response_model=list[CampaignSummary])
async def list_campaigns(
    sm: SessionmakerDep,
    _auth: AuthDep,
) -> list[CampaignSummary]:
    """List all active campaigns detected in the intelligence graph.

    Served from a 30-second TTL cache; rate-limited per process to a
    short burst then 0.5 req/sec steady-state (capacity=10).
    """
    _check_rate_limit()
    return await _all_campaigns(sm)


@router.get("/{entity_value}", response_model=CampaignSummary)
async def get_campaign(
    entity_value: str,
    sm: SessionmakerDep,
    _auth: AuthDep,
) -> CampaignSummary:
    """Retrieve details of a specific campaign by its shared entity value.

    The ``entity_value`` parameter is ``campaign_id`` from the list response.
    """
    _check_rate_limit()
    all_campaigns = await _all_campaigns(sm)
    for c in all_campaigns:
        if c.campaign_id == entity_value:
            return c
    raise HTTPException(
        status_code=404,
        detail=f"Campaign with entity value {entity_value!r} not found",
    )
