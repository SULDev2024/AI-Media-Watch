"""Scoring registry — wires engine.score() into the EvidencePackage schema hooks.

Call ``register()`` once at process start (or let EvidencePackage.score's lazy
import trigger it automatically on first access).

The two registered callables are pure functions that delegate to the engine;
they carry no state and produce byte-identical output for identical input.
"""

from __future__ import annotations

from aimw.core.schema.evidence import EvidencePackage
from aimw.core.schema.types import RiskLevel


def register() -> None:
    """Register the Phase 8 scoring implementation into the schema hooks.

    After this call, ``EvidencePackage.score`` and
    ``EvidencePackage.risk_level`` are fully operational.  Idempotent — safe
    to call multiple times (subsequent calls overwrite the previous registration
    with identical functions).
    """
    from aimw.core.schema import register_risk_level, register_scoring
    from aimw.scoring.engine import _load_thresholds, validate_thresholds
    from aimw.scoring.engine import score as _score_fn

    # Fail fast if the configured thresholds break the single-source invariant.
    validate_thresholds(_load_thresholds())

    def _compute_score(package: EvidencePackage) -> float:
        return _score_fn(package).final_score

    def _compute_level(package: EvidencePackage) -> RiskLevel:
        return _score_fn(package).level

    register_scoring(_compute_score)
    register_risk_level(_compute_level)
