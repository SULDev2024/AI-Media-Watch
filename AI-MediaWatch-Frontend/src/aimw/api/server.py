"""Programmatic Uvicorn entry point.

Run with ``python -m aimw.api.server``. Uvicorn is started with
``log_config=None`` so it installs *no* logging configuration of its own;
instead the AIMW structured-logging pipeline is configured first, and Uvicorn's
``uvicorn``, ``uvicorn.error``, and ``uvicorn.access`` loggers (which default to
``propagate=True`` with no handlers) bubble up to the single structlog handler.

This is the deliberate alternative to letting the ``uvicorn`` CLI apply its
built-in ``LOGGING_CONFIG`` (which sets ``propagate=False`` and its own
handlers, bypassing our pipeline).
"""

from __future__ import annotations

import uvicorn

from aimw.core.config import get_settings
from aimw.core.logging import configure_from_settings, get_logger


def main(*, reload: bool = False) -> None:
    """Configure logging, then run the API under Uvicorn with our pipeline."""
    # Load .env into os.environ so direct os.environ lookups (AIMW_EAGER,
    # AIMW_USE_REASONING_STUB, ...) see configured values. Existing env vars are
    # NOT overridden, so an explicit command-line var still wins.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass
    # Establish the structured-logging pipeline before Uvicorn emits anything.
    configure_from_settings()
    settings = get_settings()
    get_logger("aimw.api.server").info(
        "starting_api", host=settings.api_host, port=settings.api_port, reload=reload
    )

    uvicorn.run(
        "aimw.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        reload=reload,
        # Critical: do not let Uvicorn install its own logging config.
        log_config=None,
    )


if __name__ == "__main__":
    main(reload=False)
