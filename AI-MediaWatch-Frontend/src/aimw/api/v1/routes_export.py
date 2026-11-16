"""CSV export endpoint for reports."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from aimw.api.deps import RequestIdDep, RequireAnalyst, SessionmakerDep

router = APIRouter(prefix="/reports", tags=["export"])


@router.get("/export")
async def export_reports_csv(
    _request_id: RequestIdDep,
    _user: RequireAnalyst,
    sm: SessionmakerDep,
) -> StreamingResponse:
    """Export all evidence packages as CSV."""
    from sqlalchemy import text

    async with sm() as session:
        rows = await session.execute(
            text(
                "SELECT p.video_id, v.platform, v.url, v.collected_at, "
                "p.risk_level, p.score, p.action, p.processed_at "
                "FROM evidence_packages p "
                "LEFT JOIN videos v ON v.id = p.video_id "
                "WHERE p.risk_level IS NOT NULL AND p.risk_level != 'FAILED' "
                "ORDER BY p.processed_at DESC"
            )
        )
        results = rows.fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "video_id", "platform", "url", "collected_at",
        "risk_level", "score", "action", "processed_at",
    ])
    for r in results:
        writer.writerow(list(r))

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=aimw_reports.csv"},
    )


__all__ = ["router"]
