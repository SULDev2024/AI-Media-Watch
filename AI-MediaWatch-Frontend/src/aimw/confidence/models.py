"""Confidence data models — Phase 9 (§7 of AI_MediaWatch_v4.md).

BriefShape is provisional: the schema is used as a typed placeholder here and
finalised in Phase 10 when the LLM prosecutor/defense brief generation lands.
DiscountRequest mirrors the shape from aimw.scoring.discounts but is declared
independently so confidence does not create a circular import with scoring.
"""
from __future__ import annotations

from typing import Literal

from aimw.core.schema.evidence import FrozenModel


class BriefArgument(FrozenModel):
    """One argument inside a prosecutor or defense brief."""

    statement: str
    evidence_piece_ids: list[str]
    strength: Literal["strong", "medium", "weak"]


class DiscountRequest(FrozenModel):
    """Discount request from the defense brief (validated by the referee in Phase 10).

    ``piece_indicator_type`` is the indicator_type the defense argues should be
    discounted -- scoring filters by indicator_type, not by piece-id (pieces have
    no stable id).  ``kind`` is one of the four DiscountKinds from
    ``aimw.scoring.discounts``; the referee validates the kind via
    ``discount_is_valid`` before passing it to the re-scoring step.
    """

    kind: str
    piece_indicator_type: str | None
    reason: str


class BriefShape(FrozenModel):
    """Provisional brief schema — finalised in Phase 10.

    The prosecutor brief argues why the package is incriminating.
    The defense brief argues why it is not, and may include discount requests.
    Both are produced by the LLM; the confidence engine consumes them as read-only.
    """

    arguments: list[BriefArgument]
    discount_requests: list[DiscountRequest]


class ConfidenceBreakdown(FrozenModel):
    """Fully-auditable output of one confidence computation.

    Fields are populated in formula order so a reviewer can reproduce each
    number by hand.  ``confidence`` is the operative output.
    """

    agreement: float
    redundancy: float
    certainty: float
    gap: float
    confidence: float
