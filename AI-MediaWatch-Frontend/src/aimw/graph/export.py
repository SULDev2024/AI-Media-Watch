"""Cytoscape.js export for the Phase 14 frontend.

Output shape (frozen contract -- the React frontend depends on this):

    {
        "nodes": [
            {"data": {"id": "video::report-001", "label": "report-001", "type": "video"}},
            {"data": {"id": "entity::telegram_handle::signal_kz_vip",
                      "label": "signal_kz_vip", "type": "entity",
                      "entity_kind": "telegram_handle"}},
            ...
        ],
        "edges": [
            {"data": {"source": "video::report-001",
                       "target": "entity::telegram_handle::signal_kz_vip",
                       "label": "telegram_handle"}},
            ...
        ]
    }

Determinism: nodes and edges are sorted by their string id before emission.
The output is a plain dict; ``json.dumps(out, sort_keys=True)`` is stable.
"""
from __future__ import annotations

from typing import Any

import networkx as nx


def _node_id(node: tuple[str, ...]) -> str:
    """Stable string id for a graph node.

    Uses ``::`` as the separator because it cannot occur in any of our
    field values (handles, wallets, etc. don't contain it).
    """
    return "::".join(node)


def _edge_label(graph: nx.Graph, src: tuple[str, ...], dst: tuple[str, ...]) -> str:
    """Edge label = the entity kind, taken from the entity node's attributes."""
    entity_node = src if src[0] == "entity" else dst
    attrs = graph.nodes[entity_node]
    label: object = attrs.get("entity_kind", "")
    return str(label)


def to_cytoscape(graph: nx.Graph) -> dict[str, list[dict[str, dict[str, Any]]]]:
    """Render *graph* to the Cytoscape.js JSON shape."""
    # Sort nodes by their id for stability.
    sorted_nodes = sorted(graph.nodes(data=True), key=lambda kv: _node_id(kv[0]))
    nodes_out: list[dict[str, dict[str, Any]]] = []
    for node, attrs in sorted_nodes:
        kind = attrs.get("kind", "video" if node[0] == "video" else "entity")
        data: dict[str, Any] = {
            "id": _node_id(node),
            "label": str(attrs.get("label", node[-1])),
            "type": kind,
        }
        if kind == "entity":
            data["entity_kind"] = str(attrs.get("entity_kind", ""))
        nodes_out.append({"data": data})

    # Sort edges by (source_id, target_id) for stability; normalise endpoint order.
    sorted_edges: list[tuple[str, str, str]] = []
    for u, v in graph.edges():
        u_id = _node_id(u)
        v_id = _node_id(v)
        if u_id > v_id:
            u_id, v_id = v_id, u_id
            u, v = v, u
        sorted_edges.append((u_id, v_id, _edge_label(graph, u, v)))
    sorted_edges.sort()

    edges_out: list[dict[str, dict[str, Any]]] = []
    for u_id, v_id, lbl in sorted_edges:
        # Reconstruct node tuples from the sorted id strings for attr lookup.
        u_node = tuple(u_id.split("::"))
        v_node = tuple(v_id.split("::"))
        edge_data: dict[str, Any] = {"source": u_id, "target": v_id, "label": lbl}
        try:
            attrs = graph.edges[u_node, v_node]
            if "link_type" in attrs:
                edge_data["link_type"] = attrs["link_type"]
            if "similarity" in attrs:
                edge_data["similarity"] = round(float(attrs["similarity"]), 3)
        except Exception:
            pass
        edges_out.append({"data": edge_data})

    return {"nodes": nodes_out, "edges": edges_out}


__all__ = ["to_cytoscape"]
