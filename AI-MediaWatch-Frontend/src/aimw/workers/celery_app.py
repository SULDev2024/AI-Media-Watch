"""Celery application — Phase 13 (ADR-0002 compliant).

* One event loop per worker process, owned by :mod:`aimw.workers.runner`.
* Tasks NEVER call ``asyncio.run`` — they route through ``run_async``.
* Eager mode (``AIMW_EAGER=1``) shares the same bridge so behaviour
  matches the broker path.
* Beat schedule re-runs ``recompute_campaigns`` every 600 seconds per
  the §15 spec.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from celery import Celery
from celery.signals import (
    setup_logging,
    worker_process_init,
    worker_process_shutdown,
)

from aimw.core.config import get_settings
from aimw.workers.beat import build_schedule

_LOG = logging.getLogger("aimw.workers.celery_app")

settings = get_settings()

celery_app = Celery(
    "aimw",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

_EAGER = os.environ.get("AIMW_EAGER") == "1"

celery_app.conf.update(
    # Security: accept and produce JSON only — never pickle.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Reliability bounds.
    task_time_limit=900,  # 15 min hard kill
    task_soft_time_limit=840,  # SoftTimeLimitExceeded after 14 min
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Time.
    timezone="UTC",
    enable_utc=True,
    # Logging hand-off (see _configure_celery_logging).
    worker_hijack_root_logger=False,
    # Beat schedule (Phase 13 §15).
    beat_schedule=build_schedule(),
    # Eager mode (AIMW_EAGER=1) — runs tasks in-process while still
    # routing through aimw.workers.runner.run_async.
    task_always_eager=_EAGER,
    task_eager_propagates=_EAGER,
)


def _configure_celery_logging(**_kwargs: Any) -> None:
    """Route Celery's logging through the AIMW structlog pipeline."""
    from aimw.core.logging import configure_from_settings

    configure_from_settings()


setup_logging.connect(_configure_celery_logging, weak=False)


@worker_process_init.connect  # type: ignore[misc, untyped-decorator]
def _start_worker_loop(**_kwargs: Any) -> None:
    """Eagerly start the per-process event loop on worker boot.

    Calling :func:`init_worker_loop` here means the first task does
    not pay the lazy-start cost and all tasks share the single loop
    per ADR-0002.
    """
    from aimw.workers.runner import init_worker_loop

    init_worker_loop()
    _LOG.info("worker_loop_initialised")


@worker_process_shutdown.connect  # type: ignore[misc, untyped-decorator]
def _stop_worker_loop(**_kwargs: Any) -> None:
    """Tear down the per-process event loop on worker shutdown."""
    from aimw.workers.engine_pool import shutdown_pool
    from aimw.workers.runner import run_async, shutdown_loop

    try:
        # The engine pool's shutdown is async; run it via the bridge
        # while the loop is still alive.
        run_async(shutdown_pool(), timeout=5.0)
    except Exception:
        _LOG.warning("engine pool shutdown failed", exc_info=True)
    shutdown_loop()
    _LOG.info("worker_loop_stopped")


# ---------------------------------------------------------------------------
# Legacy module-level task imports
# ---------------------------------------------------------------------------
#
# Importing ``aimw.workers.tasks`` here ensures the tasks are registered
# on the Celery app at import time, which Celery's beat scheduler relies
# on when started with ``-A aimw.workers.celery_app``.


def _register_tasks() -> None:
    """Trigger task registration by importing the tasks module."""
    import aimw.workers.tasks  # noqa: F401 — side effect: registers tasks


_register_tasks()


# Legacy ping kept for health-check compatibility.
@celery_app.task(name="aimw.ping")  # type: ignore[untyped-decorator]
def ping() -> str:
    """Health-check task; returns ``"pong"``."""
    return "pong"


__all__ = ["celery_app", "ping"]
