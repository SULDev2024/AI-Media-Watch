"""GET /api/v1/usage/today — Groq token usage for the current UTC day."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from aimw.api.deps import RequestIdDep, RequireAnalyst, UsageRepoDep
from aimw.api.v1.schemas import UsageToday
from aimw.core.config import get_settings

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/today", response_model=UsageToday)
async def usage_today(
    request_id: RequestIdDep,
    _user: RequireAnalyst,
    usage: UsageRepoDep,
) -> UsageToday:
    settings = get_settings()
    today = dt.datetime.now(dt.UTC).date()
    model = settings.resolved_llm_model
    cap = settings.resolved_llm_daily_token_cap
    used = await usage.used(today, model)
    return UsageToday(
        date=today,
        model=model,
        tokens_used=used,
        daily_cap=cap,
        remaining=max(cap - used, 0),
        request_id=request_id,
    )


__all__ = ["router"]
