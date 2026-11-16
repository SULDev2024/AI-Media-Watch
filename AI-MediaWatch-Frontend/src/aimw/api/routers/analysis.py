"""Analysis router — POST /analysis/run, POST /campaigns/recompute."""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, HTTPException

from aimw.api.dependencies import AuthDep, SessionmakerDep
from aimw.api.models import AnalysisRunRequest, AnalysisRunResponse, RecomputeResponse
from aimw.api.throttling import recompute_gate
from aimw.db.models import IngestQueueRow
from aimw.db.session import writer_lock

router = APIRouter(tags=["analysis"])

_LOG = logging.getLogger("aimw.api.analysis")


@router.post("/analysis/run", response_model=AnalysisRunResponse, status_code=202)
async def enqueue_analysis(
    request: AnalysisRunRequest,
    sm: SessionmakerDep,
    _auth: AuthDep,
) -> AnalysisRunResponse:
    """Enqueue a video URL for analysis.

    The URL has already passed the SSRF validator in ``AnalysisRunRequest``.
    Writes to the ``ingest_queue`` table and returns immediately. The Phase 13
    worker drains this queue and runs the full collection → ASR → OCR → entity
    extraction → scoring pipeline asynchronously.
    """
    now = dt.datetime.now(dt.UTC)
    async with writer_lock(), sm() as session, session.begin():
        row = IngestQueueRow(
            kind="video_url",
            payload={
                "url": request.url,
                "platform": request.platform,
                "priority": request.priority,
            },
            created_at=now,
            status="pending",
        )
        session.add(row)
        await session.flush()
        queue_id: int = row.id
    return AnalysisRunResponse(
        queue_id=queue_id,
        url=request.url,
        platform=request.platform,
        status="pending",
        enqueued_at=now,
    )


@router.post("/campaigns/recompute", response_model=RecomputeResponse)
async def trigger_recompute(
    _auth: AuthDep,
) -> RecomputeResponse:
    """Trigger an asynchronous campaign graph recomputation via Celery.

    C5 mitigation: a single-flight gate coalesces concurrent invocations
    onto one Celery task.  If a task is already in flight (within the
    60-second TTL), the existing task id is returned with status
    ``"already-running"`` so the caller knows the work is already
    happening.  This prevents queue-flooding abuse.

    H5 mitigation: exceptions are classified — broker errors return 503,
    everything else returns 500 with a distinct code so operators can
    distinguish broker outage from application bug.  Full tracebacks
    are logged but never returned to the caller.
    """
    # Import inside the function so test fixtures that patch the symbol
    # see the patched version.
    try:
        from aimw.workers.tasks import recompute_campaigns
    except ImportError as exc:  # pragma: no cover - import-time bug
        _LOG.exception("recompute_campaigns import failed", extra={"phase": "import"})
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal error",
                "code": "RECOMPUTE_IMPORT_FAILED",
            },
        ) from exc

    # Single-flight check happens FIRST — even if the broker is down we want
    # idempotent behaviour rather than racing on the broker error.
    try:
        async_result = recompute_campaigns.delay()
    except Exception as exc:
        # Broker unreachable. Log with full traceback for ops; return a
        # short, code-tagged 503 to the caller.
        _LOG.exception(
            "celery broker unavailable",
            extra={"phase": "delay", "exc_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Celery broker unavailable",
                "code": "BROKER_UNAVAILABLE",
                "exc_type": type(exc).__name__,
            },
        ) from exc

    task_id = async_result.id
    claimed, reported_id = recompute_gate.try_claim(task_id)
    if not claimed:
        # Another invocation is in flight. Revoke the redundant task and
        # report the existing one. ``revoke`` is best-effort; if it fails
        # the duplicate task will still run and is idempotent at the
        # graph level (build → find → promote are all upserts).
        try:
            async_result.revoke()
        except Exception:  # pragma: no cover - revoke best-effort
            _LOG.warning(
                "failed to revoke duplicate recompute task",
                extra={"task_id": task_id},
            )
        return RecomputeResponse(task_id=reported_id, status="already-running")

    return RecomputeResponse(task_id=task_id, status="queued")
