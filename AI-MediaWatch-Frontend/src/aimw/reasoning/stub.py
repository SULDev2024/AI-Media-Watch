"""Deterministic offline replacement for the brief callers -- Phase 10.

``ReasoningStub`` mirrors the brief interface (``prosecutor``/``defense``)
without touching the network. CI uses it when ``GROQ_API_KEY`` is unset; the
ambiguity suite uses it because the test verdicts must be reproducible.

Briefs are looked up by ``EvidencePackage.video_id`` against a built-in
registry. Unknown video_ids get a generic shape derived from the package
evidence so the integration tests still produce valid output.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from aimw.confidence.models import BriefArgument, BriefShape, DiscountRequest
from aimw.core.schema.evidence import EvidencePackage


@dataclass(frozen=True)
class _StubEntry:
    prosecutor: BriefShape
    defense: BriefShape


def _strong_prosecutor_from_pieces(pkg: EvidencePackage) -> BriefShape:
    """Generic prosecutor brief: cite every incriminating piece once."""
    incrim_types = sorted(
        {p.indicator_type for p in pkg.evidence if p.polarity == "incriminating"}
    )
    if not incrim_types:
        return BriefShape(arguments=[], discount_requests=[])
    strength = "strong" if len(incrim_types) >= 3 else "medium" if incrim_types else "weak"
    arg = BriefArgument(
        statement=(
            f"The package shows {len(incrim_types)} distinct incriminating indicators: "
            f"{', '.join(incrim_types)}. Multiple indicators within one piece of "
            "content materially raises the likelihood of unlicensed financial activity."
        ),
        evidence_piece_ids=incrim_types,
        strength=strength,
    )
    return BriefShape(arguments=[arg], discount_requests=[])


def _weak_defense_from_pieces(pkg: EvidencePackage) -> BriefShape:
    """Generic defense brief: weak counter when no mitigating evidence exists."""
    mitig_types = sorted(
        {p.indicator_type for p in pkg.evidence if p.polarity == "mitigating"}
    )
    if not mitig_types:
        return BriefShape(arguments=[], discount_requests=[])
    return BriefShape(
        arguments=[
            BriefArgument(
                statement=(
                    f"Mitigating indicators present: {', '.join(mitig_types)}."
                ),
                evidence_piece_ids=mitig_types,
                strength="weak",
            )
        ],
        discount_requests=[],
    )


# ---------------------------------------------------------------------------
# Registry of known fixtures (§11 ambiguity cases)
# ---------------------------------------------------------------------------


def _case_b_briefs() -> _StubEntry:
    """Case B: implicit guarantee -- prosecutor explains the implication."""
    pros = BriefShape(
        arguments=[
            BriefArgument(
                statement=(
                    "Although the speaker avoids the word 'guaranteed', the "
                    "fixed daily-return phrasing is a structural promise of "
                    "return. KZ Art. 217 covers any solicitation that promises "
                    "a fixed return without an АРРФР licence."
                ),
                evidence_piece_ids=["guaranteed_return", "unlicensed_advice"],
                strength="medium",
            ),
        ],
        discount_requests=[],
    )
    defn = BriefShape(
        arguments=[
            BriefArgument(
                statement=(
                    "The speaker did not literally say 'guaranteed'; this could "
                    "be informal phrasing rather than a guarantee claim."
                ),
                evidence_piece_ids=["guaranteed_return"],
                strength="weak",
            )
        ],
        discount_requests=[],
    )
    return _StubEntry(pros, defn)


def _case_d_briefs() -> _StubEntry:
    """Case D: licensed advisor -- defense requests verified_license discount."""
    pros = BriefShape(
        arguments=[
            BriefArgument(
                statement=(
                    "An invest-now solicitation is present; this needs "
                    "verification against licensing."
                ),
                evidence_piece_ids=["unlicensed_advice"],
                strength="medium",
            )
        ],
        discount_requests=[],
    )
    defn = BriefShape(
        arguments=[
            BriefArgument(
                statement=(
                    "The speaker is an АФН-licensed advisor. The licence "
                    "identifier appears in raw_value of the licensing piece."
                ),
                evidence_piece_ids=["licensing"],
                strength="strong",
            ),
        ],
        discount_requests=[
            DiscountRequest(
                kind="verified_license",
                piece_indicator_type="unlicensed_advice",
                reason=(
                    "Speaker holds a verifiable АФН licence; the invest-now "
                    "language is therefore not unlicensed advice."
                ),
            )
        ],
    )
    return _StubEntry(pros, defn)


def _case_e_briefs() -> _StubEntry:
    """Case E: coordinated campaign -- prosecutor cites network evidence."""
    pros = BriefShape(
        arguments=[
            BriefArgument(
                statement=(
                    "The package shows network corroboration (multiple "
                    "accounts pushing the same indicator within minutes). "
                    "This pattern is consistent with a coordinated promotion."
                ),
                evidence_piece_ids=["pump_signal", "referral_code_present"],
                strength="strong",
            )
        ],
        discount_requests=[],
    )
    defn = BriefShape(arguments=[], discount_requests=[])
    return _StubEntry(pros, defn)


def _case_c_journalist_briefs() -> _StubEntry:
    """Case C: journalist, no wallet -- defense requests journalism_corroborated."""
    pros = BriefShape(
        arguments=[
            BriefArgument(
                statement=(
                    "The speaker recites guarantee and recruitment phrasing "
                    "in a clip that lacks a payment rail; investigators should "
                    "still consider whether the clip itself is incriminating."
                ),
                evidence_piece_ids=["guaranteed_return", "pyramid_recruit"],
                strength="weak",
            )
        ],
        discount_requests=[],
    )
    defn = BriefShape(
        arguments=[
            BriefArgument(
                statement=(
                    "The clip is an investigative report exposing a scheme; "
                    "journalism_framing piece corroborates this and no "
                    "payment entities are present."
                ),
                evidence_piece_ids=["journalism_framing"],
                strength="strong",
            )
        ],
        discount_requests=[
            DiscountRequest(
                kind="journalism_corroborated",
                piece_indicator_type="guaranteed_return",
                reason="Speech-sourced journalism framing, no payment rail.",
            ),
            DiscountRequest(
                kind="journalism_corroborated",
                piece_indicator_type="pyramid_recruit",
                reason="Same journalism framing applies to recruit language.",
            ),
        ],
    )
    return _StubEntry(pros, defn)


_REGISTRY: dict[str, _StubEntry] = {
    "case-b-implicit": _case_b_briefs(),
    "case-d-licensed": _case_d_briefs(),
    "case-e-campaign": _case_e_briefs(),
    "case-c-journalist": _case_c_journalist_briefs(),
}


@dataclass(frozen=True)
class ReasoningStub:
    """Deterministic offline stand-in for the brief callers."""

    registry: dict[str, _StubEntry] = field(default_factory=lambda: dict(_REGISTRY))

    async def prosecutor(self, pkg: EvidencePackage) -> BriefShape:
        entry = self.registry.get(pkg.video_id)
        if entry is not None:
            return entry.prosecutor
        return _strong_prosecutor_from_pieces(pkg)

    async def defense(self, pkg: EvidencePackage) -> BriefShape:
        entry = self.registry.get(pkg.video_id)
        if entry is not None:
            return entry.defense
        return _weak_defense_from_pieces(pkg)
