"""Read-model DTOs returned by repositories for non-canonical aux tables.

These are *not* part of the evidence schema. They are small, immutable read
projections so repository callers never receive a live ORM row (which would leak
the storage layer and a session-bound object). The canonical ``EvidencePackage``
is never represented here — it always round-trips through ``serialization``.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class VideoRow(BaseModel):
    """Immutable read view of a ``videos`` row."""

    model_config = ConfigDict(frozen=True)

    id: str
    platform: str
    url: str
    collected_at: dt.datetime
    language_hint: str | None = None
    priority_score: float | None = None
    raw_path: str | None = None
    transcript_segments: str | None = None
    title: str | None = None
