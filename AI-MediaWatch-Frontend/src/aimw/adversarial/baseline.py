"""Naive keyword-only classifier — the straw man we beat.

This is what a first-pass anti-fraud filter looks like: a fixed list of fraud
keywords, a count, a threshold. It has no notion of intent, obfuscation, or
context. We ship it ONLY to demonstrate, side-by-side, how easily it is evaded —
and how the full intent+multimodal pipeline is not.
"""
from __future__ import annotations

import re

# A representative fraud-vocabulary watchlist (RU / KZ / EN).
_KEYWORDS: tuple[str, ...] = (
    "guaranteed profit", "guaranteed return", "passive income", "double your money",
    "risk free", "100% profit", "investment opportunity", "crypto signals",
    "pyramid", "referral bonus", "get rich", "financial freedom",
    "гарантированный доход", "пассивный доход", "без риска", "удвоить",
    "инвестиции", "крипто сигналы", "пирамида", "реферал", "заработок",
    "казино", "ставки", "betting", "casino",
)

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def classify(text: str) -> dict:
    """Score *text* by literal fraud-keyword presence.

    Returns a dict with the matched keywords, a 0–1 score (saturating at 5
    hits), and a binary ``flagged`` decision at a fixed threshold.
    """
    low = text.lower()
    hits = [kw for kw in _KEYWORDS if kw in low]
    # Saturating score: every hit adds 0.2, capped at 1.0.
    score = min(1.0, 0.2 * len(hits))
    return {
        "classifier": "keyword_baseline",
        "matched_keywords": hits,
        "n_hits": len(hits),
        "score": round(score, 3),
        "flagged": len(hits) >= 1,
    }


__all__ = ["classify"]
