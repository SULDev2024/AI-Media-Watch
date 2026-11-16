"""POST /api/v1/investigate/{video_id} — run the 9-agent investigation cell.

Runs the full hub-and-spoke cell in-process (demo-reliable; no Redis/Celery
required) and returns the complete case state: every agent's structured report,
the append-only journal, and the deterministic firewall verdict + sealed chain.

GET /api/v1/investigate/roster returns the stable 9-agent roster so the
dashboard can render the cell before a run starts.
"""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException

from aimw.agents.orchestrator import ROSTER, build_context, investigate
from aimw.agents.state import CaseState
from aimw.api.deps import (
    PackagesRepoDep,
    RequestIdDep,
    RequireAnalyst,
    SessionmakerDep,
    UsageRepoDep,
    VideosRepoDep,
)
from aimw.core.config import get_settings
from aimw.scoring.registry import register

router = APIRouter(prefix="/investigate", tags=["investigate"])


def _build_llm_client(usage_repo):  # type: ignore[no-untyped-def]
    """Construct the LLM client if a key resolves, else None (deterministic cell)."""
    if os.environ.get("AIMW_USE_REASONING_STUB", "").lower() in {"1", "true", "yes", "on"}:
        return None
    settings = get_settings()
    if settings.resolved_llm_api_key is None and settings.llm_require_auth:
        return None
    try:
        from aimw.reasoning.client import build_chat_client

        return build_chat_client(usage_repo, settings)
    except Exception:
        return None


def _transcript_text(transcript_segments: str | None) -> str:
    if not transcript_segments:
        return ""
    try:
        segs = json.loads(transcript_segments)
        if isinstance(segs, list):
            return " ".join(s.get("text", "") for s in segs if isinstance(s, dict)).strip()
    except Exception:
        pass
    return str(transcript_segments)


@router.get("/roster")
async def get_roster(request_id: RequestIdDep, _user: RequireAnalyst) -> dict:
    """Return the stable 9-agent roster for the dashboard."""
    return {"roster": ROSTER, "request_id": request_id}


@router.post("/{video_id}")
async def run_investigation(
    video_id: str,
    request_id: RequestIdDep,
    _user: RequireAnalyst,
    sm: SessionmakerDep,
    videos: VideosRepoDep,
    packages: PackagesRepoDep,
    usage: UsageRepoDep,
) -> dict:
    """Run the full investigation cell over one video and return the case state."""
    register()

    video_row = await videos.get(video_id)
    if video_row is None:
        raise HTTPException(status_code=404, detail=f"video {video_id!r} not found")

    pkg_rows = await packages.list_by_video(video_id)
    if not pkg_rows:
        raise HTTPException(status_code=404, detail=f"no evidence package for video {video_id!r}")

    latest = pkg_rows[-1]
    pkg = await packages.get(latest.report_id)
    if pkg is None:
        raise HTTPException(status_code=500, detail="package blob missing")
    projection = await packages.get_projection(latest.report_id)

    transcript = _transcript_text(video_row.transcript_segments)

    state = CaseState(
        video_id=video_id,
        report_id=latest.report_id,
        platform=pkg.platform,
        url=pkg.url,
        transcript=transcript,
        package=pkg,
        projection=projection,
    )

    client = _build_llm_client(usage)
    ctx = build_context(client, sm)
    await investigate(state, ctx)

    out = state.to_public()
    out["llm_used"] = client is not None
    out["request_id"] = request_id
    return out


__all__ = ["router"]
