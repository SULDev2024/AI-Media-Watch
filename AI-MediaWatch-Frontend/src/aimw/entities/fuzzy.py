"""Fuzzy watchlist recovery for obfuscated Telegram handles and wallets (§12).

A token that fails exact regex matching may still be a known-bad actor whose
handle was altered by one character (e.g. ``@earn_kz_vlp`` vs ``@earn_kz_vip``).
``rapidfuzz`` ``fuzz.ratio`` ≥ 88 is the threshold from §12.

Recovered tokens are tagged ``recovery_method="fuzzy"`` and ``certainty=0.6``
so Phase 8 can weight them below exact-match evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

from rapidfuzz import fuzz

from aimw.core.schema.types import Source
from aimw.entities.models import RawSpan

_DEFAULT_WATCHLIST: dict[str, list[str]] = {"handles": [], "wallets": []}
_FUZZY_THRESHOLD = 88
_FUZZY_CERTAINTY = 0.6


def load_watchlist(path: Path) -> dict[str, list[str]]:
    """Load the watchlist JSON from *path*; return empty lists if absent."""
    if not path.exists():
        return _DEFAULT_WATCHLIST.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "handles": list(data.get("handles", [])),
            "wallets": list(data.get("wallets", [])),
        }
    except (json.JSONDecodeError, OSError):
        return _DEFAULT_WATCHLIST.copy()


def recover_watchlist(
    token: str,
    watchlist: list[str],
    thresh: int = _FUZZY_THRESHOLD,
) -> str | None:
    """Return the best-matching watchlist entry if ``fuzz.ratio`` ≥ *thresh*.

    Returns ``None`` when no entry meets the threshold.
    """
    if not watchlist:
        return None
    best = max(watchlist, key=lambda w: fuzz.ratio(token, w))
    return best if fuzz.ratio(token, best) >= thresh else None


def recover_handles(
    tokens: list[str],
    watchlist: dict[str, list[str]],
    *,
    source: Source,
    timestamp: float | None,
    context: str = "",
) -> list[RawSpan]:
    """Fuzzy-match *tokens* against the handle watchlist; return recovered spans."""
    spans: list[RawSpan] = []
    for token in tokens:
        match = recover_watchlist(token, watchlist.get("handles", []))
        if match is not None:
            spans.append(
                RawSpan(
                    source=source,
                    timestamp=timestamp,
                    text=context,
                    raw_value=match,
                    recovery_method="fuzzy",
                    certainty=_FUZZY_CERTAINTY,
                )
            )
    return spans


def recover_wallets(
    tokens: list[str],
    watchlist: dict[str, list[str]],
    *,
    source: Source,
    timestamp: float | None,
    context: str = "",
) -> list[RawSpan]:
    """Fuzzy-match *tokens* against the wallet watchlist; return recovered spans."""
    spans: list[RawSpan] = []
    for token in tokens:
        match = recover_watchlist(token, watchlist.get("wallets", []))
        if match is not None:
            spans.append(
                RawSpan(
                    source=source,
                    timestamp=timestamp,
                    text=context,
                    raw_value=match,
                    recovery_method="fuzzy",
                    certainty=_FUZZY_CERTAINTY,
                )
            )
    return spans
