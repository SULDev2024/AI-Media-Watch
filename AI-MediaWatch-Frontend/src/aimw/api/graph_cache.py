"""TTL-bounded cache for the campaign-graph build pipeline (H1 mitigation).

``GET /campaigns`` and ``GET /metrics`` both rebuild the bipartite
(video, entity) graph and re-run campaign detection on every request.
The rebuild is O(packages + edges) and saturates the API thread pool
under sustained load — a documented Phase-12 design tradeoff that
becomes a DoS vector at modest load.

This cache holds the *result* of ``build_from_db`` + ``find`` for a
configurable TTL (default 30 seconds).  Within the TTL window all
concurrent callers share the same cached value; once expired the next
caller pays the rebuild cost while subsequent callers wait on the
single-flight lock so the rebuild only happens once even under burst.

The cache is process-local and intentionally simple — it covers the
pilot deployment topology (one API replica).  Multi-replica pilots
must replace this with a Redis-backed cache.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aimw.graph import builder
from aimw.graph import campaigns as campaign_finder
from aimw.graph.models import Campaign


@dataclass(slots=True)
class _CacheEntry:
    expires_at: float
    campaigns: list[Campaign]
    graph: nx.Graph


class CampaignGraphCache:
    """Process-local TTL cache for the (graph, campaigns) tuple."""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl = ttl_seconds
        self._entry: _CacheEntry | None = None
        self._build_lock = asyncio.Lock()

    async def get(
        self,
        sm: async_sessionmaker[AsyncSession],
    ) -> tuple[list[Campaign], nx.Graph]:
        """Return (campaigns, graph), rebuilding only if the TTL has expired."""
        now = time.monotonic()
        cached = self._entry
        if cached is not None and cached.expires_at > now:
            return cached.campaigns, cached.graph

        # Single-flight: only one coroutine rebuilds; others wait and then
        # see the new entry.
        async with self._build_lock:
            now = time.monotonic()
            cached = self._entry
            if cached is not None and cached.expires_at > now:
                return cached.campaigns, cached.graph
            graph = await builder.build_from_db(sm)
            campaigns = list(campaign_finder.find(graph))
            self._entry = _CacheEntry(
                expires_at=now + self._ttl,
                campaigns=campaigns,
                graph=graph,
            )
            return campaigns, graph

    # Operator hooks ------------------------------------------------------

    def invalidate(self) -> None:
        """Drop the cached entry, forcing the next caller to rebuild.

        Wire this to ``POST /campaigns/recompute`` completion so analysts
        see the latest graph immediately after a recompute lands.
        """
        self._entry = None

    # Test helpers --------------------------------------------------------

    def _force_clear(self) -> None:  # pragma: no cover - test-only
        self._entry = None

    def _ttl_seconds(self) -> float:  # pragma: no cover - test-only
        return self._ttl


# Process-wide instance — wired into the routers.
campaign_graph_cache = CampaignGraphCache(ttl_seconds=30.0)


__all__ = ["CampaignGraphCache", "campaign_graph_cache"]
