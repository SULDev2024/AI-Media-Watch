"""Public alerts endpoint — no auth required.

Returns HIGH/CRITICAL detections so the mobile app can display them
without needing login credentials. Includes a detail endpoint for
full report, transcript, and evidence.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from aimw.api.deps import RequestIdDep, SessionmakerDep

router = APIRouter(prefix="/public", tags=["public"])


class AlertItem(BaseModel):
    video_id: str
    title: str
    level: str
    score: float
    platform: str
    url: str
    action: str | None = None
    summary: str | None = None
    collected_at: str


class AlertsResponse(BaseModel):
    alerts: list[AlertItem]
    total: int


class EvidenceItem(BaseModel):
    signal: str
    weight: float
    polarity: str
    detail: str | None = None


class AlertDetail(BaseModel):
    video_id: str
    title: str
    level: str
    score: float
    confidence: float | None = None
    platform: str
    url: str
    action: str | None = None
    collected_at: str
    report_markdown: str | None = None
    transcript: str | None = None
    evidence: list[EvidenceItem] = []


@router.get("/alerts", response_model=AlertsResponse)
async def get_alerts(
    _request_id: RequestIdDep,
    sm: SessionmakerDep,
    limit: int = Query(default=200, ge=1, le=500),
) -> AlertsResponse:
    """Return HIGH/CRITICAL detections for the mobile app."""
    from sqlalchemy import text as sql_text

    async with sm() as session:
        rows = await session.execute(
            sql_text(
                "SELECT p.video_id, v.title, p.risk_level, p.score, "
                "v.platform, v.url, p.action, r.markdown, v.collected_at "
                "FROM evidence_packages p "
                "LEFT JOIN videos v ON v.id = p.video_id "
                "LEFT JOIN reports r ON r.report_id = p.report_id "
                "WHERE p.risk_level IN ('HIGH', 'CRITICAL') "
                "ORDER BY p.processed_at DESC "
                "LIMIT :lim"
            ),
            {"lim": limit},
        )
        results = rows.fetchall()

    alerts: list[AlertItem] = []
    for r in results:
        raw_title = r[1] or ""
        title = raw_title.split("\n")[0][:120] if raw_title else r[5] or r[0]

        summary = ""
        if r[7]:
            for line in r[7].split("\n"):
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    summary = stripped[:300]
                    break

        alerts.append(
            AlertItem(
                video_id=r[0],
                title=title,
                level=r[2],
                score=round(r[3], 4) if r[3] is not None else 0.0,
                platform=r[4] or "unknown",
                url=r[5] or "",
                action=r[6],
                summary=summary,
                collected_at=str(r[8]) if r[8] else "",
            )
        )

    return AlertsResponse(alerts=alerts, total=len(alerts))


@router.get("/alerts/{video_id}", response_model=AlertDetail)
async def get_alert_detail(
    video_id: str,
    _request_id: RequestIdDep,
    sm: SessionmakerDep,
) -> AlertDetail:
    """Full detail for one alert: report, transcript, evidence."""
    import json

    from sqlalchemy import text as sql_text

    async with sm() as session:
        row = await session.execute(
            sql_text(
                "SELECT p.video_id, v.title, p.risk_level, p.score, "
                "p.confidence, v.platform, v.url, p.action, "
                "v.collected_at, r.markdown, v.transcript_segments, "
                "p.package_json "
                "FROM evidence_packages p "
                "LEFT JOIN videos v ON v.id = p.video_id "
                "LEFT JOIN reports r ON r.report_id = p.report_id "
                "WHERE p.video_id = :vid "
                "AND p.risk_level IS NOT NULL AND p.risk_level != 'FAILED' "
                "ORDER BY p.processed_at DESC LIMIT 1"
            ),
            {"vid": video_id},
        )
        r = row.first()

    if r is None:
        raise HTTPException(404, detail="Alert not found")

    raw_title = r[1] or ""
    title = raw_title.split("\n")[0][:120] if raw_title else r[6] or r[0]

    transcript = None
    if r[10]:
        try:
            segs = json.loads(r[10])
            if isinstance(segs, list):
                transcript = "\n".join(
                    s.get("text", "") if isinstance(s, dict) else str(s)
                    for s in segs
                )
            elif isinstance(segs, str):
                transcript = segs
        except (json.JSONDecodeError, TypeError):
            transcript = str(r[10])

    evidence: list[EvidenceItem] = []
    if r[11]:
        try:
            pkg = json.loads(r[11])
            ev_list = pkg.get("evidence", [])
            for e in ev_list:
                evidence.append(
                    EvidenceItem(
                        signal=e.get("signal", ""),
                        weight=e.get("weight", 0),
                        polarity=e.get("polarity", "neutral"),
                        detail=e.get("detail"),
                    )
                )
        except (json.JSONDecodeError, TypeError):
            pass

    return AlertDetail(
        video_id=r[0],
        title=title,
        level=r[2],
        score=round(r[3], 4) if r[3] is not None else 0.0,
        confidence=round(r[4], 4) if r[4] is not None else None,
        platform=r[5] or "unknown",
        url=r[6] or "",
        action=r[7],
        collected_at=str(r[8]) if r[8] else "",
        report_markdown=r[9],
        transcript=transcript,
        evidence=evidence,
    )


__all__ = ["router"]
