"""Pydantic v2 request/response schemas for the v1 API (Phase 12).

Every response that the analyst dashboard consumes is typed here. The
schemas re-export :class:`aimw.core.schema.EvidencePackage` for the
report endpoint per the spec (§ "Reuse EvidencePackage for GET
/reports/{id}").
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aimw.core.schema import EvidencePackage

__all__ = [
    "CampaignOut",
    "CollectorStartRequest",
    "CollectorState",
    "CytoscapeGraph",
    "EnvelopeError",
    "EvidencePackage",  # re-export per spec
    "FeedbackIn",
    "FeedbackOut",
    "IngestRequest",
    "IngestResponse",
    "PrecisionRecallCase",
    "PrecisionRecallResponse",
    "ReportResponse",
    "UsageToday",
    "User",
    "VideoDetail",
    "VideoSummary",
    "VideosList",
]


class _Schema(BaseModel):
    """Base for v1 response models — JSON-only, no extra keys."""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Auth / identity
# ---------------------------------------------------------------------------


class User(_Schema):
    """Authenticated principal exposed through ``RequireAnalyst``.

    In dev/test the API returns ``User(id="dev", roles=["analyst"])``.
    In prod the JWT branch (stubbed for Phase 12) populates the same shape.
    """

    id: str
    roles: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Errors — every response carries ``request_id`` per spec
# ---------------------------------------------------------------------------


class EnvelopeError(_Schema):
    """Error envelope returned by the exception handlers."""

    error: str
    request_id: str
    code: str | None = None
    detail: Any | None = None


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    """Request body for POST /api/v1/ingest/url."""

    model_config = ConfigDict(extra="forbid")
    url: str = Field(
        ...,
        description=(
            "URL of the video/channel to ingest. Allowed schemes: http, https, "
            "and file:// (used for fixtured local tests per Phase 12 §2 "
            "acceptance criterion)."
        ),
    )


class IngestResponse(_Schema):
    """Response for POST /api/v1/ingest/url — 202 Accepted."""

    video_id: str
    status: str = "pending"
    request_id: str
    queue_id: int


# ---------------------------------------------------------------------------
# Collector control
# ---------------------------------------------------------------------------


class CollectorStartRequest(BaseModel):
    """Request body for POST /api/v1/collector/start."""

    model_config = ConfigDict(extra="forbid")
    queries: list[str] = Field(
        default_factory=list,
        description="Search terms the crawler cycles each tick.",
    )
    platforms: list[str] = Field(
        default_factory=lambda: ["youtube"],
        description="Platforms to crawl (youtube works; others need their API).",
    )
    content_types: list[str] = Field(
        default_factory=lambda: ["video", "photo", "text"],
        description="Content kinds to collect: any of video / photo / text.",
    )
    region_focus: str = Field(
        default="global",
        description="Geographic/language focus for query expansion, e.g. global or kazakhstan.",
    )
    per_query: int = Field(
        default=5, ge=1, le=25,
        description="Candidates pulled per query per tick.",
    )


class CollectorState(_Schema):
    """Current collector run-state, mirrored from the Redis control flag."""

    status: str  # "running" | "stopped"
    queries: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=lambda: ["youtube"])
    content_types: list[str] = Field(default_factory=lambda: ["video", "photo", "text"])
    region_focus: str = "global"
    per_query: int = 5
    last_run: str | None = None
    last_enqueued: int = 0
    enqueued_total: int = 0
    supported_platforms: list[str] = Field(default_factory=lambda: ["youtube"])


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------


class VideoSummary(_Schema):
    """Compact video row for the list endpoint."""

    video_id: str
    platform: str
    url: str
    collected_at: dt.datetime
    # Joined from the package projection (NULL until the worker scores it).
    score: float | None = None
    level: str | None = None
    confidence: float | None = None
    action: str | None = None
    # Harm-weighted triage priority: harm_severity × confidence (0–1).
    # Higher values surface for investigation first.
    priority_score: float | None = None
    # Content classification: "video" | "photo" | "text" — derived from platform + raw_path.
    content_type: str = "video"
    # Platform title / headline — provides context for analysts reviewing the queue.
    title: str | None = None
    # Number of incriminating evidence pieces — gives queue-level severity signal.
    evidence_count: int = 0


class VideosList(_Schema):
    """Paginated /api/v1/videos response."""

    items: list[VideoSummary]
    total: int
    limit: int
    request_id: str


class VideoDetail(_Schema):
    """Single-video detail including its linked packages."""

    video_id: str
    platform: str
    url: str
    collected_at: dt.datetime
    language_hint: str | None = None
    raw_path: str | None = None
    package_ids: list[str]
    transcript_segments: str | None = None
    ocr_text: str | None = None
    request_id: str
    status: str = "pending"
    error: str | None = None


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class ReportResponse(_Schema):
    """JSON wrapper for the canonical EvidencePackage + rendered Markdown.

    ``score`` and ``risk_level`` are lifted from the package's computed
    ``@property`` descriptors because Pydantic's model_dump() cannot see
    Python-level properties — they must be injected explicitly before the
    response is serialized.
    """

    package: EvidencePackage
    markdown: str
    request_id: str
    # Verdict projection — the LLM judge's result when available, else the
    # rule-based computed values. Lifted out of the row so they serialize.
    score: float | None = None
    risk_level: str | None = None
    confidence: float | None = None
    action: str | None = None
    judge: str | None = None  # "llm" | "rules" — indicates whether LLM was used


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class FeedbackIn(BaseModel):
    """POST /api/v1/feedback request body."""

    model_config = ConfigDict(extra="forbid")
    report_id: str
    verdict: str = Field(
        ..., description="One of: confirmed, dismissed, escalated"
    )
    notes: str | None = None


class FeedbackOut(_Schema):
    """POST /api/v1/feedback response."""

    feedback_id: int
    report_id: str
    verdict: str
    regression_case_id: int | None = Field(
        None,
        description="Populated when verdict==confirmed (frozen regression case id).",
    )
    request_id: str


# ---------------------------------------------------------------------------
# Graph + campaigns
# ---------------------------------------------------------------------------


class CytoscapeGraph(_Schema):
    """GET /api/v1/graph response — Cytoscape JSON for the dashboard."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    request_id: str


class CampaignOut(_Schema):
    """One detected campaign."""

    campaign_id: str
    shared_entities: list[str]
    strength: str
    n_videos: int
    videos: list[str]


class CampaignsResponse(_Schema):
    """GET /api/v1/campaigns response envelope."""

    items: list[CampaignOut]
    request_id: str


# ---------------------------------------------------------------------------
# Metrics — §11 precision-recall ambiguity suite
# ---------------------------------------------------------------------------


class PrecisionRecallCase(_Schema):
    """Per-case verdict from the §11 ambiguity suite."""

    case_id: str
    expected_level: str
    predicted_level: str
    expected_action: str
    predicted_action: str
    is_correct_level: bool
    is_correct_action: bool
    is_false_positive: bool
    is_false_negative: bool


class PrecisionRecallResponse(_Schema):
    """GET /api/v1/metrics/precision-recall response."""

    n_cases: int
    precision: float
    recall: float
    f1: float
    cases: list[PrecisionRecallCase]
    cached_at: dt.datetime
    request_id: str


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


class UsageToday(_Schema):
    """GET /api/v1/usage/today — daily Groq token usage."""

    date: dt.date
    model: str
    tokens_used: int
    daily_cap: int
    remaining: int
    request_id: str
