"""Exception handlers for the Phase 12 API.

Every error response is a typed envelope including ``request_id`` so the
client (and downstream log aggregator) can correlate the failure back to
the request log line emitted by :class:`AccessLogMiddleware`.

Handled:

* ``pydantic.ValidationError`` and FastAPI's ``RequestValidationError``
  → 422 with ``code="VALIDATION_ERROR"``.
* ``aimw.reasoning.client.TokenBudgetExhausted`` → 429 with
  ``code="TOKEN_BUDGET_EXHAUSTED"``.
* ``starlette.HTTPException`` → echoed with its detail.
* generic ``Exception`` → 500 with ``code="INTERNAL_ERROR"``; details
  are NOT echoed to the caller, only logged.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from aimw.reasoning.client import TokenBudgetExhausted

_LOG = logging.getLogger("aimw.api.errors")


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid:
        return rid
    new_id = str(uuid.uuid4())
    request.state.request_id = new_id
    return new_id


def _envelope(
    *,
    request: Request,
    error: str,
    code: str,
    detail: Any | None = None,
) -> dict[str, Any]:
    return {
        "error": error,
        "request_id": _request_id(request),
        "code": code,
        "detail": detail,
    }


def install_handlers(app: FastAPI) -> None:
    """Register every Phase 12 exception handler on ``app``."""

    @app.exception_handler(RequestValidationError)
    async def _request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                request=request,
                error="validation error",
                code="VALIDATION_ERROR",
                detail=jsonable_encoder(exc.errors()),
            ),
        )

    @app.exception_handler(ValidationError)
    async def _pydantic_validation(
        request: Request, exc: ValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope(
                request=request,
                error="validation error",
                code="VALIDATION_ERROR",
                detail=jsonable_encoder(exc.errors()),
            ),
        )

    @app.exception_handler(TokenBudgetExhausted)
    async def _token_budget(
        request: Request, exc: TokenBudgetExhausted
    ) -> JSONResponse:
        _LOG.warning(
            "token_budget_exhausted",
            extra={"request_id": _request_id(request), "detail": str(exc)},
        )
        return JSONResponse(
            status_code=429,
            content=_envelope(
                request=request,
                error="token budget exhausted",
                code="TOKEN_BUDGET_EXHAUSTED",
                detail=str(exc),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # Canonical short codes for common statuses, falling back to HTTP_<n>.
        code_by_status = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
            503: "SERVICE_UNAVAILABLE",
        }
        code = code_by_status.get(exc.status_code, f"HTTP_{exc.status_code}")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                request=request,
                error=str(exc.detail) if not isinstance(exc.detail, dict) else "error",
                code=code,
                detail=exc.detail,
            ),
        )

    @app.exception_handler(Exception)
    async def _generic(request: Request, exc: Exception) -> JSONResponse:
        _LOG.exception(
            "unhandled_exception",
            extra={
                "request_id": _request_id(request),
                "exc_type": type(exc).__name__,
            },
        )
        return JSONResponse(
            status_code=500,
            content=_envelope(
                request=request,
                error="internal server error",
                code="INTERNAL_ERROR",
                # Detail intentionally omitted — never echo internal state.
                detail=None,
            ),
        )


__all__ = ["install_handlers"]
