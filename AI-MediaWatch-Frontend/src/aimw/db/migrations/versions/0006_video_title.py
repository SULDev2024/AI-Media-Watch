"""Add title column to videos table.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-21

Stores the platform title/headline on the video row. The LLM fraud-intent judge
reads it as critical framing context: a title like "Crypto Scam EXPOSED" or
"...Deep Fake..." reframes scam-sounding transcript as news/education rather
than promotion, preventing false positives. Nullable — older rows and
text/photo items (Telegram) may not have a title.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    result = bind.execute(sa.text("PRAGMA table_info(videos)"))
    columns = {row[1] for row in result}
    if "title" not in columns:
        op.add_column("videos", sa.Column("title", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("videos", "title")
