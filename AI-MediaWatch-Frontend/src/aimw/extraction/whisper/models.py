"""Pydantic models for the Whisper transcript artifact.

The :class:`Transcript` is the single record persisted to the cache; the manifest
fields (``cache_version``, ``engine``, ``engine_version``, ``model``, ``device``,
``compute_type``, ``generated_at``, ``source_file_sha256``) live inside it so a
file is self-validating — a stale cache entry from a previous model / library /
source file is detected by comparing fields, not by re-reading a side file.

Per the Phase 5 boundary, this type lives in ``aimw.extraction.whisper`` and is
NOT part of the canonical evidence schema (``aimw.core.schema``). Phase 7
consumes ``Transcript`` to produce ``EvidencePiece`` objects; Phase 5 itself
never touches the evidence schema.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

# Bumpable independently from the evidence schema version — invalidates the
# cache wrapper itself (not the transcript contents).
CACHE_VERSION = "1"
ENGINE = "faster-whisper"


class Word(BaseModel):
    """Word-level timing and probability for a single recognized token."""

    model_config = ConfigDict(frozen=True)

    w: str
    start: float
    end: float
    prob: float


class Segment(BaseModel):
    """A contiguous span of speech recognized by Whisper."""

    model_config = ConfigDict(frozen=True)

    start: float
    end: float
    text: str
    words: list[Word] = Field(default_factory=list)


class Transcript(BaseModel):
    """A Whisper transcription + the provenance needed to validate its cache.

    Manifest fields are checked by :class:`~aimw.extraction.whisper.cache.TranscriptCache`
    on load; a mismatch is treated as a cache miss (stale entries are not
    deleted, so analyst audit trails survive).
    """

    model_config = ConfigDict(frozen=True)

    # Manifest / provenance.
    cache_version: str = CACHE_VERSION
    engine: str = ENGINE
    engine_version: str
    model: str
    device: str
    compute_type: str
    source_file_sha256: str

    # Transcription payload.
    video_id: str
    language_detected: str
    segments: list[Segment] = Field(default_factory=list)
    generated_at: dt.datetime
