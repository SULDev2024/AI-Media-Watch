"""Add transcript_segments column to videos table.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-17

Stores Whisper segment JSON ([{text, start, end}]) on the video row so the
analyst dashboard can display the full video transcript with signal highlights.
Column is nullable — older rows and fixture-mode videos may not have it.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    result = bind.execute(sa.text("PRAGMA table_info(videos)"))
    columns = {row[1] for row in result}
    if "transcript_segments" not in columns:
        op.add_column("videos", sa.Column("transcript_segments", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("videos", "transcript_segments")
