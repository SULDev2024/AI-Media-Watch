"""WEIGHT table — §6.1 of AI_MediaWatch_v4.md.

This table is the contract between the evidence schema and the scoring engine.
Do not modify without a matching change to §6.1 and a review of every test in
tests/scoring/test_weights.py and tests/scoring/test_engine.py.
"""

from __future__ import annotations

from aimw.core.schema.types import EvidenceStrength, Polarity

# §6.1 base signed weights.  Incriminating: positive.  Mitigating: negative.
WEIGHT: dict[tuple[Polarity, EvidenceStrength], float] = {
    ("incriminating", "strong"): +0.30,
    ("incriminating", "medium"): +0.14,
    ("incriminating", "weak"): +0.05,
    ("mitigating", "strong"): -0.25,
    ("mitigating", "medium"): -0.12,
    ("mitigating", "weak"): -0.04,
}

# §0.2 issue #9 — per-indicator-type contribution cap.
# No single indicator_type may contribute more than 2× the STRONG incriminating weight.
# Applies to both incriminating sums (per type) and mitigating sums (per type).
MAX_INDICATOR_CONTRIBUTION: float = 2.0 * WEIGHT[("incriminating", "strong")]  # 0.60
