"""Add users, check_history, and webhooks tables.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-20

Phase 21: JWT auth, user check history, and webhook integrations.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="analyst"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "check_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("video_id", sa.String(), nullable=False),
        sa.Column("input_type", sa.String(), nullable=False),
        sa.Column("input_value", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_check_history_user_id", "check_history", ["user_id"])
    op.create_index("ix_check_history_session_id", "check_history", ["session_id"])

    op.create_table(
        "webhooks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("events", sa.String(), nullable=False, server_default="scam_detected"),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("webhooks")
    op.drop_table("check_history")
    op.drop_index("ix_users_email", "users")
    op.drop_table("users")
