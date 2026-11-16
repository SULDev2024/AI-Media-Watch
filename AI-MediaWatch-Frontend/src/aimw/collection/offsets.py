"""Per-channel Telegram message offsets, persisted via atomic writes.

Offsets are the *only* persistent state the watcher keeps (concurrency rule #6).
The file is written atomically (temp file + ``os.replace``) so a crash mid-write
never corrupts the resume point.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class Offsets:
    """Mapping of ``channel_id -> last_seen_message_id`` with atomic persistence."""

    def __init__(self, path: Path, data: dict[str, int] | None = None) -> None:
        self._path = path
        self._data: dict[str, int] = dict(data or {})

    @classmethod
    def load(cls, path: Path) -> Offsets:
        """Load offsets from ``path`` (empty if it does not exist yet)."""
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(path, {str(k): int(v) for k, v in raw.items()})
        return cls(path, {})

    def get(self, channel_id: str | int) -> int | None:
        """Return the last-seen message id for a channel, or None."""
        return self._data.get(str(channel_id))

    def set(self, channel_id: str | int, message_id: int) -> None:
        """Record a channel's last-seen message id and persist immediately."""
        self._data[str(channel_id)] = int(message_id)
        self.save()

    def save(self) -> None:
        """Atomically write the offsets file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, sort_keys=True)
            os.replace(tmp_name, self._path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def as_dict(self) -> dict[str, int]:
        """Return a copy of the current offsets."""
        return dict(self._data)
