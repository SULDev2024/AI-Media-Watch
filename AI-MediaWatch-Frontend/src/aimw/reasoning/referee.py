"""Deterministic referee -- Phase 10 (§10 of AI_MediaWatch_v4.md).

The referee is **code, not an LLM**. It combines:

  1. The deterministic ``ScoreBreakdown`` (Phase 8).
  2. The prosecutor + defense briefs (Phase 10).
  3. Discount validation (``discount_is_valid``) and re-scoring.
  4. The ``ConfidenceBreakdown`` (Phase 9).
  5. Decision A-2: the referee owns the soften-on-low-confidence coupling.
     If ``confidence < MIN_CONFIDENCE_FOR_AUTO``, the level is softened one
     step BEFORE action lookup.
  6. Action routing via ``action_for(level, confidence)``.

Determinism guarantee: given the same ``EvidencePackage`` and the same pair of
``BriefShape`` objects, the referee returns byte-identical output across runs.
When briefs are fetched live (Groq), only the briefs vary -- the referee logic
is pure.

Token-budget fallback (§0.3 #16): if the brief callers raise
``TokenBudgetExhausted``, the referee returns the base score with
``action="analyst_review"`` and ``status_note="token_budget_exhausted"`` --
the package goes to the human queue, no LLM is called.
"""
from __future__ import annotations

import asyncio
from typing import Protocol, cast

from aimw.confidence.engine import compute as compute_confidence
from aimw.confidence.models import BriefShape, ConfidenceBreakdown, DiscountRequest
from aimw.core.schema.evidence import EvidencePackage, FrozenModel
from aimw.core.schema.types import RiskLevel
from aimw.observability.metrics import emit_confidence_softened, emit_token_budget_fallback
from aimw.reasoning.client import TokenBudgetExhausted
from aimw.scoring.actions import (
    MIN_CONFIDENCE_FOR_AUTO,
    Action,
    action_for,
    soften_one_level,
)
from aimw.scoring.discounts import Discount, DiscountKind, discount_is_valid
from aimw.scoring.engine import ScoreBreakdown, score


class BriefProvider(Protocol):
    """Anything that produces prosecutor + defense briefs.

    Implementations: ``ReasoningStub`` (offline) and the Groq-backed
    ``briefs.prosecutor``/``briefs.defense`` pair wrapped by ``LiveBriefs``.
    """

    async def prosecutor(self, pkg: EvidencePackage) -> BriefShape: ...
    async def defense(self, pkg: EvidencePackage) -> BriefShape: ...


_VALID_DISCOUNT_KINDS = {
    "quote_not_offer",
    "verified_license",
    "journalism_corroborated",
    "satire_with_marker",
}


class RefereeResult(FrozenModel):
    """Complete, auditable output of one referee run."""

    base: ScoreBreakdown
    adjusted: ScoreBreakdown
    confidence: ConfidenceBreakdown | None
    prosecutor: BriefShape | None
    defense: BriefShape | None
    valid_discounts: list[DiscountRequest]
    level: RiskLevel
    confidence_softened: bool
    action: Action
    status_note: str | None = None


def _request_to_discount(req: DiscountRequest) -> Discount | None:
    """Convert a DiscountRequest to a scoring Discount, if the kind is known."""
    if req.kind not in _VALID_DISCOUNT_KINDS:
        return None
    return Discount(
        kind=cast(DiscountKind, req.kind),
        piece_indicator_type=req.piece_indicator_type,
        notes=req.reason,
    )


async def run(
    pkg: EvidencePackage,
    briefs_provider: BriefProvider | None = None,
    briefs: tuple[BriefShape, BriefShape] | None = None,
) -> RefereeResult:
    """Run the deterministic referee for *pkg*.

    Parameters
    ----------
    pkg:
        The canonical evidence package.
    briefs_provider:
        A ``BriefProvider`` (stub or live). Used when *briefs* is None.
    briefs:
        Pre-fetched (prosecutor, defense) pair. When supplied the provider is
        not called -- this is the path used by deterministic regression tests
        (same inputs -> byte-identical output).

    Returns
    -------
    RefereeResult
        Full audit trail. ``level`` and ``action`` are the operative outputs.

    Token-budget fallback
    ---------------------
    If the provider raises ``TokenBudgetExhausted``, the result carries the
    base score with no briefs/confidence, ``action="analyst_review"``, and
    ``status_note="token_budget_exhausted"``.
    """
    base = score(pkg)

    pros: BriefShape
    defn: BriefShape

    if briefs is not None:
        pros, defn = briefs
    elif briefs_provider is None:
        raise ValueError("Either briefs_provider or briefs must be supplied")
    else:
        try:
            pros, defn = await asyncio.gather(
                briefs_provider.prosecutor(pkg),
                briefs_provider.defense(pkg),
            )
        except TokenBudgetExhausted:
            emit_token_budget_fallback()
            return RefereeResult(
                base=base,
                adjusted=base,
                confidence=None,
                prosecutor=None,
                defense=None,
                valid_discounts=[],
                level=base.level,
                confidence_softened=False,
                action="analyst_review",
                status_note="token_budget_exhausted",
            )

    valid_discounts: list[DiscountRequest] = []
    scoring_discounts: list[Discount] = []
    for req in defn.discount_requests:
        candidate = _request_to_discount(req)
        if candidate is None:
            continue
        if discount_is_valid(candidate, pkg):
            valid_discounts.append(req)
            scoring_discounts.append(candidate)

    adjusted = (
        score(pkg, discount_ids=tuple(scoring_discounts))
        if scoring_discounts
        else base
    )

    conf = compute_confidence(pkg, pros, defn)

    # Decision A-2 + §7: soften ONLY HIGH/CRITICAL when confidence < 0.60.
    # MEDIUM/LOW/CLEAN are not softened -- the spec explicitly scopes the
    # coupling to "any HIGH/CRITICAL is softened one level". A low-confidence
    # LOW package stays LOW (analyst monitors it) rather than being suppressed.
    level = adjusted.level
    softened = False
    if conf.confidence < MIN_CONFIDENCE_FOR_AUTO and level in ("HIGH", "CRITICAL"):
        new_level = soften_one_level(level)
        softened = new_level != level
        level = new_level

    if softened:
        emit_confidence_softened(adjusted.level, level, conf.confidence)

    action = action_for(level, conf.confidence)

    return RefereeResult(
        base=base,
        adjusted=adjusted,
        confidence=conf,
        prosecutor=pros,
        defense=defn,
        valid_discounts=valid_discounts,
        level=level,
        confidence_softened=softened,
        action=action,
        status_note=None,
    )


__all__ = ["BriefProvider", "RefereeResult", "run"]
