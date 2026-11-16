"""Worker CLI — ``aimw queue drain --once``.

Composes Phase 13 services for manual / CI end-to-end runs without a
running Celery broker. The implementation reuses the same
``run_async`` bridge as the broker path so the eager dev workflow is
byte-identical.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import typer
from sqlalchemy import select

from aimw.db.models import IngestQueueRow
from aimw.db.session import get_sessionmaker, writer_lock
from aimw.workers.runner import run_async

_LOG = logging.getLogger("aimw.workers.cli")

queue_app = typer.Typer(help="Worker queue operations.", no_args_is_help=True)


async def _list_pending(
    platform: str | None = None,
    limit: int | None = None,
) -> list[IngestQueueRow]:
    sm = get_sessionmaker()
    async with sm() as session:
        stmt = (
            select(IngestQueueRow)
            .where(IngestQueueRow.status == "pending")
            .order_by(IngestQueueRow.created_at.asc())
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if platform:
            platform_norm = platform.lower()
            rows = [
                row
                for row in rows
                if str((row.payload or {}).get("platform", "")).lower() == platform_norm
            ]
        if limit is not None:
            rows = rows[:limit]
        for row in rows:
            session.expunge(row)
    return rows


async def _mark(row_id: int, status: str, error: str | None = None) -> None:
    sm = get_sessionmaker()
    now = dt.datetime.now(dt.UTC)
    async with writer_lock(), sm() as session, session.begin():
        row = await session.get(IngestQueueRow, row_id)
        if row is None:
            return
        row.status = status
        # Merge error into the JSON payload so the dashboard can show it.
        payload: dict[str, Any] = dict(row.payload or {})
        if error:
            payload["error"] = error
        payload["finished_at"] = now.isoformat()
        row.payload = payload


@queue_app.command("drain")
def drain(
    once: bool = typer.Option(
        False, "--once", help="Drain pending rows exactly one time, then exit."
    ),
    platform: str | None = typer.Option(
        None, "--platform", help="Only drain rows whose payload platform matches."
    ),
    limit: int | None = typer.Option(
        None, "--limit", min=1, help="Maximum number of pending rows to drain."
    ),
) -> None:
    """Drain pending ``ingest_queue`` rows through the process_video pipeline."""
    if not once:
        typer.echo("only --once is currently supported")
        raise typer.Exit(code=1)

    from aimw.workers.pipeline import run_pipeline  # local import — pulls heavy deps

    rows = run_async(_list_pending(platform=platform, limit=limit))
    if not rows:
        typer.echo("no pending ingest_queue rows")
        return

    n_done = 0
    n_failed = 0
    for row in rows:
        video_id = (row.payload or {}).get("video_id")
        if not isinstance(video_id, str):
            run_async(
                _mark(row.id, status="failed", error="payload missing video_id")
            )
            n_failed += 1
            continue
        try:
            report_id = run_async(run_pipeline(video_id))
            run_async(_mark(row.id, status="done"))
            typer.echo(f"row={row.id} video_id={video_id} report_id={report_id} status=done")
            n_done += 1
        except Exception as exc:
            run_async(_mark(row.id, status="failed", error=f"{type(exc).__name__}: {exc}"))
            typer.echo(
                f"row={row.id} video_id={video_id} status=failed error={type(exc).__name__}"
            )
            n_failed += 1

    typer.echo(f"summary: pending=0 done={n_done} failed={n_failed} total={len(rows)}")


__all__ = ["queue_app"]
