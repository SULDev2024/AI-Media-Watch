"""aimw validation CLI — Phase 15.5.

Commands:
  collect <url> --label <label>   Record a URL for later processing.
  run [--limit N] [--force]       Process pending cases through the pipeline.
  review [--all]                  Show results / failures in the terminal.
  report [--out-dir PATH]         Write validation_report.json/.md, CSV, etc.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from urllib.parse import urlsplit

import typer

validation_app = typer.Typer(help="Real-world validation commands.", no_args_is_help=True)
_LOG = logging.getLogger("aimw.validation.cli")


def _derive_video_id(url: str) -> str:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"vid-{h}"


def _classify_platform(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith("t.me") or host.endswith("telegram.org"):
        return "telegram"
    if host.endswith("youtube.com") or host == "youtu.be":
        return "youtube"
    if urlsplit(url).scheme.lower() == "file":
        return "local"
    return "unknown"


@validation_app.command("collect")
def collect(
    url: str = typer.Argument(..., help="URL of the media item to validate."),
    label: str = typer.Option(..., help="Expected label: benign|gambling|pyramid|scam|uncertain"),
    notes: str | None = typer.Option(None, help="Optional analyst notes."),
) -> None:
    """Register a URL as a validation case for later pipeline processing."""
    from datetime import UTC, datetime

    from aimw.validation.models import ValidationCase, append_case

    allowed = {"benign", "gambling", "pyramid", "scam", "uncertain"}
    if label not in allowed:
        typer.echo(f"[error] label must be one of {sorted(allowed)}", err=True)
        raise typer.Exit(1)

    video_id = _derive_video_id(url)
    source_type = _classify_platform(url)

    async def _upsert() -> None:
        from aimw.db.repositories.videos import VideosRepository
        from aimw.db.session import get_sessionmaker

        repo = VideosRepository(get_sessionmaker())
        await repo.upsert(
            id=video_id,
            platform=source_type,
            url=url,
            collected_at=datetime.now(UTC),
        )

    asyncio.run(_upsert())

    case = ValidationCase(
        source_type=source_type,
        source_url=url,
        video_id=video_id,
        expected_label=label,
        notes=notes,
    )
    append_case(case)
    typer.echo(f"[collect] {case.case_id}")
    typer.echo(f"  platform : {source_type}")
    typer.echo(f"  video_id : {video_id}")
    typer.echo(f"  label    : {label}")


@validation_app.command("run")
def run_cmd(
    limit: int = typer.Option(0, "--limit", help="Max cases to process (0 = all pending)."),
    force: bool = typer.Option(False, "--force", help="Re-run done/error cases."),
) -> None:
    """Run pending validation cases through the exact production pipeline."""
    from datetime import UTC, datetime

    from aimw.scoring.registry import register as _register
    from aimw.validation.models import load_cases, update_case

    _register()

    cases = load_cases()
    pending = [
        c for c in cases
        if c.processing_status == "pending"
        or (force and c.processing_status in ("done", "error"))
    ]
    if limit > 0:
        pending = pending[:limit]
    if not pending:
        typer.echo("[run] No pending cases.")
        return

    typer.echo(f"[run] Processing {len(pending)} case(s)…")

    for case in pending:
        typer.echo(f"  → {case.case_id[:8]} {case.source_url[:70]}")
        case.processing_status = "running"
        update_case(case)
        try:
            report_id: str = asyncio.run(_run_pipeline(case.video_id))
            result = asyncio.run(_load_result(report_id))
            case.processing_status = "done"
            case.processed_at = datetime.now(UTC)
            case.risk_level = str(result["risk_level"])
            case.system_score = float(result["score"])  # type: ignore[arg-type]
            case.action = str(result["action"]) if result["action"] is not None else None
            case.entity_count = result["entity_count"]  # type: ignore[assignment]
            typer.echo(
                f"     done  — {case.risk_level} (score={case.system_score or 0:.3f})"
            )
        except Exception as exc:
            case.processing_status = "error"
            case.error_message = f"{type(exc).__name__}: {exc}"
            typer.echo(f"     error — {case.error_message}", err=True)
        update_case(case)


async def _run_pipeline(video_id: str) -> str:
    from aimw.workers.pipeline import run_pipeline

    return await run_pipeline(video_id)


async def _load_result(report_id: str) -> dict[str, object]:
    from aimw.db.models import EvidencePackageRow
    from aimw.db.session import get_sessionmaker

    sm = get_sessionmaker()
    try:
        async with sm() as session:
            row = await session.get(EvidencePackageRow, report_id)
    except Exception:
        row = None

    if row is None:
        return {"risk_level": "UNKNOWN", "score": 0.0, "action": None, "entity_count": {}}

    from aimw.core.schema import from_json

    try:
        pkg = from_json(row.package_json)
        ec = pkg.entities
        entity_count: dict[str, int] = {
            "telegram_handles": len(ec.telegram_handles),
            "crypto_wallets": len(ec.crypto_wallets),
            "phone_numbers": len(ec.phone_numbers),
            "websites": len(ec.websites),
        }
    except Exception:
        entity_count = {}

    return {
        "risk_level": str(row.risk_level or "UNKNOWN"),
        "score": float(row.score or 0.0),
        "action": str(row.action) if row.action is not None else None,
        "entity_count": entity_count,
    }


@validation_app.command("review")
def review(
    show_all: bool = typer.Option(False, "--all", help="Show all done cases, not just failures."),
) -> None:
    """Print validation results and failure list to the terminal."""
    from aimw.validation.evaluator import case_verdict, evaluate
    from aimw.validation.models import load_cases

    cases = load_cases()
    if not cases:
        typer.echo("No validation cases found. Run `aimw validation collect` first.")
        return

    result = evaluate(cases)
    b = result.binary

    typer.echo(f"Validation cases: {result.n_total} total")
    typer.echo(
        f"  Evaluated: {result.n_evaluated}  "
        f"Pending: {result.n_pending}  "
        f"Error: {result.n_error}  "
        f"Skipped: {result.n_skipped}"
    )
    typer.echo("")

    if result.n_evaluated > 0:
        typer.echo("Binary P/R/F1  (HIGH/CRITICAL = positive):")
        typer.echo(
            f"  Precision={b.precision:.3f}  Recall={b.recall:.3f}  F1={b.f1:.3f}"
        )
        typer.echo(f"  TP={b.tp}  FP={b.fp}  FN={b.fn}  TN={b.tn}")
        typer.echo("")

    done = [c for c in cases if c.processing_status == "done"]
    to_show = done if show_all else [c for c in done if case_verdict(c) in ("FP", "FN")]

    if to_show:
        header = "All done cases:" if show_all else "Failures (FP / FN):"
        typer.echo(header)
        for c in to_show:
            v = case_verdict(c)
            score_str = f"{c.system_score:.3f}" if c.system_score is not None else "—"
            typer.echo(
                f"  [{v}] {c.case_id[:8]}  expected={c.expected_label}  "
                f"got={c.risk_level or '—'}  score={score_str}"
            )
            typer.echo(f"       {c.source_url[:90]}")
    elif done:
        typer.echo("No failures — all done cases classified correctly.")


@validation_app.command("report")
def report_cmd(
    out_dir: str | None = typer.Option(
        None, "--out-dir", help="Output directory (default: data/validation/)."
    ),
) -> None:
    """Generate validation_report.json/.md, failures.csv, entity and campaign reports."""
    from aimw.validation.reporter import generate_all

    _out = Path(out_dir) if out_dir else None
    typer.echo("[report] Generating…")
    paths = generate_all(_out)
    for name, path in paths.items():
        typer.echo(f"  {name}  →  {path}")
