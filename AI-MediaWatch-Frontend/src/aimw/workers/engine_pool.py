"""Engine + sessionmaker pool for Celery worker tasks (H4 mitigation).

The pre-fix recompute task constructed a fresh ``AsyncEngine`` per
invocation, paid the SQLite pragma + WAL setup cost, ran the task, then
disposed.  Under retries (max=3) this triples that overhead.  With
``concurrency=1`` the worker process has exactly one event loop alive at
a time, so a per-loop cache is sufficient.

This module exposes a single ``scoped_sessionmaker`` async context
manager that:

1. Reuses an ``AsyncEngine`` bound to the current event loop if one
   exists in the cache, or creates a new one and caches it.
2. Returns a ``sessionmaker`` bound to that engine for the duration of
   the ``async with`` block.

The engine is **not** disposed at the end of the block — it is reused
across tasks within the lifetime of the same event loop.  Disposal
happens via ``shutdown_pool()`` which is callable from a worker
``worker_shutdown`` signal handler or explicitly in tests.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from weakref import WeakKeyDictionary

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from aimw.db.session import create_engine, create_sessionmaker


@asynccontextmanager
async def scoped_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a sessionmaker bound to a per-loop-cached engine.

    Reuses the engine across calls within the same event loop. The first
    call in a fresh loop pays the engine-setup cost; subsequent calls
    are O(1).
    """
    loop = asyncio.get_running_loop()
    engine = _engines.get(loop)
    if engine is None:
        engine = create_engine()
        _engines[loop] = engine
        _sessionmakers[loop] = create_sessionmaker(engine)
    sm = _sessionmakers[loop]
    yield sm


async def shutdown_pool() -> None:
    """Dispose every cached engine. Call from worker shutdown."""
    loops = list(_engines.keys())
    for loop in loops:
        engine = _engines.pop(loop, None)
        _sessionmakers.pop(loop, None)
        if engine is not None:
            await engine.dispose()


# Per-event-loop engine + sessionmaker caches.
_engines: WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncEngine] = WeakKeyDictionary()
_sessionmakers: WeakKeyDictionary[
    asyncio.AbstractEventLoop, async_sessionmaker[AsyncSession]
] = WeakKeyDictionary()


__all__ = ["scoped_sessionmaker", "shutdown_pool"]
