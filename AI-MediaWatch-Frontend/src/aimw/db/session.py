"""Async SQLAlchemy engine, sessionmaker, and the single-writer lock.

SQLite correctness first (§0.3 #17): every connection enables WAL, a 5s busy
timeout, foreign-key enforcement, and ``synchronous=NORMAL``. Writes are
serialized through a single-writer lock so concurrent ``save`` calls never raise
``database is locked``.

The lock is resolved *per running event loop* (ADR-0002: one loop per worker).
An ``asyncio.Lock`` binds to the first loop that awaits it, so a single
module-level instance would break across the worker loop and per-test loops.
Keying by the running loop keeps a single writer within each loop while staying
correct everywhere.
"""

from __future__ import annotations

import asyncio
from weakref import WeakKeyDictionary

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from aimw.core.config import get_settings

_writer_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()


def writer_lock() -> asyncio.Lock:
    """Return the single-writer lock bound to the current event loop."""
    loop = asyncio.get_running_loop()
    lock = _writer_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _writer_locks[loop] = lock
    return lock


def _install_sqlite_pragmas(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


def create_engine(sqlite_url: str | None = None) -> AsyncEngine:
    """Create an async engine for the given (or configured) SQLite URL."""
    url = sqlite_url if sqlite_url is not None else get_settings().sqlite_url_async
    engine = create_async_engine(url, future=True)
    _install_sqlite_pragmas(engine)
    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build an ``async_sessionmaker`` with ``expire_on_commit=False``."""
    return async_sessionmaker(engine, expire_on_commit=False)


# --- Process-wide singletons (the app's single loop owns these) --------------

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the cached process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the cached process-wide sessionmaker, creating it on first use."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = create_sessionmaker(get_engine())
    return _sessionmaker


async def reset_engine() -> None:
    """Dispose and clear the cached engine/sessionmaker (tests / reconfigure)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
