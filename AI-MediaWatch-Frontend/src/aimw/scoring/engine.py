"""Signed scoring engine — §6 of AI_MediaWatch_v4.md.

``score(package, discount_ids=())`` is the single entry point.  It applies the
four anti-gaming rules in exactly the order specified in §6.2 and §6.4, then
returns a ``ScoreBreakdown`` with a complete, line-by-line audit trail.

Execution order (must match §6.2 and the engine spec in Phase 8 prompt):
  1. Copy evidence pieces from the package.
  2. Filter out pieces whose indicator_type is targeted by a validated discount.
  3. §6.4 evidence-gating: drop / downgrade mitigating pieces that don't pass
     their corroboration gate.
  4. apply_diminishing → (weighted_pieces, diminishing_steps)
  5. Sum incrim and mitig from weighted_pieces.
  6. apply_entity_gate → zero out mitig if a live payment rail is present.
  7. apply_mitigation_floor → mitig = max(mitig, −0.60 × incrim).
  8. raw_score = incrim + mitig.
  9. clamp to [0, 1].
  10. apply_single_source_ceiling → cap strictly below the HIGH threshold
      (high − 0.01) unless ≥2 independent modalities incriminate.  (Revision:
      the former fixed 0.59 cap sat *above* the calibrated HIGH threshold of
      ≈0.474 and therefore did not enforce the multi-source requirement.)
  11. risk_level from §6.3 thresholds.

``ablate`` / ``weights`` / ``thresholds`` exist only for the evaluation harness
(ablation and sensitivity studies); production callers never pass them.

Nothing here touches the LLM, the database, or the network.
Same EvidencePackage → byte-identical ScoreBreakdown every run.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import Field

from aimw.core.schema.evidence import EvidencePackage, EvidencePiece, FrozenModel
from aimw.core.schema.types import Polarity, RiskLevel, Source
from aimw.scoring.discounts import Discount
from aimw.scoring.rules import (
    apply_diminishing,
    apply_entity_gate,
    apply_mitigation_floor,
    apply_single_source_ceiling,
)
from aimw.scoring.weights import WEIGHT

# Verifiable licence identifier regex — mirrors discounts.py.
_LICENSE_RE: re.Pattern[str] = re.compile(
    r"(АФН|AFN|CFP|АРРФР|лицензия|лицензир)\s*[№#]?\s*[\w\-]{4,}",
    re.UNICODE,
)

# ---------------------------------------------------------------------------
# §6.3 thresholds — loaded from config/level_thresholds.yaml with mtime cache
# ---------------------------------------------------------------------------

# Anchored to the package's config/ dir (previously CWD-relative, which silently
# fell back to the 0.60 default whenever the process was started elsewhere).
_THRESHOLDS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "level_thresholds.yaml"

_DEFAULTS: dict[str, float] = {
    "critical": 0.80,
    "high": 0.60,
    "medium": 0.35,
    "low": 0.10,
}

_thresholds_cache: dict[str, float] | None = None
_thresholds_mtime: float = -1.0


def _load_thresholds() -> dict[str, float]:
    """Return thresholds, re-reading the YAML only when the file changes on disk."""
    global _thresholds_cache, _thresholds_mtime

    try:
        mtime = os.path.getmtime(_THRESHOLDS_PATH)
    except OSError:
        return dict(_DEFAULTS)

    if _thresholds_cache is not None and mtime == _thresholds_mtime:
        return _thresholds_cache

    try:
        raw: Any = yaml.safe_load(_THRESHOLDS_PATH.read_text(encoding="utf-8")) or {}
        loaded = {
            k: float(raw.get(k, _DEFAULTS[k]))
            for k in _DEFAULTS
        }
    except Exception:
        loaded = dict(_DEFAULTS)

    _thresholds_cache = loaded
    _thresholds_mtime = mtime
    return loaded


def validate_thresholds(t: dict[str, float]) -> None:
    """Raise ValueError unless the thresholds and ceilings are mutually consistent.

    Invariants (reviewer R1/R2 — "ensure the scoring rules and thresholds work
    as claimed and validate them together"):
      * 0 < low < medium < high < critical ≤ 1
      * single-source ceiling (high − margin) lies in [medium, high): a
        single-source package can be MEDIUM but never HIGH.
      * educational ceiling (high − 0.01) is likewise below HIGH.
    """
    from aimw.scoring.rules import single_source_ceiling

    if not (0.0 < t["low"] < t["medium"] < t["high"] < t["critical"] <= 1.0):
        raise ValueError(f"thresholds must be strictly increasing in (0,1]: {t}")
    ceiling = single_source_ceiling(t["high"])
    if not (t["medium"] <= ceiling < t["high"]):
        raise ValueError(
            f"single-source ceiling {ceiling} must lie in [medium, high) = "
            f"[{t['medium']}, {t['high']})"
        )


def _invalidate_thresholds_cache() -> None:
    """Force the next call to re-read the YAML (used in tests)."""
    global _thresholds_cache, _thresholds_mtime
    _thresholds_cache = None
    _thresholds_mtime = -1.0


# ---------------------------------------------------------------------------
# ScoreBreakdown — full audit trail
# ---------------------------------------------------------------------------


class DiminishingStep(FrozenModel):
    """One entry per (polarity, indicator_type) pair in diminishing returns."""

    indicator_type: str
    polarity: Polarity
    occurrences: int
    total_applied: float
    capped: bool


class PieceContribution(FrozenModel):
    """Per-piece audit record."""

    indicator_type: str
    polarity: Polarity
    source: Source
    timestamp: float | None
    base_weight: float
    applied_weight: float
    reason: str


class ScoreBreakdown(FrozenModel):
    """Complete, auditable output of one scoring run.

    Fields are populated in execution order so a reviewer can follow the
    math top-to-bottom and reproduce each number by hand.
    """

    # Post §6.4-gating, pre-diminishing totals (absolute values).
    raw_incriminating: float
    raw_mitigating: float

    # Diminishing-returns audit (one entry per indicator_type).
    diminishing_steps: list[DiminishingStep] = Field(default_factory=list)

    # Sums after diminishing returns are applied.
    incrim_after_diminishing: float
    mitig_after_diminishing: float

    # Rule B — entity gate.
    applied_entity_gate: bool

    # Rule A — mitigation floor.
    mitigation_floor_applied: bool
    mitig_after_floor: float

    # Final computation.
    raw_score: float  # incrim_after_diminishing + mitig_after_floor
    clamped_score: float  # max(0, min(raw_score, 1))
    single_source_ceiling_applied: bool
    educational_ceiling_applied: bool = False
    final_score: float

    level: RiskLevel

    # Per-piece audit (same ordering as the internal weighted list).
    per_piece: list[PieceContribution] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# §6.4 evidence-gating (applied before diminishing returns)
# ---------------------------------------------------------------------------


# Phase 15.9 — "hard scheme" indicator families. The presence of any one of
# these is what licenses the otherwise-ambiguous incriminating signals
# (unlicensed_advice, crypto_giveaway-keyword-only) to count. They are the
# signals that, on their own, strongly imply fraud/promotion rather than
# legitimate financial education.
_HARD_SCHEME_TYPES: frozenset[str] = frozenset({
    "guaranteed_return", "guaranteed_profit", "pyramid_recruit", "mlm_pyramid",
    "casino_promo", "gambling_income", "trading_bot_promo", "pump_signal",
    "sports_betting_income", "crypto_staking_income", "passive_income",
    "passive_income_ru", "kz_fraud_signals", "investment_promise",
    "recruitment_funnel", "referral_program_income",
})

# Cheap structural check for "send X get 2X"-style giveaway-scam raw values.
_GIVEAWAY_SCAM_RE: re.Pattern[str] = re.compile(
    r"\d+\.?\d*\s*(btc|eth|usdt|bnb)|send\s+\d|отправ", re.IGNORECASE | re.UNICODE
)


def _apply_evidence_gate(
    pieces: list[EvidencePiece],
    package: EvidencePackage,
) -> list[EvidencePiece]:
    """Drop or downgrade pieces that don't pass §6.4 / Phase-15.9 gates.

    Mitigating gates:
    - risk_disclosure     voided if any guaranteed_return piece in package.
    - journalism_framing  voided if any payment entity OR the piece's source
                          is not "speech" (OCR-only framing doesn't count).
    - licensing           downgraded to MEDIUM if raw_value lacks a
                          verifiable licence identifier.
    - educational_framing voided if pyramid_recruit/mlm_pyramid present.
    - satire_markers      always capped at WEAK strength.

    Phase 15.9 incriminating precision gates (fix benign finance-education FPs):
    - unlicensed_advice   voided unless a hard-scheme signal co-fires or a
                          payment entity is present. "Invest in index funds"
                          alone is education, not solicitation.
    - crypto_giveaway     downgraded STRONG→WEAK when it is the sole incriminating
                          family present, no payment entity, and the raw value is
                          not a "send X get 2X" scam pattern. Stops educational
                          bitcoin explainers from scoring HIGH on giveaway mentions.
    """
    incrim_types = {p.indicator_type for p in pieces if p.polarity == "incriminating"}
    ents = package.entities
    # Revision (R2): only promoter-linked payment rails count.  A wallet quoted
    # in a scam warning no longer voids journalism/educational framing.
    has_payment = bool(
        ents.promoter_linked(ents.crypto_wallets)
        or ents.promoter_linked(ents.payment_phones)
        or ents.promoter_linked(ents.telegram_links)
    )
    has_hard_scheme = bool(incrim_types & _HARD_SCHEME_TYPES)
    # Distinct incriminating families excluding the two "ambiguous" ones.
    corroborating_types = incrim_types - {"crypto_giveaway", "unlicensed_advice",
                                          "educational_framing"}

    result: list[EvidencePiece] = []
    for p in pieces:
        # ── Phase 15.9 incriminating precision gates ────────────────────────
        if p.polarity == "incriminating":
            if p.indicator_type == "unlicensed_advice":
                if not (has_hard_scheme or has_payment):
                    continue  # voided — bare investing advice is not solicitation
            elif p.indicator_type == "crypto_giveaway":
                sole = not bool(corroborating_types)
                if (
                    p.strength == "strong"
                    and sole
                    and not has_payment
                    and not _GIVEAWAY_SCAM_RE.search(p.raw_value)
                ):
                    p = p.model_copy(update={"strength": "weak"})
            result.append(p)
            continue

        if p.polarity != "mitigating":
            result.append(p)
            continue

        if p.indicator_type == "risk_disclosure":
            if "guaranteed_return" in incrim_types:
                continue  # voided — contradicts a guarantee claim

        elif p.indicator_type == "journalism_framing":
            if has_payment:
                continue  # voided — payment rail present
            if p.source != "speech":
                continue  # voided — OCR-only framing not credited

        elif p.indicator_type == "licensing":
            if not _LICENSE_RE.search(p.raw_value) and p.strength == "strong":
                p = p.model_copy(update={"strength": "medium"})

        elif p.indicator_type == "educational_framing":
            if has_payment:
                continue  # voided — payment entities present = actual promotion, not education

        elif p.indicator_type == "satire_markers" and p.strength != "weak":
            p = p.model_copy(update={"strength": "weak"})

        result.append(p)
    return result


# ---------------------------------------------------------------------------
# §6.3 level thresholds
# ---------------------------------------------------------------------------


def risk_level(score: float, thresholds: dict[str, float] | None = None) -> RiskLevel:
    """Map a final score to a RiskLevel per §6.3.

    Thresholds are read from ``config/level_thresholds.yaml`` with mtime-based
    hot-reload so calibration nudges take effect without a process restart.
    Falls back to §6.3 hard-coded defaults if the file is absent or corrupt.
    """
    t = thresholds if thresholds is not None else _load_thresholds()
    if score >= t["critical"]:
        return "CRITICAL"
    if score >= t["high"]:
        return "HIGH"
    if score >= t["medium"]:
        return "MEDIUM"
    if score >= t["low"]:
        return "LOW"
    return "CLEAN"


# ---------------------------------------------------------------------------
# Main engine entry point
# ---------------------------------------------------------------------------


#: Rule names accepted by ``score(ablate=...)`` (evaluation harness only).
ABLATABLE_RULES: frozenset[str] = frozenset({
    "evidence_gate",          # §6.4 / Phase-15.9 gates
    "diminishing",            # Rule C (repetition discount + per-type cap)
    "entity_gate",            # Rule B
    "mitigation_floor",       # Rule A
    "single_source_ceiling",  # Rule D
    "educational_ceiling",    # step 10.5
    "mitigation",             # drop every mitigating piece
})


def score(
    package: EvidencePackage,
    discount_ids: tuple[Discount, ...] = (),
    *,
    ablate: frozenset[str] = frozenset(),
    weights: dict[tuple[str, str], float] | None = None,
    thresholds: dict[str, float] | None = None,
) -> ScoreBreakdown:
    """Compute a fully-bounded, gated signed score for *package*.

    Parameters
    ----------
    package:
        The canonical evidence object.  Immutable; never mutated here.
    discount_ids:
        Validated ``Discount`` objects from the referee.  Each removes
        pieces whose indicator_type matches ``discount.piece_indicator_type``.
        Only pass discounts that have already been verified by
        ``discounts.discount_is_valid``.

    Returns
    -------
    ScoreBreakdown
        The complete audit trail.  ``final_score`` and ``level`` are the
        operative outputs.  Everything else is for explainability.
    """
    # ── Step 1: copy pieces ─────────────────────────────────────────────────
    pieces: list[EvidencePiece] = list(package.evidence)

    # ── Step 2: apply validated discounts ───────────────────────────────────
    discounted_types: frozenset[str] = frozenset(
        d.piece_indicator_type for d in discount_ids if d.piece_indicator_type is not None
    )
    if discounted_types:
        pieces = [p for p in pieces if p.indicator_type not in discounted_types]

    unknown = set(ablate) - ABLATABLE_RULES
    if unknown:
        raise ValueError(f"unknown ablation(s): {sorted(unknown)}")
    table = weights if weights is not None else WEIGHT
    t_live = thresholds if thresholds is not None else _load_thresholds()

    if "mitigation" in ablate:
        pieces = [p for p in pieces if p.polarity != "mitigating"]

    # ── Step 3: §6.4 evidence-gating ────────────────────────────────────────
    if "evidence_gate" not in ablate:
        pieces = _apply_evidence_gate(pieces, package)

    # Raw totals before diminishing returns (for the breakdown).
    raw_incrim = sum(
        table[(p.polarity, p.strength)] for p in pieces if p.polarity == "incriminating"
    )
    raw_mitig = sum(table[(p.polarity, p.strength)] for p in pieces if p.polarity == "mitigating")

    # ── Step 4: diminishing returns (Rule C) ────────────────────────────────
    weighted, diminishing_raw = apply_diminishing(
        pieces, weights=weights, enabled="diminishing" not in ablate
    )

    diminishing_steps = [
        DiminishingStep(
            indicator_type=cast(str, s["indicator_type"]),
            polarity=cast(Polarity, s["polarity"]),
            occurrences=cast(int, s["occurrences"]),
            total_applied=cast(float, s["total_applied"]),
            capped=cast(bool, s["capped"]),
        )
        for s in diminishing_raw
    ]

    # ── Step 5: sum after diminishing ───────────────────────────────────────
    incrim = sum(w for p, w in weighted if p.polarity == "incriminating")
    mitig = sum(w for p, w in weighted if p.polarity == "mitigating")

    # ── Step 6: entity gate (Rule B) ────────────────────────────────────────
    if "entity_gate" in ablate:
        gate_fired = False
    else:
        incrim, mitig, gate_fired = apply_entity_gate(incrim, mitig, package.entities)

    # ── Step 7: mitigation floor (Rule A) ───────────────────────────────────
    if "mitigation_floor" in ablate:
        floor_applied = False
    else:
        mitig, floor_applied = apply_mitigation_floor(incrim, mitig)

    # ── Step 8 + 9: raw score and clamp ─────────────────────────────────────
    raw = incrim + mitig
    clamped = max(0.0, min(raw, 1.0))

    # ── Step 10: single-source ceiling (Rule D) ──────────────────────────────
    if "single_source_ceiling" in ablate:
        final, ceiling_applied = clamped, False
    else:
        final, ceiling_applied = apply_single_source_ceiling(
            weighted, clamped, high_threshold=t_live["high"]
        )

    # ── Step 10.5: educational content ceiling ──────────────────────────────
    # When educational_framing signals survived gating AND no payment entities
    # or profit claims are present, cap the score below CRITICAL. Genuine
    # educational content about scams/MLM should not rank the same as an
    # actual promotion.
    edu_ceiling_applied = False
    has_edu = any(p.indicator_type == "educational_framing" for p, _ in weighted)
    ents = package.entities
    has_payment_entities = bool(
        ents.promoter_linked(ents.crypto_wallets)
        or ents.promoter_linked(ents.payment_phones)
        or ents.promoter_linked(ents.telegram_links)
    )
    has_profit_entities = bool(package.entities.profit_claims)
    if (
        "educational_ceiling" not in ablate
        and has_edu and not has_payment_entities and not has_profit_entities
    ):
        edu_cap = t_live["high"] - 0.01  # just below HIGH threshold → caps at MEDIUM
        if final > edu_cap:
            final = edu_cap
            edu_ceiling_applied = True

    # ── Step 11: level ───────────────────────────────────────────────────────
    level = risk_level(final, t_live)

    # ── Build per-piece audit ────────────────────────────────────────────────
    per_piece: list[PieceContribution] = []
    for p, applied in weighted:
        base = table[(p.polarity, p.strength)]
        if applied == base:
            reason = "1st occurrence (full weight)"
        elif applied == 0.0:
            reason = "contribution cap reached"
        elif abs(applied) < abs(base):
            occ_idx = _occurrence_index(weighted, p)
            if occ_idx == 1:
                reason = "2nd occurrence (×0.5)"
            else:
                reason = f"occurrence {occ_idx + 1} (×0.25)"
        else:
            reason = "partial (cap partial)"
        per_piece.append(
            PieceContribution(
                indicator_type=p.indicator_type,
                polarity=p.polarity,
                source=p.source,
                timestamp=p.timestamp,
                base_weight=base,
                applied_weight=applied,
                reason=reason,
            )
        )

    return ScoreBreakdown(
        raw_incriminating=round(raw_incrim, 10),
        raw_mitigating=round(raw_mitig, 10),
        diminishing_steps=diminishing_steps,
        incrim_after_diminishing=round(incrim, 10),
        mitig_after_diminishing=round(mitig, 10),
        applied_entity_gate=gate_fired,
        mitigation_floor_applied=floor_applied,
        mitig_after_floor=round(mitig, 10),
        raw_score=round(raw, 10),
        clamped_score=round(clamped, 10),
        single_source_ceiling_applied=ceiling_applied,
        educational_ceiling_applied=edu_ceiling_applied,
        final_score=round(final, 10),
        level=level,
        per_piece=per_piece,
    )


def _occurrence_index(
    weighted: list[tuple[EvidencePiece, float]],
    target: EvidencePiece,
) -> int:
    """Return the 0-based occurrence index of *target* in its indicator_type group."""
    count = 0
    for p, _ in weighted:
        if p is target:
            return count
        if p.polarity == target.polarity and p.indicator_type == target.indicator_type:
            count += 1
    return count
