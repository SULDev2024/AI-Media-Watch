"""ADR-0002 worker async/sync bridge.

Single source of truth for the async/sync seam inside the Celery worker
process (and the in-process eager path used by the CLI / tests).

Contract:

* **One event loop per worker process** — created on the first call to
  :func:`run_async` (or via the ``worker_process_init`` signal hook) and
  owned by a long-lived background thread.  The loop never closes until
  :func:`shutdown_loop` is called.

* **Tasks never call ``asyncio.run``** — every coroutine the worker
  needs to await is funnelled through :func:`run_async`, which submits
  it to the long-lived loop via
  :func:`asyncio.run_coroutine_threadsafe` and blocks on the result.

* **Eager mode uses the same bridge** — when ``AIMW_EAGER=1`` and a
  task is invoked in-process, the call still routes through
  :func:`run_async` so behaviour is byte-identical to the broker path.

This module imports only the standard library so it cannot create
cyclic dependencies with the rest of the worker stack.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

_LOG = logging.getLogger("aimw.workers.runner")

_T = TypeVar("_T")

# Process-wide singletons. Module-level state is correct here because
# a Celery worker is one OS process; in tests we expose :func:`shutdown_loop`
# to dispose the loop between fixtures when needed.
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _runner(loop: asyncio.AbstractEventLoop, started: threading.Event) -> None:
    """Background thread body — owns the event loop for the worker's lifetime."""
    asyncio.set_event_loop(loop)
    started.set()
    try:
        loop.run_forever()
    finally:
        try:
            # Cancel any leftover tasks before closing the loop.
            pending = asyncio.all_tasks(loop=loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        finally:
            loop.close()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Start the per-process loop if it does not yet exist."""
    global _loop, _thread
    with _lock:
        if _loop is not None and _thread is not None and _thread.is_alive():
            return _loop
        loop = asyncio.new_event_loop()
        started = threading.Event()
        thread = threading.Thread(
            target=_runner,
            args=(loop, started),
            name="aimw-worker-loop",
            daemon=True,
        )
        thread.start()
        if not started.wait(timeout=5.0):
            raise RuntimeError(
                "worker event loop failed to start within 5 seconds"
            )
        _loop = loop
        _thread = thread
        _LOG.info("worker event loop started", extra={"thread_name": thread.name})
        return loop


def init_worker_loop() -> None:
    """Eagerly create the worker loop.

    Connected to Celery's ``worker_process_init`` signal in
    :mod:`aimw.workers.celery_app` so each worker process starts with
    its loop already running.  Calling this from non-Celery contexts
    (e.g. the eager CLI path) is also valid and idempotent.
    """
    _ensure_loop()


def run_async(coro: Coroutine[Any, Any, _T], *, timeout: float | None = None) -> _T:
    """Submit *coro* to the worker's long-lived loop and block on the result.

    The single allowed sync→async bridge per ADR-0002.  Code that needs
    to await a coroutine inside a Celery task or the CLI eager path
    must go through this function — never ``asyncio.run``.

    Parameters
    ----------
    coro:
        The coroutine to execute on the worker loop.
    timeout:
        Optional wait timeout in seconds.  ``None`` means wait
        indefinitely.  A ``TimeoutError`` from the underlying
        ``concurrent.futures.Future`` is re-raised as
        :class:`asyncio.TimeoutError` so callers see a consistent type.

    Returns
    -------
    The value the coroutine resolved to.

    Raises
    ------
    Anything the coroutine raised — exceptions surface unchanged so the
    Celery task layer can map them to retry / fail-closed semantics.
    """
    loop = _ensure_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return fut.result(timeout=timeout)
    except TimeoutError as exc:
        fut.cancel()
        raise TimeoutError(str(exc)) from exc


def shutdown_loop() -> None:
    """Stop the worker loop and join its thread.

    Wired to Celery's ``worker_process_shutdown`` signal and exposed for
    tests.  Idempotent.
    """
    global _loop, _thread
    with _lock:
        loop = _loop
        thread = _thread
        _loop = None
        _thread = None
    if loop is not None and thread is not None and thread.is_alive():
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5.0)
        _LOG.info("worker event loop stopped")


def loop_is_running() -> bool:
    """Test helper — True if the worker loop is alive in this process."""
    return _loop is not None and _thread is not None and _thread.is_alive()


__all__ = [
    "init_worker_loop",
    "loop_is_running",
    "run_async",
    "shutdown_loop",
]
