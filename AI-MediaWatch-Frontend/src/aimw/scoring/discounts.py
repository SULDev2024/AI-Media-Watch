"""Discount validation — §0.2 issue #6 of AI_Media_Watch_v4_Implementation_Prompts.md.

The referee (Phase 10) receives discount requests from the LLM defense brief and
passes only the validated ones to ``engine.score()``.  This module decides
validity — deterministically, with no LLM involvement.

Valid discount kinds
--------------------
quote_not_offer        The cited incriminating piece is in quotation context
                       (reporting/quoting, not offering).
verified_license       A licensing EvidencePiece exists with recovery_method="raw"
                       and raw_value matching a verifiable licence identifier.
journalism_corroborated  A journalism_framing piece exists from source="speech"
                          AND the package has no live payment entity.
satire_with_marker     A satire_markers EvidencePiece exists in the package
                       (marker /s or 😉 was detected).

Anything else → False (silently dropped by the referee).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import ConfigDict

from aimw.core.schema.evidence import EvidencePackage, FrozenModel

# Matches a verifiable KZ licence identifier in raw_value.
_LICENSE_RE: re.Pattern[str] = re.compile(
    r"(АФН|AFN|CFP|АРРФР|лицензия|лицензир)\s*[№#]?\s*[\w\-]{4,}",
    re.UNICODE,
)

# Matches quotation marks that may precede incriminating text.
_QUOTE_OPEN_RE: re.Pattern[str] = re.compile(r'[«""\'`]', re.UNICODE)

DiscountKind = Literal[
    "quote_not_offer",
    "verified_license",
    "journalism_corroborated",
    "satire_with_marker",
]


class Discount(FrozenModel):
    """A validated or candidate discount from the LLM defense brief.

    ``piece_indicator_type`` names which indicator_type the discount targets;
    the engine filters pieces of that type when the discount is valid.
    ``notes`` is informational only — never used in validation logic.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DiscountKind
    piece_indicator_type: str | None = None
    notes: str | None = None


def discount_is_valid(discount: Discount, package: EvidencePackage) -> bool:
    """Return True iff the discount is substantiated by evidence in *package*.

    This is the sole gate between LLM requests and the deterministic score.
    Each kind requires specific, independently verifiable evidence; a claim
    that cannot be checked against the package is always False.
    """
    kind = discount.kind

    if kind == "quote_not_offer":
        return _validate_quote_not_offer(discount, package)
    if kind == "verified_license":
        return _validate_verified_license(package)
    if kind == "journalism_corroborated":
        return _validate_journalism_corroborated(package)
    if kind == "satire_with_marker":
        return _validate_satire_with_marker(package)

    return False  # unknown kind — silently rejected


# ---------------------------------------------------------------------------
# Per-kind validators
# ---------------------------------------------------------------------------


def _validate_quote_not_offer(
    discount: Discount,
    package: EvidencePackage,
) -> bool:
    """Check that the cited incriminating piece appears in quotation context.

    Phase 19B remediation — hard funnel-entity gate:
    A video that is actively soliciting via a Telegram handle/link, a crypto
    wallet, or a payment phone is making the offer, regardless of how
    elegantly the LLM defense frames the language. ``quote_not_offer`` is
    refused in that case before the quotation-context check runs.

    Excluded from the gate by deliberate choice: ``referral_codes`` and
    ``websites``. Educational explainers in the Phase 19B benchmark legitimately
    extract those fields (e.g. "promo code", citation URLs); blocking on them
    would re-introduce false positives the benchmark proved we can avoid.
    """
    hard_funnel = bool(
        package.entities.telegram_handles
        or package.entities.telegram_links
        or package.entities.crypto_wallets
        or package.entities.payment_phones
    )
    if hard_funnel:
        return False

    target_type = discount.piece_indicator_type
    if not target_type:
        return False
    for piece in package.evidence:
        if piece.indicator_type != target_type:
            continue
        # Accept if a quotation mark appears within 15 chars before raw_value
        # in the piece's content field (the context window from the tagger).
        content = piece.content
        raw = piece.raw_value
        idx = content.find(raw)
        if idx >= 0:
            prefix = content[max(0, idx - 15) : idx]
            if _QUOTE_OPEN_RE.search(prefix):
                return True
        # Fallback: raw_value itself starts or ends with a quotation mark.
        if (raw and raw[0] in "«\"'`") or (raw and raw[-1] in "»\"'`"):
            return True
    return False


def _validate_verified_license(package: EvidencePackage) -> bool:
    """Accept if there is a licensing piece with a verifiable licence id."""
    for piece in package.evidence:
        if (
            piece.indicator_type == "licensing"
            and piece.recovery_method == "raw"
            and _LICENSE_RE.search(piece.raw_value)
        ):
            return True
    return False


def _validate_journalism_corroborated(package: EvidencePackage) -> bool:
    """Accept if journalism_framing from speech AND no payment entity."""
    has_payment = bool(package.entities.crypto_wallets or package.entities.payment_phones)
    if has_payment:
        return False
    return any(
        p.indicator_type == "journalism_framing" and p.source == "speech" for p in package.evidence
    )


def _validate_satire_with_marker(package: EvidencePackage) -> bool:
    """Accept if a satire_markers piece was detected (marker in text)."""
    return any(p.indicator_type == "satire_markers" for p in package.evidence)
