"""SQLAlchemy 2.0 ORM models — a *storage projection* of the canonical schema.

These tables exist for indexed SQL queries. The authoritative source of truth is
always ``evidence_packages.package_json`` (the exact :func:`aimw.core.schema.to_json`
output). If a flattened row ever disagrees with ``package_json``, ``package_json``
wins; reconstruction goes only through :func:`aimw.core.schema.from_json`.

These models therefore never carry domain logic and are never used to build an
``EvidencePackage`` directly (ADR-0004; Phase 3 integration rule).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all storage-projection models."""


class Video(Base):
    """Collected media. Owned by the collection subsystem (Phase 4)."""

    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    collected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    language_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    priority_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_path: Mapped[str | None] = mapped_column(String, nullable=True)
    transcript_segments: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The platform title/headline. Critical context for the judge: a title like
    # "Crypto Scam EXPOSED" or "...Deep Fake..." reframes scam-sounding
    # transcript as news/education rather than promotion.
    title: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidencePackageRow(Base):
    """The canonical package blob plus indexed projections of derived fields.

    ``score``/``risk_level``/``confidence``/``action`` are nullable because the
    scoring engine does not exist until Phase 8. The repository writes NULL and
    never fabricates a value.
    """

    __tablename__ = "evidence_packages"

    report_id: Mapped[str] = mapped_column(String, primary_key=True)
    video_id: Mapped[str] = mapped_column(
        String, ForeignKey("videos.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    processed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Derived (computed by Phase 8) — nullable, never fabricated.
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    action: Mapped[str | None] = mapped_column(String, nullable=True)

    # Authoritative canonical blob.
    schema_version: Mapped[str] = mapped_column(String, nullable=False)
    package_json: Mapped[str] = mapped_column(Text, nullable=False)


class EvidencePieceRow(Base):
    """Flattened evidence pieces for SQL filtering (projection of package.evidence)."""

    __tablename__ = "evidence_pieces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("evidence_packages.report_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    polarity: Mapped[str] = mapped_column(String, nullable=False)
    strength: Mapped[str] = mapped_column(String, nullable=False)
    indicator_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    recovery_method: Mapped[str | None] = mapped_column(String, nullable=True)
    regulation_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)


class EntityRow(Base):
    """Flattened entities for SQL filtering / the intelligence graph (Phase 11).

    The ``(kind, value)`` composite index supports the Phase 11 cross-package
    correlation query "find all packages containing entity X" without forcing
    a table scan.
    """

    __tablename__ = "entities"
    __table_args__ = (Index("ix_entities_kind_value", "kind", "value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("evidence_packages.report_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    value: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # Per-entity certainty arrives in Phase 7; NULL until then (never fabricated).
    certainty: Mapped[float | None] = mapped_column(Float, nullable=True)


class NetworkConnectionRow(Base):
    """Network connection payloads (projection of package.network_connections).

    Phase 11 added the ``detected_at`` column so the graph subsystem can answer
    "campaigns active in the last 7 days" without joining back through
    evidence_packages. The column is indexed for time-window queries.
    """

    __tablename__ = "network_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("evidence_packages.report_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    detected_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class ReportRow(Base):
    """Rendered Markdown evidence report (Phase 10 writes this)."""

    __tablename__ = "reports"

    report_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("evidence_packages.report_id", ondelete="CASCADE"),
        primary_key=True,
    )
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalystFeedbackRow(Base):
    """Analyst verdicts on reports (Phase 15)."""

    __tablename__ = "analyst_feedback"
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('confirmed', 'dismissed', 'escalated')",
            name="ck_analyst_feedback_verdict",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("evidence_packages.report_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RegressionCaseRow(Base):
    """Frozen regression cases (Phase 15). ``expected_level`` is NULL until scored."""

    __tablename__ = "regression_cases"
    __table_args__ = (UniqueConstraint("name", name="uq_regression_cases_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    input_url: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_level: Mapped[str | None] = mapped_column(String, nullable=True)
    frozen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frozen_from_report: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("evidence_packages.report_id", ondelete="SET NULL"),
        nullable=True,
    )


class DailyTokenUsageRow(Base):
    """Per-(date, model) token usage for the Groq budget guard (Phase 10/13)."""

    __tablename__ = "daily_token_usage"

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    model: Mapped[str] = mapped_column(String, primary_key=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class IngestQueueRow(Base):
    """Staging table drained by the worker (Phase 13)."""

    __tablename__ = "ingest_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")


class UserRow(Base):
    """Registered users with hashed passwords (Phase 21 auth)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="analyst")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CheckHistoryRow(Base):
    """User check history for the Scam Check page (Phase 21)."""

    __tablename__ = "check_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    video_id: Mapped[str] = mapped_column(String, nullable=False)
    input_type: Mapped[str] = mapped_column(String, nullable=False)  # "url" or "text"
    input_value: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str | None] = mapped_column(String, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WebhookRow(Base):
    """Admin-configured webhook endpoints (Phase 21)."""

    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    events: Mapped[str] = mapped_column(String, nullable=False, default="scam_detected")
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PipelineMetricsRow(Base):
    """Phase 13 periodic metric snapshot.

    Populated by ``replay_regression_suite`` so dashboards can read the
    historical precision/recall/F1 of the §11 ambiguity suite.
    """

    __tablename__ = "pipeline_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
