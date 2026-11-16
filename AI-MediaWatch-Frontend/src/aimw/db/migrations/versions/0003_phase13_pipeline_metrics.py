"""phase 13 pipeline metrics table

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-13

Adds the ``pipeline_metrics`` table used by
``aimw.workers.tasks.replay_regression_suite`` to persist precision /
recall / F1 snapshots of the §11 ambiguity benchmark suite.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("metric_name", sa.String(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_pipeline_metrics_metric_name",
        "pipeline_metrics",
        ["metric_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pipeline_metrics_metric_name", table_name="pipeline_metrics"
    )
    op.drop_table("pipeline_metrics")
