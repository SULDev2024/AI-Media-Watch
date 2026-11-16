"""phase 11 graph: detected_at + composite entities index

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-13

Adds:
  * ``network_connections.detected_at`` (DateTime, timezone-aware, NOT NULL).
    Existing rows are backfilled from ``evidence_packages.processed_at``
    before NOT NULL is enforced; if any orphan rows exist (FK should prevent
    this) the migration falls back to NOW().
  * ``ix_network_connections_detected_at`` for time-window queries.
  * ``ix_entities_kind_value`` composite index for the Phase 11 cross-package
    correlation query "find all packages containing entity X".

Downgrade drops both indexes and the column (column data is lost on downgrade).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add ``detected_at`` as nullable so we can backfill.
    with op.batch_alter_table("network_connections") as batch_op:
        batch_op.add_column(
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True)
        )

    # 2. Backfill existing rows from the parent package's processed_at.
    op.execute(
        """
        UPDATE network_connections
           SET detected_at = (
               SELECT processed_at FROM evidence_packages
                WHERE evidence_packages.report_id = network_connections.report_id
           )
         WHERE detected_at IS NULL
        """
    )

    # 3. Catch any orphan rows that lacked a join target (FK should prevent
    #    this, but defence in depth -- we cannot leave NULLs before adding the
    #    NOT NULL constraint).
    op.execute(
        "UPDATE network_connections SET detected_at = CURRENT_TIMESTAMP "
        "WHERE detected_at IS NULL"
    )

    # 4. Enforce NOT NULL.
    with op.batch_alter_table("network_connections") as batch_op:
        batch_op.alter_column(
            "detected_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )

    # 5. Indexes.
    op.create_index(
        "ix_network_connections_detected_at",
        "network_connections",
        ["detected_at"],
    )
    op.create_index("ix_entities_kind_value", "entities", ["kind", "value"])


def downgrade() -> None:
    op.drop_index("ix_entities_kind_value", table_name="entities")
    op.drop_index("ix_network_connections_detected_at", table_name="network_connections")
    with op.batch_alter_table("network_connections") as batch_op:
        batch_op.drop_column("detected_at")
