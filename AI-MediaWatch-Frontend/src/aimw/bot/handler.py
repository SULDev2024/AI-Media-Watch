"""Bot message handler — receive content, run pipeline, return verdict.

Flow per user message:
1. Extract content (text / photo / video) from the Telegram update
2. Save to media dir with the appropriate suffix
3. Enqueue through the pipeline via enqueue_prepared()
4. Poll for the report (async, with timeout)
5. Send the verdict back to the user
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

from aimw.bot.telegram_api import TelegramAPI

_LOG = logging.getLogger("aimw.bot.handler")

_WELCOME = (
    "<b>AI MediaWatch Scam Checker</b>\n\n"
    "Forward me any suspicious message, photo, or video "
    "and I'll analyze it for scam indicators.\n\n"
    "Supported:\n"
    "• Text messages\n"
    "• Photos (screenshots of chats, ads)\n"
    "• Videos (screen recordings, promos)\n\n"
    "Just forward or send — I'll reply with a risk verdict."
)

_ANALYZING = "Analyzing… this may take a moment."
_POLL_INTERVAL = 2.0
_POLL_TIMEOUT = 120.0


def _content_id(data: bytes) -> str:
    return f"vid-{hashlib.sha256(data).hexdigest()[:16]}"


async def handle_update(api: TelegramAPI, update: dict[str, Any], media_dir: Path) -> None:
    if update.get("inline_query"):
        await _handle_inline_query(api, update["inline_query"], media_dir)
        return

    msg = update.get("message")
    if not msg:
        return

    chat_id: int = msg["chat"]["id"]
    msg_id: int = msg["message_id"]

    text_body: str | None = msg.get("text")
    if text_body and text_body.startswith("/start"):
        await api.send_message(chat_id, _WELCOME, reply_to_message_id=msg_id)
        return
    if text_body and text_body.startswith("/help"):
        await api.send_message(chat_id, _WELCOME, reply_to_message_id=msg_id)
        return

    if msg.get("video") or msg.get("video_note") or msg.get("animation"):
        await _handle_video(api, msg, chat_id, msg_id, media_dir)
    elif msg.get("photo"):
        await _handle_photo(api, msg, chat_id, msg_id, media_dir)
    elif text_body:
        await _handle_text(api, text_body, chat_id, msg_id, media_dir)
    elif msg.get("document"):
        mime = msg["document"].get("mime_type", "")
        if mime.startswith("video/"):
            await _handle_video(api, msg, chat_id, msg_id, media_dir, doc=True)
        elif mime.startswith("image/"):
            await _handle_photo(api, msg, chat_id, msg_id, media_dir, doc=True)
        else:
            await api.send_message(
                chat_id,
                "I can analyze text, photos, and videos. "
                "Please forward one of those.",
                reply_to_message_id=msg_id,
            )
    else:
        forwarded_text = msg.get("caption")
        if forwarded_text and not msg.get("photo") and not msg.get("video"):
            await _handle_text(api, forwarded_text, chat_id, msg_id, media_dir)
            return
        await api.send_message(
            chat_id,
            "I can analyze text, photos, and videos. "
            "Please forward one of those.",
            reply_to_message_id=msg_id,
        )


async def _handle_text(
    api: TelegramAPI, text: str, chat_id: int, msg_id: int, media_dir: Path
) -> None:
    if len(text.strip()) < 10:
        await api.send_message(
            chat_id,
            "Message is too short to analyze. Forward a longer message.",
            reply_to_message_id=msg_id,
        )
        return

    data = text.encode("utf-8")
    vid = _content_id(data)
    path = media_dir / f"{vid}.manual.txt"
    media_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    await api.send_chat_action(chat_id)
    await api.send_message(chat_id, _ANALYZING, reply_to_message_id=msg_id)
    await _enqueue_and_respond(api, chat_id, msg_id, vid, path, "telegram")


async def _handle_photo(
    api: TelegramAPI,
    msg: dict[str, Any],
    chat_id: int,
    msg_id: int,
    media_dir: Path,
    *,
    doc: bool = False,
) -> None:
    if doc:
        file_id = msg["document"]["file_id"]
    else:
        file_id = msg["photo"][-1]["file_id"]

    await api.send_chat_action(chat_id)
    await api.send_message(chat_id, _ANALYZING, reply_to_message_id=msg_id)

    file_info = await api.get_file(file_id)
    file_path = file_info.get("file_path", "")
    if not file_path:
        await api.send_message(chat_id, "Could not download the photo.", reply_to_message_id=msg_id)
        return

    media_dir.mkdir(parents=True, exist_ok=True)
    tmp = media_dir / f"_tmp_{chat_id}_{msg_id}.jpg"
    await api.download_file(file_path, tmp)

    data = tmp.read_bytes()
    vid = _content_id(data)
    dest = media_dir / f"{vid}.manual.jpg"
    tmp.rename(dest)

    caption = msg.get("caption")
    if caption and len(caption.strip()) >= 10:
        txt_path = media_dir / f"{vid}.manual.txt"
        txt_path.write_text(caption, encoding="utf-8")

    await _enqueue_and_respond(api, chat_id, msg_id, vid, dest, "telegram")


async def _handle_video(
    api: TelegramAPI,
    msg: dict[str, Any],
    chat_id: int,
    msg_id: int,
    media_dir: Path,
    *,
    doc: bool = False,
) -> None:
    if doc:
        file_id = msg["document"]["file_id"]
    elif msg.get("video"):
        file_id = msg["video"]["file_id"]
    elif msg.get("video_note"):
        file_id = msg["video_note"]["file_id"]
    else:
        file_id = msg["animation"]["file_id"]

    await api.send_chat_action(chat_id, action="upload_video")
    await api.send_message(chat_id, _ANALYZING, reply_to_message_id=msg_id)

    file_info = await api.get_file(file_id)
    file_path = file_info.get("file_path", "")
    if not file_path:
        await api.send_message(
            chat_id, "Could not download the video. It may be too large (max 20 MB via Bot API).",
            reply_to_message_id=msg_id,
        )
        return

    media_dir.mkdir(parents=True, exist_ok=True)
    tmp = media_dir / f"_tmp_{chat_id}_{msg_id}.mp4"
    await api.download_file(file_path, tmp)

    data = tmp.read_bytes()
    vid = _content_id(data)
    dest = media_dir / f"{vid}.mp4"
    tmp.rename(dest)

    await _enqueue_and_respond(api, chat_id, msg_id, vid, dest, "telegram")


async def _enqueue_and_respond(
    api: TelegramAPI,
    chat_id: int,
    msg_id: int,
    video_id: str,
    raw_path: Path,
    platform: str,
) -> None:
    from aimw.db.session import get_sessionmaker
    from aimw.workers.enqueue import enqueue_prepared

    sm = get_sessionmaker()
    try:
        await enqueue_prepared(
            sm,
            video_id=video_id,
            url=f"tg-bot://{video_id}",
            platform=platform,
            raw_path=str(raw_path),
        )
    except Exception:
        _LOG.exception("bot_enqueue_failed", extra={"video_id": video_id})
        await api.send_message(
            chat_id, "Sorry, something went wrong. Please try again.",
            reply_to_message_id=msg_id,
        )
        return

    report = await _poll_for_report(sm, video_id)
    if report:
        verdict = _format_verdict(report)
        await api.send_message(chat_id, verdict, reply_to_message_id=msg_id)
    else:
        await api.send_message(
            chat_id,
            "Analysis is taking longer than expected. "
            "Your content has been queued — check back later or forward it again.",
            reply_to_message_id=msg_id,
        )


async def _poll_for_report(sm: Any, video_id: str) -> dict[str, Any] | None:
    from sqlalchemy import text

    elapsed = 0.0
    while elapsed < _POLL_TIMEOUT:
        await asyncio.sleep(_POLL_INTERVAL)
        elapsed += _POLL_INTERVAL
        try:
            async with sm() as session:
                row = await session.execute(
                    text(
                        "SELECT r.risk_level, r.risk_score, r.summary, r.recommended_action "
                        "FROM reports r "
                        "JOIN evidence_packages p ON r.report_id = p.report_id "
                        "WHERE p.video_id = :vid "
                        "ORDER BY r.created_at DESC LIMIT 1"
                    ),
                    {"vid": video_id},
                )
                result = row.first()
                if result:
                    return {
                        "risk_level": result[0],
                        "risk_score": result[1],
                        "summary": result[2],
                        "recommended_action": result[3],
                    }
        except Exception:
            _LOG.warning("bot_poll_error", extra={"video_id": video_id})
    return None


async def _handle_inline_query(
    api: TelegramAPI, query: dict[str, Any], media_dir: Path
) -> None:
    """Handle inline queries — user types @bot <text> in any chat."""
    query_id = query["id"]
    text = (query.get("query") or "").strip()

    if len(text) < 10:
        await api.answer_inline_query(query_id, [
            {
                "type": "article",
                "id": "help",
                "title": "AI MediaWatch Scam Checker",
                "description": "Type at least 10 characters to check for scam indicators",
                "input_message_content": {
                    "message_text": "Forward me a suspicious message to check for scam indicators. @AI_MediaWatch_bot",
                    "parse_mode": "HTML",
                },
            }
        ])
        return

    data = text.encode("utf-8")
    vid = _content_id(data)
    path = media_dir / f"{vid}.manual.txt"
    media_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

    from aimw.db.session import get_sessionmaker
    from aimw.workers.enqueue import enqueue_prepared

    sm = get_sessionmaker()
    try:
        await enqueue_prepared(
            sm, video_id=vid, url=f"inline://{vid}", platform="telegram", raw_path=str(path),
        )
    except Exception:
        _LOG.exception("inline_enqueue_failed", extra={"video_id": vid})
        await api.answer_inline_query(query_id, [
            {
                "type": "article",
                "id": "error",
                "title": "Error",
                "description": "Something went wrong. Try again.",
                "input_message_content": {"message_text": "Error analyzing content."},
            }
        ])
        return

    report = await _poll_for_report(sm, vid)
    if report:
        level = report.get("risk_level", "UNKNOWN")
        emoji = _LEVEL_EMOJI.get(level, "❓")
        score = report.get("risk_score")
        score_str = f" ({score:.0%})" if score is not None else ""
        summary = report.get("summary", "No details available.")[:300]

        await api.answer_inline_query(query_id, [
            {
                "type": "article",
                "id": f"result-{vid}",
                "title": f"{emoji} {level}{score_str}",
                "description": summary[:100],
                "input_message_content": {
                    "message_text": _format_verdict(report),
                    "parse_mode": "HTML",
                },
            }
        ])
    else:
        await api.answer_inline_query(query_id, [
            {
                "type": "article",
                "id": f"pending-{vid}",
                "title": "Analysis in progress...",
                "description": "Taking longer than expected. Try again in a moment.",
                "input_message_content": {
                    "message_text": "Analysis is still in progress. Please try again shortly.",
                },
            }
        ])


_LEVEL_EMOJI = {
    "CRITICAL": "\U0001f6a8",  # 🚨
    "HIGH": "⚠️",  # ⚠️
    "MEDIUM": "\U0001f7e1",  # 🟡
    "LOW": "\U0001f7e2",  # 🟢
    "NONE": "✅",  # ✅
}


def _format_verdict(report: dict[str, Any]) -> str:
    level = report.get("risk_level", "UNKNOWN")
    score = report.get("risk_score")
    summary = report.get("summary", "")
    action = report.get("recommended_action", "")
    emoji = _LEVEL_EMOJI.get(level, "❓")

    score_str = f" ({score:.0%})" if score is not None else ""

    lines = [
        f"{emoji} <b>Risk Level: {level}{score_str}</b>",
        "",
    ]
    if summary:
        lines.append(summary[:800])
        lines.append("")
    if action:
        lines.append(f"<b>Recommended:</b> {action}")

    return "\n".join(lines)
