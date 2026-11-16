"""End-to-end video processing pipeline (Phase 13).

Composes Phase 5–11 services for one video and persists every artefact.
This module owns NO business logic — every stage delegates to an
existing service. Workers (Celery tasks, eager CLI) call
:func:`run_pipeline`; the function is ``async`` so the only sync→async
bridge in the system is :func:`aimw.workers.runner.run_async`.

Failure semantics (acceptance criterion 5):

* Each stage runs inside a ``try`` block.
* On any extractor / scoring / reasoning exception the package is
  persisted with ``status="failed"`` (the canonical blob carries an
  ``error`` field with the exception type and message).
* The route surfaces failed videos via the existing report endpoints.

Fixture mode for testing:

* If the video's ``raw_path`` ends in ``.fixture.json`` and exists on
  disk, the pipeline reads pre-canned ``transcript`` and ``ocr``
  payloads from that file instead of running Whisper/PaddleOCR.  This
  is the only test-only hook in the pipeline; it cannot be triggered
  in production because operators do not produce ``.fixture.json``
  files in normal ingest paths.

Token-budget behaviour (acceptance criterion 4):

* The pipeline picks the briefs provider via :func:`_select_briefs_provider`.
  When no Groq key is configured the provider raises
  :class:`aimw.reasoning.client.TokenBudgetExhausted` immediately,
  which routes through the referee's documented fallback and yields
  ``action="analyst_review"`` with no LLM calls.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from aimw.workers.cancellation import JobCancelled, check_cancelled, event_for
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from aimw.core.config import get_settings
from aimw.core.schema import (
    EvidencePackage,
    EvidencePiece,
    ExtractedEntities,
)
from aimw.db.models import EvidencePackageRow, ReportRow, Video
from aimw.db.repositories.packages import PackagesRepository
from aimw.db.session import get_sessionmaker, writer_lock
from aimw.extraction.ocr.models import OcrBlock, OcrFrameResult, OcrResult
from aimw.extraction.whisper.models import Segment, Transcript
from aimw.reasoning.client import TokenBudgetExhausted
from aimw.reasoning.referee import BriefProvider, RefereeResult
from aimw.reasoning.referee import run as referee_run
from aimw.reasoning.stub import ReasoningStub
from aimw.report.generator import render_markdown
from aimw.scoring.registry import register
from aimw.scoring.signals import tag as tag_signals

_LOG = logging.getLogger("aimw.workers.pipeline")

# Sentinel suffix that switches the pipeline into fixture mode.
_FIXTURE_SUFFIX = ".fixture.json"

# Manual-input markers encoded in the saved file name so the existing
# ``process_video`` task and report pipeline are reused verbatim — only the
# extraction stage branches. A ``.manual.txt`` file holds pasted text; a
# ``.manual.<img>`` file is a single uploaded image to OCR.
_MANUAL_TEXT_SUFFIX = ".manual.txt"
_MANUAL_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff")


# ---------------------------------------------------------------------------
# Custom errors
# ---------------------------------------------------------------------------


class PipelineError(Exception):
    """Base for any pipeline-stage failure."""


class VideoNotFoundError(PipelineError):
    """Raised when the queued video id is missing from the Video table."""


# ---------------------------------------------------------------------------
# Briefs providers
# ---------------------------------------------------------------------------


class _TokenBudgetExhaustedProvider:
    """Briefs provider that always raises TokenBudgetExhausted.

    Used when no Groq key is configured (acceptance criterion 1: "or
    analyst_review action if no GROQ key") and when the daily usage is
    above the configured cap (acceptance criterion 4).
    """

    async def prosecutor(self, pkg: EvidencePackage) -> Any:
        raise TokenBudgetExhausted("no Groq key or daily cap reached")

    async def defense(self, pkg: EvidencePackage) -> Any:
        raise TokenBudgetExhausted("no Groq key or daily cap reached")


async def _select_briefs_provider() -> BriefProvider:
    """Pick the briefs provider for this run (async — runs inside pipeline loop).

    * ``AIMW_USE_REASONING_STUB=1`` → :class:`ReasoningStub` (deterministic
      tests; produces real briefs without burning Groq tokens).
    * ``AIMW_LLM_PROVIDER=local`` → :class:`LiveBriefProvider` via the
      sovereign on-prem LLM (Ollama). No Groq key needed.
    * No Groq key → ``_TokenBudgetExhaustedProvider`` (forces
      ``analyst_review`` action; acceptance criterion 1).
    * Groq key set but daily usage near the cap (acceptance criterion 4)
      → ``_TokenBudgetExhaustedProvider``.
    * Otherwise → :class:`LiveBriefProvider` (live Groq briefs).
    """
    import datetime as _dt
    settings = get_settings()

    if os.environ.get("AIMW_FAST_ANALYSIS") == "1":
        return ReasoningStub()

    if os.environ.get("AIMW_USE_REASONING_STUB") == "1":
        return ReasoningStub()

    # Local LLM (Ollama) — skip Groq key/budget checks entirely
    if settings.llm_provider == "local":
        from aimw.db.repositories.usage import UsageRepository
        from aimw.reasoning.client import build_chat_client
        from aimw.reasoning.live import LiveBriefProvider

        client = build_chat_client(UsageRepository(get_sessionmaker()))
        return LiveBriefProvider(client)

    groq_key = settings.groq_api_key
    if groq_key is None or not groq_key.get_secret_value():
        return _TokenBudgetExhaustedProvider()

    try:
        from aimw.db.repositories.usage import UsageRepository

        usage = UsageRepository(get_sessionmaker())
        remaining = await usage.remaining(
            _dt.date.today(),
            settings.groq_model,
            settings.groq_daily_token_cap,
        )
        if remaining < settings.groq_request_token_budget * 2:
            return _TokenBudgetExhaustedProvider()
    except Exception:
        _LOG.warning(
            "token budget probe failed; falling back to stub", exc_info=True
        )
        return ReasoningStub()

    from aimw.db.repositories.usage import UsageRepository
    from aimw.reasoning.client import build_chat_client
    from aimw.reasoning.live import LiveBriefProvider

    client = build_chat_client(UsageRepository(get_sessionmaker()))
    return LiveBriefProvider(client)


# ---------------------------------------------------------------------------
# Extraction stage — fixture-aware
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ExtractionPayload:
    transcript: Transcript
    ocr: OcrResult
    vision_description: str = ""
    gpu_verdict: Any = None


def _load_fixture(path: Path, video_id: str) -> _ExtractionPayload:
    """Load a pre-canned transcript + OCR result from a fixture JSON."""
    blob = json.loads(path.read_text(encoding="utf-8"))
    transcript = Transcript.model_validate(blob["transcript"])
    ocr = OcrResult.model_validate(blob["ocr"])
    _LOG.info(
        "fixture_loaded",
        extra={"video_id": video_id, "path": str(path)},
    )
    return _ExtractionPayload(transcript=transcript, ocr=ocr)


_MAX_MEDIA_BYTES = 500 * 1024 * 1024  # 500 MB — larger files OOM the Whisper model


async def _extract_real(path: Path, video_id: str) -> _ExtractionPayload:
    """Real-media extraction path — Whisper + (vision LLM or PaddleOCR).

    When ``llm_vision`` is enabled and a multimodal model is configured,
    video frames are sent directly to the vision model instead of running
    local PaddleOCR. Whisper and the vision call run in parallel for speed.
    Falls back to PaddleOCR if the vision call fails.
    """
    settings = get_settings()

    if settings.llm_vision:
        try:
            return await _extract_with_vision(path, video_id, settings)
        except Exception:
            _LOG.warning(
                "vision_extraction_failed_falling_back",
                extra={"video_id": video_id},
                exc_info=True,
            )

    return await _extract_legacy(path, video_id)


async def _extract_legacy(path: Path, video_id: str) -> _ExtractionPayload:
    """Original Whisper + PaddleOCR path (sequential)."""
    from aimw.extraction.ocr.cache import sha256_file as _sha256
    from aimw.extraction.whisper.transcriber import get_transcriber

    file_size = path.stat().st_size
    if file_size > _MAX_MEDIA_BYTES:
        _LOG.warning(
            "media_too_large_skip_whisper",
            extra={"video_id": video_id, "size_mb": file_size // (1024 * 1024)},
        )
        source_hash = _sha256(path)
        transcript = _empty_transcript(video_id, source_hash)
    else:
        transcriber = get_transcriber()
        transcript = await transcriber.transcribe(path, video_id)

    try:
        from aimw.extraction.ocr.engine import get_extractor
        ocr_result = await get_extractor().extract(path, video_id)
    except Exception:
        from aimw.extraction.ocr.cache import sha256_file
        ocr_result = OcrResult(
            engine="disabled",
            engine_version="0",
            source_file_sha256=sha256_file(path),
            video_id=video_id,
            frames=[],
            generated_at=dt.datetime.now(dt.UTC),
        )
    return _ExtractionPayload(transcript=transcript, ocr=ocr_result)


async def _extract_with_vision(
    path: Path, video_id: str, settings: Any,
) -> _ExtractionPayload:
    """Vision fast path — Whisper + vision LLM in parallel."""
    from aimw.db.repositories.usage import UsageRepository
    from aimw.extraction.ocr.cache import sha256_file as _sha256
    from aimw.extraction.vision import extract_with_vision
    from aimw.extraction.whisper.transcriber import get_transcriber
    from aimw.reasoning.client import build_chat_client

    client = build_chat_client(UsageRepository(get_sessionmaker()))

    async def _whisper() -> Transcript:
        file_size = path.stat().st_size
        if file_size > _MAX_MEDIA_BYTES:
            source_hash = _sha256(path)
            return _empty_transcript(video_id, source_hash)
        transcriber = get_transcriber()
        return await transcriber.transcribe(path, video_id)

    async def _vision():  # type: ignore[return]
        return await extract_with_vision(
            source_path=path,
            video_id=video_id,
            frame_cache_dir=settings.resolved_frame_cache_dir,
            vision_fn=client.complete_vision,
            model_name=settings.resolved_llm_model,
            scene_threshold=settings.scene_change_threshold,
            frames_per_3s=settings.frames_per_3s,
        )

    _LOG.info("vision_parallel_start", extra={"video_id": video_id})
    transcript, vision_result = await asyncio.gather(_whisper(), _vision())
    _LOG.info(
        "vision_parallel_done",
        extra={
            "video_id": video_id,
            "vision_chars": len(vision_result.vision_description),
        },
    )
    return _ExtractionPayload(
        transcript=transcript,
        ocr=vision_result.ocr_result,
        vision_description=vision_result.vision_description,
    )


def _is_manual_image(name: str) -> bool:
    lowered = name.lower()
    return ".manual." in lowered and lowered.endswith(_MANUAL_IMAGE_EXTS)


def _empty_ocr(video_id: str, source_hash: str) -> OcrResult:
    return OcrResult(
        engine="manual",
        engine_version="0",
        source_file_sha256=source_hash,
        video_id=video_id,
        frames=[],
        generated_at=dt.datetime.now(dt.UTC),
    )


def _empty_transcript(video_id: str, source_hash: str) -> Transcript:
    return Transcript(
        engine_version="manual",
        model="manual",
        device="manual",
        compute_type="manual",
        source_file_sha256=source_hash,
        video_id=video_id,
        language_detected="unknown",
        segments=[],
        generated_at=dt.datetime.now(dt.UTC),
    )


async def _prefetch_yt_metadata(video_row: Video) -> Video:
    """Fetch YouTube/TikTok title+description via yt-dlp info-only (no download).

    Updates the video row in the DB so the dashboard shows the real title.
    Returns a patched video_row with title set.
    """
    if video_row.title or video_row.platform not in ("youtube", "tiktok", "instagram"):
        return video_row  # already have it, or not a video platform

    def _fetch() -> tuple[str, str]:
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "skip_download": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video_row.url, download=False) or {}
                title = (info.get("title") or "")[:200]
                desc = (info.get("description") or "")[:600]
                return title, desc
        except Exception:
            return "", ""

    loop = asyncio.get_event_loop()
    title, desc = await loop.run_in_executor(None, _fetch)

    if title:
        # Patch the mutable DB row and update transcript field so we persist
        # the enriched context for the judge.
        from aimw.db.repositories.videos import VideosRepository
        sm = get_sessionmaker()
        async with sm() as session, session.begin():
            from sqlalchemy import update as sa_update
            from aimw.db.models import Video as _VideoModel
            await session.execute(
                sa_update(_VideoModel)
                .where(_VideoModel.id == video_row.id)
                .values(title=title)
            )
        # video_row is a detached SQLAlchemy model — set title directly.
        video_row.title = f"{title}\n{desc}".strip()
    return video_row


def _extract_fast_metadata(video_row: Video) -> _ExtractionPayload:
    """Seconds-fast URL triage: no download, no Whisper, no OCR."""
    title_field = getattr(video_row, 'title', '') or ''
    text = "\n".join(
        part
        for part in (
            f"Platform: {video_row.platform}",
            f"URL: {video_row.url}",
            f"Title/Description: {title_field}",
        )
        if part.strip()
    )
    source_hash = hashlib.sha256(
        f"{video_row.id}|{video_row.platform}|{video_row.url}|{text}".encode()
    ).hexdigest()
    transcript = Transcript(
        engine_version="fast-metadata",
        model="metadata",
        device="none",
        compute_type="none",
        source_file_sha256=source_hash,
        video_id=video_row.id,
        language_detected="unknown",
        segments=[Segment(start=0.0, end=0.0, text=text)],
        generated_at=dt.datetime.now(dt.UTC),
    )
    _LOG.info(
        "fast_metadata_extracted",
        extra={"video_id": video_row.id, "chars": len(text)},
    )
    return _ExtractionPayload(
        transcript=transcript,
        ocr=_empty_ocr(video_row.id, source_hash),
    )


def _extract_manual_text(path: Path, video_id: str) -> _ExtractionPayload:
    """Pasted text → a one-segment Transcript, no OCR. Same scoring half runs."""
    from aimw.extraction.ocr.cache import sha256_file

    text = path.read_text(encoding="utf-8")
    source_hash = sha256_file(path)
    transcript = Transcript(
        engine_version="manual",
        model="manual",
        device="manual",
        compute_type="manual",
        source_file_sha256=source_hash,
        video_id=video_id,
        language_detected="unknown",
        segments=[Segment(start=0.0, end=0.0, text=text)],
        generated_at=dt.datetime.now(dt.UTC),
    )
    _LOG.info("manual_text_extracted", extra={"video_id": video_id, "chars": len(text)})
    return _ExtractionPayload(transcript=transcript, ocr=_empty_ocr(video_id, source_hash))


async def _extract_manual_image(path: Path, video_id: str) -> _ExtractionPayload:
    """Uploaded image → OCR (one frame), no transcript. Same scoring half runs."""
    from aimw.extraction.ocr.cache import sha256_file
    from aimw.extraction.ocr.engine import get_extractor

    source_hash = sha256_file(path)
    blocks: list[OcrBlock] = []
    try:
        engine = get_extractor().engine
        blocks = await asyncio.to_thread(engine.recognize, path)
        engine_name, engine_version = engine.engine, engine.engine_version
    except Exception:
        _LOG.warning("manual_image_ocr_failed", extra={"video_id": video_id}, exc_info=True)
        engine_name, engine_version = "disabled", "0"

    ocr = OcrResult(
        engine=engine_name,
        engine_version=engine_version,
        source_file_sha256=source_hash,
        video_id=video_id,
        frames=[
            OcrFrameResult(
                frame_index=0, timestamp_s=0.0, image_path=str(path), blocks=blocks
            )
        ],
        generated_at=dt.datetime.now(dt.UTC),
    )
    _LOG.info("manual_image_extracted", extra={"video_id": video_id, "blocks": len(blocks)})
    return _ExtractionPayload(
        transcript=_empty_transcript(video_id, source_hash), ocr=ocr
    )


async def _extract(video_row: Video) -> _ExtractionPayload:
    """Decide between fixture, manual (text/image), and real extraction."""
    if not video_row.raw_path:
        raise PipelineError(
            f"video {video_row.id!r} has no raw_path; cannot extract"
        )
    path = Path(video_row.raw_path)
    if not path.exists():
        raise PipelineError(f"raw_path missing on disk: {path}")
    name = path.name
    if name.endswith(_FIXTURE_SUFFIX):
        return _load_fixture(path, video_row.id)
    if name.endswith(_MANUAL_TEXT_SUFFIX):
        return _extract_manual_text(path, video_row.id)
    if get_settings().gpu_pipeline_url:
        from aimw.workers.local_agent import analyze_file
        from aimw.extraction.ocr.cache import sha256_file
        settings = get_settings()
        data = await analyze_file(
            path, base_url=settings.gpu_pipeline_url,
            caption=getattr(video_row, "title", "") or "",
            platform=video_row.platform or "unknown",
            timeout_s=settings.gpu_pipeline_timeout_s,
        )
        source_hash = sha256_file(path)
        ocr = OcrResult(
            engine="easyocr", engine_version="local-agent-1",
            source_file_sha256=source_hash, video_id=video_row.id,
            generated_at=dt.datetime.now(dt.UTC),
            frames=[OcrFrameResult(
                frame_index=i, timestamp_s=frame["time"], image_path="",
                blocks=[OcrBlock.model_validate(block) for block in frame["blocks"]],
            ) for i, frame in enumerate(data.get("ocr_results", []))],
        )
        from aimw.extraction.ocr.cache import OcrCache
        await asyncio.to_thread(OcrCache(settings.resolved_ocr_cache_dir).save, ocr)
        transcript = _empty_transcript(video_row.id, source_hash).model_copy(update={
            "engine": "local-agent", "engine_version": "local-agent",
            "model": "local-agent",
            "segments": ([Segment(start=0.0, end=0.0, text=data["transcript"])]
                         if data["transcript"].strip() else []),
        })
        return _ExtractionPayload(
            transcript=transcript, ocr=ocr,
            vision_description=data.get("visual_report", ""),
            gpu_verdict=_gpu_verdict(data),
        )
    if _is_manual_image(name):
        return await _extract_manual_image(path, video_row.id)
    return await _extract_real(path, video_row.id)


# ---------------------------------------------------------------------------
# Failure-mode persistence
# ---------------------------------------------------------------------------


async def _persist_failed_package(
    video_row: Video, exc: BaseException
) -> str:
    """Save a stub EvidencePackageRow with status='failed' + error message.

    Returns the synthesised ``report_id`` so the caller can include it
    in logs.  Uses a sentinel ``schema_version`` of ``"failed"`` so the
    repository's `from_json` reader never tries to reconstruct a
    canonical package from a failure record.
    """
    sm = get_sessionmaker()
    report_id = f"failed-{uuid.uuid4().hex}"
    now = dt.datetime.now(dt.UTC)
    blob = json.dumps(
        {
            "status": "failed",
            "video_id": video_row.id,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
            "failed_at": now.isoformat(),
        },
        sort_keys=True,
    )
    async with writer_lock(), sm() as session, session.begin():
        stmt = sqlite_insert(EvidencePackageRow).values(
            report_id=report_id,
            video_id=video_row.id,
            processed_at=now,
            schema_version="failed",
            package_json=blob,
            risk_level="FAILED",
            action="failed",
        )
        await session.execute(stmt)
    _LOG.error(
        "pipeline_failed",
        extra={
            "video_id": video_row.id,
            "report_id": report_id,
            "exc_type": type(exc).__name__,
            "error_message": str(exc),
        },
    )
    return report_id


# ---------------------------------------------------------------------------
# Report persistence (no dedicated repo exists — use SQLAlchemy directly)
# ---------------------------------------------------------------------------


async def _save_report(report_id: str, markdown: str) -> None:
    sm = get_sessionmaker()
    now = dt.datetime.now(dt.UTC)
    async with writer_lock(), sm() as session, session.begin():
        stmt = sqlite_insert(ReportRow).values(
            report_id=report_id,
            markdown=markdown,
            generated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ReportRow.report_id],
            set_={"markdown": stmt.excluded.markdown, "generated_at": stmt.excluded.generated_at},
        )
        await session.execute(stmt)


# ---------------------------------------------------------------------------
# Campaign promotion (per-package)
# ---------------------------------------------------------------------------


async def _promote_if_campaign(pkg: EvidencePackage) -> None:
    """Run a single graph build → find → promote pass for this package.

    The graph operations are idempotent (Phase 11 ADR), so doing this
    per-package is safe.  We use the existing batch ``promote`` for
    compatibility.
    """
    from aimw.graph import builder, campaigns, feedback

    sm = get_sessionmaker()
    try:
        graph = await builder.build_from_db(sm)
        found = list(campaigns.find(graph))
        if found:
            await feedback.promote(sm, found)
    except Exception:
        _LOG.warning(
            "campaign_promotion_failed",
            extra={"report_id": pkg.report_id},
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def _load_video(video_id: str) -> Video:
    sm = get_sessionmaker()
    async with sm() as session:
        row = await session.get(Video, video_id)
        if row is None:
            raise VideoNotFoundError(video_id)
        # Detach from session so the caller can read fields outside.
        session.expunge(row)
        return row


async def _download_video(video_row: Video) -> Video:
    """Download the video with yt-dlp and persist raw_path, then return updated row."""
    from aimw.collection.ytdlp import download as ytdlp_download

    settings = get_settings()
    loop = asyncio.get_event_loop()
    cancel_event = event_for(video_row.id)
    _LOG.info("downloading_video %s from %s", video_row.id, video_row.url)
    media = await loop.run_in_executor(
        None,
        lambda: ytdlp_download(
            video_row.url,
            settings.resolved_media_dir,
            max_duration_s=settings.max_download_duration_s,
            cancel_event=cancel_event,
        ),
    )
    sm = get_sessionmaker()
    async with writer_lock(), sm() as session, session.begin():
        values: dict[str, Any] = {"raw_path": str(media.path)}
        if getattr(media, "title", None):
            values["title"] = media.title
        await session.execute(
            update(Video).where(Video.id == video_row.id).values(**values)
        )
    video_row.raw_path = str(media.path)
    if getattr(media, "title", None):
        video_row.title = media.title
    _LOG.info("download_complete %s -> %s", video_row.id, media.path)
    return video_row


async def _persist_gpu_verdict(video_row: Video, verdict: Any) -> str:
    """Build a minimal evidence package from a GPU pipeline verdict and persist it."""
    report_id = _deterministic_report_id(video_row.id)
    now = dt.datetime.now(dt.UTC)

    pkg = EvidencePackage(
        report_id=report_id,
        video_id=video_row.id,
        platform=video_row.platform,
        url=video_row.url,
        collected_at=video_row.collected_at,
        processed_at=now,
        evidence=[],
        entities=ExtractedEntities(),
    )

    markdown = _verdict_markdown(verdict)
    from aimw.reasoning.referee import RefereeResult
    referee_result = RefereeResult(action="report" if verdict.is_fraud_promotion else "clear")

    await _save_package_with_projections(pkg, referee_result, verdict)
    await _save_report(report_id, markdown)

    _LOG.info("pipeline_gpu_direct_ok", extra={
        "video_id": video_row.id, "report_id": report_id,
        "level": verdict.risk_level, "score": verdict.risk_score,
    })
    return report_id


async def run_pipeline(video_id: str) -> str:
    """Execute the end-to-end pipeline for *video_id*.

    Returns the resulting ``report_id``.  On failure, persists a
    failure-record package and re-raises so the caller can decide on
    retries.

    Idempotency: if a non-FAILED package already exists for this video, returns
    its report_id immediately without reprocessing.  FAILED packages are retried
    (the Whisper bug was transient and is now fixed).
    """
    check_cancelled(video_id)
    register()  # idempotent — wires EvidencePackage.score / .risk_level

    # Skip re-processing if the video already has a valid (non-FAILED) result.
    deterministic_id = _deterministic_report_id(video_id)
    sm = get_sessionmaker()
    async with sm() as session:
        existing = await session.get(EvidencePackageRow, deterministic_id)
        if existing is not None and existing.risk_level not in (None, "FAILED"):
            _LOG.info(
                "pipeline_already_done",
                extra={"video_id": video_id, "report_id": deterministic_id},
            )
            return deterministic_id

    video_row: Video | None = None
    try:
        video_row = await _load_video(video_id)
        # Keep failed attempts for auditing, but don't display an old failure
        # as the outcome of a new in-progress retry.
        async with writer_lock(), sm() as session, session.begin():
            await session.execute(update(EvidencePackageRow).where(
                EvidencePackageRow.video_id == video_id,
                EvidencePackageRow.schema_version == "failed",
            ).values(action="retrying"))
        # Manual submissions (.manual.txt / .manual.<img>) already have a file
        # on disk — always use the real extraction path so the judge sees the
        # actual user text, not metadata stubs like "Platform: manual".
        raw_name = Path(video_row.raw_path).name if video_row.raw_path else ""
        is_manual = raw_name.endswith(_MANUAL_TEXT_SUFFIX) or _is_manual_image(raw_name)

        if get_settings().fast_analysis and not is_manual and not get_settings().gpu_pipeline_url:
            video_row = await _prefetch_yt_metadata(video_row)
            payload = _extract_fast_metadata(video_row)
        else:
            if not video_row.raw_path or not Path(video_row.raw_path).exists():
                video_row = await _download_video(video_row)
            payload = await _extract(video_row)

        check_cancelled(video_id)
        # Persist transcript segments so the dashboard can show the full text.
        try:
            segs = [
                {"text": s.text, "start": s.start, "end": s.end}
                for s in payload.transcript.segments
            ]
            from aimw.db.repositories.videos import VideosRepository
            await VideosRepository(get_sessionmaker()).update_transcript(
                video_id, json.dumps(segs, ensure_ascii=False)
            )
        except Exception:
            _LOG.warning("transcript_save_failed", extra={"video_id": video_id}, exc_info=True)

        entities, raw_spans = _extract_entities(payload)
        pieces: list[EvidencePiece] = tag_signals(
            raw_spans, entities, payload.ocr, payload.transcript
        )

        report_id = _deterministic_report_id(video_id)
        now = dt.datetime.now(dt.UTC)
        pkg = EvidencePackage(
            report_id=report_id,
            video_id=video_row.id,
            platform=video_row.platform,
            url=video_row.url,
            collected_at=video_row.collected_at,
            processed_at=now,
            evidence=pieces,
            entities=entities,
        )

        provider = ReasoningStub() if payload.gpu_verdict is not None else await _select_briefs_provider()
        referee_result: RefereeResult = await referee_run(
            pkg, briefs_provider=provider
        )

        # Phase 20 inversion: the LLM judges fraud INTENT from the text and
        # owns the verdict; the rule engine below is the auditable evidence.
        verdict = payload.gpu_verdict if payload.gpu_verdict is not None else await _run_judge(pkg, _combined_text(payload), video_row)

        markdown = render_markdown(pkg, referee_result)
        if verdict is not None:
            markdown = markdown.replace("## Verdict", "## Rule-only assessment (supporting evidence)", 1)
            markdown = f"{_verdict_markdown(verdict)}\n\n---\n\n{markdown}"

        # Persist canonical package; projection columns carry the *verdict*
        # (LLM when available, rule-based otherwise) so the API reads it
        # without re-running anything per request.
        check_cancelled(video_id)
        await _save_package_with_projections(pkg, referee_result, verdict)
        await _save_report(report_id, markdown)
        await _promote_if_campaign(pkg)

        final_level = verdict.risk_level if verdict is not None else pkg.risk_level
        final_score = verdict.risk_score if verdict is not None else pkg.score

        try:
            from aimw.alerts import dispatch_alert

            summary_text = ""
            if verdict is not None and hasattr(verdict, "reasoning"):
                summary_text = verdict.reasoning or ""
            await dispatch_alert(
                video_id=video_id,
                risk_level=final_level,
                risk_score=final_score,
                summary=summary_text,
                platform=video_row.platform,
                url=video_row.url,
            )
        except Exception:
            _LOG.warning("alert_dispatch_failed", extra={"video_id": video_id}, exc_info=True)

        # Read the stored action — it's the authoritative post-LLM+rules decision.
        stored_action: str | None = None
        async with sm() as session:
            stored_row = await session.get(EvidencePackageRow, report_id)
            if stored_row is not None:
                stored_action = stored_row.action

        _LOG.info(
            "pipeline_ok",
            extra={
                "video_id": video_id,
                "report_id": report_id,
                "level": final_level,
                "action": stored_action,
                "judge": "llm" if verdict is not None else "rules",
            },
        )
        # Auto-purge: only purge if the video was actually downloaded (raw_path
        # exists). Fast-analysis mode never downloads, so raw_path is None —
        # purging would delete the DB record the frontend is about to display.
        # Never purge manual/check submissions — the user is actively polling.
        _PURGE_ACTIONS = frozenset({"monitor", "clear", "suppress"})
        is_user_check = video_row.url == "check:text" or video_row.platform in {"manual", "manual-image", "manual-video"}
        if (
            get_settings().auto_purge_clean
            and final_level not in _SCAM_LEVELS
            and stored_action in _PURGE_ACTIONS
            and video_row.raw_path
            and not is_user_check
        ):
            try:
                await _purge_clean_video(video_row, report_id)
            except Exception:
                _LOG.warning(
                    "pipeline_purge_clean_failed",
                    extra={"video_id": video_id, "report_id": report_id},
                    exc_info=True,
                )
        return report_id
    except JobCancelled:
        raise
    except Exception as exc:
        if video_row is not None and not event_for(video_id).is_set():
            await _persist_failed_package(video_row, exc)
        raise


_SCAM_LEVELS = frozenset({"HIGH", "CRITICAL", "MEDIUM"})


async def _purge_clean_video(video_row: Video, report_id: str) -> None:
    """Delete LOW/CLEAN verdicts from DB and disk — collector keeps only scams."""
    sm = get_sessionmaker()
    async with writer_lock(), sm() as session, session.begin():
        # Delete ALL packages for this video (including stale FAILED ones from
        # previous runs) so the FK constraint on videos.id is fully satisfied.
        await session.execute(
            delete(EvidencePackageRow).where(EvidencePackageRow.video_id == video_row.id)
        )
        await session.execute(
            delete(Video).where(Video.id == video_row.id)
        )
    if video_row.raw_path:
        with suppress(OSError):
            Path(video_row.raw_path).unlink(missing_ok=True)
    _LOG.info("pipeline_purged_clean", extra={"video_id": video_row.id, "report_id": report_id})


def _deterministic_report_id(video_id: str) -> str:
    """Stable id so re-runs collapse onto the same row."""
    digest = hashlib.sha256(video_id.encode("utf-8")).hexdigest()[:16]
    return f"rpt-{digest}"


# ---------------------------------------------------------------------------
# LLM judge (Phase 20) — the verdict layer on top of the rule engine
# ---------------------------------------------------------------------------

# Representative signed score per LLM risk level (the projection the dashboard
# reads). The LLM owns the level + confidence; this just gives the queue a
# numeric sort key consistent with the level.
_VERDICT_SCORE = {"HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.25, "CLEAN": 0.0}


def _combined_text(payload: _ExtractionPayload) -> str:
    """All readable text from the item: speech transcript + OCR + vision."""
    parts = [s.text for s in payload.transcript.segments if s.text]
    for frame in payload.ocr.frames:
        parts.extend(b.text for b in frame.blocks if b.text)
    if payload.vision_description:
        parts.append(
            f"\n[Visual analysis of video frames]\n{payload.vision_description}"
        )
    return "\n".join(parts)


def _gpu_verdict(data: dict) -> Any:
    """Translate a validated Local Agent score into the dashboard verdict."""
    from aimw.reasoning.judge import FraudVerdict
    score = int(round(data["risk_score"]))
    if score >= 60:
        level, intent, fraud = "HIGH", "promotion", True
    elif score >= 40:
        level, intent, fraud = "MEDIUM", "gray", False
    elif score >= 15:
        level, intent, fraud = "LOW", "gray", False
    else:
        level, intent, fraud = "CLEAN", "clean", False
    return FraudVerdict(
        intent=intent, is_fraud_promotion=fraud, risk_score=score,
        risk_level=level,
        confidence=min(score / 100.0, 1.0) if fraud else max(1.0 - score / 100.0, 0.5),
        rationale=data["reasoning"], key_evidence=data["flags"],
    )


async def _run_judge(pkg: EvidencePackage, text: str, video_row: Video) -> Any:
    """Run the LLM fraud-intent judge; return a FraudVerdict or None.

    Media verdicts come from Local Agent during extraction. This path handles
    text-only inputs and installations without a configured Local Agent.
    """
    import os

    if not text.strip():
        return None
    if os.environ.get("AIMW_USE_REASONING_STUB") == "1":
        _LOG.info("llm_judge_skipped_stub", extra={"video_id": video_row.id})
        return None

    # Fall back to local LLM judge
    try:
        from aimw.db.repositories.usage import UsageRepository
        from aimw.reasoning.client import TokenBudgetExhausted, build_chat_client
        from aimw.reasoning.judge import classify

        client = build_chat_client(UsageRepository(get_sessionmaker()))
        verdict = await classify(
            pkg, text, client,
            title=getattr(video_row, "title", None) or "",
            channel=video_row.platform or "",
        )
        _LOG.info(
            "llm_judge_ok",
            extra={
                "video_id": video_row.id,
                "intent": verdict.intent,
                "risk_level": verdict.risk_level,
                "fraud": verdict.is_fraud_promotion,
            },
        )
        return verdict
    except TokenBudgetExhausted:
        _LOG.info("llm_judge_skipped_budget", extra={"video_id": video_row.id})
    except Exception:
        _LOG.warning("llm_judge_failed", extra={"video_id": video_row.id}, exc_info=True)
    return None


def _verdict_markdown(verdict: Any) -> str:
    """Render the LLM verdict as the lead section of the stored report."""
    pct = round(float(verdict.confidence) * 100)
    fraud = "YES" if verdict.is_fraud_promotion else "no"
    rs = getattr(verdict, "risk_score", None)
    score_bit = f"**Risk score:** {rs}/100  ·  " if rs is not None else ""
    lines = [
        f"## AI judge verdict — {verdict.risk_level}",
        "",
        f"{score_bit}**Intent:** {verdict.intent}  ·  **Fraud promotion:** {fraud}  ·  "
        f"**Confidence:** {pct}%",
        "",
        str(verdict.rationale),
    ]
    if getattr(verdict, "key_evidence", None):
        lines += ["", "**Key evidence:**", *[f"- {e}" for e in verdict.key_evidence]]
    return "\n".join(lines)


def _extract_entities(payload: _ExtractionPayload) -> tuple[ExtractedEntities, list[Any]]:
    """Wrap the entity extractor — single import boundary."""
    from aimw.entities.extractor import extract as extract_entities

    return extract_entities(payload.transcript, payload.ocr, vlm=None)


async def _save_package_with_projections(
    pkg: EvidencePackage,
    referee_result: RefereeResult,
    verdict: Any = None,
) -> None:
    """Save canonical blob + write projection columns the API reads.

    When the LLM ``verdict`` is present it owns the projection (level / score /
    confidence / action); otherwise the deterministic rule + referee result
    does. The canonical blob is always the rule-based audit trail.
    """
    repo = PackagesRepository(get_sessionmaker())
    await repo.save(pkg)
    # Backfill projection columns the route reads at view time.
    sm = get_sessionmaker()
    async with writer_lock(), sm() as session, session.begin():
        row = await session.get(EvidencePackageRow, pkg.report_id)
        if row is None:
            return
        if verdict is not None:
            # Prefer the LLM's own 0-100 severity so scores vary per video;
            # fall back to the level bucket only if the model omitted it.
            rs = getattr(verdict, "risk_score", 0) or 0
            row.score = (rs / 100.0) if rs else _VERDICT_SCORE.get(verdict.risk_level, 0.0)
            row.risk_level = verdict.risk_level
            row.confidence = float(verdict.confidence)
            row.action = "report" if verdict.is_fraud_promotion else "clear"
        else:
            row.score = pkg.score
            row.risk_level = pkg.risk_level
            if referee_result.confidence is not None:
                row.confidence = referee_result.confidence.confidence
            row.action = referee_result.action


__all__ = [
    "PipelineError",
    "VideoNotFoundError",
    "run_pipeline",
]
