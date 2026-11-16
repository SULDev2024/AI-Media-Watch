"""Fast local scam-promotion prescreening for collectors.

This runs before downloads, transcription, OCR, or LLM judging. It is not a
final verdict; it is a cheap ranking/filtering layer so heavy analysis sees the
most suspicious promotional material first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PrescreenResult:
    score: int
    positives: tuple[str, ...]
    negatives: tuple[str, ...]

    @property
    def keep(self) -> bool:
        return self.score >= 2


_POSITIVE_PHRASES: dict[str, int] = {
    "guaranteed profit": 5,
    "guaranteed income": 5,
    "risk free": 4,
    "daily profit": 4,
    "daily income": 4,
    "passive income": 3,
    "double your": 5,
    "send usdt": 5,
    "send btc": 5,
    "crypto signals": 4,
    "betting signals": 4,
    "casino bonus": 4,
    "promo code": 3,
    "referral link": 4,
    "join telegram": 3,
    "join vip": 4,
    "private signal": 4,
    "limited spots": 2,
    "dm admin": 4,
    "contact admin": 4,
    "withdraw proof": 4,
    "proof of withdrawal": 4,
    "minimum deposit": 4,
    "investment platform": 3,
    "arbitrage bot": 4,
    "binary options": 4,
    "ai trading bot": 4,
    "binance pay": 3,
    "copy trading": 3,
    "fixed match": 4,
    "free spins": 3,
    "investment group": 3,
    "trading bot": 4,
    "vip group": 4,
}

_POSITIVE_WORDS: dict[str, int] = {
    "usdt": 2,
    "btc": 1,
    "wallet": 1,
    "deposit": 3,
    "withdraw": 1,
    "profit": 2,
    "returns": 1,
    "roi": 2,
    "earn": 2,
    "casino": 4,
    "betting": 4,
    "gambling": 3,
    "forex": 3,
    "signals": 2,
    "pump": 3,
    "referral": 3,
    "bonus": 2,
    "airdrop": 1,
    "ponzi": 2,
    "pyramid": 2,
    "investment": 1,
    "crypto": 1,
    "slot": 3,
    "slots": 3,
    "stake": 2,
    "1xbet": 4,
}

_NEGATIVE_PHRASES: dict[str, int] = {
    "scam warning": 5,
    "how to avoid": 4,
    "avoid scams": 4,
    "anti scam": 5,
    "fact check": 4,
    "news report": 3,
    "documentary": 3,
    "investigation into": 4,
    "victims of": 4,
    "scam exposed": 4,
    "exposing scams": 4,
    "best investment plans": 5,
    "index fund": 4,
    "mutual funds": 5,
    "personal finance": 4,
    "stock market": 5,
    "systematic withdrawal plan": 6,
}

_NEGATIVE_WORDS: dict[str, int] = {
    "tutorial": 2,
    "lecture": 2,
    "explained": 2,
    "explanation": 2,
    "review": 1,
    "debunked": 3,
    "beware": 3,
    "warning": 3,
    "exposed": 3,
    "documentary": 3,
    "cfp": 2,
    "nism": 3,
    "portfolio": 3,
}

_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
_PERCENT_RE = re.compile(r"\b(?:100|200|300|500|1000)\s*%")
_MONEY_MULTIPLIER_RE = re.compile(
    r"(?:\$|usd|usdt)?\s*\d{2,6}\s*(?:to|get|into|->)\s*(?:\$|usd|usdt)?\s*\d{2,7}",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _query_terms(query: str) -> set[str]:
    stop = {
        "a",
        "an",
        "and",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "scam",
        "the",
        "to",
        "video",
        "videos",
        "with",
    }
    return {term for term in _WORD_RE.findall(query.lower()) if len(term) > 2 and term not in stop}


def score_text(text: str, *, query: str = "") -> PrescreenResult:
    """Score text for scam-promotion likelihood."""
    haystack = _normalise(text)
    if not haystack:
        return PrescreenResult(score=0, positives=(), negatives=())

    words = set(_WORD_RE.findall(haystack))
    score = 0
    positives: list[str] = []
    negatives: list[str] = []

    for phrase, weight in _POSITIVE_PHRASES.items():
        if phrase in haystack:
            score += weight
            positives.append(phrase)
    for word, weight in _POSITIVE_WORDS.items():
        if word in words:
            score += weight
            positives.append(word)

    if _PERCENT_RE.search(haystack):
        score += 2
        positives.append("high-percent-return")
    if _MONEY_MULTIPLIER_RE.search(haystack):
        score += 4
        positives.append("money-multiplier")

    terms = _query_terms(query)
    if terms:
        matched = sorted(term for term in terms if term in words)
        if matched:
            boost = min(2, len(matched))
            score += boost
            positives.extend(f"query:{term}" for term in matched[:boost])

    for phrase, weight in _NEGATIVE_PHRASES.items():
        if phrase in haystack:
            score -= weight
            negatives.append(phrase)
    for word, weight in _NEGATIVE_WORDS.items():
        if word in words:
            score -= weight
            negatives.append(word)

    return PrescreenResult(
        score=score,
        positives=tuple(dict.fromkeys(positives)),
        negatives=tuple(dict.fromkeys(negatives)),
    )


def should_collect_text(text: str, *, query: str = "", allow_empty: bool = False) -> bool:
    if not text.strip():
        return allow_empty
    return score_text(text, query=query).keep


__all__ = ["PrescreenResult", "score_text", "should_collect_text"]
