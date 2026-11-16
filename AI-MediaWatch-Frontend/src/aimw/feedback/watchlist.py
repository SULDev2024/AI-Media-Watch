"""Confirmed entity watchlist — §14 of AI_MediaWatch_v4.md.

``add(kind, value)`` appends a confirmed handle or wallet to
``data/watchlist.json`` (the same file Phase 7's fuzzy-recovery reads from).
All writes are atomic; duplicates are silently ignored. Every addition is
audit-logged.

``kind`` values that are accepted: ``"handles"``, ``"wallets"``, ``"phones"``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from aimw.feedback import audit

_WATCHLIST_PATH = Path("data/watchlist.json")

_ALLOWED_KINDS = frozenset({"handles", "wallets", "phones"})

# Sentinel for "no existing entry" in a kind bucket.
_EMPTY: list[str] = []


def _load_raw() -> dict[str, list[str]]:
    if _WATCHLIST_PATH.exists():
        raw = json.loads(_WATCHLIST_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {str(k): list(v) for k, v in raw.items() if isinstance(v, list)}
    return {}


def _save(data: dict[str, list[str]]) -> None:
    _WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_WATCHLIST_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, _WATCHLIST_PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def add(kind: str, value: str, *, user_id: str = "system") -> bool:
    """Add ``value`` to the ``kind`` bucket of the watchlist.

    Parameters
    ----------
    kind:
        One of ``"handles"``, ``"wallets"``, ``"phones"``.
    value:
        The entity value to persist (e.g. ``"@signal_kz_vip"``).
    user_id:
        Analyst identity for the audit log.

    Returns
    -------
    bool
        ``True`` if the entry was added; ``False`` if it was already present
        (duplicate silently ignored, no audit entry written for dups).

    Raises
    ------
    ValueError
        ``kind`` is not one of the allowed values.
    """
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"unknown kind {kind!r}; must be one of {sorted(_ALLOWED_KINDS)}")

    data = _load_raw()
    bucket = data.setdefault(kind, [])
    if value in bucket:
        return False

    bucket.append(value)
    _save(data)
    audit.append(
        "watchlist_add",
        before=None,
        after={"kind": kind, "value": value},
        user_id=user_id,
    )
    return True


def load() -> dict[str, list[str]]:
    """Return a copy of the full watchlist."""
    return _load_raw()


def contains(kind: str, value: str) -> bool:
    """Check whether ``value`` is in the ``kind`` bucket."""
    data = _load_raw()
    return value in data.get(kind, _EMPTY)
