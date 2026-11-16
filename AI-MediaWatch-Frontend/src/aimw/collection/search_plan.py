"""Search expansion for high-yield scam collection.

Operators often enter broad terms like ``scam`` or ``crypto``. Real scam
uploads usually avoid those labels and use bait language instead. This module
turns a small admin query list into focused discovery variants while keeping a
hard cap so each collector tick remains bounded.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z0-9]+")

_GENERIC_TERMS = frozenset({"fraud", "scam", "scams", "spam"})
_CRYPTO_TERMS = frozenset(
    {"bitcoin", "btc", "crypto", "forex", "invest", "investment", "trading", "usdt"}
)
_GAMBLING_TERMS = frozenset({"bet", "betting", "casino", "gambling", "slot", "slots"})

_GENERIC_VARIANTS = (
    "guaranteed profit crypto signals",
    "minimum deposit usdt daily income",
    "join vip telegram investment",
    "casino bonus promo code betting signals",
    "passive income telegram minimum deposit usdt",
    "withdraw proof investment platform",
)

_CRYPTO_VARIANTS = (
    "guaranteed profit crypto signals",
    "minimum deposit usdt investment",
    "join vip telegram crypto",
    "ai trading bot daily income",
    "forex signals guaranteed profit",
    "binance pay investment platform",
)

_GAMBLING_VARIANTS = (
    "casino bonus promo code",
    "betting signals fixed match",
    "slot bonus referral link",
    "risk free casino bonus",
    "telegram betting vip group",
    "guaranteed betting profit",
)

_REGION_ALIASES: dict[str, tuple[str, ...]] = {
    "kz": ("kazakhstan", "kz", "қазақстан", "казахстан", "almaty", "astana", "kaspi"),
    "kazakhstan": (
        "kazakhstan",
        "kz",
        "қазақстан",
        "казахстан",
        "almaty",
        "astana",
        "kaspi",
        "тенге",
    ),
}

_REGION_VARIANTS: dict[str, tuple[str, ...]] = {
    "kazakhstan": (
        "kazakhstan crypto investment telegram",
        "kz usdt guaranteed profit",
        "kaspi заработок инвестиции",
        "казахстан гарантированный доход",
        "қазақстан табыс инвестиция",
        "алматы ставки казино бонус",
        "астана крипто сигналдар telegram",
        "тенге пассивный доход usdt",
    ),
}


def _tokens(query: str) -> set[str]:
    return set(_WORD_RE.findall(query.lower()))


def _normalise_region(region_focus: str | None) -> str:
    raw = (region_focus or "global").strip().lower()
    if raw in ("", "global", "worldwide", "any"):
        return "global"
    if raw in ("kz", "kazakhstan", "қазақстан", "казахстан"):
        return "kazakhstan"
    return raw


def _variant_pool(query: str) -> tuple[str, ...]:
    tokens = _tokens(query)
    if tokens & _GAMBLING_TERMS:
        return _GAMBLING_VARIANTS
    if tokens & _CRYPTO_TERMS:
        return _CRYPTO_VARIANTS
    if not tokens or tokens <= _GENERIC_TERMS:
        return _GENERIC_VARIANTS
    return _GENERIC_VARIANTS[:3] + _CRYPTO_VARIANTS[:2] + _GAMBLING_VARIANTS[:1]


def _merge_query_variant(base: str, variant: str) -> str:
    base_tokens = _tokens(base)
    variant_tokens = _tokens(variant)
    if base_tokens <= _GENERIC_TERMS or base_tokens & variant_tokens:
        return variant
    return f"{base} {variant}"


def expand_queries(
    queries: list[str],
    *,
    region_focus: str | None = None,
    variants_per_query: int = 5,
    max_total: int = 18,
) -> list[str]:
    """Return original queries plus high-signal scam-bait variants.

    The original user-entered terms always stay first. Variants are deduped and
    capped to avoid accidental runaway crawling.
    """
    variants_per_query = max(0, min(variants_per_query, 8))
    max_total = max(1, min(max_total, 50))

    region = _normalise_region(region_focus)
    expanded: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        query = " ".join(value.strip().split())
        key = query.lower()
        if query and key not in seen and len(expanded) < max_total:
            seen.add(key)
            expanded.append(query)

    for query in queries:
        _add(query)

    for query in queries:
        base = " ".join(query.strip().split())
        if not base or len(expanded) >= max_total:
            continue
        pool = _variant_pool(base)
        for variant in pool[:variants_per_query]:
            if len(expanded) >= max_total:
                break
            _add(_merge_query_variant(base, variant))

    if region != "global":
        aliases = _REGION_ALIASES.get(region, (region,))
        for query in queries:
            base = " ".join(query.strip().split())
            if not base or len(expanded) >= max_total:
                break
            for alias in aliases[:4]:
                if len(expanded) >= max_total:
                    break
                _add(f"{base} {alias}")
        for variant in _REGION_VARIANTS.get(region, ()):
            if len(expanded) >= max_total:
                break
            _add(variant)

    return expanded


__all__ = ["expand_queries"]
