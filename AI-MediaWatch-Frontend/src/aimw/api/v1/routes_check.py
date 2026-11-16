"""Public user-facing check endpoint — no auth required.

Users submit a URL or text via the PWA / Telegram bot and poll for
the verdict. Rate-limited by IP (simple in-memory counter).
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from aimw.api.deps import RequestIdDep, SessionmakerDep
from aimw.api.rate_limit import check_rate_limit
from aimw.workers.enqueue import classify_platform, enqueue_video_url

router = APIRouter(prefix="/check", tags=["check"])

_ALLOWED_PLATFORMS = ("youtube", "telegram", "tiktok", "instagram")


class CheckRequest(BaseModel):
    url: str | None = None
    text: str | None = None
    urls: list[str] | None = None


class CheckResponse(BaseModel):
    video_id: str
    status: str


class BatchCheckResponse(BaseModel):
    results: list[CheckResponse]


class CheckResult(BaseModel):
    video_id: str
    risk_level: str | None = None
    risk_score: float | None = None
    summary: str | None = None
    recommended_action: str | None = None
    status: str = "pending"
    report: str | None = None
    transcript: str | None = None


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=CheckResponse)
async def submit_check(
    body: CheckRequest,
    sm: SessionmakerDep,
    request_id: RequestIdDep,
    request: Request,
) -> CheckResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Try again in a minute.")

    if body.url and body.text:
        raise HTTPException(status_code=422, detail="Provide url OR text, not both.")
    if not body.url and not body.text:
        raise HTTPException(status_code=422, detail="Provide a url or text to check.")

    if body.url:
        url = body.url.strip()
        scheme = (urlsplit(url).scheme or "").lower()
        if scheme not in ("http", "https"):
            raise HTTPException(status_code=422, detail="Only http/https URLs are accepted.")
        platform = classify_platform(url)
        if platform not in _ALLOWED_PLATFORMS:
            raise HTTPException(
                status_code=422,
                detail="URL must be from YouTube, Telegram, TikTok, or Instagram.",
            )
        video_id, _queue_id = await enqueue_video_url(sm, url)
        return CheckResponse(video_id=video_id, status="pending")

    import hashlib

    from aimw.core.config import get_settings
    from aimw.workers.enqueue import enqueue_prepared

    text = (body.text or "").strip()
    if len(text) < 10:
        raise HTTPException(status_code=422, detail="Text too short (min 10 chars).")
    vid = f"vid-{hashlib.sha256(text.encode()).hexdigest()[:16]}"
    media_dir = get_settings().resolved_media_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    path = media_dir / f"{vid}.manual.txt"
    path.write_text(text, encoding="utf-8")
    await enqueue_prepared(
        sm, video_id=vid, url="check:text", platform="manual", raw_path=str(path)
    )
    return CheckResponse(video_id=vid, status="pending")


class HistoryItem(BaseModel):
    video_id: str
    input_type: str
    input_value: str
    risk_level: str | None = None
    risk_score: float | None = None
    created_at: str


class HistoryResponse(BaseModel):
    items: list[HistoryItem]


@router.post("/batch", status_code=status.HTTP_202_ACCEPTED, response_model=BatchCheckResponse)
async def batch_check(
    body: CheckRequest,
    sm: SessionmakerDep,
    request_id: RequestIdDep,
    request: Request,
) -> BatchCheckResponse:
    """Submit multiple URLs for analysis at once."""
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip, limit=5):
        raise HTTPException(status_code=429, detail="Too many requests.")

    urls = body.urls or []
    if not urls:
        raise HTTPException(status_code=422, detail="Provide a list of urls.")
    if len(urls) > 20:
        raise HTTPException(status_code=422, detail="Maximum 20 URLs per batch.")

    results: list[CheckResponse] = []
    for url in urls:
        url = url.strip()
        scheme = (urlsplit(url).scheme or "").lower()
        if scheme not in ("http", "https"):
            continue
        platform = classify_platform(url)
        if platform not in _ALLOWED_PLATFORMS:
            continue
        try:
            video_id, _ = await enqueue_video_url(sm, url)
            results.append(CheckResponse(video_id=video_id, status="pending"))
        except Exception:
            pass

    return BatchCheckResponse(results=results)


@router.get("/history/{session_id}", response_model=HistoryResponse)
async def get_check_history(
    session_id: str,
    sm: SessionmakerDep,
) -> HistoryResponse:
    """Get check history for a session."""
    from sqlalchemy import text

    async with sm() as session:
        rows = await session.execute(
            text(
                "SELECT video_id, input_type, input_value, risk_level, risk_score, created_at "
                "FROM check_history WHERE session_id = :sid "
                "ORDER BY created_at DESC LIMIT 50"
            ),
            {"sid": session_id},
        )
        items = [
            HistoryItem(
                video_id=r[0],
                input_type=r[1],
                input_value=r[2][:200],
                risk_level=r[3],
                risk_score=r[4],
                created_at=str(r[5]),
            )
            for r in rows
        ]
    return HistoryResponse(items=items)


@router.get("/{video_id}", response_model=CheckResult)
async def get_check_result(
    video_id: str,
    sm: SessionmakerDep,
) -> CheckResult:
    from sqlalchemy import text

    async with sm() as session:
        # Always check evidence_packages first — ingest_queue.status stays
        # "pending" in EAGER mode (never updated by the task), so checking
        # queue status first would hide completed results.
        row = await session.execute(
            text(
                "SELECT p.risk_level, p.score, p.action, r.markdown, "
                "v.transcript_segments "
                "FROM evidence_packages p "
                "LEFT JOIN reports r ON r.report_id = p.report_id "
                "LEFT JOIN videos v ON v.id = p.video_id "
                "WHERE p.video_id = :vid "
                "ORDER BY p.processed_at DESC LIMIT 1"
            ),
            {"vid": video_id},
        )
        result = row.first()
        if result and result[0] and result[0] != "FAILED":  # real verdict (not FAILED = still-processing)
            summary = ""
            if result[3]:
                _skip = ("**Report ID**", "**Video ID**", "**Platform**",
                         "**URL**", "**Collected**", "**Processed**",
                         "| Field", "| ---", "| Risk", "| Confidence",
                         "| Action", "| Status", "_schema_version")
                lines = result[3].split("\n")
                for line in lines:
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    if any(s.startswith(p) for p in _skip):
                        continue
                    summary = s[:200]
                    break
            if not summary:
                level = result[0] or "UNKNOWN"
                score_pct = round((result[1] or 0) * 100)
                summary = f"Risk: {level} ({score_pct}%) - {result[2] or 'review'}"

            transcript = None
            if result[4]:
                import json as _json
                try:
                    segs = _json.loads(result[4])
                    if isinstance(segs, list):
                        transcript = "\n".join(
                            s.get("text", "") if isinstance(s, dict) else str(s)
                            for s in segs
                        )
                    elif isinstance(segs, str):
                        transcript = segs
                except (ValueError, TypeError):
                    transcript = str(result[4])

            return CheckResult(
                video_id=video_id,
                risk_level=result[0],
                risk_score=result[1],
                summary=summary,
                recommended_action=result[2],
                status="done",
                report=result[3],
                transcript=transcript,
            )

        from aimw.db.repositories.packages import PackagesRepository
        failure = await PackagesRepository(sm).latest_failure(video_id)
        if failure:
            return CheckResult(video_id=video_id, status="failed", summary=failure)

        # No finished package yet — report queue status so frontend can poll
        q = await session.execute(
            text(
                "SELECT status FROM ingest_queue "
                "WHERE payload LIKE :pat "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"pat": f"%{video_id}%"},
        )
        qrow = q.first()
        if qrow:
            return CheckResult(video_id=video_id, status=qrow[0] or "pending")

    raise HTTPException(status_code=404, detail="Check not found.")


__all__ = ["router"]
