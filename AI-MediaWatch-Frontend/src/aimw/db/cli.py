"""Database management CLI (``aimw db ...``)."""

from __future__ import annotations

from pathlib import Path

import typer

from aimw.core.config import get_settings
from aimw.db import migrate

db_app = typer.Typer(help="Database management commands.", no_args_is_help=True)


@db_app.command()
def upgrade(revision: str = typer.Argument("head")) -> None:
    """Apply migrations up to a revision (default: head)."""
    migrate.upgrade(revision)
    typer.echo(f"upgraded to {revision}")


@db_app.command()
def downgrade(revision: str = typer.Argument("-1")) -> None:
    """Revert migrations down by/to a revision (default: -1)."""
    migrate.downgrade(revision)
    typer.echo(f"downgraded to {revision}")


@db_app.command()
def init() -> None:
    """Create the data directory and upgrade to head."""
    settings = get_settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    migrate.upgrade("head")
    typer.echo(f"initialized database at {settings.resolved_sqlite_path}")


@db_app.command()
def reset(
    yes_i_mean_it: bool = typer.Option(
        False, "--yes-i-mean-it", help="Required: confirm destructive reset."
    ),
) -> None:
    """Delete the SQLite database file(s) and re-initialize."""
    if not yes_i_mean_it:
        typer.echo("refusing to reset without --yes-i-mean-it")
        raise typer.Exit(code=1)
    settings = get_settings()
    base = settings.resolved_sqlite_path
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(base) + suffix)
        if candidate.exists():
            candidate.unlink()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    migrate.upgrade("head")
    typer.echo(f"reset database at {base}")
