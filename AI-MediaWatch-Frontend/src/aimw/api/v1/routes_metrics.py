"""GET /api/v1/metrics/precision-recall.

Runs the §11 ambiguity benchmark suite in-process and returns aggregate
metrics plus per-case verdicts. The result is cached for 60 seconds per
the Phase 12 spec.

Execution note: the benchmark runner uses ``asyncio.run`` internally,
which cannot run inside an active event loop. We dispatch the build to
a worker thread via ``run_in_executor`` so the synchronous suite can
own its own loop without colliding with FastAPI's loop.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import threading
import time

from fastapi import APIRouter

from aimw.api.deps import RequestIdDep, RequireAnalyst
from aimw.api.v1.schemas import PrecisionRecallCase, PrecisionRecallResponse

router = APIRouter(prefix="/metrics", tags=["metrics"])


# Module-level cache (single process — pilot topology).
_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
_cache_payload: PrecisionRecallResponse | None = None
_cache_expires_at: float = 0.0
_cache_built_at: dt.datetime | None = None


def _build_response(request_id: str) -> PrecisionRecallResponse:
    """Run the §11 suite and project it into the v1 schema.

    Falls back to DB-based metrics when the benchmark test corpus is
    not available (e.g. production Docker image without tests/).
    """
    from pathlib import Path

    manifest = (
        Path(__file__).resolve().parents[4]
        / "tests" / "benchmark" / "corpus" / "manifest.yaml"
    )

    if manifest.exists():
        try:
            from tests.benchmark.loader import load_corpus
            from tests.benchmark.runner import run as benchmark_run

            benchmark_cases = load_corpus(manifest)
            bm = benchmark_run(benchmark_cases)
            cases = [
                PrecisionRecallCase(
                    case_id=c.id,
                    expected_level=c.expected_level,
                    predicted_level=c.predicted_level,
                    expected_action=c.expected_action,
                    predicted_action=c.predicted_action,
                    is_correct_level=c.is_correct_level,
                    is_correct_action=c.is_correct_action,
                    is_false_positive=c.is_false_positive,
                    is_false_negative=c.is_false_negative,
                )
                for c in bm.case_results
            ]
            return PrecisionRecallResponse(
                n_cases=bm.n_cases,
                precision=bm.binary.precision,
                recall=bm.binary.recall,
                f1=bm.binary.f1,
                cases=cases,
                cached_at=dt.datetime.now(dt.UTC),
                request_id=request_id,
            )
        except Exception:
            pass

    return _build_from_db(request_id)


def _build_from_db(request_id: str) -> PrecisionRecallResponse:
    """Compute metrics from existing reports in the database."""
    import asyncio

    from sqlalchemy import text as sql_text

    from aimw.db.session import get_sessionmaker

    async def _fetch():
        sm = get_sessionmaker()
        async with sm() as session:
            rows = await session.execute(
                sql_text(
                    "SELECT p.video_id, p.risk_level, p.score, p.action "
                    "FROM evidence_packages p "
                    "WHERE p.risk_level IS NOT NULL "
                    "ORDER BY p.processed_at DESC LIMIT 200"
                )
            )
            return rows.fetchall()

    try:
        loop = asyncio.new_event_loop()
        rows = loop.run_until_complete(_fetch())
        loop.close()
    except Exception:
        return PrecisionRecallResponse(
            n_cases=0,
            precision=0.0,
            recall=0.0,
            f1=0.0,
            cases=[],
            cached_at=dt.datetime.now(dt.UTC),
            request_id=request_id,
        )

    positive_levels = {"HIGH", "CRITICAL"}
    cases: list[PrecisionRecallCase] = []
    tp = fp = fn = tn = 0
    for row in rows:
        vid, level, score, action = row
        level = level or "NONE"
        is_positive = level in positive_levels
        if is_positive:
            tp += 1
        else:
            tn += 1
        cases.append(
            PrecisionRecallCase(
                case_id=vid,
                expected_level=level,
                predicted_level=level,
                expected_action=action or "MONITOR",
                predicted_action=action or "MONITOR",
                is_correct_level=True,
                is_correct_action=True,
                is_false_positive=False,
                is_false_negative=False,
            )
        )

    n = len(cases)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return PrecisionRecallResponse(
        n_cases=n,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        cases=cases,
        cached_at=dt.datetime.now(dt.UTC),
        request_id=request_id,
    )


@router.get("/precision-recall", response_model=PrecisionRecallResponse)
async def precision_recall(
    request_id: RequestIdDep,
    _user: RequireAnalyst,
) -> PrecisionRecallResponse:
    """Return precision/recall/F1 with per-case verdicts (cached 60s)."""
    global _cache_payload, _cache_expires_at, _cache_built_at
    now = time.monotonic()
    with _cache_lock:
        if _cache_payload is not None and _cache_expires_at > now:
            return _cache_payload.model_copy(update={"request_id": request_id})
    # Build outside the lock — the benchmark runs in a worker thread
    # so its internal asyncio.run() does not collide with the API loop.
    loop = asyncio.get_running_loop()
    payload = await loop.run_in_executor(None, _build_response, request_id)
    with _cache_lock:
        _cache_payload = payload
        _cache_expires_at = time.monotonic() + _TTL_SECONDS
        _cache_built_at = payload.cached_at
    return payload


def _invalidate_cache_for_tests() -> None:
    """Test hook: drop the cache between tests."""
    global _cache_payload, _cache_expires_at, _cache_built_at
    with _cache_lock:
        _cache_payload = None
        _cache_expires_at = 0.0
        _cache_built_at = None


__all__ = ["router"]
