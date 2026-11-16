"""CLI for manual package rescoring (Phase 8).

``aimw score package <json_file>`` reads a serialized EvidencePackage from a
JSON file (or stdin if ``-`` is given), scores it, and prints the full
ScoreBreakdown as JSON.

The scoring module is pure (no DB access); loading from the database is the
responsibility of the caller (e.g. ``aimw db export <report_id>`` piped here).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

score_app = typer.Typer(
    help="Manual rescoring of serialized evidence packages (Phase 8).",
    no_args_is_help=True,
)


@score_app.command("package")
def score_package(
    source: Annotated[
        str,
        typer.Argument(
            help="Path to a package JSON file, or '-' to read from stdin.",
            show_default=False,
        ),
    ],
    pretty: Annotated[
        bool,
        typer.Option("--pretty/--compact", help="Pretty-print the breakdown JSON."),
    ] = True,
) -> None:
    """Re-score an EvidencePackage and print the ScoreBreakdown.

    The input must be a JSON file produced by ``aimw.core.schema.serialization.to_json``.
    """
    from aimw.core.schema.serialization import from_json
    from aimw.scoring.engine import score as _score

    if source == "-":
        raw = sys.stdin.read()
    else:
        path = Path(source)
        if not path.exists():
            typer.echo(f"Error: file not found: {path}", err=True)
            raise typer.Exit(code=1)
        raw = path.read_text(encoding="utf-8")

    try:
        package = from_json(raw)
    except Exception as exc:
        typer.echo(f"Error: could not parse package JSON: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    breakdown = _score(package)
    indent = 2 if pretty else None
    typer.echo(json.dumps(json.loads(breakdown.model_dump_json()), indent=indent))
