"""GET /api/v1/graph (Cytoscape JSON) and GET /api/v1/campaigns.

Both endpoints compose the Phase 11 graph builder. The graph view
emits Cytoscape elements ({nodes, edges}) for the dashboard. The
campaigns view returns the same campaign list the dashboard renders.
"""
from __future__ import annotations

from typing import Any

import networkx as nx
from fastapi import APIRouter

from aimw.api.deps import RequestIdDep, RequireAnalyst, SessionmakerDep
from aimw.api.graph_cache import campaign_graph_cache
from aimw.api.v1.schemas import (
    CampaignOut,
    CampaignsResponse,
    CytoscapeGraph,
)

router = APIRouter(tags=["graph"])


def _cyto_node(node: Any) -> dict[str, Any]:
    """Convert a NetworkX node + attrs tuple to Cytoscape element JSON."""
    nid = "|".join(str(x) for x in node[0]) if isinstance(node[0], tuple) else str(node[0])
    data: dict[str, Any] = {"id": nid}
    data.update({k: v for k, v in node[1].items() if isinstance(v, (str, int, float, bool))})
    return {"data": data}


def _cyto_edge(edge: Any) -> dict[str, Any]:
    """Convert a NetworkX edge tuple to Cytoscape element JSON."""
    u, v, attrs = edge
    src = "|".join(str(x) for x in u) if isinstance(u, tuple) else str(u)
    dst = "|".join(str(x) for x in v) if isinstance(v, tuple) else str(v)
    data: dict[str, Any] = {"source": src, "target": dst}
    data.update({k: v for k, v in attrs.items() if isinstance(v, (str, int, float, bool))})
    return {"data": data}


@router.get("/graph", response_model=CytoscapeGraph)
async def get_graph(
    sm: SessionmakerDep,
    request_id: RequestIdDep,
    _user: RequireAnalyst,
) -> CytoscapeGraph:
    _campaigns, graph = await campaign_graph_cache.get(sm)
    if not isinstance(graph, nx.Graph):  # defensive — cache miss path
        graph = nx.Graph()
    nodes = [_cyto_node((n, graph.nodes[n])) for n in graph.nodes]
    edges = [_cyto_edge((u, v, graph.edges[u, v])) for u, v in graph.edges]
    return CytoscapeGraph(nodes=nodes, edges=edges, request_id=request_id)


@router.get("/campaigns", response_model=CampaignsResponse)
async def list_campaigns_v1(
    sm: SessionmakerDep,
    request_id: RequestIdDep,
    _user: RequireAnalyst,
) -> CampaignsResponse:
    campaigns, _graph = await campaign_graph_cache.get(sm)
    items = [
        CampaignOut(
            campaign_id=c.shared_entities[0],
            shared_entities=list(c.shared_entities),
            strength=c.strength,
            n_videos=len(c.videos),
            videos=list(c.videos),
        )
        for c in campaigns
    ]
    return CampaignsResponse(items=items, request_id=request_id)


__all__ = ["router"]
