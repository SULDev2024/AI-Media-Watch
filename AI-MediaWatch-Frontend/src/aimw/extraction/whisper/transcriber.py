"""Whisper transcription wrapper.

Lifecycle (per ADR-0002, one event loop per worker process):

* :func:`get_transcriber` returns a process-wide singleton, lazily constructed
  on first use. The underlying ``WhisperModel`` is loaded once per process; the
  weights stay resident for the lifetime of the worker.
* :func:`reset_transcriber` clears the singleton; used by tests and by any
  future reconfiguration path. Calling it does NOT unload weights in-flight —
  it only drops the reference, so the next caller pays a fresh load.
* :meth:`Transcriber.transcribe` is async, runs the synchronous Whisper call
  inside :func:`asyncio.to_thread`, and is protected by ``Semaphore(1)`` so
  the model is single-tenant inside one process (matches ADR-0002's one-loop
  contract and avoids CTranslate2 contention).

Device fallback (load-time only; Decision A):

* ``device=auto`` resolves via ``ctranslate2.get_supported_compute_types("cuda")``.
* ``device=cuda`` attempts CUDA; on ImportError / OSError / RuntimeError at load
  time, the transcriber falls back to ``cpu``/``int8`` with a structured warning.
* ``device=cpu`` failures are real install problems and propagate.
* **Per-call** failures (CUDA OOM, runtime errors) raise :class:`TranscriptionError`.
  They are never auto-retried on CPU and never cached.

Determinism: transcripts are semantically equivalent under the same
``(model, device, compute_type, engine_version)`` tuple, byte-stable for the
lifetime of a cache entry, and NOT guaranteed byte-equal across reruns or
across configurations. The cache (with ``source_file_sha256``) is the
reproducibility boundary; the EvidencePackage reads from the cache, so
verdict-level determinism (Phase 8) holds across reruns of the same cache.

Windows install fallback (§0.3 #14): if ``faster-whisper``'s CUDA path fails on
your machine (missing cuDNN, driver mismatch, etc.), set ``AIMW_WHISPER_DEVICE=cpu``
in ``.env``. The auto path will also fall back, but the explicit setting avoids
the load-time warning and the CPU rebuild.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

import ctranslate2
from faster_whisper import WhisperModel

from aimw.core.config import get_settings
from aimw.core.logging import get_logger
from aimw.extraction.whisper.cache import ExpectedManifest, TranscriptCache, sha256_file
from aimw.extraction.whisper.models import ENGINE, Segment, Transcript, Word

log = get_logger("aimw.extraction.whisper.transcriber")

Device = Literal["cpu", "cuda"]
DeviceSetting = Literal["cpu", "cuda", "auto"]


# --- Errors -----------------------------------------------------------------


class TranscriptionError(Exception):
    """Base error for any transcription failure surfaced to callers.

    Failures are never cached (Decision A). Callers (Phase 13 worker) are
    expected to log the structured event and record a per-video failure marker,
    not retry transparently.
    """

    def __init__(self, kind: str, message: str, *, video_id: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.video_id = video_id


class TranscriptionRuntimeError(TranscriptionError):
    """A per-call Whisper / CTranslate2 runtime failure (e.g. CUDA OOM, decode)."""


class SourceMediaMissingError(TranscriptionError):
    """The raw media file does not exist on disk."""


# --- Singleton --------------------------------------------------------------


_TRANSCRIBER: Transcriber | None = None


def get_transcriber() -> Transcriber:
    """Return the process-wide :class:`Transcriber`, building it on first use."""
    global _TRANSCRIBER
    if _TRANSCRIBER is None:
        _TRANSCRIBER = _build_from_settings()
    return _TRANSCRIBER


def reset_transcriber() -> None:
    """Drop the singleton; the next :func:`get_transcriber` call rebuilds it."""
    global _TRANSCRIBER
    _TRANSCRIBER = None


def _engine_version() -> str:
    try:
        return version("faster-whisper")
    except PackageNotFoundError:  # pragma: no cover - install always succeeds in tests
        return "unknown"


def _resolve_target_device(setting: DeviceSetting) -> tuple[Device, str]:
    """Pick the device/compute pair before any model is loaded."""
    if setting == "cpu":
        return "cpu", get_settings().whisper_compute_type
    if setting == "cuda":
        return "cuda", "float16"
    # auto
    try:
        supported = ctranslate2.get_supported_compute_types("cuda")
    except Exception:  # CTranslate2 itself can raise when CUDA libs are absent
        supported = ()
    if "float16" in supported:
        return "cuda", "float16"
    return "cpu", get_settings().whisper_compute_type


def _build_from_settings() -> Transcriber:
    settings = get_settings()
    target_device, target_compute = _resolve_target_device(settings.whisper_device)
    cache = TranscriptCache(settings.resolved_whisper_cache_dir)
    return Transcriber(
        model_name=settings.whisper_model,
        device=target_device,
        compute_type=target_compute,
        engine_version=_engine_version(),
        cache=cache,
    )


# --- Transcriber ------------------------------------------------------------


class Transcriber:
    """Lazy-loading wrapper around :class:`faster_whisper.WhisperModel`."""

    def __init__(
        self,
        *,
        model_name: str,
        device: Device,
        compute_type: str,
        engine_version: str,
        cache: TranscriptCache,
    ) -> None:
        self._model_name = model_name
        self._device: Device = device
        self._compute_type = compute_type
        self._engine_version = engine_version
        self._cache = cache
        self._model: WhisperModel | None = None
        self._semaphore = asyncio.Semaphore(1)

    # Public read-only state (handy for tests and logging).

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def device(self) -> Device:
        return self._device

    @property
    def compute_type(self) -> str:
        return self._compute_type

    @property
    def engine_version(self) -> str:
        return self._engine_version

    @property
    def cache(self) -> TranscriptCache:
        return self._cache

    @property
    def loaded(self) -> bool:
        """Whether the underlying ``WhisperModel`` weights have been loaded."""
        return self._model is not None

    # --- Loading ----------------------------------------------------------

    def _ensure_model_loaded(self) -> None:
        """Load weights on first use; fall back from CUDA → CPU at load time only."""
        if self._model is not None:
            return
        try:
            self._model = WhisperModel(
                self._model_name, device=self._device, compute_type=self._compute_type
            )
            log.info(
                "whisper_model_loaded",
                model=self._model_name,
                device=self._device,
                compute_type=self._compute_type,
            )
        except (ImportError, OSError, RuntimeError) as exc:
            if self._device != "cuda":
                # CPU load failure is a real install problem; let it propagate.
                raise
            log.warning(
                "whisper_cuda_load_failed",
                model=self._model_name,
                error=str(exc),
                falling_back_to="cpu/int8",
            )
            self._device = "cpu"
            self._compute_type = "int8"
            self._model = WhisperModel(
                self._model_name, device=self._device, compute_type=self._compute_type
            )
            log.info(
                "whisper_model_loaded",
                model=self._model_name,
                device=self._device,
                compute_type=self._compute_type,
            )

    # --- Transcription ----------------------------------------------------

    def _expected_manifest(self, source_hash: str) -> ExpectedManifest:
        return ExpectedManifest(
            engine_version=self._engine_version,
            model=self._model_name,
            device=self._device,
            compute_type=self._compute_type,
            source_file_sha256=source_hash,
        )

    async def transcribe(self, source_path: Path, video_id: str) -> Transcript:
        """Return a :class:`Transcript` for ``source_path``, caching the result.

        Cache hit (every manifest field including ``source_file_sha256`` matches)
        returns instantly without loading the model. Cache miss runs Whisper in
        a worker thread under ``Semaphore(1)``; runtime errors raise
        :class:`TranscriptionRuntimeError` and are not cached (Decision A).
        """
        if not source_path.exists():
            raise SourceMediaMissingError(
                "source_missing", f"raw media not found at {source_path}", video_id=video_id
            )

        source_hash = sha256_file(source_path)
        cached = self._cache.load(video_id, expected=self._expected_manifest(source_hash))
        if cached is not None:
            log.debug("transcript_cache_hit", video_id=video_id)
            return cached

        async with self._semaphore:
            self._ensure_model_loaded()
            try:
                raw_segments, info = await asyncio.to_thread(self._run_whisper, source_path)
            except TranscriptionError:
                raise
            except (ValueError, IndexError) as exc:
                # faster-whisper raises ``ValueError("max() arg is an empty sequence")``
                # when VAD removes the entire audio (silent intro, music-only clip, or
                # synthetic test fixtures). It also raises ``IndexError: tuple index out
                # of range`` on certain Telegram mp4/ogg audio tracks with unusual
                # encoding. Both are "no usable audio", not hardware failures — return an
                # empty transcript so the pipeline continues with OCR + metadata only.
                is_no_speech = (
                    "empty sequence" in str(exc)
                    or isinstance(exc, IndexError)
                )
                if not is_no_speech:
                    log.error(
                        "whisper_runtime_failed",
                        video_id=video_id,
                        device=self._device,
                        error=str(exc),
                    )
                    raise TranscriptionRuntimeError(
                        "runtime", f"whisper transcribe failed: {exc}", video_id=video_id
                    ) from exc
                log.info("whisper_no_speech_detected", video_id=video_id, reason=str(exc))
                raw_segments, info = [], type("Info", (), {"language": "unknown"})()
            except Exception as exc:
                log.error(
                    "whisper_runtime_failed",
                    video_id=video_id,
                    device=self._device,
                    error=str(exc),
                )
                raise TranscriptionRuntimeError(
                    "runtime", f"whisper transcribe failed: {exc}", video_id=video_id
                ) from exc

        transcript = self._build_transcript(
            raw_segments=raw_segments,
            info=info,
            video_id=video_id,
            source_hash=source_hash,
        )
        self._cache.save(transcript)
        return transcript

    def _run_whisper(self, source_path: Path) -> tuple[list[object], object]:
        """Run the synchronous Whisper call and materialize the segment generator.

        Materializing inside the worker thread (rather than streaming) keeps
        downstream code synchronous-free and surfaces any decode error here,
        where the ``except`` clause around ``to_thread`` can structure it.
        """
        assert self._model is not None  # _ensure_model_loaded ran under the semaphore
        segments, info = self._model.transcribe(
            str(source_path),
            language=None,
            word_timestamps=True,
            vad_filter=True,
            temperature=0.0,
            beam_size=5,
            condition_on_previous_text=False,
        )
        return list(segments), info

    def _build_transcript(
        self,
        *,
        raw_segments: list[object],
        info: object,
        video_id: str,
        source_hash: str,
    ) -> Transcript:
        segments: list[Segment] = []
        for raw in raw_segments:
            words: list[Word] = []
            raw_words = getattr(raw, "words", None) or []
            for raw_word in raw_words:
                words.append(
                    Word(
                        w=getattr(raw_word, "word", "") or "",
                        start=float(getattr(raw_word, "start", 0.0) or 0.0),
                        end=float(getattr(raw_word, "end", 0.0) or 0.0),
                        prob=float(getattr(raw_word, "probability", 0.0) or 0.0),
                    )
                )
            segments.append(
                Segment(
                    start=float(getattr(raw, "start", 0.0) or 0.0),
                    end=float(getattr(raw, "end", 0.0) or 0.0),
                    text=(getattr(raw, "text", "") or "").strip(),
                    words=words,
                )
            )

        language_detected = str(getattr(info, "language", "") or "unknown")
        return Transcript(
            engine=ENGINE,
            engine_version=self._engine_version,
            model=self._model_name,
            device=self._device,
            compute_type=self._compute_type,
            source_file_sha256=source_hash,
            video_id=video_id,
            language_detected=language_detected,
            segments=segments,
            generated_at=dt.datetime.now(dt.UTC),
        )
