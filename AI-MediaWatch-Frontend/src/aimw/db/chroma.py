"""ChromaDB persistent client.

A single cosine-distance collection ``aimw_embeddings`` is provisioned at the
configured (absolute) Chroma path. No embeddings are written in Phase 3 — this
wires the storage so later phases (retrieval / campaign clustering) can use it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aimw.core.config import get_settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from chromadb.api.models.Collection import Collection

COLLECTION_NAME = "aimw_embeddings"

_client: Any | None = None


def get_client() -> Any:
    """Return a cached persistent Chroma client at the configured path."""
    global _client
    if _client is None:
        import chromadb

        path = get_settings().resolved_chroma_path
        path.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(path))
    return _client


def get_collection() -> Collection:
    """Return (creating if needed) the cosine-distance embeddings collection."""
    client = get_client()
    collection: Collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def reset_client() -> None:
    """Drop the cached client (tests / reconfigure)."""
    global _client
    _client = None
