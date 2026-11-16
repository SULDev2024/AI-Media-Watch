"""Campaign detection over the (video, entity) bipartite graph -- Phase 11.

A campaign is one entity node with at least ``min_videos`` distinct video
neighbours. Per §13, ``strength`` is:

  * ``"strong"`` iff ``len(videos) >= 5``
  * ``"medium"`` iff ``min_videos <= len(videos) < 5``
  * ``"weak"`` iff ``len(videos) < min_videos`` (filtered out)

The result is sorted by ``len(videos)`` descending and, on tie, by entity-value
ascending -- giving callers (CLI, tests, exports) a stable ordering across runs.

Determinism: every iteration over graph nodes/edges sorts first; given a fixed
graph (which ``builder.build_from_db`` produces deterministically) the campaign
list is byte-identical across runs.
"""
from __future__ import annotations

import networkx as nx

from aimw.graph.models import Campaign, CampaignStrength
from aimw.observability.metrics import emit_campaign_size_distribution

DEFAULT_MIN_VIDEOS: int = 3


def _campaign_strength(n_videos: int) -> CampaignStrength:
    if n_videos >= 5:
        return "strong"
    return "medium"


def find(graph: nx.Graph, *, min_videos: int = DEFAULT_MIN_VIDEOS) -> list[Campaign]:
    """Return campaigns with at least ``min_videos`` participating videos.

    Each campaign covers exactly one shared entity (Phase 11). Phase 12+ may
    merge campaigns whose video sets overlap above a threshold; this function
    is intentionally simple so the output is easy to test and render.
    """
    # Iterate entity nodes in deterministic order.
    entity_nodes = sorted(
        node for node, attrs in graph.nodes(data=True) if attrs.get("bipartite") == 1
    )

    campaigns: list[Campaign] = []
    for ent in entity_nodes:
        # Sort neighbours so the output is stable across NetworkX versions.
        neighbours = sorted(graph.neighbors(ent))
        videos = [n[1] for n in neighbours if isinstance(n, tuple) and n[0] == "video"]
        if len(videos) < min_videos:
            continue
        # ent is ("entity", kind, value); shared entity value is the third part.
        _, _kind, value = ent
        campaigns.append(
            Campaign(
                videos=videos,
                shared_entities=[value],
                strength=_campaign_strength(len(videos)),
            )
        )

    # Sort by size desc, then by shared entity asc for stable ordering.
    campaigns.sort(key=lambda c: (-len(c.videos), c.shared_entities[0]))
    emit_campaign_size_distribution([len(c.videos) for c in campaigns])
    return campaigns


__all__ = ["DEFAULT_MIN_VIDEOS", "find"]
