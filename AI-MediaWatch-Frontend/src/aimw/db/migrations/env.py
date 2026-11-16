"""Alembic environment. Uses a synchronous engine; the URL comes from settings."""

from __future__ import annotations

import contextlib
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from aimw.core.config import get_settings
from aimw.db.models import Base

config = context.config

if config.config_file_name is not None:
    with contextlib.suppress(Exception):  # pragma: no cover - logging config is optional
        fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return get_settings().sqlite_url_sync


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _install_sqlite_pragmas_sync(engine: object) -> None:
    """Mirror aimw.db.session._install_sqlite_pragmas on a sync engine.

    The migration runs *before* any application code touches the engine,
    so WAL must be established here or the file is left in the default
    'delete' journal mode — defeating the C2 cross-process safety net.
    Re-enabling WAL after the fact races between concurrent writers.
    """
    from sqlalchemy import event as _event

    @_event.listens_for(engine, "connect")  # type: ignore[misc]
    def _set_pragmas(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    _install_sqlite_pragmas_sync(engine)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
