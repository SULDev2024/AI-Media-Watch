"""Bipartite graph builder over (video, entity) -- Phase 11.

``build_from_db`` queries the persisted ``entities`` projection and emits a
NetworkX ``Graph`` with two node bipartitions:

* ``("video", report_id)`` — one per ``EvidencePackage``.
* ``("entity", kind, value)`` — one per distinct entity value seen in the corpus.

An edge ``video <-> entity`` exists iff the entity appears in that package's
``entities`` projection with ``certainty >= 0.5`` (filters fuzzy-only and
uncorroborated recoveries from the §0.2 #5 escalation path; NULL certainty is
treated as 1.0 for compatibility with Phase 3 rows where the column predates
per-entity certainty).

Determinism: queries are ordered by ``(report_id, kind, value)`` and node/edge
insertion follows the query order. The resulting graph is structurally
identical across runs for the same corpus.
"""
from __future__ import annotations

import json

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aimw.db.models import EntityRow, EvidencePackageRow
from aimw.db.models import Video as VideoModel
from aimw.fingerprint import compute as fp_compute
from aimw.fingerprint import find_matches as fp_find

# Entity kinds the graph cares about (mirrors NetworkConnection.SharedEntityKind).
# The entities-projection table uses the FIELD NAMES from ExtractedEntities
# (e.g. ``telegram_handles``) as ``kind`` -- so this map is field-name -> graph kind.
_ENTITY_KIND_MAP: dict[str, str] = {
    "telegram_handles": "telegram_handle",
    "telegram_links": "telegram_link",
    "crypto_wallets": "crypto_wallet",
    "phone_numbers": "phone",
    "websites": "website",
    "referral_codes": "referral_code",
}

# Minimum certainty for an entity to participate in the graph.
MIN_ENTITY_CERTAINTY: float = 0.5


def _video_node(report_id: str) -> tuple[str, str]:
    return ("video", report_id)


def _entity_node(kind: str, value: str) -> tuple[str, str, str]:
    return ("entity", kind, value)


async def build_from_db(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> nx.Graph:
    """Build the bipartite (video, entity) graph from persisted rows.

    Parameters
    ----------
    sessionmaker:
        Async sessionmaker bound to the application's SQLite engine.

    Returns
    -------
    networkx.Graph
        Undirected bipartite graph. Each ``video`` node has attribute
        ``bipartite=0``; each ``entity`` node has ``bipartite=1``. Entity nodes
        additionally carry ``kind`` and ``value`` attributes for fast export.
    """
    graph: nx.Graph = nx.Graph()

    async with sessionmaker() as session:
        # All successfully analyzed packages, sorted for determinism.
        package_rows = await session.execute(
            select(EvidencePackageRow.report_id)
            .where(EvidencePackageRow.schema_version != "failed")
            .order_by(EvidencePackageRow.report_id)
        )
        report_ids = [r for (r,) in package_rows.all()]
        if not report_ids:
            return graph

        for rid in report_ids:
            graph.add_node(_video_node(rid), bipartite=0, label=rid, kind="video")

        # All entities for those packages, sorted for determinism.
        ent_rows = await session.execute(
            select(EntityRow.report_id, EntityRow.kind, EntityRow.value, EntityRow.certainty)
            .where(EntityRow.report_id.in_(report_ids))
            .order_by(EntityRow.report_id, EntityRow.kind, EntityRow.value)
        )
        for rid, kind, value, certainty in ent_rows.all():
            # NULL certainty is treated as 1.0 (Phase 3 rows predate the field).
            cert = 1.0 if certainty is None else float(certainty)
            if cert < MIN_ENTITY_CERTAINTY:
                continue
            graph_kind = _ENTITY_KIND_MAP.get(kind)
            if graph_kind is None:
                continue
            ent_node = _entity_node(graph_kind, value)
            if ent_node not in graph:
                graph.add_node(
                    ent_node,
                    bipartite=1,
                    label=value,
                    kind="entity",
                    entity_kind=graph_kind,
                )
            graph.add_edge(_video_node(rid), ent_node, kind=graph_kind)

    # ── Second pass: fingerprint-based video↔video similarity edges ──────────
    # Detects same-operator videos that share no entity values but use the
    # same scripted pitch text or entity value set.
    await _add_fingerprint_edges(graph, sessionmaker)

    return graph


async def _add_fingerprint_edges(
    graph: nx.Graph,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Add direct video↔video edges based on content-fingerprint similarity.

    These edges carry ``link_type="entity_match"`` or ``"content_match"``
    and ``similarity`` weight so the Cytoscape export colours them differently
    from the bipartite entity edges.
    """
    video_node_ids = [
        n for n, attr in graph.nodes(data=True) if attr.get("kind") == "video"
    ]
    if len(video_node_ids) < 2:
        return

    # Build entity_set for each video directly from the graph (already loaded).
    fingerprints: dict[str, dict] = {}
    for node in video_node_ids:
        vid_id = node[1] if isinstance(node, tuple) else str(node)
        entity_vals: list[str] = []
        for neighbour in graph.neighbors(node):
            if isinstance(neighbour, tuple) and neighbour[0] == "entity":
                entity_vals.append(neighbour[2])
        fingerprints[vid_id] = {
            "minhash": [],  # no transcript loaded yet
            "entity_set": sorted(set(entity_vals)),
        }

    # Load transcripts for text-similarity pass.
    async with sessionmaker() as session:
        rows = await session.execute(
            select(VideoModel.id, VideoModel.transcript_segments)
            .where(VideoModel.id.in_(list(fingerprints)))
            .order_by(VideoModel.id)
        )
        for vid_id, transcript_json in rows.all():
            transcript = ""
            if transcript_json:
                try:
                    segs = json.loads(transcript_json)
                    transcript = " ".join(
                        s.get("text", "") for s in segs if isinstance(s, dict)
                    )
                except Exception:
                    transcript = str(transcript_json)
            existing = fingerprints.get(vid_id, {})
            fp = fp_compute(
                transcript=transcript,
                ocr_text="",
                entities={"referral_codes": existing.get("entity_set", [])},
            )
            fingerprints[vid_id] = {
                "minhash": fp["minhash"],
                "entity_set": existing.get("entity_set", fp["entity_set"]),
            }

    matches = fp_find(fingerprints)
    for vid_a, vid_b, similarity, link_type in matches:
        node_a = _video_node(vid_a)
        node_b = _video_node(vid_b)
        if node_a in graph and node_b in graph and not graph.has_edge(node_a, node_b):
            graph.add_edge(
                node_a,
                node_b,
                link_type=link_type,
                similarity=similarity,
                kind="fingerprint",
            )


__all__ = ["MIN_ENTITY_CERTAINTY", "build_from_db"]
