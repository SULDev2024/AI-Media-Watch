"""Entity extraction CLI: ``aimw entities <video_id>``.

Loads the cached Transcript (Phase 5) and OcrResult (Phase 6) for the video,
runs Phase 7 entity extraction, and prints a structured JSON summary to stdout.
Both caches are optional — if one is absent the extractor runs with whichever
artifact is available.

Architecture note: entities is a *schema* module (it produces ExtractedEntities
from raw artifacts). It lives above the extraction layer and cannot be mounted
under ``aimw extract`` without violating the ADR-0004 extractor boundary.
The command is therefore a top-level group: ``aimw entities <video_id>``.

Owns its own event loop (``asyncio.run``) — the one-shot CLI pattern per ADR-0002.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from aimw.core.logging import configure_from_settings, get_logger

entities_app = typer.Typer(
    help="Entity extraction: wallets, handles, phones, profits (Phase 7).",
    no_args_is_help=True,
)


def register(parent: typer.Typer) -> None:
    """Mount the entities Typer app on *parent* (used by the main CLI)."""
    parent.add_typer(entities_app, name="entities")


@entities_app.command("run")
def run_entities(
    video_id: Annotated[
        str, typer.Argument(help="The 16-hex-char video id to extract entities from")
    ],
    watchlist: Annotated[
        Path | None,
        typer.Option("--watchlist", "-w", help="Path to watchlist JSON (optional)"),
    ] = None,
    vlm: Annotated[
        bool,
        typer.Option("--vlm/--no-vlm", help="Enable VLM recovery pass on OCR frames"),
    ] = False,
) -> None:
    """Extract entities (wallets, handles, phones, profits) from a video's artifacts."""
    asyncio.run(_extract(video_id, watchlist_override=watchlist, use_vlm=vlm))


async def _extract(
    video_id: str,
    *,
    watchlist_override: Path | None,
    use_vlm: bool,
) -> None:
    configure_from_settings()
    log = get_logger("aimw.entities.cli")

    from aimw.core.config import get_settings
    from aimw.entities import extractor as ext_mod
    from aimw.entities import fuzzy as fuzz_mod
    from aimw.extraction.ocr.models import OcrResult
    from aimw.extraction.whisper.models import Transcript

    settings = get_settings()

    # Load Transcript (may be None if not yet transcribed).
    # We load the raw JSON without manifest validation — the CLI just works with
    # whatever is cached; provenance enforcement happens at extract-time.
    transcript_path = settings.resolved_whisper_cache_dir / f"{video_id}.json"
    transcript = None
    if transcript_path.exists():
        try:
            transcript = Transcript.model_validate_json(transcript_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("transcript_cache_unreadable", video_id=video_id, error=str(exc))
    if transcript is None:
        log.warning("transcript_cache_miss", video_id=video_id)

    # Load OcrResult (may be None if not yet OCR'd).
    ocr_path = settings.resolved_ocr_cache_dir / f"{video_id}.json"
    ocr_result = None
    if ocr_path.exists():
        try:
            ocr_result = OcrResult.model_validate_json(ocr_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("ocr_cache_unreadable", video_id=video_id, error=str(exc))
    if ocr_result is None:
        log.warning("ocr_cache_miss", video_id=video_id)

    if transcript is None and ocr_result is None:
        typer.echo(
            f"No transcript or OCR cache found for video_id={video_id!r}. "
            "Run 'aimw extract whisper' and/or 'aimw extract ocr' first.",
            err=True,
        )
        raise typer.Exit(2)

    # Load watchlist (from CLI override, then settings, then skip).
    watchlist: dict[str, list[str]] | None = None
    wl_path = watchlist_override or (
        settings.resolved_watchlist_path if settings.resolved_watchlist_path.exists() else None
    )
    if wl_path is not None:
        try:
            watchlist = fuzz_mod.load_watchlist(wl_path)
            log.info("watchlist_loaded", path=str(wl_path))
        except Exception as exc:
            log.warning("watchlist_load_failed", path=str(wl_path), error=str(exc))

    # Optionally load VLM wrapper.
    vlm_wrapper = None
    if use_vlm:
        from aimw.entities.vlm.qwen import get_qwen

        vlm_wrapper = get_qwen()
        if not vlm_wrapper.is_available():
            typer.echo(
                "VLM requested but not available. Install with: uv sync --extra vlm",
                err=True,
            )
            vlm_wrapper = None

    entities_result, spans = await ext_mod.extract_async(
        transcript, ocr_result, vlm=vlm_wrapper, watchlist=watchlist
    )

    # Print JSON summary.
    summary = {
        "video_id": video_id,
        "telegram_handles": entities_result.telegram_handles,
        "telegram_links": entities_result.telegram_links,
        "crypto_wallets": entities_result.crypto_wallets,
        "phone_numbers": entities_result.phone_numbers,
        "payment_phones": entities_result.payment_phones,
        "profit_claims": entities_result.profit_claims,
        "referral_codes": entities_result.referral_codes,
        "raw_span_count": len(spans),
    }
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
