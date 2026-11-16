"""FastAPI dependency injectors for the Phase 12 analyst API.

Three concerns are isolated here:

* **Database access** — yields the process-wide ``async_sessionmaker`` so
  routers never touch the session factory directly. Tests can override the
  dependency to inject a test-scoped sessionmaker.

* **Pagination** — ``PageParams`` captures ``?limit=`` and ``?offset=`` query
  parameters with validated ranges. Injected via ``Annotated`` so the OpenAPI
  schema is generated automatically.

* **Authentication stub** — ``auth_guard`` reads ``AIMW_API_KEY`` from
  settings. When the setting is absent or empty, the guard is a no-op (dev /
  test). When set, every analyst endpoint requires a matching ``X-API-Key``
  header. The guard is wired as a FastAPI dependency, not middleware, so it
  appears in the OpenAPI security scheme without a separate security definition.
"""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aimw.core.config import get_settings
from aimw.db.session import get_sessionmaker


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return get_sessionmaker()


SessionmakerDep = Annotated[async_sessionmaker[AsyncSession], Depends(_get_sessionmaker)]


async def auth_guard(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    """X-API-Key enforcement with a constant-time secret comparison.

    Disabled when ``AIMW_API_KEY`` is unset or empty.  When enabled,
    every analyst endpoint requires a matching ``X-API-Key`` header.

    The comparison uses :func:`secrets.compare_digest` so it does not
    leak the matched-prefix length via timing — addressing C4's
    constant-time-comparison requirement.  A missing header is treated
    as an empty string for the comparison so the timing of "missing
    header" and "wrong header" are indistinguishable to a caller.
    """
    configured = get_settings().api_key
    if configured is None:
        return
    secret = configured.get_secret_value()
    if not secret:
        return
    # secrets.compare_digest requires non-None; coerce a missing header to "".
    supplied = x_api_key if x_api_key is not None else ""
    # Normalise to bytes — compare_digest's length-comparison branch is
    # type-uniform on bytes, avoiding a CPython str-vs-bytes fast path.
    if not secrets.compare_digest(
        supplied.encode("utf-8"), secret.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401, detail="Invalid or missing X-API-Key header"
        )


AuthDep = Annotated[None, Depends(auth_guard)]


class PageParams:
    """Pagination query parameters shared across list endpoints."""

    def __init__(
        self,
        limit: int = Query(20, ge=1, le=100, description="Maximum items per page"),
        offset: int = Query(0, ge=0, description="Items to skip before the page"),
    ) -> None:
        self.limit = limit
        self.offset = offset


PageDep = Annotated[PageParams, Depends(PageParams)]
