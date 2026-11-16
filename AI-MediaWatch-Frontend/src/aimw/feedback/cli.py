"""``aimw feedback`` CLI subcommands — §14 calibration and audit inspection."""

from __future__ import annotations

from typing import Annotated

import typer

feedback_app = typer.Typer(
    help="Analyst feedback loop: calibration, watchlist, and audit log.",
    no_args_is_help=True,
)

calibration_app = typer.Typer(help="Band-threshold calibration commands.", no_args_is_help=True)
feedback_app.add_typer(calibration_app, name="calibration")


# ---------------------------------------------------------------------------
# calibration subcommands
# ---------------------------------------------------------------------------


@calibration_app.command("nudge")
def calibration_nudge(
    band: Annotated[str, typer.Option("--band", help="Band to adjust: low/medium/high/critical")],
    delta: Annotated[float, typer.Option("--delta", help="Signed threshold delta (e.g. +0.002)")],
    dry_run: Annotated[bool, typer.Option("--dry-run/--no-dry-run")] = False,
) -> None:
    """Adjust a band threshold within the per-session cap (±0.03)."""
    from aimw.feedback.calibration import BandGapViolation, SessionCapExceeded, nudge

    try:
        after = nudge(band, delta, dry_run=dry_run, user_id="cli")
    except (SessionCapExceeded, BandGapViolation, ValueError) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc

    prefix = "[dry-run] " if dry_run else ""
    typer.echo(f"{prefix}thresholds after nudge: {after}")


@calibration_app.command("reset")
def calibration_reset() -> None:
    """Restore §6.3 default thresholds and clear per-session deltas."""
    from aimw.feedback.calibration import DEFAULTS, reset

    reset(user_id="cli")
    typer.echo(f"thresholds reset to defaults: {DEFAULTS}")


@calibration_app.command("show")
def calibration_show() -> None:
    """Print the current thresholds and per-session deltas."""
    from aimw.feedback.calibration import load_thresholds, session_deltas

    typer.echo(f"current thresholds: {load_thresholds()}")
    typer.echo(f"session deltas:     {session_deltas()}")


# ---------------------------------------------------------------------------
# audit log
# ---------------------------------------------------------------------------


@feedback_app.command("list-audit")
def list_audit(
    tail: Annotated[int, typer.Option("--tail", "-n", help="Show last N entries (0 = all)")] = 20,
) -> None:
    """Print recent entries from the append-only feedback audit log."""
    import json

    from aimw.feedback.audit import read_all

    entries = read_all()
    shown = entries if tail == 0 else entries[-tail:]
    if not shown:
        typer.echo("(no audit entries yet)")
        return
    for entry in shown:
        typer.echo(json.dumps(entry, ensure_ascii=False))
