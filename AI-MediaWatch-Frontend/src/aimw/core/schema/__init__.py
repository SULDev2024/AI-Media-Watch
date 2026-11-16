"""Canonical evidence schema — the public, stable contract for AI Media Watch.

Every subsystem depends on these objects. Import the names from this package
rather than the submodules so the internal layout can evolve without breaking
callers.
"""

from aimw.core.schema.evidence import (
    CampaignStrength,
    EvidencePackage,
    EvidencePiece,
    ExtractedEntities,
    FrozenModel,
    NetworkConnection,
    NetworkConnectionKind,
    SharedEntityKind,
    register_risk_level,
    register_scoring,
    reset_scoring,
)
from aimw.core.schema.serialization import (
    SchemaVersionMismatch,
    from_json,
    migrate_payload,
    register_schema_migration,
    to_json,
)
from aimw.core.schema.types import (
    SCHEMA_VERSION,
    EvidenceStrength,
    Polarity,
    RiskLevel,
    Source,
)

__all__ = [
    # Versioning
    "SCHEMA_VERSION",
    # Type aliases
    "EvidenceStrength",
    "Polarity",
    "Source",
    "RiskLevel",
    # Models
    "EvidencePiece",
    "ExtractedEntities",
    "EvidencePackage",
    "FrozenModel",
    "NetworkConnection",
    "NetworkConnectionKind",
    "SharedEntityKind",
    "CampaignStrength",
    # Serialization
    "to_json",
    "from_json",
    "SchemaVersionMismatch",
    # Versioning / migration (W1)
    "register_schema_migration",
    "migrate_payload",
    # Scoring registration hooks (Phase 8)
    "register_scoring",
    "register_risk_level",
    "reset_scoring",
]
