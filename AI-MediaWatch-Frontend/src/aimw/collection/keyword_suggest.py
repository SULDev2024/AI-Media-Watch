"""Auto-keyword suggestion — frequency-based extraction from flagged content.

This module lives in the collection layer so it MUST NOT import scoring,
reasoning, entities, or DB internals (see test_no_leakage.py).  The pure
frequency extractor runs locally on text; the LLM-powered expansion and
DB reads live in ``aimw.workers.keyword_suggest`` (which may import anything).

Storage: suggestions are persisted in Redis under ``aimw:keyword_suggestions``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from typing import Any

from aimw.core.logging import get_logger

log = get_logger("aimw.collection.keyword_suggest")

_REDIS_KEY = "aimw:keyword_suggestions"

_SCAM_PATTERN_SEEDS = [
    r"invest\s+\$?\d+.*(?:get|earn|receive|make)\s+\$?\d+",
    r"guaranteed?\s+(?:profit|return|income|earning)",
    r"(?:join|contact|message|DM)\s+(?:us|me|admin|now)",
    r"(?:passive|daily|weekly)\s+income",
    r"minimum\s+(?:investment|deposit)",
    r"(?:telegram|whatsapp|signal)\s+(?:group|channel|bot)",
    r"(?:crypto|bitcoin|forex)\s+(?:investment|trading|signal)",
    r"(?:100|200|300|500)%\s+(?:profit|return|ROI)",
    r"(?:withdrawal|payout)\s+(?:within|in)\s+\d+\s*(?:hour|day|minute)",
    r"(?:referral|affiliate)\s+(?:bonus|commission|program)",
]

_STOP = frozenset({
    "the", "and", "for", "that", "this", "with", "you", "are", "was",
    "has", "have", "will", "can", "not", "but", "from", "they", "been",
    "all", "its", "our", "your", "their", "about", "into", "more",
    "also", "some", "just", "very", "when", "what", "which",
})


def extract_frequency_keywords(texts: list[str], top_n: int = 20) -> list[dict[str, Any]]:
    """Extract recurring scam-related n-grams from flagged content."""
    bigram_counter: Counter[str] = Counter()
    trigram_counter: Counter[str] = Counter()
    pattern_hits: Counter[str] = Counter()

    for text in texts:
        text_lower = text.lower()
        words = re.findall(r"[a-zA-Zа-яА-ЯёЁЀ-ӿ]+", text_lower)

        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i + 1]}"
            bigram_counter[bigram] += 1

        for i in range(len(words) - 2):
            trigram = f"{words[i]} {words[i + 1]} {words[i + 2]}"
            trigram_counter[trigram] += 1

        for pattern in _SCAM_PATTERN_SEEDS:
            matches = re.findall(pattern, text_lower)
            for m in matches:
                normalized = re.sub(r"\s+", " ", m.strip())
                if normalized:
                    pattern_hits[normalized] += 1

    suggestions: list[dict[str, Any]] = []

    for phrase, count in pattern_hits.most_common(top_n):
        if count >= 2:
            suggestions.append({
                "keyword": phrase,
                "source": "pattern",
                "count": count,
                "confidence": min(1.0, count / 5),
            })

    for phrase, count in trigram_counter.most_common(top_n * 2):
        words_in = phrase.split()
        if any(w in _STOP for w in words_in):
            continue
        if count >= 3:
            suggestions.append({
                "keyword": phrase,
                "source": "trigram",
                "count": count,
                "confidence": min(0.8, count / 8),
            })

    for phrase, count in bigram_counter.most_common(top_n * 2):
        words_in = phrase.split()
        if any(w in _STOP for w in words_in):
            continue
        if count >= 4:
            suggestions.append({
                "keyword": phrase,
                "source": "bigram",
                "count": count,
                "confidence": min(0.6, count / 10),
            })

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for s in sorted(suggestions, key=lambda x: x["confidence"], reverse=True):
        if s["keyword"] not in seen:
            seen.add(s["keyword"])
            deduped.append(s)

    return deduped[:top_n]


def store_suggestions(suggestions: list[dict[str, Any]], flagged_count: int) -> None:
    """Persist suggestions to Redis."""
    import redis

    from aimw.core.config import get_settings

    try:
        r = None if get_settings().eager else redis.Redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)
        payload = {
            "suggestions": suggestions,
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
            "flagged_count": flagged_count,
        }
        if r is None:
            path = get_settings().resolved_data_dir / "keyword-suggestions.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            r.set(_REDIS_KEY, json.dumps(payload))
    except Exception as exc:
        log.warning("keyword_suggest_store_failed", error=str(exc))


def get_suggestions() -> dict[str, Any]:
    """Read stored suggestions from Redis."""
    import redis

    from aimw.core.config import get_settings

    try:
        r = None if get_settings().eager else redis.Redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)
        if r is None:
            path = get_settings().resolved_data_dir / "keyword-suggestions.json"
            raw = path.read_text(encoding="utf-8") if path.exists() else None
        else:
            raw = r.get(_REDIS_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {"suggestions": [], "generated_at": None, "flagged_count": 0}


__all__ = [
    "extract_frequency_keywords",
    "store_suggestions",
    "get_suggestions",
]
