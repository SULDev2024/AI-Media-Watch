"""Confidence engine — §7 of AI_MediaWatch_v4.md.

``compute(package, prosecutor, defense)`` is the single entry point.  It
returns a ``ConfidenceBreakdown`` with a complete audit trail.

Formula (§7 verbatim):
    agreement  = fraction of incriminating indicator types corroborated by >= 2 sources
    redundancy = min(n_independent_strong_sources / 3, 1.0)
    certainty  = mean per-piece certainty (1.0 for raw/None, 0.6 for recovered)
    gap        = |strength_num(prosecutor) - strength_num(defense)|
    confidence = round(0.30*agreement + 0.25*redundancy + 0.20*certainty + 0.25*gap, 2)

Decision coupling (§7): if confidence < MIN_CONFIDENCE_FOR_AUTO, any HIGH or
CRITICAL level is softened one step by soften_one_level() before action routing.
That coupling is enforced in the Phase 10 referee; this module only computes.

Nothing here touches persistence, LLMs, or the network.
Same inputs -> byte-identical ConfidenceBreakdown every run.
"""
from __future__ import annotations

from aimw.confidence.models import BriefShape, ConfidenceBreakdown
from aimw.core.schema.evidence import EvidencePackage

# Strength -> numeric value for the argument-gap formula.
# Chosen so that the §7 worked examples are achievable from package+brief construction:
#   strong(1.0) vs weak(0.2) -> gap = 0.8  (strong clear case)
#   medium(0.4) vs weak(0.2) -> gap = 0.2  (near-tie case)
# NOTE: the implementation prompt in Phase_9 states {strong:1.0, medium:0.6, weak:0.3};
# that mapping cannot produce gap=0.8 or gap=0.2 from any brief pair, so it contradicts
# the §7 worked examples.  The mapping below is derived from the examples (spec governs).
_STRENGTH_NUM: dict[str, float] = {
    "strong": 1.0,
    "medium": 0.4,
    "weak": 0.2,
}


# ---------------------------------------------------------------------------
# Sub-computations
# ---------------------------------------------------------------------------


def _group_indicators_by_source(package: EvidencePackage) -> dict[str, set[str]]:
    """Return {indicator_type: set_of_sources} for all incriminating pieces."""
    result: dict[str, set[str]] = {}
    for p in package.evidence:
        if p.polarity == "incriminating":
            result.setdefault(p.indicator_type, set()).add(p.source)
    return result


def _count_independent_strong(package: EvidencePackage) -> int:
    """Count distinct sources that have at least one strong incriminating piece.

    Saturates redundancy at 3 independent sources (see formula).
    """
    sources_with_strong: set[str] = set()
    for p in package.evidence:
        if p.polarity == "incriminating" and p.strength == "strong":
            sources_with_strong.add(p.source)
    return len(sources_with_strong)


def _mean_entity_certainty(package: EvidencePackage) -> float:
    """Mean per-piece certainty: 1.0 for raw/None recovery, 0.6 for recovered.

    Returns 1.0 for packages with no evidence (nothing to be uncertain about).
    """
    pieces = list(package.evidence)
    if not pieces:
        return 1.0
    total = sum(
        1.0 if p.recovery_method in (None, "raw") else 0.6 for p in pieces
    )
    return total / len(pieces)


def _strength_num(brief: BriefShape) -> float:
    """Return the numeric strength of a brief's strongest argument.

    Empty brief -> weak (0.2): no arguments is the weakest possible position.
    Uses semantic ordering (strong > medium > weak), not lexicographic.
    """
    if not brief.arguments:
        return _STRENGTH_NUM["weak"]
    best = max(brief.arguments, key=lambda a: _STRENGTH_NUM[a.strength])
    return _STRENGTH_NUM[best.strength]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute(
    package: EvidencePackage,
    prosecutor: BriefShape,
    defense: BriefShape,
) -> ConfidenceBreakdown:
    """Compute confidence for *package* given two opposing briefs.

    Parameters
    ----------
    package:
        The canonical evidence object.  Read-only; never mutated.
    prosecutor:
        LLM brief arguing incriminating.  Consumed as a typed shape only.
    defense:
        LLM brief arguing mitigating.  Consumed as a typed shape only.

    Returns
    -------
    ConfidenceBreakdown
        Full audit trail.  ``confidence`` is the operative output.
        Range: 0.00 .. 1.00 (rounded to 2 d.p.).
    """
    indicators = _group_indicators_by_source(package)
    multi = [ind for ind, sources in indicators.items() if len(sources) >= 2]
    agreement = len(multi) / max(len(indicators), 1)

    n_strong = _count_independent_strong(package)
    redundancy = min(n_strong / 3, 1.0)

    certainty = _mean_entity_certainty(package)

    gap = abs(_strength_num(prosecutor) - _strength_num(defense))

    # Decision A-4 (Phase 10): when no incriminating indicators exist, the
    # package has nothing to be confident about. Returning 0.0 here prevents
    # an empty package from carrying a misleading 0.20 confidence (which would
    # otherwise come from certainty=1.0 default + no other contributions).
    if not indicators:
        return ConfidenceBreakdown(
            agreement=0.0,
            redundancy=0.0,
            certainty=certainty,
            gap=gap,
            confidence=0.0,
        )

    confidence = round(
        0.30 * agreement
        + 0.25 * redundancy
        + 0.20 * certainty
        + 0.25 * gap,
        2,
    )

    return ConfidenceBreakdown(
        agreement=agreement,
        redundancy=redundancy,
        certainty=certainty,
        gap=gap,
        confidence=confidence,
    )
