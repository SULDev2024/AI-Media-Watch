"""POST /api/v1/ingest/url — enqueue a URL for the Phase 13 worker.

The route composes the existing ingest_queue table; no business logic
lives here. The route MUST accept ``file://`` URLs because Phase 12's
acceptance criterion 2 requires that test fixtures use a ``file://`` URL
for the end-to-end test ("POST /api/v1/ingest/url for a pre-fixtured
local file (using a file:// URL for tests) returns 202").

For ``http``/``https`` URLs we still run the v1 SSRF allow-list check
(reusing :mod:`aimw.api.url_validation`).  The ``file://`` scheme is
allowed unconditionally — this endpoint is the documented test fixture
path.  Operators must restrict access via the auth layer or network
ACLs.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from aimw.api.deps import RequestIdDep, RequireAnalyst, SessionmakerDep
from aimw.api.url_validation import URLValidationError, validate_ingest_url
from aimw.api.v1.schemas import IngestRequest, IngestResponse
from aimw.core.config import get_settings
from aimw.workers.enqueue import classify_platform as _classify_platform
from aimw.workers.enqueue import enqueue_prepared, enqueue_video_url

router = APIRouter(prefix="/ingest", tags=["ingest"])

_ALLOWED_SCHEMES = ("http", "https", "file")


def _ssrf_check(url: str) -> None:
    """Apply the SSRF allow-list to http(s) URLs only."""
    scheme = (urlsplit(url).scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=422,
            detail=f"scheme {scheme!r} not allowed; only http, https, file",
        )
    if scheme == "file":
        return  # spec-required path for tests; no allow-list check
    platform = _classify_platform(url)
    if platform not in ("youtube", "telegram", "tiktok", "instagram"):
        raise HTTPException(
            status_code=422,
            detail=(
                f"host {urlsplit(url).hostname!r} not on the platform allow-list "
                "(youtube/telegram/tiktok/instagram)"
            ),
        )
    try:
        validate_ingest_url(url, platform)
    except URLValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/url", status_code=status.HTTP_202_ACCEPTED, response_model=IngestResponse)
async def ingest_url(
    body: IngestRequest,
    sm: SessionmakerDep,
    request_id: RequestIdDep,
    _user: RequireAnalyst,
) -> IngestResponse:
    """Enqueue a URL for analysis. Returns 202 with the derived ``video_id``.

    Phase 13 wiring:

    1. Validate the URL (SSRF allow-list).
    2. Upsert a ``videos`` row keyed by the derived ``video_id``.
    3. Write the ``ingest_queue`` row.
    4. Enqueue ``process_video.delay(video_id)`` so the worker picks it
       up.  Broker failures are best-effort: the queue row is the
       authoritative source of work, and the CLI / next beat tick will
       drain anything the broker missed.
    """
    _ssrf_check(body.url)

    # Shared path: derive id, upsert the video, write the queue row, and
    # best-effort kick the worker. The collector uses the same helper.
    video_id, queue_id = await enqueue_video_url(sm, body.url)
    assert queue_id is not None  # route never sets skip_if_exists

    return IngestResponse(
        video_id=video_id,
        status="pending",
        request_id=request_id,
        queue_id=queue_id,
    )


# ---------------------------------------------------------------------------
# Manual ingest — paste text, drop an image, upload a video, or paste a link.
# ---------------------------------------------------------------------------

_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB cap per uploaded file
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}
_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}


def _vid_from_bytes(data: bytes) -> str:
    return f"vid-{hashlib.sha256(data).hexdigest()[:16]}"


@router.post(
    "/manual", status_code=status.HTTP_202_ACCEPTED, response_model=IngestResponse
)
async def ingest_manual(
    sm: SessionmakerDep,
    request_id: RequestIdDep,
    _user: RequireAnalyst,
    text: Annotated[str | None, Form()] = None,
    url: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> IngestResponse:
    """Analyze a manually supplied input: text, image, video, or link.

    Exactly one of ``text``, ``url``, or ``file`` must be provided. Text and
    files are written to the media dir with a suffix the pipeline recognises,
    then enqueued through the same worker that processes crawled videos.
    """
    provided = [p for p in (text, url, file) if p]
    if len(provided) != 1:
        raise HTTPException(
            status_code=422,
            detail="provide exactly one of: text, url, file",
        )

    # 1) Link → reuse the validated URL path.
    if url:
        _ssrf_check(url)
        video_id, queue_id = await enqueue_video_url(sm, url)
        assert queue_id is not None
        return IngestResponse(
            video_id=video_id, status="pending", request_id=request_id, queue_id=queue_id
        )

    media_dir = get_settings().resolved_media_dir
    media_dir.mkdir(parents=True, exist_ok=True)

    # 2) Pasted text → a one-segment transcript the scoring engine reads.
    if text:
        cleaned = text.strip()
        if not cleaned:
            raise HTTPException(status_code=422, detail="text is empty")
        video_id = f"vid-{hashlib.sha256(cleaned.encode('utf-8')).hexdigest()[:16]}"
        path = media_dir / f"{video_id}.manual.txt"
        path.write_text(cleaned, encoding="utf-8")
        label = f"manual:text · {cleaned[:60]}"
        _vid, queue_id = await enqueue_prepared(
            sm, video_id=video_id, url=label, platform="manual", raw_path=str(path)
        )
        return IngestResponse(
            video_id=video_id, status="pending", request_id=request_id, queue_id=queue_id
        )

    # 3) Uploaded file → image (OCR) or video (full pipeline) by extension.
    assert file is not None
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="uploaded file is empty")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file exceeds 200 MB limit")

    ext = Path(file.filename or "").suffix.lower()
    if ext in _IMAGE_EXTS:
        platform, kind_ext = "manual-image", f".manual{ext}"
    elif ext in _VIDEO_EXTS:
        platform, kind_ext = "manual-video", ext
    else:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported file type {ext!r}; images or videos only",
        )

    video_id = _vid_from_bytes(data)
    path = media_dir / f"{video_id}{kind_ext}"
    path.write_bytes(data)
    label = f"{platform} · {file.filename}"
    _vid, queue_id = await enqueue_prepared(
        sm, video_id=video_id, url=label, platform=platform, raw_path=str(path)
    )
    return IngestResponse(
        video_id=video_id, status="pending", request_id=request_id, queue_id=queue_id
    )


__all__ = ["router"]
