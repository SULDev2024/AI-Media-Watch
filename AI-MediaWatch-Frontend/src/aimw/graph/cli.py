"""``aimw graph`` subcommand -- Phase 11.

Two operations:

* ``aimw graph recompute`` -- build the corpus graph, find campaigns,
  promote network evidence back into participating packages, then re-render
  and persist their reports.
* ``aimw graph export <out.json>`` -- write the Cytoscape.js JSON the Phase 14
  frontend consumes.

Both are I/O thin wrappers around the pure functions in ``builder``,
``campaigns``, ``feedback``, and ``export``.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import typer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

graph_app = typer.Typer(help="Intelligence graph subsystem.")

# Defaults pulled out so ruff B008 doesn't fire on the typer.Argument calls.
_OUT_ARG = typer.Argument(..., help="Output JSON path.")
_MIN_VIDEOS_OPT = typer.Option(3, help="Minimum videos for a campaign.")


def _sessionmaker() -> tuple[async_sessionmaker[AsyncSession], AsyncEngine]:
    """Build a sessionmaker for the configured SQLite database."""
    from aimw.db.session import create_engine, create_sessionmaker

    engine = create_engine()
    return create_sessionmaker(engine), engine


@graph_app.command("recompute")
def recompute(
    min_videos: int = _MIN_VIDEOS_OPT,
) -> None:
    """Build the graph, detect campaigns, promote network evidence."""

    async def _go() -> int:
        from aimw.graph import builder, campaigns, feedback

        sm, engine = _sessionmaker()
        try:
            graph = await builder.build_from_db(sm)
            found = campaigns.find(graph, min_videos=min_videos)
            updated = await feedback.promote(sm, found)
            return updated
        finally:
            await engine.dispose()

    updated = asyncio.run(_go())
    typer.echo(f"updated_packages={updated}")


@graph_app.command("export")
def export(
    out: Path = _OUT_ARG,
) -> None:
    """Write the Cytoscape.js JSON for the frontend."""

    async def _go() -> dict[str, Any]:
        from aimw.graph import builder
        from aimw.graph.export import to_cytoscape

        sm, engine = _sessionmaker()
        try:
            graph = await builder.build_from_db(sm)
            payload: dict[str, Any] = to_cytoscape(graph)
            return payload
        finally:
            await engine.dispose()

    payload = asyncio.run(_go())
    out.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    typer.echo(f"wrote {out}")
