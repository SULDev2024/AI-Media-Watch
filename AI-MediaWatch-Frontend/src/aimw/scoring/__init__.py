"""Signed, bounded, gated scoring engine — Phase 8.

Public surface
--------------
``engine.score(package, discount_ids=())``   → ScoreBreakdown
``engine.risk_level(score)``                 → RiskLevel  (§6.3)
``signals.tag(raw_spans, entities, ocr, transcript)`` → list[EvidencePiece]
``actions.action_for(level, confidence)``    → Action
``actions.soften_one_level(level)``          → RiskLevel
``discounts.Discount``                       → discount request model
``discounts.discount_is_valid(d, pkg)``      → bool
``registry.register()``                      → wires EvidencePackage.score
``weights.WEIGHT``                           → §6.1 table
``weights.MAX_INDICATOR_CONTRIBUTION``       → §0.2 issue #9 cap
"""
