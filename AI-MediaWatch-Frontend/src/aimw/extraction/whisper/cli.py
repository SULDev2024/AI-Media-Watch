"""Extraction CLI: ``aimw extract transcribe <video_id>``.

Reads a ``videos`` row, transcribes the file at ``raw_path``, and prints a one-
line summary. The CLI is a one-shot entry point and owns its event loop with
``asyncio.run`` (this is *not* the per-Celery-task pattern ADR-0002 forbids).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from aimw.core.logging import configure_from_settings, get_logger
from aimw.extraction.whisper.transcriber import (
    SourceMediaMissingError,
    TranscriptionError,
    get_transcriber,
)


def register(extract_app: typer.Typer) -> None:
    """Register the ``transcribe`` subcommand on the parent ``extract`` Typer app."""

    @extract_app.command("transcribe")
    def transcribe(
        video_id: Annotated[str, typer.Argument(help="The 16-hex-char video id to transcribe")],
    ) -> None:
        """Transcribe a previously collected video and write the cache entry."""
        asyncio.run(_transcribe(video_id))


async def _transcribe(video_id: str) -> None:
    configure_from_settings()
    log = get_logger("aimw.extraction.whisper.cli")

    # Lazy: keep CLI startup cheap; only touch the DB when actually running.
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

    transcriber = get_transcriber()
    try:
        transcript = await transcriber.transcribe(Path(video.raw_path), video_id)
    except SourceMediaMissingError as exc:
        typer.echo(f"source media missing: {exc}", err=True)
        raise typer.Exit(2) from exc
    except TranscriptionError as exc:
        log.error("transcribe_failed", video_id=video_id, kind=exc.kind, error=str(exc))
        typer.echo(f"transcription failed ({exc.kind}): {exc}", err=True)
        raise typer.Exit(3) from exc

    typer.echo(
        f"transcribed {video_id}: {len(transcript.segments)} segments, "
        f"language={transcript.language_detected}, "
        f"device={transcript.device}, compute={transcript.compute_type}"
    )
