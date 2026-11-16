"""Pydantic models for the OCR extraction artifact.

The :class:`OcrResult` is the single record persisted to the cache. Like
:class:`~aimw.extraction.whisper.models.Transcript`, manifest fields
(``cache_version``, ``engine``, ``engine_version``, ``source_file_sha256``,
``generated_at``) are embedded in the file so a cache entry is self-validating
— a stale entry from a previous engine or source file is detected by comparing
fields, not by re-reading a side file.

Per the Phase 5/6 boundary, this type lives in ``aimw.extraction.ocr`` and is
NOT part of the canonical evidence schema (``aimw.core.schema``). Phase 7
consumes ``OcrResult`` to produce ``EvidencePiece`` objects; Phase 6 itself
never touches the evidence schema.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

CACHE_VERSION = "1"


class OcrBlock(BaseModel):
    """A single OCR text block recognized in one frame."""

    model_config = ConfigDict(frozen=True)

    text: str
    bbox: tuple[int, int, int, int]  # (x0, y0, x1, y1) in pixels
    confidence: float


class OcrFrameResult(BaseModel):
    """OCR output for a single sampled frame."""

    model_config = ConfigDict(frozen=True)

    frame_index: int
    timestamp_s: float
    image_path: str
    blocks: list[OcrBlock] = Field(default_factory=list)


class OcrResult(BaseModel):
    """OCR extraction output + the provenance needed to validate its cache."""

    model_config = ConfigDict(frozen=True)

    # Manifest / provenance (mirrors the Phase 5 Transcript pattern).
    cache_version: str = CACHE_VERSION
    engine: str
    engine_version: str
    source_file_sha256: str

    # OCR payload.
    video_id: str
    frames: list[OcrFrameResult] = Field(default_factory=list)
    generated_at: dt.datetime
