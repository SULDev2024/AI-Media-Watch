"""Programmatic Alembic entry points.

The migration ``script_location`` is resolved from this file's location (not the
CWD), so migrations run identically from the API process, Celery workers, tests,
and Docker (ADR-0003). The database URL comes from settings via ``env.py``.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from aimw.core.config import get_settings

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config() -> Config:
    """Build an Alembic ``Config`` pointing at the packaged migrations."""
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    # env.py reads the URL from settings; this keeps Config self-consistent.
    cfg.set_main_option("sqlalchemy.url", get_settings().sqlite_url_sync)
    return cfg


def upgrade(revision: str = "head") -> None:
    """Upgrade the database to the given revision (default: head)."""
    command.upgrade(alembic_config(), revision)


def downgrade(revision: str = "-1") -> None:
    """Downgrade the database by/to the given revision."""
    command.downgrade(alembic_config(), revision)
