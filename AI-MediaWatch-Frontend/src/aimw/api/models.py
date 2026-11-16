"""Pydantic models for the Phase 12 analyst-facing REST API.

All response models re-derive computed fields (score, risk_level, confidence,
action) from the canonical EvidencePackage at serialisation time. They are
*never* copied from the DB projection columns, which may be NULL until Phase 13
populates them, and *never* fabricated.
"""
from __future__ import annotations

import datetime as dt
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aimw.api.url_validation import URLValidationError, validate_ingest_url

T = TypeVar("T")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Paginated(_Frozen, Generic[T]):
    """Envelope for paginated list responses."""

    total: int = Field(..., description="Total matching items across all pages")
    limit: int = Field(..., description="Page size requested")
    offset: int = Field(..., description="Items skipped before this page")
    items: list[T]


class EvidencePieceResponse(_Frozen):
    source: str
    polarity: str
    strength: str
    indicator_type: str
    raw_value: str
    timestamp: float | None
    corroborated_by: list[str]
    recovery_method: str | None
    regulation_ref: str | None


class NetworkConnectionResponse(_Frozen):
    kind: str
    shared_entity_kind: str
    shared_entity_value: str
    co_occurring_report_ids: list[str]
    campaign_strength: str
    detected_at: dt.datetime


class EntitiesResponse(_Frozen):
    telegram_handles: list[str]
    telegram_links: list[str]
    crypto_wallets: list[str]
    phone_numbers: list[str]
    websites: list[str]
    referral_codes: list[str]
    profit_claims: list[str]
    payment_phones: list[str]


class PackageSummary(_Frozen):
    """Compact per-package representation for list views."""

    report_id: str
    video_id: str
    platform: str
    url: str
    processed_at: dt.datetime
    risk_level: str = Field(..., description="Computed risk level (never stored)")
    score: float = Field(..., description="Computed signed score (never stored)")
    n_evidence: int
    n_network_connections: int


class PackageDetail(PackageSummary):
    """Full package detail including evidence, entities, and inference results."""

    confidence: float | None = Field(
        None, description="Confidence score (0–1); None if not computed"
    )
    action: str | None = Field(None, description="Recommended action; None if not computed")
    evidence: list[EvidencePieceResponse]
    entities: EntitiesResponse
    network_connections: list[NetworkConnectionResponse]


class CampaignSummary(_Frozen):
    """One detected coordinated campaign."""

    campaign_id: str = Field(
        ...,
        description="Stable identifier = shared_entities[0] (unique per Phase 11 campaign)",
    )
    shared_entities: list[str]
    strength: str
    n_videos: int
    videos: list[str]


class AnalysisRunRequest(BaseModel):
    """Request body for POST /analysis/run.

    The ``url`` field is validated through
    :func:`aimw.api.url_validation.validate_ingest_url` — the single point
    that enforces the SSRF allow-list (C3 mitigation).  Validation rejects
    IP literals, internal hostnames, non-http(s) schemes, embedded
    credentials, and hosts not on the per-platform allow-list.
    """

    url: str = Field(..., description="URL of the video or channel to analyse")
    platform: str = Field("telegram", description="Platform identifier")
    priority: int = Field(1, ge=1, le=10, description="Processing priority (1=highest)")

    @model_validator(mode="after")
    def _enforce_ssrf_guard(self) -> AnalysisRunRequest:
        try:
            validate_ingest_url(self.url, self.platform)
        except URLValidationError as exc:
            # Surface as a Pydantic ValidationError so FastAPI returns 422.
            raise ValueError(str(exc)) from exc
        return self


class AnalysisRunResponse(_Frozen):
    """Response for POST /analysis/run — confirms the item was enqueued."""

    queue_id: int
    url: str
    platform: str
    status: str
    enqueued_at: dt.datetime


class RecomputeResponse(_Frozen):
    """Response for POST /campaigns/recompute."""

    task_id: str
    status: str


class MetricsSnapshot(_Frozen):
    """Real-time operational metrics derived from the live database and graph."""

    total_packages: int
    packages_by_level: dict[str, int] = Field(
        ...,
        description=(
            "Packages grouped by risk_level. All values may be zero until "
            "Phase 13 populates the risk_level column in the database."
        ),
    )
    total_campaigns: int
    campaigns_by_strength: dict[str, int]
    token_usage_today: int
    token_cap_today: int


class ErrorResponse(_Frozen):
    """Structured error envelope returned on 4xx/5xx responses."""

    error: str
    code: str
    detail: str | None = None
