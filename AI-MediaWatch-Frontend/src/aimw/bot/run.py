"""Telegram bot long-polling runner.

Start with:  python -m aimw.bot.run
Or via CLI:  aimw bot
"""

from __future__ import annotations

import asyncio
import logging
import signal

from aimw.bot.handler import handle_update
from aimw.bot.telegram_api import TelegramAPI

_LOG = logging.getLogger("aimw.bot.run")


async def run_bot() -> None:
    from aimw.core.config import get_settings
    from aimw.core.logging import configure_from_settings

    configure_from_settings()

    cfg = get_settings()
    token = cfg.telegram_bot_token
    if not token:
        raise SystemExit(
            "AIMW_TELEGRAM_BOT_TOKEN is not set. "
            "Create a bot via @BotFather and set the token in .env"
        )

    media_dir = cfg.resolved_media_dir
    media_dir.mkdir(parents=True, exist_ok=True)

    api = TelegramAPI(token.get_secret_value())
    me = await api.get_me()
    bot_name = me.get("result", {}).get("username", "unknown")
    _LOG.info("bot_started", extra={"username": bot_name})

    stop = asyncio.Event()

    def _signal_handler() -> None:
        _LOG.info("bot_stopping")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    offset = 0
    while not stop.is_set():
        try:
            updates = await api.get_updates(offset=offset, timeout=30)
        except Exception:
            _LOG.warning("bot_poll_error", exc_info=True)
            await asyncio.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            try:
                await handle_update(api, update, media_dir)
            except Exception:
                _LOG.exception("bot_handle_error", extra={"update_id": update["update_id"]})

    await api.close()
    _LOG.info("bot_stopped")


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
