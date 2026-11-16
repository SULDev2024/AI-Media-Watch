"""Extraction CLI command: ``aimw extract ocr <video_id>``.

Reads the videos row (the only DB contract Phase 6 is allowed to touch),
extracts OCR for the media at ``raw_path``, and prints a per-frame block
count summary. Owns its own event loop with ``asyncio.run`` — this is the
one-shot CLI pattern, not the per-Celery-task pattern ADR-0002 forbids.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from aimw.core.logging import configure_from_settings, get_logger
from aimw.extraction.ocr.engine import (
    FrameSamplingError,
    OcrError,
    SourceMediaMissingError,
    get_extractor,
)
from aimw.extraction.ocr.paddle import OcrEngineUnavailable


def register(extract_app: typer.Typer) -> None:
    """Register the ``ocr`` subcommand on the parent ``extract`` Typer app."""

    @extract_app.command("ocr")
    def ocr(
        video_id: Annotated[
            str, typer.Argument(help="The 16-hex-char video id to extract OCR for")
        ],
    ) -> None:
        """Extract OCR text blocks from a previously collected video."""
        asyncio.run(_extract(video_id))


async def _extract(video_id: str) -> None:
    configure_from_settings()
    log = get_logger("aimw.extraction.ocr.cli")

    # Lazy: keep CLI startup cheap.
    from aimw.db.repositories.videos import VideosRepository
    from aimw.db.session import get_sessionmaker

    repo = VideosRepository(get_sessionmaker())
    video = await repo.get(video_id)
    if video is None:
        typer.echo(f"video {video_id} not found", err=True)
        raise typer.Exit(2)
    if not video.raw_path:
        typer.echo(f"video {video_id} has no raw_path", err=True)
        raise typer.Exit(2)

    try:
        extractor = get_extractor()
    except OcrEngineUnavailable as exc:
        typer.echo(f"OCR engine not installed: {exc}", err=True)
        raise typer.Exit(4) from exc

    try:
        result = await extractor.extract(Path(video.raw_path), video_id)
    except SourceMediaMissingError as exc:
        typer.echo(f"source media missing: {exc}", err=True)
        raise typer.Exit(2) from exc
    except (FrameSamplingError, OcrError) as exc:
        log.error("ocr_failed", video_id=video_id, kind=exc.kind, error=str(exc))
        typer.echo(f"OCR failed ({exc.kind}): {exc}", err=True)
        raise typer.Exit(3) from exc

    total_blocks = sum(len(frame.blocks) for frame in result.frames)
    typer.echo(
        f"OCR {video_id}: {len(result.frames)} frames, {total_blocks} blocks, "
        f"engine={result.engine}"
    )
    for frame in result.frames:
        typer.echo(f"  t={frame.timestamp_s:6.2f}s blocks={len(frame.blocks)}")
