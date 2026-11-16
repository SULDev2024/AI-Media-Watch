"""POST /api/v1/feedback.

Records an analyst verdict and triggers the §14 feedback loop:

* ``confirmed``  → regression.freeze (YAML fixture) + watchlist.add for each entity
* ``dismissed``  → calibration.nudge (raise band threshold toward dismissed score)
* ``escalated``  → regression.freeze with current level (locks the correct call)

The heavy work (freeze, nudge, watchlist) is best-effort: errors are logged
but do not fail the response. The feedback row is always recorded first.
"""

from __future__ import annotations

import logging

import pydantic
from fastapi import APIRouter, HTTPException

from aimw.api.deps import FeedbackRepoDep, PackagesRepoDep, RequestIdDep, RequireAnalyst
from aimw.api.deps import get_sessionmaker_dep as _get_sm
from aimw.api.v1.schemas import FeedbackIn, FeedbackOut

router = APIRouter(prefix="/feedback", tags=["feedback"])

_ALLOWED_VERDICTS = ("confirmed", "dismissed", "escalated")
_LOG = logging.getLogger(__name__)


@router.post("", response_model=FeedbackOut)
async def post_feedback(
    body: FeedbackIn,
    request_id: RequestIdDep,
    user: RequireAnalyst,
    feedback: FeedbackRepoDep,
    packages: PackagesRepoDep,
) -> FeedbackOut:
    verdict = body.verdict.lower().strip()
    if verdict not in _ALLOWED_VERDICTS:
        raise HTTPException(
            status_code=422,
            detail=f"verdict {body.verdict!r} not in {_ALLOWED_VERDICTS}",
        )

    feedback_id = await feedback.record(
        body.report_id,
        verdict,  # type: ignore[arg-type]
        notes=body.notes,
        analyst_id=user.id,
    )

    regression_id: int | None = None

    if verdict in ("confirmed", "escalated"):
        # Keep the DB regression_cases row for the dashboard counter.
        regression_id = await feedback.freeze_as_regression(feedback_id)
        # Write the YAML fixture (best-effort; never fail the response).
        try:
            from aimw.feedback import regression

            sm = _get_sm()
            await regression.freeze(
                feedback_id,
                packages_repo=packages,
                db_sessionmaker=sm,
                user_id=user.id,
            )
        except Exception:
            _LOG.exception("regression_freeze_failed", extra={"feedback_id": feedback_id})

        if verdict == "confirmed":
            # Add confirmed entities to the watchlist (best-effort).
            try:
                pkg = await packages.get(body.report_id)
                if pkg is not None:
                    from aimw.feedback import watchlist

                    for handle in pkg.entities.telegram_handles:
                        watchlist.add("handles", handle, user_id=user.id)
                    for wallet in pkg.entities.crypto_wallets:
                        watchlist.add("wallets", wallet, user_id=user.id)
                    for phone in pkg.entities.phone_numbers:
                        watchlist.add("phones", phone, user_id=user.id)
            except Exception:
                _LOG.exception("watchlist_add_failed", extra={"report_id": body.report_id})

    elif verdict == "dismissed":
        # Nudge the band threshold toward the dismissed score (best-effort).
        try:
            pkg = await packages.get(body.report_id)
            if pkg is not None:
                from aimw.feedback import calibration
                from aimw.scoring.registry import register as _reg

                _reg()
                pkg_score = pkg.score
                pkg_level = str(pkg.risk_level).lower()
                thresholds = calibration.load_thresholds()
                band_thresh = thresholds.get(pkg_level)
                if band_thresh is not None and pkg_level in calibration.DEFAULTS:
                    # Raise the threshold toward the dismissed score so future
                    # similar packages fall below the line.
                    gap = max(0.0, pkg_score - band_thresh)
                    delta = round(gap * 0.05, 6)
                    if delta > 0:
                        calibration.nudge(pkg_level, delta, user_id=user.id)
        except Exception:
            _LOG.exception("calibration_nudge_failed", extra={"report_id": body.report_id})

    return FeedbackOut(
        feedback_id=feedback_id,
        report_id=body.report_id,
        verdict=verdict,
        regression_case_id=regression_id,
        request_id=request_id,
    )


class FeedbackListItem(FeedbackOut):
    notes: str | None = None
    saved_at: str


class FeedbackListResponse(pydantic.BaseModel):
    items: list[FeedbackListItem]
    request_id: str


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    request_id: RequestIdDep,
    _user: RequireAnalyst,
    feedback: FeedbackRepoDep,
) -> FeedbackListResponse:
    """Return recent feedback entries from the database."""
    items_raw = await feedback.list_recent(limit=100)
    items = [
        FeedbackListItem(
            feedback_id=r["feedback_id"],
            report_id=r["report_id"],
            verdict=r["verdict"],
            regression_case_id=r.get("regression_case_id"),
            request_id=request_id,
            notes=r.get("notes"),
            saved_at=str(r.get("created_at", "")),
        )
        for r in items_raw
    ]
    return FeedbackListResponse(items=items, request_id=request_id)


__all__ = ["router"]
