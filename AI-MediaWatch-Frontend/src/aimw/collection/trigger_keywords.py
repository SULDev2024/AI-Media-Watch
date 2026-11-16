"""Trigger keywords — COLLECTION PRIORITY ONLY, never evidence (§4).

These keywords decide *processing order* under rate limits. They are NEVER cited
as evidence: doing so would be circular (the evidence indicator vocabulary lives
separately in Phase 8's ``signals.yaml``). This module must be imported only
from within ``aimw.collection`` — enforced by ``tests/collection/test_no_leakage.py``.

Located inside the collection package (rather than the repo-root ``config/``) so
it is importable identically across the API process, Celery workers, tests, and
Docker, and so the "collection-only" rule is also physical.

Keyword set mirrors §4 of ``AI_MediaWatch_v4.md`` exactly, grouped so the
priority heuristic counts distinct *categories* of signal rather than raw
frequency (see ``priority.py``).
"""

from __future__ import annotations

GUARANTEE: frozenset[str] = frozenset(
    {
        "гарантир",
        "без риска",
        "100% прибыл",
        "ежедневн выплат",
        "пассивн доход",
        "доход с каждого",
    }
)
REFERRAL: frozenset[str] = frozenset(
    {
        "пригласи друзей",
        "реферальн",
    }
)
GAMBLING: frozenset[str] = frozenset(
    {
        "ставки",
        "казино",
        "беспроигрышн",
        "обыграй",
    }
)
KAZAKH: frozenset[str] = frozenset(
    {
        "табыс",
        "кепілдік",
        "пайда",
    }
)
CONTACT: frozenset[str] = frozenset(
    {
        "@",
        "t.me/",
        "USDT",
        "крипт",
    }
)

TRIGGER_KEYWORD_GROUPS: dict[str, frozenset[str]] = {
    "GUARANTEE": GUARANTEE,
    "REFERRAL": REFERRAL,
    "GAMBLING": GAMBLING,
    "KAZAKH": KAZAKH,
    "CONTACT": CONTACT,
}

# Flat union mirroring §4 (kept for reference / parity checks). Not used directly
# by the priority heuristic, which counts groups.
TRIGGER_KEYWORDS: frozenset[str] = frozenset().union(*TRIGGER_KEYWORD_GROUPS.values())
