"""The canonical evidence objects.

This module is the product's contract. Everything downstream — collection,
ASR, OCR, VLM, entity extraction, scoring, confidence, persistence, the API —
reads or writes through these objects. They are therefore:

* **Immutable.** All models are ``frozen``; an analyst report cannot be mutated
  in place once built. Deterministic extractors *append* new evidence by
  constructing a new package, never by editing one.
* **Strictly validated.** ``extra="forbid"`` rejects unknown fields so a
  producer bug surfaces immediately rather than silently corrupting evidence.
* **Free of derived state.** The score and risk level are *computed* from the
  evidence (§6), never stored, so they can never drift from what justifies them.
  ``payment_phones`` is likewise computed from ``phone_numbers`` +
  ``phone_purposes`` and is recomputed on load, never trusted from input.

The single most important guarantee (ADR-0004): **the LLM never writes to these
objects.** Only deterministic code constructs them.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from aimw.core.schema.types import (
    EvidenceStrength,
    Polarity,
    RiskLevel,
    Source,
)

_LOG = logging.getLogger(__name__)


class FrozenModel(BaseModel):
    """Base for every schema object: frozen, strict, and round-trip safe.

    The ``mode="before"`` validator drops any *computed* field that appears in
    input data. Computed fields (e.g. ``payment_phones``) are emitted during
    serialization for the convenience of consumers, but they are derived state:
    on load they are stripped and recomputed, so a hand-edited or stale value
    can never enter the model. This is what lets a serialized package — which
    includes computed fields — round-trip cleanly under ``extra="forbid"``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_fields(cls, data: Any) -> Any:
        if isinstance(data, dict) and cls.model_computed_fields:
            return {k: v for k, v in data.items() if k not in cls.model_computed_fields}
        return data


class EvidencePiece(FrozenModel):
    """One atomic, source-attributed observation that argues a direction."""

    source: Source
    polarity: Polarity
    timestamp: float | None
    content: str
    raw_value: str
    indicator_type: str
    strength: EvidenceStrength
    # Allowed values include "raw" | "normalized" | "fuzzy" | "vlm_recovered"
    # (and others such as "spacy" introduced by later extractors). Kept as a
    # free string per §2 rather than a Literal so the vocabulary can grow
    # without a schema bump; see the Phase 2 review note on tightening this.
    recovery_method: str | None = None
    corroborated_by: list[Source] = Field(default_factory=list)
    regulation_ref: str | None = None

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("timestamp must be a finite number (no NaN/inf)")
        return value


NetworkConnectionKind = Literal["shared_entity"]
SharedEntityKind = Literal[
    "telegram_handle",
    "telegram_link",
    "crypto_wallet",
    "phone",
    "website",
    "referral_code",
]
CampaignStrength = Literal["weak", "medium", "strong"]


class NetworkConnection(FrozenModel):
    """One link between this package and other packages sharing an entity.

    Phase 11 generates exactly one kind, ``shared_entity``; the discriminator
    is kept so Phase 12+ can add edge kinds (e.g. ``coordinated_timing``)
    without a destructive schema change.

    All list fields are sorted at construction for byte-identical serialisation.
    """

    kind: NetworkConnectionKind
    shared_entity_kind: SharedEntityKind
    shared_entity_value: str
    co_occurring_report_ids: list[str]
    campaign_strength: CampaignStrength
    detected_at: datetime

    @field_validator("detected_at")
    @classmethod
    def _normalize_to_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("co_occurring_report_ids")
    @classmethod
    def _sort_report_ids(cls, value: list[str]) -> list[str]:
        return sorted(value)


# Fields required by the typed NetworkConnection -- used by the tolerant loader
# on EvidencePackage to distinguish a legacy dict from a modern one.
_NETWORK_CONNECTION_REQUIRED_FIELDS = frozenset(
    {
        "kind",
        "shared_entity_kind",
        "shared_entity_value",
        "co_occurring_report_ids",
        "campaign_strength",
        "detected_at",
    }
)


class ExtractedEntities(FrozenModel):
    """Deterministically extracted entities for one package."""

    telegram_handles: list[str] = Field(default_factory=list)
    telegram_links: list[str] = Field(default_factory=list)
    crypto_wallets: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    websites: list[str] = Field(default_factory=list)
    referral_codes: list[str] = Field(default_factory=list)
    profit_claims: list[str] = Field(default_factory=list)
    # Maps a phone number to its purpose (e.g. "payment"). Resolves §0.1 #2
    # without renaming any documented field.
    phone_purposes: dict[str, str] = Field(default_factory=dict)
    # Revision (reviewer R1/R2): how each payment-type entity is linked to the
    # video's promoter.  Values: "promoter" (offered in a call-to-action by the
    # video itself), "reported" (reproduced in a warning / news / quotation
    # context), "unlinked" (no cue either way).  Entities absent from this map
    # are treated as "promoter" so packages produced before the revision score
    # exactly as before.  Populated deterministically by aimw.entities.linkage.
    payment_linkage: dict[str, str] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def payment_phones(self) -> list[str]:
        """Phones tagged as a payment rail; drives the §6.2 Rule B entity gate."""
        return [p for p in self.phone_numbers if self.phone_purposes.get(p) == "payment"]

    def linkage_of(self, value: str) -> str:
        """Promoter linkage of one entity value (legacy default: "promoter")."""
        return self.payment_linkage.get(value, "promoter")

    def promoter_linked(self, values: list[str]) -> list[str]:
        """Subset of *values* that are offered by the promoter themself."""
        return [v for v in values if self.linkage_of(v) == "promoter"]

    def not_reported(self, values: list[str]) -> list[str]:
        """Subset of *values* that are not merely reproduced in a warning/report."""
        return [v for v in values if self.linkage_of(v) != "reported"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def promoter_payment_entities(self) -> list[str]:
        """Payment rails (wallets, referral codes, payment phones) the promoter offers.

        Drives the §6.2 Rule B entity gate after the revision.
        """
        return (
            self.promoter_linked(self.crypto_wallets)
            + self.promoter_linked(self.referral_codes)
            + self.promoter_linked(self.payment_phones)
        )


# --- Scoring registration hook (wired by Phase 8; never by the LLM) ----------
#
# The score and risk level are *computed*, never stored. Phase 8 registers the
# deterministic implementations here; until then, accessing them fails loudly so
# no caller can silently depend on an unscored package.

_score_impl: Callable[[EvidencePackage], float] | None = None
_risk_level_impl: Callable[[EvidencePackage], RiskLevel] | None = None

_NOT_WIRED = "scoring engine not wired; implement Phase 8"


def register_scoring(fn: Callable[[EvidencePackage], float]) -> None:
    """Register the deterministic score implementation (Phase 8)."""
    global _score_impl
    _score_impl = fn


def register_risk_level(fn: Callable[[EvidencePackage], RiskLevel]) -> None:
    """Register the deterministic risk-level implementation (Phase 8)."""
    global _risk_level_impl
    _risk_level_impl = fn


def reset_scoring() -> None:
    """Unregister both implementations (test isolation)."""
    global _score_impl, _risk_level_impl
    _score_impl = None
    _risk_level_impl = None


def _try_auto_register() -> None:
    """Lazy import of the Phase 8 registry on first property access.

    This avoids a circular import at module load time while still letting
    ``EvidencePackage.score`` work without an explicit ``registry.register()``
    call in application code.  Tests that need isolation should call
    ``reset_scoring()`` in teardown and re-call ``registry.register()``
    (or leave it un-registered to verify the NotImplementedError path).
    """
    try:
        import aimw.scoring.registry as _reg

        _reg.register()
    except ImportError:
        pass


class EvidencePackage(FrozenModel):
    """The canonical analyst artifact: evidence + entities + network context.

    ``score`` and ``risk_level`` are properties derived from the evidence, never
    stored. They raise until Phase 8 registers the scoring engine.
    """

    report_id: str
    video_id: str
    platform: str
    url: str
    collected_at: datetime
    processed_at: datetime
    evidence: list[EvidencePiece] = Field(default_factory=list)
    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    network_connections: list[NetworkConnection] = Field(default_factory=list)

    @field_validator("collected_at", "processed_at")
    @classmethod
    def _normalize_to_utc(cls, value: datetime) -> datetime:
        """Normalize to timezone-aware UTC so serialization is deterministic."""
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="before")
    @classmethod
    def _coerce_network_connections(cls, data: Any) -> Any:
        """Tolerant loader for legacy ``network_connections`` dict entries.

        Phase 11 promotes the field type to ``list[NetworkConnection]``. Older
        rows in the database (and ad-hoc test fixtures) may still carry raw
        dicts whose shape differs from the typed model. This validator:

        * passes through items already typed as ``NetworkConnection``;
        * validates dicts that contain all required fields;
        * **drops** dicts missing required fields and emits a structured
          warning instead of raising -- silent corruption is worse than a
          forward-compatible drop for an analyst-facing tool.
        """
        if not isinstance(data, dict):
            return data
        raw = data.get("network_connections")
        if not isinstance(raw, list):
            return data
        kept: list[Any] = []
        for item in raw:
            if isinstance(item, NetworkConnection):
                kept.append(item)
                continue
            if isinstance(item, dict):
                if _NETWORK_CONNECTION_REQUIRED_FIELDS.issubset(item.keys()):
                    kept.append(item)
                else:
                    _LOG.warning(
                        "network_connections.legacy_drop",
                        extra={
                            "missing_fields": sorted(
                                _NETWORK_CONNECTION_REQUIRED_FIELDS - set(item.keys())
                            ),
                            "report_id": data.get("report_id"),
                        },
                    )
                continue
            # Anything else (None, bare string) is silently dropped.
            _LOG.warning(
                "network_connections.unknown_item_dropped",
                extra={"type": type(item).__name__, "report_id": data.get("report_id")},
            )
        return {**data, "network_connections": kept}

    @property
    def score(self) -> float:
        """Deterministic signed score (§6). Computed, never stored."""
        if _score_impl is None:
            _try_auto_register()
        if _score_impl is None:
            raise NotImplementedError(_NOT_WIRED)
        return _score_impl(self)

    @property
    def risk_level(self) -> RiskLevel:
        """Five-band risk level (§6.3). Computed, never stored."""
        if _risk_level_impl is None:
            _try_auto_register()
        if _risk_level_impl is None:
            raise NotImplementedError(_NOT_WIRED)
        return _risk_level_impl(self)
