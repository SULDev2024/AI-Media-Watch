"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-20

Hand-written DDL (no ``create_all`` shortcut) so future revisions can ALTER from
a known baseline. SQLite ALTERs in later revisions must use ``op.batch_alter_table``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("language_hint", sa.String(), nullable=True),
        sa.Column("priority_score", sa.Float(), nullable=True),
        sa.Column("raw_path", sa.String(), nullable=True),
        sa.Column("transcript_segments", sa.Text(), nullable=True),
    )

    op.create_table(
        "evidence_packages",
        sa.Column("report_id", sa.String(), primary_key=True),
        sa.Column("video_id", sa.String(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("package_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"], ondelete="RESTRICT", name="fk_packages_video"
        ),
    )
    op.create_index("ix_evidence_packages_video_id", "evidence_packages", ["video_id"])
    op.create_index("ix_evidence_packages_risk_level", "evidence_packages", ["risk_level"])

    op.create_table(
        "evidence_pieces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("polarity", sa.String(), nullable=False),
        sa.Column("strength", sa.String(), nullable=False),
        sa.Column("indicator_type", sa.String(), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=False),
        sa.Column("recovery_method", sa.String(), nullable=True),
        sa.Column("regulation_ref", sa.String(), nullable=True),
        sa.Column("timestamp", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["evidence_packages.report_id"],
            ondelete="CASCADE",
            name="fk_pieces_report",
        ),
    )
    op.create_index("ix_evidence_pieces_report_id", "evidence_pieces", ["report_id"])
    op.create_index("ix_evidence_pieces_indicator_type", "evidence_pieces", ["indicator_type"])

    op.create_table(
        "entities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("certainty", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["evidence_packages.report_id"],
            ondelete="CASCADE",
            name="fk_entities_report",
        ),
    )
    op.create_index("ix_entities_report_id", "entities", ["report_id"])
    op.create_index("ix_entities_kind", "entities", ["kind"])
    op.create_index("ix_entities_value", "entities", ["value"])

    op.create_table(
        "network_connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["evidence_packages.report_id"],
            ondelete="CASCADE",
            name="fk_network_report",
        ),
    )
    op.create_index("ix_network_connections_report_id", "network_connections", ["report_id"])

    op.create_table(
        "reports",
        sa.Column("report_id", sa.String(), primary_key=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["evidence_packages.report_id"],
            ondelete="CASCADE",
            name="fk_reports_report",
        ),
    )

    op.create_table(
        "analyst_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["evidence_packages.report_id"],
            ondelete="CASCADE",
            name="fk_feedback_report",
        ),
        sa.CheckConstraint(
            "verdict IN ('confirmed', 'dismissed', 'escalated')",
            name="ck_analyst_feedback_verdict",
        ),
    )
    op.create_index("ix_analyst_feedback_report_id", "analyst_feedback", ["report_id"])

    op.create_table(
        "regression_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("input_url", sa.String(), nullable=True),
        sa.Column("expected_level", sa.String(), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_from_report", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["frozen_from_report"],
            ["evidence_packages.report_id"],
            ondelete="SET NULL",
            name="fk_regression_report",
        ),
        sa.UniqueConstraint("name", name="uq_regression_cases_name"),
    )

    op.create_table(
        "daily_token_usage",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("model", sa.String(), primary_key=True),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "ingest_queue",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
    )


def downgrade() -> None:
    op.drop_table("ingest_queue")
    op.drop_table("daily_token_usage")
    op.drop_table("regression_cases")
    op.drop_index("ix_analyst_feedback_report_id", table_name="analyst_feedback")
    op.drop_table("analyst_feedback")
    op.drop_table("reports")
    op.drop_index("ix_network_connections_report_id", table_name="network_connections")
    op.drop_table("network_connections")
    op.drop_index("ix_entities_value", table_name="entities")
    op.drop_index("ix_entities_kind", table_name="entities")
    op.drop_index("ix_entities_report_id", table_name="entities")
    op.drop_table("entities")
    op.drop_index("ix_evidence_pieces_indicator_type", table_name="evidence_pieces")
    op.drop_index("ix_evidence_pieces_report_id", table_name="evidence_pieces")
    op.drop_table("evidence_pieces")
    op.drop_index("ix_evidence_packages_risk_level", table_name="evidence_packages")
    op.drop_index("ix_evidence_packages_video_id", table_name="evidence_packages")
    op.drop_table("evidence_packages")
    op.drop_table("videos")
