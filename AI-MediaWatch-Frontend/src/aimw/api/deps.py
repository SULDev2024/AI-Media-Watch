"""FastAPI dependency injectors for the Phase 12 v1 API.

The dependency-injector layer is the single bridge between routes and
the services they compose. Routes import only the typed deps below;
they never reach into ``aimw.db.session`` or repositories directly.

Per the Phase 12 spec, this file is at ``src/aimw/api/deps.py``.
"""
from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aimw.api.v1.schemas import User
from aimw.db.repositories.feedback import FeedbackRepository
from aimw.db.repositories.packages import PackagesRepository
from aimw.db.repositories.usage import UsageRepository
from aimw.db.repositories.videos import VideosRepository
from aimw.db.session import get_sessionmaker

__all__ = [
    "FeedbackRepoDep",
    "PackagesRepoDep",
    "RequestIdDep",
    "RequireAnalyst",
    "SessionDep",
    "SessionmakerDep",
    "UsageRepoDep",
    "VideosRepoDep",
    "get_current_user",
    "get_feedback_repo",
    "get_packages_repo",
    "get_request_id",
    "get_session",
    "get_sessionmaker_dep",
    "get_usage_repo",
    "get_videos_repo",
]


# ---------------------------------------------------------------------------
# Session / repositories
# ---------------------------------------------------------------------------


def get_sessionmaker_dep() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide async sessionmaker."""
    return get_sessionmaker()


SessionmakerDep = Annotated[
    async_sessionmaker[AsyncSession], Depends(get_sessionmaker_dep)
]


async def get_session(
    sm: SessionmakerDep,
) -> AsyncSession:
    """Yield a transactional session for the duration of the request."""
    # Used as a regular dep — FastAPI handles teardown via async context.
    async with sm() as session:
        return session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_packages_repo(sm: SessionmakerDep) -> PackagesRepository:
    return PackagesRepository(sm)


def get_videos_repo(sm: SessionmakerDep) -> VideosRepository:
    return VideosRepository(sm)


def get_feedback_repo(sm: SessionmakerDep) -> FeedbackRepository:
    return FeedbackRepository(sm)


def get_usage_repo(sm: SessionmakerDep) -> UsageRepository:
    return UsageRepository(sm)


PackagesRepoDep = Annotated[PackagesRepository, Depends(get_packages_repo)]
VideosRepoDep = Annotated[VideosRepository, Depends(get_videos_repo)]
FeedbackRepoDep = Annotated[FeedbackRepository, Depends(get_feedback_repo)]
UsageRepoDep = Annotated[UsageRepository, Depends(get_usage_repo)]


# ---------------------------------------------------------------------------
# Request id
# ---------------------------------------------------------------------------


def get_request_id(request: Request) -> str:
    """Return the per-request id placed on ``request.state`` by middleware.

    Routes use this to embed the id in every response per Phase 12 spec.
    Falls back to generating a fresh id if middleware did not set one
    (e.g. when a route is exercised directly without going through the
    ASGI middleware stack).
    """
    rid: str | None = getattr(request.state, "request_id", None)
    if not rid:
        rid = str(uuid.uuid4())
        request.state.request_id = rid
    return rid


RequestIdDep = Annotated[str, Depends(get_request_id)]


# ---------------------------------------------------------------------------
# Auth — RequireAnalyst
# ---------------------------------------------------------------------------

_DEV_USER = User(id="dev", roles=["analyst"])


def _jwt_stub_user(_token: str) -> User:
    """Production JWT path — stubbed for Phase 12.

    Real authentication is deferred to Phase 18. This stub returns the
    same dev user so the contract is identical regardless of mode; the
    body of this function is the only place the real JWT decoder will
    eventually live.
    """
    return _DEV_USER


async def get_current_user(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User:
    """Resolve the calling principal.

    Behaviour:

    * ``AIMW_API_MODE=prod`` and a Bearer header present → JWT stub path.
    * Otherwise → dev no-op user.

    Phase 12 wires this as ``RequireAnalyst``. The dev path is always
    accepted with role ``analyst`` so existing tests do not require an
    auth header.
    """
    mode = os.environ.get("AIMW_API_MODE", "dev").lower()
    if mode == "prod" and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        return _jwt_stub_user(token)
    return _DEV_USER


RequireAnalyst = Annotated[User, Depends(get_current_user)]
