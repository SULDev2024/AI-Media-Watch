"""Regex patterns for high-precision entity extraction (§12).

Each pattern targets one entity class. Patterns are run over both the raw
and the normalized text so that homoglyph/ZW-stripped versions are also caught.

Deduplication is by *canonical form* (stripped of formatting): a wallet that
appears as ``bc1q…`` in speech and ``bc1 q…`` in OCR (space-injected) produces
one canonical entry, not two.
"""

from __future__ import annotations

import regex

# --- Crypto wallets ----------------------------------------------------------

# Bitcoin bech32 (SegWit, P2WPKH/P2WSH). The character set excludes b/i/o/1.
_RE_BTC_BECH32 = regex.compile(r"\bbc1[ac-hj-np-z02-9]{6,87}\b", regex.IGNORECASE)

# Bitcoin legacy (P2PKH starts with 1, P2SH starts with 3).
_RE_BTC_LEGACY = regex.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b")

# Ethereum (and ERC-20 tokens).
_RE_ETH = regex.compile(r"\b0x[a-fA-F0-9]{40}\b")

# TRC-20 (TRON).
_RE_TRC20 = regex.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")

# --- Contact vectors ---------------------------------------------------------

# KZ/RU mobile: +7 (NXX) NXX-XX-XX with optional separators.
_RE_PHONE = regex.compile(r"\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")

# Telegram username: @<letter><alphanum/underscore>{4,31} (Telegram rules).
_RE_TG_HANDLE = regex.compile(r"@[a-zA-Z][a-zA-Z0-9_]{4,31}")

# Telegram deep link (invite links, channel links, etc.).
_RE_TG_LINK = regex.compile(r"t\.me/[a-zA-Z0-9_+/\-]{4,}")

# --- Fraud-specific signals --------------------------------------------------

# Profit percentage claim, optionally tied to a time period.
_RE_PROFIT = regex.compile(
    r"(?:\d{1,3})\s?%(?:\s?(?:в|за|/)?\s?(?:день|неделю|месяц))?",
    regex.IGNORECASE | regex.UNICODE,
)

# Referral / promo code.
# Revision: the code must contain at least one digit.  The previous pattern
# matched ordinary phrases such as "Invite friends" as a referral *code*, which
# then fired referral_code_present and the Rule-B entity gate on plain speech.
_RE_REFERRAL = regex.compile(
    r"(?:реферал|invite|promo)[\s:=]+(?=[A-Za-z]*\d)[A-Za-z0-9]{4,}",
    regex.IGNORECASE | regex.UNICODE,
)


def _canon_wallet(raw: str) -> str:
    """Strip whitespace separators so duplicate wallets with spaces collapse."""
    return raw.replace(" ", "").replace("-", "").upper()


def _canon_phone(raw: str) -> str:
    """Normalize phone to +7XXXXXXXXXX format for deduplication."""
    digits = str(regex.sub(r"\D", "", raw))
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    return digits


def extract_wallets(text: str) -> list[str]:
    """Return deduplicated crypto wallet addresses found in *text*."""
    seen: set[str] = set()
    results: list[str] = []
    for pat in (_RE_BTC_BECH32, _RE_BTC_LEGACY, _RE_ETH, _RE_TRC20):
        for m in pat.finditer(text):
            canon = _canon_wallet(m.group())
            if canon not in seen:
                seen.add(canon)
                results.append(m.group())
    return results


def extract_phones(text: str) -> list[str]:
    """Return deduplicated phone numbers found in *text*."""
    seen: set[str] = set()
    results: list[str] = []
    for m in _RE_PHONE.finditer(text):
        canon = _canon_phone(m.group())
        if canon not in seen:
            seen.add(canon)
            results.append(m.group())
    return results


def extract_handles(text: str) -> list[str]:
    """Return Telegram handles found in *text* (with leading @, deduplicated)."""
    seen: set[str] = set()
    results: list[str] = []
    for m in _RE_TG_HANDLE.finditer(text):
        key = m.group().lower()
        if key not in seen:
            seen.add(key)
            results.append(m.group())
    return results


def extract_links(text: str) -> list[str]:
    """Return t.me/… links found in *text*."""
    seen: set[str] = set()
    results: list[str] = []
    for m in _RE_TG_LINK.finditer(text):
        key = m.group().lower()
        if key not in seen:
            seen.add(key)
            results.append(m.group())
    return results


def extract_profits(text: str) -> list[str]:
    """Return profit-claim spans (% claims with optional time period)."""
    return [m.group() for m in _RE_PROFIT.finditer(text)]


def extract_referrals(text: str) -> list[str]:
    """Return referral/promo code spans."""
    return [m.group() for m in _RE_REFERRAL.finditer(text)]
