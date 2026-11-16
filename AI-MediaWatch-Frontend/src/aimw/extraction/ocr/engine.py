"""OCR extractor orchestrator: sample frames → recognize → assemble → cache.

Lifecycle (mirrors Phase 5 Transcriber):

* :func:`get_extractor` returns a process-wide singleton, lazily built on first
  use. The underlying :class:`OcrEngine` loads PaddleOCR weights once per
  process (or fails fast if PaddleOCR isn't installed).
* :func:`reset_extractor` clears the singleton; used by tests.
* :meth:`OcrExtractor.extract` is async, runs synchronous OCR calls via
  :func:`asyncio.to_thread` under ``Semaphore(1)`` so the engine is
  single-tenant inside one worker process (ADR-0002 compatible).

Per-call failures raise :class:`OcrError` and are NOT cached (matches Phase 5's
Decision A semantics: operational failures stay visible and reproducible).
Load-time PaddleOCR unavailability raises :class:`~aimw.extraction.ocr.paddle.OcrEngineUnavailable`,
which the worker is expected to surface as a structured per-video failure
rather than crashing the loop.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os
from pathlib import Path

from aimw.core.config import get_settings
from aimw.core.logging import get_logger
from aimw.extraction.ocr.cache import ExpectedManifest, OcrCache, sha256_file
from aimw.extraction.ocr.frames import FrameMeta, sample
from aimw.extraction.ocr.models import OcrFrameResult, OcrResult
from aimw.extraction.ocr.paddle import OcrEngine

log = get_logger("aimw.extraction.ocr.engine")


# --- Errors -----------------------------------------------------------------


class OcrError(Exception):
    """Base class for per-call OCR failures (never cached, Decision A)."""

    def __init__(self, kind: str, message: str, *, video_id: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.video_id = video_id


class SourceMediaMissingError(OcrError):
    """The raw media file does not exist on disk."""


class FrameSamplingError(OcrError):
    """The frame sampler failed (corrupt video, codec missing, etc.)."""


class OcrRuntimeError(OcrError):
    """PaddleOCR raised during recognition."""


# --- Singleton --------------------------------------------------------------


_EXTRACTOR: OcrExtractor | None = None


def get_extractor() -> OcrExtractor:
    """Return the process-wide :class:`OcrExtractor`, building it on first use."""
    global _EXTRACTOR
    if _EXTRACTOR is None:
        _EXTRACTOR = _build_from_settings()
    return _EXTRACTOR


def reset_extractor() -> None:
    """Drop the singleton; the next :func:`get_extractor` call rebuilds it."""
    global _EXTRACTOR
    _EXTRACTOR = None


def _build_from_settings() -> OcrExtractor:
    settings = get_settings()
    engine = OcrEngine(requested=settings.ocr_engine)
    cache = OcrCache(settings.resolved_ocr_cache_dir)
    return OcrExtractor(
        engine=engine,
        cache=cache,
        frame_cache_dir=settings.resolved_frame_cache_dir,
        scene_threshold=settings.scene_change_threshold,
        frames_per_3s=settings.frames_per_3s,
    )


# --- Extractor --------------------------------------------------------------


class OcrExtractor:
    """OCR extraction pipeline for one video."""

    def __init__(
        self,
        *,
        engine: OcrEngine,
        cache: OcrCache,
        frame_cache_dir: Path,
        scene_threshold: float,
        frames_per_3s: int,
    ) -> None:
        self._engine = engine
        self._cache = cache
        self._frame_cache_dir = frame_cache_dir
        self._scene_threshold = scene_threshold
        self._frames_per_3s = frames_per_3s
        self._semaphore = asyncio.Semaphore(1)

    @property
    def cache(self) -> OcrCache:
        return self._cache

    @property
    def engine(self) -> OcrEngine:
        return self._engine

    def _expected_manifest(self, source_hash: str) -> ExpectedManifest:
        return ExpectedManifest(
            engine=self._engine.engine,
            engine_version=self._engine.engine_version,
            source_file_sha256=source_hash,
        )

    async def extract(self, source_path: Path, video_id: str) -> OcrResult:
        """Return an :class:`OcrResult` for ``source_path``, caching the output."""
        if not source_path.exists():
            raise SourceMediaMissingError(
                "source_missing",
                f"raw media not found at {source_path}",
                video_id=video_id,
            )

        source_hash = sha256_file(source_path)
        cached = self._cache.load(video_id, expected=self._expected_manifest(source_hash))
        if cached is not None:
            log.debug("ocr_cache_hit", video_id=video_id)
            return cached

        async with self._semaphore:
            try:
                frames = await asyncio.to_thread(self._sample, source_path, video_id)
            except OcrError:
                raise
            except Exception as exc:
                log.error("ocr_frame_sampling_failed", video_id=video_id, error=str(exc))
                raise FrameSamplingError(
                    "sampling", f"frame sampling failed: {exc}", video_id=video_id
                ) from exc
            max_frames_raw = os.environ.get("AIMW_OCR_MAX_FRAMES")
            if max_frames_raw:
                max_frames = max(1, int(max_frames_raw))
                frames = frames[:max_frames]

            frame_results: list[OcrFrameResult] = []
            for idx, frame in enumerate(frames):
                try:
                    blocks = await asyncio.to_thread(self._engine.recognize, frame.path)
                except Exception as exc:
                    log.error(
                        "ocr_recognize_failed",
                        video_id=video_id,
                        frame=str(frame.path),
                        error=str(exc),
                    )
                    raise OcrRuntimeError(
                        "runtime",
                        f"paddleocr recognize failed on {frame.path}: {exc}",
                        video_id=video_id,
                    ) from exc
                frame_results.append(
                    OcrFrameResult(
                        frame_index=idx,
                        timestamp_s=frame.timestamp_s,
                        image_path=str(frame.path),
                        blocks=blocks,
                    )
                )

        result = OcrResult(
            engine=self._engine.engine,
            engine_version=self._engine.engine_version,
            source_file_sha256=source_hash,
            video_id=video_id,
            frames=frame_results,
            generated_at=dt.datetime.now(dt.UTC),
        )
        self._cache.save(result)
        return result

    def _sample(self, source_path: Path, video_id: str) -> list[FrameMeta]:
        out_dir = self._frame_cache_dir / video_id
        return sample(
            source_path,
            out_dir,
            threshold=self._scene_threshold,
            frames_per_3s=self._frames_per_3s,
        )
