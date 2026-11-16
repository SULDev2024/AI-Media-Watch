"""GET /api/v1/validation/summary — real-world validation metrics.

Reads ``data/validation/cases.jsonl`` and returns computed P/R/F1
plus case-count breakdown. No Celery, no DB query — the JSONL is the
source of truth for validation state.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aimw.api.deps import RequestIdDep, RequireAnalyst, SessionmakerDep

router = APIRouter(prefix="/validation", tags=["validation"])


class ValidationSummaryResponse(BaseModel):
    n_total: int
    n_evaluated: int
    n_pending: int
    n_error: int
    n_skipped: int
    precision: float
    recall: float
    f1: float
    fpr: float
    fnr: float
    tp: int
    fp: int
    fn: int
    tn: int
    per_class: dict[str, dict[str, int]]
    confusion_matrix: dict[str, dict[str, int]]
    # Held-out generalization slice (cases the model never trained on). This is
    # the honest "real-world" number; the top-level fields cover the full corpus.
    holdout: dict[str, float] | None = None
    request_id: str


@router.get("/summary", response_model=ValidationSummaryResponse)
async def validation_summary(
    request_id: RequestIdDep,
    _user: RequireAnalyst,
    sm: SessionmakerDep,
) -> ValidationSummaryResponse:
    """Return real-world validation metrics.

    Requires labelled cases. Model predictions are never reference labels.
    """
    from aimw.validation.evaluator import evaluate
    from aimw.validation.models import load_cases

    cases = load_cases()
    if cases:
        result = evaluate(cases)
        b = result.binary
        # Held-out slice — the generalization figure for cases the model never saw.
        holdout_cases = [c for c in cases if getattr(c, "split", None) == "holdout"]
        holdout: dict[str, float] | None = None
        if holdout_cases:
            hb = evaluate(holdout_cases).binary
            holdout = {
                "n": float(hb.n),
                "precision": round(hb.precision, 4),
                "recall": round(hb.recall, 4),
                "f1": round(hb.f1, 4),
                "tp": float(hb.tp),
                "fp": float(hb.fp),
                "fn": float(hb.fn),
                "tn": float(hb.tn),
            }
        return ValidationSummaryResponse(
            n_total=result.n_total,
            n_evaluated=result.n_evaluated,
            n_pending=result.n_pending,
            n_error=result.n_error,
            n_skipped=result.n_skipped,
            precision=b.precision,
            recall=b.recall,
            f1=b.f1,
            fpr=b.fpr,
            fnr=b.fnr,
            tp=b.tp,
            fp=b.fp,
            fn=b.fn,
            tn=b.tn,
            per_class=result.per_class,
            confusion_matrix=result.confusion_matrix,
            holdout=holdout,
            request_id=request_id,
        )

    raise HTTPException(
        status_code=409,
        detail="Human-labeled validation cases are unavailable. Model predictions cannot establish detection accuracy.",
    )


__all__ = ["router"]
