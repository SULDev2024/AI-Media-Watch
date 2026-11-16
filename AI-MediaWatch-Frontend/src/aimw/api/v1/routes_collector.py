"""Collector control — start / stop the beat-driven crawler from the UI.

These three endpoints are the admin's "go collect" / "stop" buttons:

* ``GET  /api/v1/collector/status`` — current run-state for the dashboard.
* ``POST /api/v1/collector/start``  — set queries + flip the flag to running,
  and trigger one immediate tick so the first results appear without waiting
  for the next beat.
* ``POST /api/v1/collector/stop``   — flip the flag to stopped (queries kept).

The actual crawling happens in the worker's ``collector_tick`` task; these
routes only mutate the shared control flag in Redis.
"""

from __future__ import annotations
import asyncio
import logging

from fastapi import APIRouter, HTTPException, status

from aimw.api.deps import RequireAnalyst
from aimw.api.v1.schemas import CollectorStartRequest, CollectorState
from aimw.collection import control
from aimw.collection.keyword_suggest import get_suggestions
from aimw.core.config import get_settings

router = APIRouter(prefix="/collector", tags=["collector"])
_local_task: asyncio.Task | None = None


async def _local_loop() -> None:
    from aimw.workers.tasks import collect_once
    while control.is_running():
        try:
            await collect_once()
        except Exception:
            logging.getLogger(__name__).exception("local_collector_failed")
            control.stop()
            return
        await asyncio.sleep(60)


async def shutdown_local_collector() -> None:
    global _local_task
    if _local_task is not None:
        _local_task.cancel()
        try:
            await _local_task
        except asyncio.CancelledError:
            pass
        _local_task = None
    if get_settings().eager:
        control.stop()


def _state_with_capabilities(state: dict) -> CollectorState:
    """Enrich the raw state dict with platform capability info."""
    state["supported_platforms"] = list(control.supported_platforms())
    return CollectorState(**state)


@router.get("/status", response_model=CollectorState)
async def collector_status(_user: RequireAnalyst) -> CollectorState:
    """Return the current collector run-state."""
    return _state_with_capabilities(control.get_state())


@router.post("/start", response_model=CollectorState)
async def collector_start(
    body: CollectorStartRequest,
    _user: RequireAnalyst,
) -> CollectorState:
    """Turn the collector on and kick an immediate crawl tick."""
    queries = [q.strip() for q in body.queries if q and q.strip()]
    if not queries:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide at least one search term before starting the collector.",
        )
    try:
        state = control.start(queries, body.per_query, body.platforms,
                              body.content_types, body.region_focus)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if get_settings().eager:
        global _local_task
        if _local_task is None or _local_task.done():
            _local_task = asyncio.create_task(_local_loop())
        return _state_with_capabilities(state)

    try:
        from aimw.workers.tasks import collector_tick

        collector_tick.delay()
    except Exception:
        import logging

        logging.getLogger("aimw.api.v1.routes_collector").warning(
            "collector immediate tick enqueue failed; beat will pick it up"
        )

    return _state_with_capabilities(state)


@router.post("/stop", response_model=CollectorState)
async def collector_stop(_user: RequireAnalyst) -> CollectorState:
    """Turn the collector off; the next tick becomes a no-op."""
    state = control.stop()
    if get_settings().eager:
        await shutdown_local_collector()
    return _state_with_capabilities(state)


@router.get("/suggestions")
async def keyword_suggestions(_user: RequireAnalyst) -> dict:
    """Return auto-generated keyword suggestions from flagged content."""
    return get_suggestions()


@router.post("/suggestions/refresh")
async def refresh_suggestions(_user: RequireAnalyst) -> dict:
    """Trigger an immediate keyword suggestion refresh."""
    try:
        from aimw.workers.tasks import refresh_keyword_suggestions

        refresh_keyword_suggestions.delay()
    except Exception:
        pass
    return {"status": "refresh_queued"}


__all__ = ["router"]
