"""OcrResult cache — one ``<video_id>.json`` per video, manifest-validated.

Mirrors :mod:`aimw.extraction.whisper.cache`: a cache hit requires every
provenance field on the stored :class:`OcrResult` to match the current engine
config AND the current source-media SHA-256. Mismatches are misses, not
deletions (stale files survive for audit). Writes are atomic.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from aimw.core.logging import get_logger
from aimw.extraction.ocr.models import CACHE_VERSION, OcrResult

log = get_logger("aimw.extraction.ocr.cache")

_HASH_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of the file at ``path`` (streaming)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ExpectedManifest:
    """Provenance the loader requires a cached OCR result to match."""

    engine: str
    engine_version: str
    source_file_sha256: str


class OcrCache:
    """File-backed cache of :class:`OcrResult` JSON, one per ``video_id``."""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir

    def path_for(self, video_id: str) -> Path:
        return self._dir / f"{video_id}.json"

    def load(self, video_id: str, *, expected: ExpectedManifest) -> OcrResult | None:
        """Return the cached OcrResult iff every manifest field matches."""
        path = self.path_for(video_id)
        if not path.exists():
            return None
        try:
            result = OcrResult.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("ocr_cache_unreadable", video_id=video_id, path=str(path), error=str(exc))
            return None
        reason = self._mismatch_reason(result, expected)
        if reason is not None:
            log.debug("ocr_cache_miss", video_id=video_id, reason=reason)
            return None
        return result

    def save(self, result: OcrResult) -> Path:
        """Atomically persist ``result`` and return the written path."""
        self._dir.mkdir(parents=True, exist_ok=True)
        final = self.path_for(result.video_id)
        fd, tmp_name = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(result.model_dump_json())
            os.replace(tmp_name, final)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return final

    @staticmethod
    def _mismatch_reason(result: OcrResult, expected: ExpectedManifest) -> str | None:
        if result.cache_version != CACHE_VERSION:
            return "cache_version"
        if result.engine != expected.engine:
            return "engine"
        if result.engine_version != expected.engine_version:
            return "engine_version"
        if result.source_file_sha256 != expected.source_file_sha256:
            return "source_file_sha256"
        return None
