"""Structured logging via ``structlog`` with a stdlib-logging bridge.

A single logging pipeline is established: ``structlog`` events *and* records
from the standard library (FastAPI, SQLAlchemy, third-party ML libraries) are
both routed through one :class:`structlog.stdlib.ProcessorFormatter` on one root
handler. Output is human-readable in ``dev`` and JSON elsewhere.
``contextvars`` are merged into every event, so a request- or job-correlation id
bound with :func:`bind_context` appears on all downstream logs automatically.

Two runtime hosts would otherwise bypass this pipeline; both are reconciled so
the single-pipeline guarantee actually holds:

* **Uvicorn** is started via :mod:`aimw.api.server` with ``log_config=None``, so
  it installs no logging config and its ``uvicorn`` / ``uvicorn.error`` /
  ``uvicorn.access`` loggers propagate to this root handler.
* **Celery** sets ``worker_hijack_root_logger = False`` and connects the
  ``setup_logging`` signal to :func:`configure_from_settings` (see
  :mod:`aimw.workers.celery_app`), so Celery and task loggers propagate here too.

Because these library loggers carry ``propagate=True`` and no handlers of their
own, configuring the root handler is sufficient — no per-logger handler wiring
is required.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog
from structlog.typing import Processor

_configured = False


def _coerce_level(level: int | str) -> int:
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(level.upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def configure_logging(level: int | str = logging.INFO, *, json_logs: bool = False) -> None:
    """Configure structlog + the stdlib logging bridge exactly once."""
    global _configured
    if _configured:
        return

    int_level = _coerce_level(level)

    # Processors shared by structlog-native events and foreign stdlib records.
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    # structlog hands its events to the stdlib formatter rather than rendering
    # them itself, so both streams converge on one formatter.
    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[*shared, structlog.processors.format_exc_info],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(int_level)

    # Let library loggers propagate to the root handler instead of their own.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery", "sqlalchemy.engine"):
        lib_logger = logging.getLogger(noisy)
        lib_logger.handlers.clear()
        lib_logger.propagate = True

    _configured = True


def configure_from_settings() -> None:
    """Configure logging from application settings (env + log level)."""
    from aimw.core.config import get_settings

    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger, configuring logging on first use."""
    if not _configured:
        configure_from_settings()
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def bind_context(**values: Any) -> None:
    """Bind correlation values (e.g. ``request_id``) to the logging context."""
    structlog.contextvars.bind_contextvars(**values)


def clear_context() -> None:
    """Clear all bound correlation context for the current execution."""
    structlog.contextvars.clear_contextvars()
