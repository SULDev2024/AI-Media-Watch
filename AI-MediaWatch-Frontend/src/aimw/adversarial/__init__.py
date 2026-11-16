"""Adversarial robustness — prove the system catches what keyword filters miss.

Two pieces:

``baseline.classify(text)``
    A naive keyword-only classifier — the kind most teams ship. It scores on the
    literal presence of fraud vocabulary. It is deliberately brittle: it is the
    straw man we beat.

``evasion.mutate(text)``
    Generates the obfuscations real scammers use to dodge keyword filters:
    homoglyph swaps, character spacing, leetspeak, and zero-width insertion. We
    run BOTH classifiers on the original and the mutated text to show that the
    keyword baseline collapses under evasion while the multimodal/intent pipeline
    holds.

Pure stdlib — no dependencies, fully deterministic.
"""
from __future__ import annotations

from aimw.adversarial import baseline, evasion

__all__ = ["baseline", "evasion"]
