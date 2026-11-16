"""ASGI middleware for the Phase 12 API.

Two middlewares are installed in this order on the app:

1. ``RequestIdMiddleware`` — generates or accepts an ``X-Request-Id`` for
   every request, attaches it to ``request.state.request_id``, and binds
   it into the structlog context so every log line emitted while
   handling the request carries ``request_id``.

2. ``AccessLogMiddleware`` — logs ``method``, ``path``, ``status``,
   ``duration_ms``, and the bound ``request_id`` after every request.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_LOG = logging.getLogger("aimw.api.access")
_STRUCT = structlog.get_logger("aimw.api")

_HEADER = "X-Request-Id"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generate / accept ``X-Request-Id`` and bind it to structlog."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = request.headers.get(_HEADER) or str(uuid.uuid4())
        request.state.request_id = rid

        # Bind into structlog's contextvar dict so every log emitted
        # inside route handlers carries request_id automatically.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        # Echo the id back so clients can correlate downstream logs.
        response.headers[_HEADER] = rid
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Emit a structured access log per request.

    Records ``method``, ``path``, ``status``, ``duration_ms``, and
    ``request_id``. Errors are still logged with status from the
    response (or 500 on uncaught exception).
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        status: int = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000.0, 2)
            rid: str = getattr(request.state, "request_id", "") or ""
            payload = {
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "duration_ms": duration_ms,
                "request_id": rid,
            }
            # Emit via both the structlog binding (carries ``request_id``
            # in contextvars) and the stdlib logger so a vanilla log
            # consumer also sees the line per spec.
            _STRUCT.info("access", **payload)
            _LOG.info("access", extra=payload)


__all__ = ["AccessLogMiddleware", "RequestIdMiddleware"]
