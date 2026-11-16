"""Telegram global keyword search — discover AND collect scam content.

Uses Telethon's ``SearchGlobalRequest`` to search the entire Telegram public
space for keywords.  For each result it downloads the content:

- **Text-only messages** → saved as ``.manual.txt`` (pipeline OCR-skips, runs
  scoring + LLM judge on the text)
- **Photos** → saved as ``.manual.jpg`` (pipeline runs OCR → scoring → judge)
- **Videos** → saved as ``.mp4`` (full pipeline: transcribe → OCR → scoring → judge)

Each downloaded item is enqueued via ``enqueue_prepared`` so the standard
pipeline processes it exactly like a manual upload — no special paths needed.

Session requirement: ``AIMW_TELEGRAM_SESSION`` (a portable StringSession
produced by ``scripts/telegram_login.py``).  When absent the search is a
graceful no-op.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from aimw.collection.prescreen import should_collect_text
from aimw.core.logging import get_logger

log = get_logger("aimw.collection.telegram_search")


def _build_client(api_id: int, api_hash: str, session_str: str) -> Any:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    return TelegramClient(StringSession(session_str), api_id, api_hash)


def _content_id(data: bytes) -> str:
    return f"vid-{hashlib.sha256(data).hexdigest()[:16]}"


async def search_and_collect(
    query: str,
    *,
    api_id: int,
    api_hash: str,
    session_str: str,
    media_dir: Path,
    limit: int = 10,
    min_date: dt.datetime | None = None,
    content_types: list[str] | None = None,
    exclude_urls: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Search Telegram globally, download content, return prepared items.

    Each returned dict has the fields ``enqueue_prepared`` needs::

        {
            "video_id": "vid-abc123...",
            "url": "https://t.me/channel/42",
            "platform": "telegram",
            "raw_path": "/data/media/vid-abc123.manual.txt",
            "content_type": "text" | "photo" | "video",
        }

    Errors on individual messages are logged and skipped — the collector
    must never crash.
    """
    try:
        from telethon.tl.functions.messages import SearchGlobalRequest
        from telethon.tl.types import (InputMessagesFilterEmpty, InputMessagesFilterPhotos, InputMessagesFilterVideo, InputMessagesFilterPhotoVideo, InputPeerEmpty)
    except ImportError:
        log.warning("telegram_search_skip", reason="telethon not installed")
        return []

    limit = max(1, min(limit, 50))
    client = _build_client(api_id, api_hash, session_str)
    media_dir.mkdir(parents=True, exist_ok=True)

    collected: list[dict[str, Any]] = []
    try:
        await client.connect()
        if not await client.is_user_authorized():
            log.error("telegram_search_unauthorized")
            return []

        kinds = set(content_types or ('video', 'photo', 'text'))
        if kinds == {'photo'}:
            media_filter = InputMessagesFilterPhotos()
        elif kinds == {'video'}:
            media_filter = InputMessagesFilterVideo()
        elif kinds == {'photo', 'video'}:
            media_filter = InputMessagesFilterPhotoVideo()
        else:
            media_filter = InputMessagesFilterEmpty()
        offset_rate, offset_peer, offset_id = 0, InputPeerEmpty(), 0
        seen_messages: set[tuple[int, int]] = set()
        seen_content: set[str] = set()
        # Bounded pagination: known or filtered first-page items must not hide
        # fresh matches behind them, or consume downloads every minute.
        for _page in range(3):
            result = await client(SearchGlobalRequest(
                q=query, filter=media_filter,
                min_date=min_date or dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
                max_date=dt.datetime.now(dt.UTC), offset_rate=offset_rate,
                offset_peer=offset_peer, offset_id=offset_id,
                limit=min(100, max(20, limit * 4)),
            ))
            messages = getattr(result, 'messages', [])
            if not messages:
                break
            chats_by_id = {getattr(chat, 'id', 0): chat for chat in getattr(result, 'chats', [])}
            for msg in messages:
                peer_id = getattr(getattr(msg, 'peer_id', None), 'channel_id', 0)
                key = (peer_id, getattr(msg, 'id', 0))
                if key in seen_messages:
                    continue
                seen_messages.add(key)
                try:
                    item = await _process_message(client, msg, chats_by_id, media_dir,
                        kinds, query=query, exclude_urls=exclude_urls)
                    if item and item['video_id'] not in seen_content:
                        collected.append(item)
                        seen_content.add(item['video_id'])
                        if len(collected) >= limit:
                            break
                except Exception as exc:
                    log.warning('telegram_msg_failed', msg_id=getattr(msg, 'id', None), error=str(exc))
            if len(collected) >= limit:
                break
            last = messages[-1]
            next_id = getattr(last, 'id', 0)
            next_rate = getattr(result, 'next_rate', 0) or 0
            if (next_id, next_rate) == (offset_id, offset_rate):
                break
            offset_peer = await client.get_input_entity(last.peer_id)
            offset_id, offset_rate = next_id, next_rate

        log.info("telegram_search_collected", query=query, collected=len(collected))
    except Exception as exc:
        log.warning("telegram_search_failed", query=query, error=str(exc))
    finally:
        with suppress(Exception):
            await client.disconnect()

    return collected


async def discover_and_collect(
    query: str,
    *,
    api_id: int,
    api_hash: str,
    session_str: str,
    media_dir: Path,
    channels_per_query: int = 8,
    messages_per_channel: int = 15,
    video_prescreen: Any | None = None,
) -> list[dict[str, Any]]:
    """Find public channels matching *query*, then collect their recent messages.

    Global message search (``SearchGlobalRequest``) returns nothing for a fresh
    account with no joined dialogs. This path instead discovers public channels
    via ``contacts.SearchRequest`` and reads each channel's recent messages —
    the reliable way to surface scam/gambling channels by keyword. Returns
    enqueue-ready item dicts (text/photo/video), same shape as
    :func:`search_and_collect`.

    ``video_prescreen``: optional async ``(caption, channel, url) -> bool``.
    When given, a video is only DOWNLOADED if the prescreen returns True — so the
    judge can vet a clip from its caption/channel *before* paying the
    download+transcribe cost. Videos that pass screening (or have no prescreen)
    are downloaded as before. This is the "judge analyses before we collect it"
    path: non-promotional clips never enter the system.
    """
    try:
        from telethon import functions
    except ImportError:
        log.warning("telegram_search_skip", reason="telethon not installed")
        return []

    client = _build_client(api_id, api_hash, session_str)
    media_dir.mkdir(parents=True, exist_ok=True)
    collected: list[dict[str, Any]] = []
    try:
        await client.connect()
        if not await client.is_user_authorized():
            log.error("telegram_search_unauthorized")
            return []

        res = await client(functions.contacts.SearchRequest(q=query, limit=channels_per_query))
        channels = [
            c for c in getattr(res, "chats", [])
            if (getattr(c, "broadcast", False) or getattr(c, "megagroup", False))
            and getattr(c, "username", None)
        ]
        log.info("telegram_channels_found", query=query, channels=len(channels))

        for chan in channels:
            uname = chan.username
            try:
                async for msg in client.iter_messages(chan, limit=messages_per_channel):
                    msg_id = getattr(msg, "id", 0)
                    url = f"https://t.me/{uname}/{msg_id}"
                    caption = getattr(msg, "message", "") or ""
                    has_video = bool(getattr(msg, "video", None))
                    if not has_video:
                        doc = getattr(msg, "document", None)
                        mime = getattr(doc, "mime_type", "") if doc else ""
                        has_video = bool(
                            mime and isinstance(mime, str) and mime.startswith("video")
                        )
                    has_photo = bool(getattr(msg, "photo", None))
                    try:
                        if has_video:
                            if not should_collect_text(caption, query=query, allow_empty=True):
                                log.info("telegram_video_prescreen_skip", url=url, reason="local")
                                continue
                            # Judge screens the caption/channel BEFORE we download
                            # the (heavy) clip. Skip videos that don't look like a
                            # promotion so non-scams never enter the system.
                            if video_prescreen is not None:
                                keep = await video_prescreen(caption, uname, url)
                                if not keep:
                                    log.info("telegram_video_prescreen_skip", url=url)
                                    continue
                            item = await _save_video(client, msg, url, media_dir)
                        elif has_photo:
                            if not should_collect_text(caption, query=query, allow_empty=True):
                                log.info("telegram_photo_prescreen_skip", url=url, reason="local")
                                continue
                            item = await _save_photo(client, msg, url, caption, media_dir)
                        elif caption.strip():
                            if not should_collect_text(caption, query=query):
                                log.info("telegram_text_prescreen_skip", url=url, reason="local")
                                continue
                            item = _save_text(caption.strip(), url, media_dir)
                        else:
                            continue
                        if item:
                            collected.append(item)
                    except Exception as exc:
                        log.warning("telegram_msg_failed", url=url, error=str(exc))
            except Exception as exc:
                log.warning("telegram_channel_failed", channel=uname, error=str(exc))
        log.info("telegram_discover_collected", query=query, collected=len(collected))
    except Exception as exc:
        log.warning("telegram_discover_failed", query=query, error=str(exc))
    finally:
        with suppress(Exception):
            await client.disconnect()
    return collected


async def _process_message(
    client: Any,
    msg: Any,
    chats_by_id: dict[int, Any],
    media_dir: Path,
    kinds: set[str] | None = None,
    query: str = "",
    exclude_urls: set[str] | None = None,
) -> dict[str, Any] | None:
    """Download one message's content and return an enqueue-ready dict.

    ``kinds`` restricts which content types are collected (video/photo/text);
    a message whose type is not selected is skipped (returns None).
    """
    allowed = kinds if kinds is not None else {"video", "photo", "text"}
    peer = getattr(msg, "peer_id", None)
    chan_id = getattr(peer, "channel_id", None) if peer else None
    chat = chats_by_id.get(chan_id) if chan_id else None
    channel_name = getattr(chat, "username", None) if chat else None

    msg_id = getattr(msg, "id", 0)
    if channel_name:
        url = f"https://t.me/{channel_name}/{msg_id}"
    elif chan_id:
        url = f"https://t.me/c/{chan_id}/{msg_id}"
    else:
        return None

    if exclude_urls and url in exclude_urls:
        log.info('telegram_known_post_skipped', url=url)
        return None

    caption = getattr(msg, "message", "") or ""
    has_video = bool(getattr(msg, "video", None))
    if not has_video:
        doc = getattr(msg, "document", None)
        mime = getattr(doc, "mime_type", "") if doc else ""
        has_video = bool(mime and isinstance(mime, str) and mime.startswith("video"))

    has_photo = bool(getattr(msg, "photo", None))

    # Priority: video > photo > text — but only for the kinds the admin chose.
    if has_video and "video" in allowed:
        if not should_collect_text(caption, query=query, allow_empty=True):
            log.info("telegram_video_prescreen_skip", url=url, reason="local")
            return None
        return await _save_video(client, msg, url, media_dir)
    elif has_photo and "photo" in allowed:
        if not should_collect_text(caption, query=query, allow_empty=True):
            log.info("telegram_photo_prescreen_skip", url=url, reason="local")
            return None
        return await _save_photo(client, msg, url, caption, media_dir)
    elif not has_video and not has_photo and caption.strip() and "text" in allowed:
        if not should_collect_text(caption, query=query):
            log.info("telegram_text_prescreen_skip", url=url, reason="local")
            return None
        return _save_text(caption.strip(), url, media_dir)
    else:
        return None


def _save_text(text: str, url: str, media_dir: Path) -> dict[str, Any]:
    """Save a text message as .manual.txt for the pipeline."""
    data = text.encode("utf-8")
    video_id = _content_id(data)
    path = media_dir / f"{video_id}.manual.txt"
    path.write_text(text, encoding="utf-8")
    log.info("telegram_saved_text", video_id=video_id, chars=len(text))
    return {
        "video_id": video_id,
        "url": url,
        "platform": "telegram",
        "raw_path": str(path),
        "content_type": "text",
    }


async def _save_photo(
    client: Any, msg: Any, url: str, caption: str, media_dir: Path
) -> dict[str, Any]:
    """Download a photo and save as .manual.jpg for OCR pipeline."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "photo.jpg"
        await client.download_media(msg.photo, file=str(tmp_path))
        if not tmp_path.exists():
            raise FileNotFoundError("photo download produced no file")
        data = tmp_path.read_bytes()
        video_id = _content_id(data)
        final = media_dir / f"{video_id}.manual.jpg"
        if not final.exists():
            shutil.move(str(tmp_path), str(final))

    if caption.strip():
        txt_path = media_dir / f"{video_id}.caption.txt"
        txt_path.write_text(caption.strip(), encoding="utf-8")

    log.info("telegram_saved_photo", video_id=video_id, size=len(data))
    return {
        "video_id": video_id,
        "url": url,
        "platform": "telegram",
        "raw_path": str(final),
        "content_type": "photo",
    }


async def _save_video(
    client: Any, msg: Any, url: str, media_dir: Path
) -> dict[str, Any]:
    """Download a video and save as .mp4 for full pipeline."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "video.mp4"
        await client.download_media(msg, file=str(tmp_path))
        if not tmp_path.exists():
            raise FileNotFoundError("video download produced no file")
        data = tmp_path.read_bytes()
        video_id = _content_id(data)
        final = media_dir / f"{video_id}.mp4"
        if not final.exists():
            shutil.move(str(tmp_path), str(final))

    log.info("telegram_saved_video", video_id=video_id, size=len(data))
    return {
        "video_id": video_id,
        "url": url,
        "platform": "telegram",
        "raw_path": str(final),
        "content_type": "video",
    }


def is_telegram_configured() -> bool:
    """True when the Telegram session + credentials are present in config."""
    from aimw.core.config import get_settings

    cfg = get_settings()
    return bool(
        cfg.telegram_api_id
        and cfg.telegram_api_hash
        and cfg.telegram_session
    )


__all__ = ["discover_and_collect", "is_telegram_configured", "search_and_collect"]
