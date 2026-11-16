"""Thin Telegram Bot API client using httpx (no extra dependency).

Covers only what the scam-checker bot needs: getUpdates long-polling,
sendMessage, getFile, and downloading media.  Everything is async.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

_LOG = logging.getLogger("aimw.bot.telegram_api")
_BASE = "https://api.telegram.org/bot{token}"
_FILE = "https://api.telegram.org/file/bot{token}/{path}"
_TIMEOUT = httpx.Timeout(connect=10, read=90, write=10, pool=10)


class TelegramAPI:
    def __init__(self, token: str) -> None:
        self._token = token
        self._base = _BASE.format(token=token)
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, **params: Any) -> dict[str, Any]:
        url = f"{self._base}/{method}"
        resp = await self._client.post(url, json={k: v for k, v in params.items() if v is not None})
        data = resp.json()
        if not data.get("ok"):
            _LOG.warning("tg_api_error", extra={"method": method, "error": data})
        return data

    async def get_me(self) -> dict[str, Any]:
        return await self._call("getMe")

    async def get_updates(self, offset: int = 0, timeout: int = 30) -> list[dict[str, Any]]:
        data = await self._call("getUpdates", offset=offset, timeout=timeout)
        return data.get("result", [])

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        return await self._call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_to_message_id=reply_to_message_id,
        )

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        await self._call("sendChatAction", chat_id=chat_id, action=action)

    async def get_file(self, file_id: str) -> dict[str, Any]:
        data = await self._call("getFile", file_id=file_id)
        return data.get("result", {})

    async def answer_inline_query(
        self,
        inline_query_id: str,
        results: list[dict[str, Any]],
        cache_time: int = 30,
    ) -> dict[str, Any]:
        import json

        return await self._call(
            "answerInlineQuery",
            inline_query_id=inline_query_id,
            results=json.dumps(results),
            cache_time=cache_time,
        )

    async def download_file(self, file_path: str, dest: Path) -> Path:
        url = _FILE.format(token=self._token, path=file_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with self._client.stream("GET", url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
        return dest
