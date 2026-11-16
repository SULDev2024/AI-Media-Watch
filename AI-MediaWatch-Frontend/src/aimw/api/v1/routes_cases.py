"""GET /api/v1/cases/{video_id} — tamper-evident case file.

Returns a sealed, hash-chained evidence package ready for regulatory
submission.  Every evidence piece is individually hashed (SHA-256) and
chained Merkle-style so that any post-hoc modification breaks the
``chain_root`` commitment.

Each piece is annotated with the specific Kazakhstan statute it violates
(loaded from ``config/regulations_kz.yaml``).

The response also carries a ``verify_ok`` field so the caller can
immediately confirm integrity without a separate round-trip.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aimw.api.deps import (
    PackagesRepoDep,
    RequestIdDep,
    RequireAnalyst,
    VideosRepoDep,
)
from aimw.custody import seal, verify_chain
from aimw.reasoning import regulations as reg_catalog
from aimw.reasoning.referee import run as referee_run
from aimw.reasoning.stub import ReasoningStub
from aimw.scoring.engine import score as compute_score
from aimw.scoring.registry import register

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("/{video_id}")
async def get_case(
    video_id: str,
    request_id: RequestIdDep,
    _user: RequireAnalyst,
    videos: VideosRepoDep,
    packages: PackagesRepoDep,
) -> dict:
    """Return a tamper-evident, statute-annotated case file for one video.

    The ``chain_root`` field is a SHA-256 commitment over all evidence
    pieces in order.  Verification: re-run ``verify_chain(response)``
    locally — any modification to any field breaks the root.
    """
    register()

    video_row = await videos.get(video_id)
    if video_row is None:
        raise HTTPException(status_code=404, detail=f"video {video_id!r} not found")

    pkg_rows = await packages.list_by_video(video_id)
    if not pkg_rows:
        raise HTTPException(
            status_code=404,
            detail=f"no evidence package for video {video_id!r}",
        )

    latest_row = pkg_rows[-1]
    pkg = await packages.get(latest_row.report_id)
    if pkg is None:
        raise HTTPException(status_code=500, detail="package blob missing")

    # Score the package (deterministic, no LLM).
    breakdown = compute_score(pkg)

    # Prefer the stored projection (includes LLM judge verdict when available).
    proj = await packages.get_projection(latest_row.report_id)
    final_score = proj["score"] if proj and proj.get("score") is not None else breakdown.final_score
    risk_level = proj["risk_level"] if proj and proj.get("risk_level") else breakdown.level
    confidence = proj.get("confidence") if proj else None
    action = proj.get("action") if proj else None
    verdict = str(risk_level)

    # Load regulation catalog and seal.
    regs = reg_catalog.load()
    case_file = seal(
        package=pkg,
        final_score=final_score,
        risk_level=str(risk_level),
        verdict=verdict,
        confidence=confidence,
        regulations=regs,
    )

    # Inline verification — proves integrity to the caller immediately.
    verify_ok, verify_reason = verify_chain(case_file)

    case_file["verify_ok"] = verify_ok
    case_file["verify_reason"] = verify_reason
    case_file["action"] = action
    case_file["request_id"] = request_id

    return case_file


__all__ = ["router"]
