"""Transcript cache — one ``<video_id>.json`` per video, manifest-validated.

A cache hit requires every provenance field on the stored :class:`Transcript`
to match the current configuration (engine, engine_version, model, device,
compute_type, cache_version) AND the current source-media SHA-256. Any
mismatch is treated as a miss and the caller recomputes; stale files are NOT
deleted so the audit trail survives.

Atomic writes use a same-directory temp file + ``os.replace`` so a crash
mid-write cannot corrupt the resume point (same pattern as Phase 4 offsets).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from aimw.core.logging import get_logger
from aimw.extraction.whisper.models import CACHE_VERSION, ENGINE, Transcript

log = get_logger("aimw.extraction.whisper.cache")

_HASH_CHUNK = 1 << 20  # 1 MiB


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of the file at ``path`` (streaming)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ExpectedManifest:
    """Provenance the loader requires a cached transcript to match.

    ``engine`` and ``cache_version`` are derived from constants, not provided
    by the caller, so they stay in sync with the package they were built for.
    """

    engine_version: str
    model: str
    device: str
    compute_type: str
    source_file_sha256: str


class TranscriptCache:
    """File-backed cache of :class:`Transcript` JSON, one per ``video_id``."""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir

    def path_for(self, video_id: str) -> Path:
        """Return the cache file path for a given ``video_id`` (no I/O)."""
        return self._dir / f"{video_id}.json"

    def load(self, video_id: str, *, expected: ExpectedManifest) -> Transcript | None:
        """Return the cached transcript if every manifest field matches.

        Returns ``None`` for: file absent, malformed JSON, schema mismatch, or
        any provenance field disagreeing with ``expected``. Logs the reason at
        DEBUG so cache misses are observable.
        """
        path = self.path_for(video_id)
        if not path.exists():
            return None

        try:
            transcript = Transcript.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # malformed file → treat as miss, never crash
            log.warning(
                "transcript_cache_unreadable", video_id=video_id, path=str(path), error=str(exc)
            )
            return None

        reason = self._mismatch_reason(transcript, expected)
        if reason is not None:
            log.debug("transcript_cache_miss", video_id=video_id, reason=reason)
            return None
        return transcript

    def save(self, transcript: Transcript) -> Path:
        """Atomically persist ``transcript`` and return the written path."""
        self._dir.mkdir(parents=True, exist_ok=True)
        final = self.path_for(transcript.video_id)
        fd, tmp_name = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(transcript.model_dump_json())
            os.replace(tmp_name, final)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return final

    @staticmethod
    def _mismatch_reason(transcript: Transcript, expected: ExpectedManifest) -> str | None:
        if transcript.cache_version != CACHE_VERSION:
            return "cache_version"
        if transcript.engine != ENGINE:
            return "engine"
        if transcript.engine_version != expected.engine_version:
            return "engine_version"
        if transcript.model != expected.model:
            return "model"
        if transcript.device != expected.device:
            return "device"
        if transcript.compute_type != expected.compute_type:
            return "compute_type"
        if transcript.source_file_sha256 != expected.source_file_sha256:
            return "source_file_sha256"
        return None
