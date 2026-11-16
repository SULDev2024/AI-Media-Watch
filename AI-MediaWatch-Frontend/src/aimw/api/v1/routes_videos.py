"""GET /api/v1/videos and GET /api/v1/videos/{video_id}.

Composes ``VideosRepository`` and ``PackagesRepository``. The list view
supports ``limit``, ``since`` (ISO datetime), and ``level`` filters per
the Phase 12 spec.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from aimw.api.deps import (
    PackagesRepoDep,
    RequestIdDep,
    RequireAnalyst,
    VideosRepoDep,
    SessionmakerDep,
)
from aimw.api.v1.schemas import VideoDetail, VideosList, VideoSummary
from aimw.scoring.registry import register

_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_VIDEO_EXT = {".mp4", ".webm", ".avi", ".mov", ".mkv", ".flv"}
_TEXT_EXT  = {".txt", ".text"}


def _content_type(platform: str, raw_path: str | None) -> str:
    """Derive whether this entry is a video, photo, or text."""
    p = (platform or "").lower()
    if p == "manual-image":
        return "photo"
    if p in ("manual", "manual-text"):
        return "text"
    if raw_path:
        from pathlib import PurePosixPath
        ext = PurePosixPath(raw_path).suffix.lower()
        if ext in _PHOTO_EXT:
            return "photo"
        if ext in _TEXT_EXT:
            return "text"
        if ext in _VIDEO_EXT:
            return "video"
    if p in ("youtube", "tiktok", "instagram", "manual-video"):
        return "video"
    if p == "telegram":
        return "video"  # telegram collector defaults to video; text items have .txt raw_path
    return "video"


_HARM_WEIGHT: dict[str, float] = {
    "CRITICAL": 1.0,
    "HIGH": 0.80,
    "MEDIUM": 0.50,
    "LOW": 0.20,
    "CLEAN": 0.0,
}


def _priority(risk_level: str | None, confidence: float | None) -> float | None:
    """Harm-weighted triage score: severity × confidence.

    Regulators see the highest-harm, highest-certainty videos first.
    """
    if risk_level is None:
        return None
    hw = _HARM_WEIGHT.get(str(risk_level).upper(), 0.0)
    conf = confidence if confidence is not None else 0.5
    return round(hw * conf, 3)

router = APIRouter(prefix="/videos", tags=["videos"])


@router.post('/{video_id}/cancel')
async def cancel_video_job(video_id: str, _user: RequireAnalyst, sm: SessionmakerDep) -> dict:
    from aimw.core.config import get_settings
    from aimw.workers.cancellation import cancel_video
    if not get_settings().eager:
        raise HTTPException(status_code=409, detail='Live cancellation currently requires local (AIMW_EAGER=1) mode.')
    try:
        await cancel_video(sm, video_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {'video_id': video_id, 'status': 'cancelled'}


@router.get("", response_model=VideosList)
async def list_videos(
    request_id: RequestIdDep,
    _user: RequireAnalyst,
    videos: VideosRepoDep,
    packages: PackagesRepoDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    since: Annotated[dt.datetime | None, Query()] = None,
    level: Annotated[str | None, Query()] = None,
) -> VideosList:
    """List recent videos with optional filters."""
    register()  # ensure scoring is wired so computed fields populate
    rows = await videos.list_recent(limit=limit)
    items: list[VideoSummary] = []
    for r in rows:
        if since is not None and r.collected_at < since:
            continue
        pkgs = await packages.list_by_video(r.id)
        # Prefer the stored verdict projection (LLM judge when available, else
        # rule-based) so the queue matches the report page; fall back to the
        # package's computed score for older rows with no projection.
        score: float | None = None
        risk_level: str | None = None
        confidence: float | None = None
        action: str | None = None
        if pkgs:
            latest = pkgs[-1]
            proj = await packages.get_projection(latest.report_id)
            if proj is not None and proj.get("risk_level") is not None:
                score = round(proj["score"], 4) if proj["score"] is not None else None
                risk_level = proj["risk_level"]
                confidence = proj["confidence"]
                action = proj["action"]
            else:
                score = round(latest.score, 4)
                risk_level = latest.risk_level
        if not pkgs:
            failure = await packages.latest_failure(r.id)
            if failure:
                risk_level, action = ("CANCELLED", "cancelled") if failure == "Cancelled by user." else ("FAILED", "failed")
        if level is not None and risk_level != level:
            continue
        n_evidence = 0
        if pkgs:
            try:
                n_evidence = sum(
                    1 for e in pkgs[-1].evidence
                    if e.polarity == "incriminating"
                )
            except Exception:
                pass

        items.append(
            VideoSummary(
                video_id=r.id,
                platform=r.platform,
                url=r.url,
                collected_at=r.collected_at,
                score=score,
                level=risk_level,
                confidence=confidence,
                action=action,
                priority_score=_priority(risk_level, confidence),
                content_type=_content_type(r.platform, r.raw_path),
                title=(r.title.split("\n")[0][:120] if r.title else None),
                evidence_count=n_evidence,
            )
        )
    # Sort by priority descending so the highest-risk videos surface first.
    items.sort(key=lambda v: (v.priority_score or 0.0), reverse=True)
    return VideosList(
        items=items,
        total=len(items),
        limit=limit,
        request_id=request_id,
    )


@router.get("/{video_id}", response_model=VideoDetail)
async def get_video(
    video_id: str,
    request_id: RequestIdDep,
    _user: RequireAnalyst,
    videos: VideosRepoDep,
    packages: PackagesRepoDep,
) -> VideoDetail:
    """Return metadata and linked package ids for one video."""
    row = await videos.get(video_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"video {video_id!r} not found")
    pkgs = await packages.list_by_video(video_id)
    failure = await packages.latest_failure(video_id) if not pkgs else None
    from aimw.core.config import get_settings
    from aimw.extraction.ocr.cache import OcrCache
    from aimw.extraction.ocr.models import OcrResult
    ocr_text = None
    ocr_path = OcrCache(get_settings().resolved_ocr_cache_dir).path_for(row.id)
    if ocr_path.exists():
        try:
            ocr = OcrResult.model_validate_json(ocr_path.read_text(encoding="utf-8"))
            ocr_text = "\n".join(dict.fromkeys(
                block.text for frame in ocr.frames for block in frame.blocks if block.text.strip()
            ))
        except (ValueError, OSError):
            pass
    return VideoDetail(
        video_id=row.id,
        platform=row.platform,
        url=row.url,
        collected_at=row.collected_at,
        language_hint=row.language_hint,
        raw_path=row.raw_path,
        package_ids=[p.report_id for p in pkgs],
        transcript_segments=row.transcript_segments,
        ocr_text=ocr_text,
        request_id=request_id,
        status="complete" if pkgs else "failed" if failure else "pending",
        error=failure,
    )


__all__ = ["router"]
