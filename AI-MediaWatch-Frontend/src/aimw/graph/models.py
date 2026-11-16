"""Graph-only typed models -- Phase 11.

``NetworkConnection`` lives in ``aimw.core.schema.evidence`` because it is a
field type on the canonical ``EvidencePackage`` -- this module re-exports it
for the graph subsystem's convenience and defines ``Campaign``, which is a
graph-analysis output (not a schema field).
"""
from __future__ import annotations

from typing import Literal

from pydantic import field_validator

from aimw.core.schema.evidence import (
    CampaignStrength,
    FrozenModel,
    NetworkConnection,
    NetworkConnectionKind,
    SharedEntityKind,
)

VideoKey = tuple[Literal["video"], str]
EntityKey = tuple[Literal["entity"], SharedEntityKind, str]
GraphNode = VideoKey | EntityKey


class Campaign(FrozenModel):
    """A detected coordinated campaign over the corpus.

    ``videos`` is the set of report_ids that all share at least one entity in
    ``shared_entities``. ``strength`` follows §13: ``strong`` iff
    ``len(videos) >= 5``, ``medium`` iff ``len(videos) >= 3``, ``weak`` otherwise.
    """

    videos: list[str]
    shared_entities: list[str]
    strength: CampaignStrength

    @field_validator("videos", "shared_entities")
    @classmethod
    def _sort_lists(cls, value: list[str]) -> list[str]:
        return sorted(value)


__all__ = [
    "Campaign",
    "CampaignStrength",
    "EntityKey",
    "GraphNode",
    "NetworkConnection",
    "NetworkConnectionKind",
    "SharedEntityKind",
    "VideoKey",
]
