"""Alert dispatchers — notify admins when HIGH/CRITICAL content is detected."""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any

import httpx

from aimw.core.config import get_settings

_LOG = logging.getLogger("aimw.alerts")


async def send_telegram_alert(message: str) -> None:
    cfg = get_settings()
    token = cfg.alert_telegram_bot_token
    chat_id = cfg.alert_telegram_chat_id
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token.get_secret_value()}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
            })
        except Exception:
            _LOG.warning("telegram_alert_failed", exc_info=True)


def send_email_alert(subject: str, body: str) -> None:
    cfg = get_settings()
    if not cfg.alert_email_smtp_host or not cfg.alert_email_from or not cfg.alert_email_to:
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = cfg.alert_email_from
    msg["To"] = cfg.alert_email_to

    try:
        with smtplib.SMTP(cfg.alert_email_smtp_host, cfg.alert_email_smtp_port) as server:
            server.starttls()
            if cfg.alert_email_password:
                server.login(cfg.alert_email_from, cfg.alert_email_password.get_secret_value())
            server.send_message(msg)
    except Exception:
        _LOG.warning("email_alert_failed", exc_info=True)


async def send_webhook_alert(payload: dict[str, Any]) -> None:
    cfg = get_settings()
    if not cfg.webhook_urls:
        return

    urls = [u.strip() for u in cfg.webhook_urls.split(",") if u.strip()]
    async with httpx.AsyncClient(timeout=10) as client:
        for url in urls:
            try:
                await client.post(url, json=payload)
            except Exception:
                _LOG.warning("webhook_alert_failed", extra={"url": url})


async def dispatch_alert(
    video_id: str,
    risk_level: str,
    risk_score: float | None,
    summary: str,
    platform: str = "",
    url: str = "",
) -> None:
    """Fire all configured alert channels for a HIGH/CRITICAL detection."""
    if risk_level not in ("HIGH", "CRITICAL"):
        return

    score_str = f"{risk_score:.0%}" if risk_score is not None else "N/A"

    tg_msg = (
        f"🚨 <b>{risk_level}</b> scam detected ({score_str})\n\n"
        f"<b>Platform:</b> {platform}\n"
        f"<b>URL:</b> {url}\n"
        f"<b>ID:</b> {video_id}\n\n"
        f"{summary[:500]}"
    )
    await send_telegram_alert(tg_msg)

    email_body = (
        f"Risk Level: {risk_level} ({score_str})\n"
        f"Platform: {platform}\n"
        f"URL: {url}\n"
        f"Video ID: {video_id}\n\n"
        f"Summary:\n{summary}"
    )
    send_email_alert(f"[AI MediaWatch] {risk_level} — {video_id}", email_body)

    await send_webhook_alert({
        "event": "scam_detected",
        "video_id": video_id,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "summary": summary,
        "platform": platform,
        "url": url,
    })
