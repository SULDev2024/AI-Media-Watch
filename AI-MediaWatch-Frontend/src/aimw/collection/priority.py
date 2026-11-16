"""Ingestion priority heuristic (NOT evidence, NOT a risk score).

``priority_score`` is a raw routing signal in [0, 1] that biases the processing
queue under rate limits. It is never normalized into ``EvidencePackage.score``
and carries no Phase 8 semantics (no coupling to risk_level/action/confidence).

The score counts how many distinct keyword *groups* a caption hits (not raw
frequency), so spamming one word cannot dominate the queue.
"""

from __future__ import annotations

from aimw.collection.trigger_keywords import TRIGGER_KEYWORD_GROUPS

# A caption hitting this many distinct groups saturates priority at 1.0.
_SATURATION_GROUPS = 4


def _normalize(text: str) -> str:
    """Case-insensitive, unicode-aware normalization for substring matching."""
    return text.casefold()


def score(text: str) -> float:
    """Return a 0..1 priority from the number of distinct keyword groups hit."""
    if not text:
        return 0.0
    norm = _normalize(text)
    groups_hit = sum(
        1
        for keywords in TRIGGER_KEYWORD_GROUPS.values()
        if any(keyword.casefold() in norm for keyword in keywords)
    )
    return min(1.0, groups_hit / _SATURATION_GROUPS)
