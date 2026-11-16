"""Payment-channel verification and promoter linkage (revision, reviewers R1/R2).

Reviewer R2: *"Clarify how payment channels are verified and linked to
promoters. Avoid penalizing journalism or educational content simply because it
reproduces wallet addresses or referral codes."*

This module answers both halves deterministically (no LLM involvement):

1. **Format verification** (:func:`verify_wallet_format`). A string that merely
   *looks* like a wallet is checked against the address checksum of its chain:
   Base58Check (double-SHA256) for Bitcoin legacy/P2SH and TRON, BIP-173/350
   bech32/bech32m for Bitcoin SegWit, and the 0x+40-hex shape for EVM chains
   (EIP-55 mixed-case checksums need Keccak, which is not in the stdlib, so EVM
   addresses are reported as ``"format_only"``). A checksum failure usually
   means a placeholder in a tutorial (``bc1qxxxx…``) or an OCR misread.
   Format verification does **not** establish ownership; on-chain ownership
   attribution is out of scope and is stated as a limitation.

2. **Promoter linkage** (:func:`classify_linkage`). For every payment-type
   entity (crypto wallet, payment phone, referral/promo code, Telegram link or
   handle) the sentence(s) in which it occurs are inspected:

   * ``"promoter"`` — a non-negated call-to-action addressed to the viewer
     ("send", "deposit", "use my code", "join our channel", "пиши", "переведи"),
     or a first-person ownership marker ("my wallet", "наш канал").
   * ``"reported"`` — the entity sits in a warning / reporting / quotation
     context ("the scammer's wallet", "do not send", "victims sent", "reported
     to police", "мошенники") and no un-negated CTA accompanies it.
   * ``"unlinked"`` — neither cue is present.

   Scoring policy (see ``aimw.scoring``): only ``promoter`` rails fire the
   Rule-B entity gate and void journalism/educational mitigation; ``unlinked``
   rails still raise a payment signal but one strength level weaker;
   ``reported`` rails raise no incriminating signal at all (they are kept in the
   package for the intelligence graph, where a wallet named in a warning is
   useful blacklist intelligence).
   Invalid-checksum wallets are never ``promoter``: at best ``unlinked``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

Linkage = str  # "promoter" | "reported" | "unlinked"

# ---------------------------------------------------------------------------
# 1. Wallet format verification
# ---------------------------------------------------------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _b58decode(s: str) -> bytes | None:
    n = 0
    for ch in s:
        idx = _B58_ALPHABET.find(ch)
        if idx < 0:
            return None
        n = n * 58 + idx
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


def _base58check_ok(s: str) -> bool:
    raw = _b58decode(s)
    if raw is None or len(raw) < 5:
        return False
    payload, checksum = raw[:-4], raw[-4:]
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] == checksum


def _bech32_polymod(values: Iterable[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def _bech32_ok(addr: str) -> bool:
    if addr.lower() != addr and addr.upper() != addr:
        return False  # mixed case is invalid in bech32
    addr = addr.lower()
    pos = addr.rfind("1")
    if pos < 1 or pos + 7 > len(addr):
        return False
    hrp, data = addr[:pos], addr[pos + 1 :]
    if any(c not in _BECH32_CHARSET for c in data):
        return False
    values = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    values += [_BECH32_CHARSET.find(c) for c in data]
    const = _bech32_polymod(values)
    return const in (1, 0x2BC830A3)  # bech32 (BIP-173) or bech32m (BIP-350)


def verify_wallet_format(addr: str) -> str:
    """Return ``"valid"``, ``"invalid"`` or ``"format_only"`` for *addr*."""
    a = addr.strip().replace(" ", "")
    if a.lower().startswith("bc1"):
        return "valid" if _bech32_ok(a) else "invalid"
    if a.startswith("0x") and re.fullmatch(r"0x[0-9a-fA-F]{40}", a):
        return "format_only"
    if a[:1] in ("1", "3", "T"):
        return "valid" if _base58check_ok(a) else "invalid"
    return "format_only"


# ---------------------------------------------------------------------------
# 2. Promoter linkage
# ---------------------------------------------------------------------------

# Calls to action addressed to the viewer, and first-person ownership markers.
_CTA = re.compile(
    r"\b(send|deposit|transfer|pay|top[ -]?up|join|subscribe|register|sign[ -]?up|"
    r"use (?:my|our|the) (?:code|link|promo)|use code|enter (?:my |the )?code|"
    r"dm me|message me|write (?:to )?me|contact (?:me|us)|click|tap|buy|invest|"
    r"get started|claim)\b"
    r"|\b(my|our) (?:wallet|address|code|link|channel|group|number|card)\b"
    r"|(отправ|переведи|переводи|пополн|вступай|подпис|регистрир|пиши|напиши|"
    r"жми|переходи|мой (?:кошел|код|канал|номер)|наш (?:канал|кошел|чат))",
    re.IGNORECASE | re.UNICODE,
)

# Warning / reporting / quotation context.
_REPORTED = re.compile(
    r"\b(scam(?:mer|mers|s)?|fraud(?:ster|sters|ulent)?|fake|impostor|victims?|"
    r"reported|police|warning|beware|blacklist(?:ed)?|stolen|was used|were used|"
    r"used by (?:the )?(?:scam|fraud)|example|for example|e\.g\.|placeholder|"
    r"sample|investigat\w*|journalist|news|according to|allegedly)\b"
    r"|(мошенн|афер|жертв|полици|осторожно|пример|расследован|украден)",
    re.IGNORECASE | re.UNICODE,
)

_NEGATION = re.compile(
    r"\b(do not|don't|never|not|no one should|avoid|stop)\b|\b(не|никогда)\b",
    re.IGNORECASE | re.UNICODE,
)

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")


def _sentences_with(value: str, texts: Iterable[str]) -> list[str]:
    v = value.lower()
    out: list[str] = []
    for text in texts:
        for sent in _SENT_SPLIT.split(text):
            if v in sent.lower():
                out.append(sent)
    return out


def _has_unnegated_cta(sentence: str) -> bool:
    for m in _CTA.finditer(sentence):
        prefix = sentence[max(0, m.start() - 25) : m.start()]
        if not _NEGATION.search(prefix):
            return True
    return False


def classify_value(value: str, texts: Iterable[str], *, is_wallet: bool = False) -> Linkage:
    """Classify one entity value given all text (speech segments + OCR blocks)."""
    sents = _sentences_with(value, texts)
    if not sents:
        return "unlinked"
    cta = any(_has_unnegated_cta(s) for s in sents)
    reported = any(_REPORTED.search(s) for s in sents)
    negated_cta = any(_CTA.search(s) and not _has_unnegated_cta(s) for s in sents)

    if is_wallet and verify_wallet_format(value) == "invalid":
        # A checksum-invalid "wallet" cannot receive funds: placeholder/misread.
        return "reported" if (reported or negated_cta) else "unlinked"
    if cta and not reported:
        return "promoter"
    if cta and reported:
        # Mixed context ("scammers hate it — send to my wallet now"): only a CTA
        # in a sentence *without* reporting cues counts as promotion.
        if any(_has_unnegated_cta(s) and not _REPORTED.search(s) for s in sents):
            return "promoter"
        return "reported"
    if reported or negated_cta:
        return "reported"
    return "unlinked"


def classify_linkage(
    *,
    wallets: list[str],
    payment_values: list[str],
    texts: list[str],
) -> dict[str, Linkage]:
    """Return ``{entity_value: linkage}`` for every payment-type entity."""
    result: dict[str, Linkage] = {}
    for w in wallets:
        result[w] = classify_value(w, texts, is_wallet=True)
    for v in payment_values:
        if v not in result:
            result[v] = classify_value(v, texts)
    return result


__all__ = ["classify_linkage", "classify_value", "verify_wallet_format"]
