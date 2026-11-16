"""Deterministic JSON serialization + forward-compatible versioning.

The serialized form is the cross-subsystem and cross-version wire format, so it
must be **stable** and **deterministic**:

* keys are sorted recursively, separators are fixed, and ``ensure_ascii`` is
  pinned — two serializations of equal data are byte-identical;
* timestamps are ISO 8601 UTC (the model normalizes to UTC on construction);
* ``NaN``/``inf`` are rejected (``allow_nan=False``);
* every payload carries a top-level ``schema_version``.

Versioning policy (W1):

* a payload at the current :data:`SCHEMA_VERSION` loads directly;
* an *older* payload loads if a migration path is registered that upgrades it to
  the current version (see :func:`register_schema_migration`);
* anything else — a missing version, or a version with no path to the current
  one (e.g. an unknown *future* version) — raises :class:`SchemaVersionMismatch`.

This keeps the strict guarantee ("never silently misread a foreign format")
while giving stored evidence a forward path across schema bumps.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from itertools import pairwise
from typing import Any

from aimw.core.schema.evidence import EvidencePackage
from aimw.core.schema.types import SCHEMA_VERSION

# A migration transforms a bare field payload (no ``schema_version`` key) from
# one version's shape to the next.
Migration = Callable[[dict[str, Any]], dict[str, Any]]

# Directed edges: (from_version, to_version) -> transform.
_MIGRATIONS: dict[tuple[str, str], Migration] = {}


class SchemaVersionMismatch(ValueError):
    """Raised when a payload's ``schema_version`` cannot be loaded."""

    def __init__(self, found: Any) -> None:
        super().__init__(
            f"Unsupported schema_version {found!r}; this build expects {SCHEMA_VERSION!r} "
            f"and no migration path was found"
        )
        self.found = found


# --- Migration registry ------------------------------------------------------


def register_schema_migration(from_version: str, to_version: str, fn: Migration) -> None:
    """Register a migration that upgrades a payload from one version to another.

    ``fn`` receives the field payload (the parsed JSON object with
    ``schema_version`` removed) and returns the payload reshaped for
    ``to_version``. Registering the same edge twice replaces it.
    """
    _MIGRATIONS[(from_version, to_version)] = fn


def _reset_migrations() -> None:
    """Clear the migration registry (test isolation)."""
    _MIGRATIONS.clear()


def _find_path(from_version: str, to_version: str) -> list[tuple[str, str]] | None:
    """Shortest chain of registered edges from one version to another, or None."""
    if from_version == to_version:
        return []
    queue: deque[list[str]] = deque([[from_version]])
    visited: set[str] = {from_version}
    while queue:
        path = queue.popleft()
        current = path[-1]
        for edge_from, edge_to in sorted(_MIGRATIONS):  # sorted -> deterministic path
            if edge_from != current or edge_to in visited:
                continue
            if edge_to == to_version:
                return list(pairwise([*path, edge_to]))
            visited.add(edge_to)
            queue.append([*path, edge_to])
    return None


def migrate_payload(payload: dict[str, Any], from_version: str, to_version: str) -> dict[str, Any]:
    """Upgrade a bare field payload along the registered migration path.

    Raises :class:`SchemaVersionMismatch` if no path of registered migrations
    connects ``from_version`` to ``to_version``.
    """
    path = _find_path(from_version, to_version)
    if path is None:
        raise SchemaVersionMismatch(from_version)
    result = payload
    for edge in path:
        result = _MIGRATIONS[edge](result)
    return result


# --- Serialization -----------------------------------------------------------


def to_json(package: EvidencePackage) -> str:
    """Serialize a package to a deterministic, versioned JSON string."""
    payload = package.model_dump(mode="json")
    payload["schema_version"] = SCHEMA_VERSION
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def from_json(data: str) -> EvidencePackage:
    """Deserialize a versioned JSON string back into a package.

    For a current-version payload this is the exact inverse of :func:`to_json`
    (``to_json(from_json(s))`` is byte-stable). An older payload is upgraded
    through registered migrations first.
    """
    raw = json.loads(data)
    if not isinstance(raw, dict):
        raise SchemaVersionMismatch(None)
    version = raw.get("schema_version")
    if version is None:
        raise SchemaVersionMismatch(None)

    payload = {k: v for k, v in raw.items() if k != "schema_version"}
    if version != SCHEMA_VERSION:
        payload = migrate_payload(payload, version, SCHEMA_VERSION)
    return EvidencePackage.model_validate(payload)
