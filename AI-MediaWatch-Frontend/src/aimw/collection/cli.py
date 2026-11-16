"""Collection CLI: ``aimw collect ingest-url`` and ``aimw collect watch``.

The CLI is a one-shot entry point, so it owns its event loop with
``asyncio.run`` (this is *not* the Celery per-task pattern ADR-0002 forbids).
Heavy/optional dependencies (yt-dlp, Telethon) are imported lazily inside the
commands so ``--help`` and import-time stay cheap and resilient.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path
from typing import Annotated

import typer
import yaml

from aimw.collection import priority
from aimw.collection.language_detect import detect as detect_language
from aimw.core.config import get_settings
from aimw.core.logging import configure_from_settings, get_logger

collect_app = typer.Typer(
    help="Collection: ingest analyst URLs and watch curated channels.",
    no_args_is_help=True,
)


def _platform_from_url(url: str) -> str:
    lowered = url.lower()
    if "tiktok" in lowered:
        return "tiktok"
    if "youtube" in lowered or "youtu.be" in lowered:
        return "youtube"
    if "t.me" in lowered or "telegram" in lowered:
        return "telegram"
    return "web"


@collect_app.command("ingest-url")
def ingest_url(url: Annotated[str, typer.Argument(help="Video URL to ingest")]) -> None:
    """Download a single URL (<=720p) and record a videos row."""
    asyncio.run(_ingest_url(url))


async def _ingest_url(url: str) -> None:
    configure_from_settings()
    log = get_logger("aimw.collection.cli")
    from aimw.collection.ytdlp import download
    from aimw.db.repositories.videos import VideosRepository
    from aimw.db.session import get_sessionmaker

    settings = get_settings()
    media = download(url, settings.resolved_media_dir)
    caption = f"{media.title or ''} {media.description or ''}".strip()

    repo = VideosRepository(get_sessionmaker())
    await repo.upsert(
        id=media.video_id,
        platform=_platform_from_url(url),
        url=url,
        collected_at=dt.datetime.now(dt.UTC),
        language_hint=detect_language(caption),
        priority_score=priority.score(caption),
        raw_path=str(media.path),
    )
    log.info("ingested_url", url=url, video_id=media.video_id, path=str(media.path))
    typer.echo(f"ingested {media.video_id} -> {media.path}")


def _load_channels(path: Path) -> list[tuple[str, str | int]]:
    """Parse a channels YAML file into (name, entity) pairs.

    Each entry is either a bare username string or a mapping with ``name`` and
    optional ``entity`` (defaults to ``name``).
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    channels: list[tuple[str, str | int]] = []
    for item in raw:
        if isinstance(item, str):
            channels.append((item, item))
        elif isinstance(item, dict) and item.get("name"):
            channels.append((str(item["name"]), item.get("entity", item["name"])))
    return channels


@collect_app.command("watch")
def watch(
    channels: Annotated[Path, typer.Option("--channels", help="Path to channels YAML")],
    once: Annotated[bool, typer.Option("--once", help="Poll each channel once and exit")] = False,
) -> None:
    """Watch curated public channels for new video messages."""
    asyncio.run(_watch(channels, once))


async def _watch(channels_path: Path, once: bool) -> None:
    configure_from_settings()
    log = get_logger("aimw.collection.cli")
    from telethon import TelegramClient

    from aimw.collection.offsets import Offsets
    from aimw.collection.telegram import ChannelSpec, ChannelWatcher
    from aimw.db.repositories.videos import VideosRepository
    from aimw.db.session import get_sessionmaker

    settings = get_settings()
    if settings.telegram_api_id is None or settings.telegram_api_hash is None:
        log.error("telegram_credentials_missing")
        raise typer.Exit(2)

    specs = [
        ChannelSpec(name=name, entity=entity) for name, entity in _load_channels(channels_path)
    ]
    offsets = Offsets.load(settings.resolved_state_dir / "telegram_offsets.json")
    repo = VideosRepository(get_sessionmaker())
    client = TelegramClient(
        str(settings.resolved_state_dir / "aimw.session"),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
    )
    watcher = ChannelWatcher(client, repo, offsets, settings.resolved_media_dir)

    await client.start()
    try:
        while True:
            for spec in specs:
                try:
                    count = await watcher.poll_channel(spec)
                    log.info("channel_polled", channel=spec.name, processed=count)
                except Exception as exc:  # never crash the loop (constraint #8)
                    log.error("channel_poll_error", channel=spec.name, error=str(exc))
            if once:
                break
            await asyncio.sleep(60)
    finally:
        await client.disconnect()
