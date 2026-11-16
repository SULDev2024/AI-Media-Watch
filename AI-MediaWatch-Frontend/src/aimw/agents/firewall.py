"""The deterministic firewall — the one place a verdict is decided.

No LLM writes here. Given the evidence package, the firewall:
  1. runs the deterministic scoring engine (Phase 8),
  2. seals the tamper-evident case file (chain of custody),
and writes the authoritative ``final_score`` / ``risk_level`` / ``chain_root``
onto the shared :class:`CaseState`.

The agents above propose, investigate, and challenge — but the number that goes
in the record is produced HERE, reproducibly, every time. This is the boundary
that keeps the system court-admissible.
"""
from __future__ import annotations

from aimw.agents.state import CaseState
from aimw.custody import seal
from aimw.reasoning import regulations as reg_catalog
from aimw.scoring.engine import score as compute_score


def adjudicate(state: CaseState) -> None:
    """Run deterministic scoring + custody sealing and write the verdict.

    Mutates *state* in place: sets ``final_score``, ``risk_level``,
    ``confidence`` (best available), ``chain_root`` and ``case_file``.
    Idempotent — same package yields the same numbers every call.
    """
    pkg = state.package
    if pkg is None:
        state.log("firewall", "skipped", "no evidence package to adjudicate")
        return

    breakdown = compute_score(pkg)
    final_score = breakdown.final_score
    risk_level = str(breakdown.level)

    # Confidence: prefer a triage/forensics-informed value if the cell produced
    # one, but the SCORE itself is always the deterministic engine's.
    confidence = state.confidence
    if confidence is None:
        # Light deterministic proxy: more incriminating indicators → higher conf.
        n_incrim = sum(1 for p in pkg.evidence if p.polarity == "incriminating")
        confidence = round(min(1.0, 0.25 + 0.15 * n_incrim), 3)

    regs = reg_catalog.load()
    case_file = seal(
        package=pkg,
        final_score=final_score,
        risk_level=risk_level,
        verdict=risk_level,
        confidence=confidence,
        regulations=regs,
    )

    state.final_score = round(final_score, 4)
    state.risk_level = risk_level
    state.confidence = confidence
    state.chain_root = case_file["chain_root"]
    state.case_file = case_file
    state.log(
        "firewall",
        "adjudicated",
        f"score={state.final_score} level={risk_level} chain={state.chain_root[:16]}…",
    )


__all__ = ["adjudicate"]
