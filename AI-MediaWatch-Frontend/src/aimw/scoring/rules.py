"""Anti-gaming rules — §6.2 of AI_MediaWatch_v4.md.

Four pure functions.  Each takes the working piece list and supporting data;
each returns a (result, breakdown_fields) tuple so the engine can assemble
a complete ScoreBreakdown audit trail.

Rule application order inside engine.score():
  1. apply_diminishing   — adjusts per-piece weight
  2. split incrim / mitig sums
  3. apply_entity_gate   — zeroes mitig total if live payment rail present
  4. apply_mitigation_floor — floors mitig at −60% of incrim
  5. clamp [0, 1]
  6. apply_single_source_ceiling — caps strictly below HIGH if <2 independent
     modalities incriminate (ceiling derived from the live HIGH threshold)

Nothing here touches persistence, LLMs, or the network.
"""

from __future__ import annotations

from collections import defaultdict

from aimw.core.schema.evidence import EvidencePiece, ExtractedEntities
from aimw.scoring.weights import MAX_INDICATOR_CONTRIBUTION, WEIGHT

# Each rule returns its result alongside a lightweight dict of audit fields
# that gets merged into ScoreBreakdown by the engine.
_WeightedPiece = tuple[EvidencePiece, float]


# ---------------------------------------------------------------------------
# Rule C — Diminishing returns on repetition (§6.2 Rule C + §0.2 issue #9)
# ---------------------------------------------------------------------------


def apply_diminishing(
    pieces: list[EvidencePiece],
    weights: dict[tuple[str, str], float] | None = None,
    enabled: bool = True,
) -> tuple[list[_WeightedPiece], list[dict[str, object]]]:
    """Assign applied weights with diminishing returns per indicator_type.

    Multipliers:  1st occurrence → 1.0×, 2nd → 0.5×, 3rd+ → 0.25×.
    Per-type contribution is capped at MAX_INDICATOR_CONTRIBUTION (0.60).

    Returns
    -------
    weighted
        Parallel list of (piece, applied_weight) with the same ordering as
        *pieces*.  applied_weight is 0.0 for pieces dropped by the cap.
    steps
        One dict per indicator_type that participated in diminishing; suitable
        for ScoreBreakdown.diminishing_steps.
    """
    # Count occurrences per (polarity, indicator_type) independently so that
    # incriminating and mitigating pieces don't share a counter.
    counters: dict[tuple[str, str], int] = defaultdict(int)
    totals: dict[tuple[str, str], float] = defaultdict(float)
    capped: dict[tuple[str, str], bool] = defaultdict(bool)

    weighted: list[_WeightedPiece] = []
    table = weights if weights is not None else WEIGHT
    max_contrib = (
        2.0 * table[("incriminating", "strong")] if weights is not None
        else MAX_INDICATOR_CONTRIBUTION
    )

    for piece in pieces:
        key = (piece.polarity, piece.indicator_type)
        base = table[(piece.polarity, piece.strength)]
        occurrence = counters[key]
        counters[key] += 1

        if occurrence == 0 or not enabled:
            factor = 1.0
        elif occurrence == 1:
            factor = 0.5
        else:
            factor = 0.25

        applied = base * factor

        # Enforce per-type cap: total (absolute) contribution ≤ MAX_INDICATOR_CONTRIBUTION.
        abs_running = abs(totals[key])
        abs_applied = abs(applied)
        if not enabled:
            pass  # ablation: no per-type cap either
        elif abs_running >= max_contrib:
            applied = 0.0
            capped[key] = True
        elif abs_running + abs_applied > max_contrib:
            # Partial application to hit cap exactly.
            remaining = max_contrib - abs_running
            applied = remaining if applied > 0 else -remaining
            capped[key] = True

        totals[key] += applied
        weighted.append((piece, applied))

    # Build audit steps — one per unique (polarity, type) key.
    steps: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for piece, _ in weighted:
        key = (piece.polarity, piece.indicator_type)
        if key in seen:
            continue
        seen.add(key)
        steps.append(
            {
                "indicator_type": piece.indicator_type,
                "polarity": piece.polarity,
                "occurrences": counters[key],
                "total_applied": round(totals[key], 10),
                "capped": capped.get(key, False),
            }
        )

    return weighted, steps


# ---------------------------------------------------------------------------
# Rule B — Entity gate (§6.2 Rule B)
# ---------------------------------------------------------------------------


def apply_entity_gate(
    incrim: float,
    mitig: float,
    entities: ExtractedEntities,
) -> tuple[float, float, bool]:
    """Zero out mitigation when a live payment rail is present.

    Returns (incrim, mitig_after_gate, gate_fired).
    gate_fired=True means the mitig total was set to 0.0.
    """
    # Revision (reviewer R2): only payment rails *linked to the promoter* (offered
    # by the video's own speaker / overlay in a call-to-action) fire the gate.
    # Wallets or codes that are reproduced in a warning, news report or tutorial
    # no longer erase mitigating evidence.  See aimw.entities.linkage.
    gate = bool(entities.promoter_payment_entities)
    return incrim, (0.0 if gate else mitig), gate


# ---------------------------------------------------------------------------
# Rule A — Mitigation floor (§6.2 Rule A)
# ---------------------------------------------------------------------------


def apply_mitigation_floor(
    incrim: float,
    mitig: float,
) -> tuple[float, bool]:
    """Cap total mitigation at −60% of incrimination.

    Returns (mitig_after_floor, floor_applied).
    floor_applied=True means the floor was the binding constraint.
    """
    floor = -0.60 * incrim
    if mitig < floor:
        return floor, True
    return mitig, False


# ---------------------------------------------------------------------------
# Rule D — Single-source ceiling (§6.2 Rule D + §0.1 issue #4)
# ---------------------------------------------------------------------------
#
# Revision (reviewer R1/R2): the original rule capped single-source scores at a
# hard-coded 0.59 while the calibrated HIGH threshold had moved to ~0.474, so a
# single-source package could still be labelled HIGH -- contradicting the claim
# that HIGH requires corroboration.  The ceiling is now *derived from* the live
# HIGH threshold (``high - SINGLE_SOURCE_MARGIN``), so the invariant
# "single-source evidence never reaches HIGH" holds for any threshold setting.
#
# "Source" means an independent *capture modality*.  ``entity`` pieces are
# derived from speech/OCR/vision text (a wallet read out in speech is still the
# speech channel), so they do not count as an extra independent source.

#: Capture modalities that count as independent evidence channels.
INDEPENDENT_SOURCES: frozenset[str] = frozenset({"speech", "ocr", "vision", "network"})

#: Gap kept between the single-source ceiling and the HIGH threshold.
SINGLE_SOURCE_MARGIN: float = 0.01

#: Legacy constant kept for backward compatibility (no longer used by the engine).
LEGACY_SINGLE_SOURCE_CEILING: float = 0.59


def independent_incriminating_sources(weighted: list[_WeightedPiece]) -> set[str]:
    """Return the set of independent modalities that carry non-zero incrimination."""
    return {
        p.source
        for p, w in weighted
        if p.polarity == "incriminating" and w != 0.0 and p.source in INDEPENDENT_SOURCES
    }


def single_source_ceiling(high_threshold: float) -> float:
    """Ceiling applied to single-source packages: strictly below HIGH."""
    return round(high_threshold - SINGLE_SOURCE_MARGIN, 10)


def apply_single_source_ceiling(
    weighted: list[_WeightedPiece],
    score: float,
    high_threshold: float | None = None,
) -> tuple[float, bool]:
    """Cap the score strictly below HIGH unless ≥2 independent modalities incriminate.

    Only *incriminating* pieces are considered (§0.1 issue #4).  When
    ``high_threshold`` is ``None`` the legacy 0.59 cap is used (kept only so old
    callers/tests keep working; the engine always passes the live threshold).

    Returns (score_after_ceiling, ceiling_applied).
    ceiling_applied=True only when the ceiling actually reduced the score.
    """
    cap = (
        LEGACY_SINGLE_SOURCE_CEILING
        if high_threshold is None
        else single_source_ceiling(high_threshold)
    )
    if len(independent_incriminating_sources(weighted)) <= 1 and score > cap:
        return cap, True
    return score, False
