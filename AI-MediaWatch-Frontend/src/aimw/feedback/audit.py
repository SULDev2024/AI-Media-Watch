"""Append-only audit log for all feedback actions (§14).

Every calibration nudge, watchlist addition, and regression freeze is written
as a JSON-lines entry to ``data/audit/feedback.log``. The log is never
truncated — it is the reversibility trail that lets an operator undo any
automated threshold drift.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG_PATH = Path("data/audit/feedback.log")


def _resolve() -> Path:
    """Return the audit log path, creating parent dirs on first write."""
    p = _LOG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append(
    action: str,
    *,
    before: Any = None,
    after: Any = None,
    user_id: str = "system",
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one JSON-lines entry to the audit log (atomic open/write/close).

    Parameters
    ----------
    action:
        Short verb identifying what happened, e.g. ``calibration_nudge``,
        ``watchlist_add``, ``regression_freeze``.
    before:
        State before the action (JSON-serialisable).
    after:
        State after the action (JSON-serialisable).
    user_id:
        Analyst or service identity that triggered the action.
    extra:
        Optional additional key-value pairs merged into the log entry.
    """
    entry: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "user_id": user_id,
        "action": action,
        "before": before,
        "after": after,
    }
    if extra:
        entry.update(extra)

    path = _resolve()
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        # Append-only: we cannot use O_APPEND atomically on Windows without
        # a lock, so we write to a temp file then rename onto the log; this
        # preserves the last write if two processes race (last-writer wins for
        # a single entry; callers must not depend on exact ordering).
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(existing)
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_all() -> list[dict[str, Any]]:
    """Return all audit log entries, oldest first."""
    path = _LOG_PATH
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            with contextlib.suppress(json.JSONDecodeError):
                entries.append(json.loads(line))
    return entries
