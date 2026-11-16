"""FastAPI application factory — Phase 12.

Composes:

* ``/api/v1`` routers (ingest, videos, reports, feedback, graph,
  metrics, usage).
* Middleware stack: RequestIdMiddleware → AccessLogMiddleware → CORS.
* Exception handlers from ``aimw.api.errors`` — every error includes
  ``request_id``.
* OpenAPI metadata sourced from ``pyproject``-installed package.

Backwards compatibility: the prior unversioned routes (``/packages``,
``/campaigns``, ``/analysis/run``, ``/campaigns/recompute``,
``/metrics``) remain wired so the Red-Team-era integration tests keep
passing.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, metadata, version
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from aimw.api.errors import install_handlers
from aimw.api.middleware import AccessLogMiddleware, RequestIdMiddleware
from aimw.api.routers import analysis, campaigns, metrics, packages
from aimw.api.v1 import (
    routes_adversarial,
    routes_agents,
    routes_alerts,
    routes_auth,
    routes_biometrics,
    routes_cases,
    routes_check,
    routes_collector,
    routes_export,
    routes_feedback,
    routes_graph,
    routes_ingest,
    routes_investigate,
    routes_metrics,
    routes_reports,
    routes_system,
    routes_usage,
    routes_validation,
    routes_videos,
)
from aimw.core.logging import configure_from_settings
from aimw.db.session import get_sessionmaker


def _app_meta() -> tuple[str, str]:
    """Return ``(title, version)`` sourced from package metadata."""
    try:
        ver = version("aimw")
    except PackageNotFoundError:
        from aimw import __version__

        ver = __version__
    title = "AI Media Watch"
    try:
        md = metadata("aimw")
        # importlib.metadata.PackageMetadata supports __getitem__ across all
        # supported Python versions; use it instead of .get for typing.
        # PackageMetadata supports __getitem__ but stubs don't expose .get;
        # use the indexing form with the explicit key-presence check.
        if "Summary" in md:
            summary_val = md["Summary"]
            if summary_val:
                title = summary_val
    except PackageNotFoundError:
        pass
    return title, ver


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    from aimw.scoring.registry import register

    register()
    try:
        from aimw.api.auth import ensure_default_admin

        await ensure_default_admin()
    except Exception:
        pass
    from aimw.core.config import get_settings
    if get_settings().eager:
        from aimw.collection import control
        control.stop()  # Collection resumes only after an explicit Start click.
    try:
        yield
    finally:
        await routes_collector.shutdown_local_collector()


def _cors_origins() -> list[str]:
    """Return the dev/web origins allowed by CORS.

    Reads ``AIMW_CORS_ORIGINS`` (comma-separated) when present; otherwise
    defaults to common ``web/`` dev origins.
    """
    raw = os.environ.get("AIMW_CORS_ORIGINS", "")
    if raw.strip():
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    configure_from_settings()
    title, version_str = _app_meta()
    app = FastAPI(
        title=title,
        version=version_str,
        description=(
            "Analyst-facing REST API for the AI Media Watch intelligence "
            "system. v1 routes live under ``/api/v1``."
        ),
        lifespan=_lifespan,
    )

    # Middleware order (outermost to innermost): CORS → AccessLog → RequestId
    # Starlette executes middlewares in reverse-add order on the request path,
    # so we add CORS first, then AccessLog, then RequestId, giving:
    # request → RequestId → AccessLog → CORS → route → ...
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_origin_regex=r"^chrome-extension://.*$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # Exception handlers — every error envelope includes request_id.
    install_handlers(app)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": version_str}

    @app.get("/health/live", tags=["system"])
    def health_live() -> dict[str, str]:
        return {"status": "ok", "version": version_str}

    @app.get("/health/ready", tags=["system"])
    async def health_ready() -> JSONResponse:
        from aimw.db.models import EvidencePackageRow as _PkgRow

        checks: dict[str, str] = {}
        status_code = 200
        try:
            sm = get_sessionmaker()
            async with sm() as session:
                await session.execute(
                    text(f"SELECT COUNT(*) FROM {_PkgRow.__tablename__}")
                )
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"unhealthy: {type(exc).__name__}"
            status_code = 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok" if status_code == 200 else "degraded",
                "version": version_str,
                "checks": checks,
            },
        )

    # -----------------------------------------------------------------
    # v1 routers — Phase 12 spec
    # -----------------------------------------------------------------
    api_v1 = "/api/v1"
    app.include_router(routes_ingest.router, prefix=api_v1)
    app.include_router(routes_collector.router, prefix=api_v1)
    app.include_router(routes_videos.router, prefix=api_v1)
    app.include_router(routes_export.router, prefix=api_v1)
    app.include_router(routes_reports.router, prefix=api_v1)
    app.include_router(routes_feedback.router, prefix=api_v1)
    app.include_router(routes_graph.router, prefix=api_v1)
    app.include_router(routes_metrics.router, prefix=api_v1)
    app.include_router(routes_usage.router, prefix=api_v1)
    app.include_router(routes_validation.router, prefix=api_v1)
    app.include_router(routes_check.router, prefix=api_v1)
    app.include_router(routes_cases.router, prefix=api_v1)
    app.include_router(routes_auth.router, prefix=api_v1)
    app.include_router(routes_investigate.router, prefix=api_v1)
    app.include_router(routes_system.router, prefix=api_v1)
    app.include_router(routes_adversarial.router, prefix=api_v1)
    app.include_router(routes_biometrics.router, prefix=api_v1)
    app.include_router(routes_alerts.router, prefix=api_v1)
    app.include_router(routes_agents.router, prefix=api_v1)

    # -----------------------------------------------------------------
    # Backwards-compatible unversioned routes (pre-Phase-12 endpoints).
    # -----------------------------------------------------------------
    app.include_router(packages.router)
    app.include_router(campaigns.router)
    app.include_router(analysis.router)
    app.include_router(metrics.router)

    # -----------------------------------------------------------------
    # PWA — user-facing scam checker (served at /check/)
    # -----------------------------------------------------------------
    _pwa_dir = Path(__file__).resolve().parent.parent / "pwa"
    if _pwa_dir.is_dir():
        from fastapi.responses import FileResponse

        @app.get("/check/share", include_in_schema=False)
        async def pwa_share_target(
            url: str = "", text: str = "", title: str = ""
        ) -> FileResponse:
            return FileResponse(
                _pwa_dir / "index.html",
                media_type="text/html",
            )

        app.mount(
            "/check",
            StaticFiles(directory=str(_pwa_dir), html=True),
            name="pwa",
        )

    return app
