"""Action matrix — §0.2 issue #8 of AI_Media_Watch_v4_Implementation_Prompts.md.

``action_for(level, confidence)`` is the single authority on what happens to a
scored package.  It is called by the deterministic referee (Phase 10); this
module contains no LLM calls and no I/O.
"""

from __future__ import annotations

from typing import Literal

from aimw.core.schema.types import RiskLevel

Action = Literal["auto_escalate", "analyst_review", "monitor", "suppress"]

# Minimum confidence for auto-escalation (§7 decision coupling).
# If confidence < this value, HIGH/CRITICAL is softened one level by
# soften_one_level() before action routing.  The Phase 10 referee enforces
# this coupling; this constant is declared here so it is co-located with the
# action matrix that depends on it.
MIN_CONFIDENCE_FOR_AUTO: float = 0.60


def soften_one_level(level: RiskLevel) -> RiskLevel:
    """Soften a risk level by one step (§7: applied when confidence < 0.60).

    CRITICAL → HIGH → MEDIUM → LOW → CLEAN (floor).
    """
    _SOFTEN: dict[RiskLevel, RiskLevel] = {
        "CRITICAL": "HIGH",
        "HIGH": "MEDIUM",
        "MEDIUM": "LOW",
        "LOW": "CLEAN",
        "CLEAN": "CLEAN",
    }
    return _SOFTEN[level]


def action_for(level: RiskLevel, confidence: float) -> Action:
    """Return the action for a scored package per §0.2 issue #8.

    Action matrix
    -------------
    CRITICAL + conf ≥ 0.6 → auto_escalate
    CRITICAL + conf < 0.6 → analyst_review  (softened to HIGH by §7 first)
    HIGH     + conf ≥ 0.6 → auto_escalate
    HIGH     + conf < 0.6 → analyst_review  (softened to MEDIUM by §7 first)
    MEDIUM   (any conf)   → analyst_review
    LOW                   → monitor
    CLEAN                 → suppress  (stored; network hit can resurface it)
    """
    if level in ("CRITICAL", "HIGH"):
        return "auto_escalate" if confidence >= MIN_CONFIDENCE_FOR_AUTO else "analyst_review"
    if level == "MEDIUM":
        return "analyst_review"
    if level == "LOW":
        return "monitor"
    return "suppress"  # CLEAN
