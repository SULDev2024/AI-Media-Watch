"""Collect scam content from Telegram and keep only judge-verified scams.

Uses the Telegram global keyword search (Telethon) to discover + download text,
photo, and video messages, runs each through the full pipeline (entities ->
signals -> score -> LLM judge), keeps HIGH/CRITICAL fraud-promotions, and purges
everything else — same verified-only policy as the YouTube collector.

Requires AIMW_TELEGRAM_API_ID / _API_HASH / _SESSION in .env (run
scripts/telegram_login.py once to produce the session). Usage:

    python scripts/collect_telegram_scams.py --target 40 --per-query 20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("collect_tg")
for noisy in ("aiosqlite", "httpx", "telethon"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

# Scam/gambling-targeting queries (Telegram skews RU/EN financial-fraud + casino).
QUERIES = [
    "guaranteed profit investment", "crypto signals vip join", "double your bitcoin",
    "passive income crypto bot", "forex guaranteed daily profit", "usdt arbitrage bot",
    "casino bonus promo code", "betting fixed matches", "mlm recruit earn",
    "гарантированный доход крипто", "инвестиции пассивный доход", "схема заработка крипто",
    "ставки прогнозы договорные", "казино бонус промокод", "арбитраж криптовалюты бот",
    "заработок без вложений вывод",
]

_CHILD = ("evidence_pieces", "entities", "network_connections", "reports", "analyst_feedback")


def _verdict(db: str, vid: str):
    c = sqlite3.connect(db, timeout=30)
    try:
        return c.execute(
            "SELECT risk_level, score, action FROM evidence_packages "
            "WHERE video_id=? ORDER BY processed_at DESC LIMIT 1", (vid,)).fetchone()
    finally:
        c.close()


def _purge(db: str, vid: str) -> None:
    c = sqlite3.connect(db, timeout=30)
    try:
        rids = [r[0] for r in c.execute(
            "SELECT report_id FROM evidence_packages WHERE video_id=?", (vid,))]
        for rid in rids:
            for t in _CHILD:
                c.execute(f"DELETE FROM {t} WHERE report_id=?", (rid,))
            c.execute("UPDATE regression_cases SET frozen_from_report=NULL "
                      "WHERE frozen_from_report=?", (rid,))
        c.execute("DELETE FROM evidence_packages WHERE video_id=?", (vid,))
        c.execute("DELETE FROM videos WHERE id=?", (vid,))
        c.commit()
    finally:
        c.close()


def _persist_caption_scam(db: str, vid: str, url: str, cap_v: dict) -> None:
    """Write a judge-confirmed scam verdict for a video from its caption alone.

    Builds a minimal evidence package + report (no transcription) so the clip
    shows as a HIGH/report scam in the dashboard and audit report.
    """
    import datetime as _dt
    import hashlib
    rid = "rpt-" + hashlib.sha256(vid.encode()).hexdigest()[:16]
    now = _dt.datetime.now(_dt.UTC).isoformat()
    caption = cap_v["caption"]
    pkg = {
        "report_id": rid, "video_id": vid, "platform": "telegram", "url": url,
        "collected_at": now, "processed_at": now, "schema_version": "4.0.0",
        "evidence": [{
            "source": "speech", "polarity": "incriminating", "strength": "strong",
            "indicator_type": "caption_fraud_promotion", "raw_value": caption[:300],
            "timestamp": 0.0, "content": caption[:300], "regulation_ref": None,
            "recovery_method": "raw",
        }],
        "entities": {"crypto_wallets": [], "payment_phones": [], "phone_numbers": [],
                     "phone_purposes": {}, "profit_claims": [], "referral_codes": [],
                     "telegram_handles": [], "telegram_links": []},
        "network_connections": [],
    }
    md = (f"## AI judge verdict — HIGH\n\n**Intent:** promotion  ·  **Fraud promotion:** YES  ·  "
          f"**Confidence:** {round(cap_v['confidence']*100)}%\n\n{cap_v['rationale']}\n\n"
          f"**Flagged caption:** \"{caption[:400]}\"")
    c = sqlite3.connect(db, timeout=30)
    try:
        c.execute(
            "INSERT OR REPLACE INTO evidence_packages "
            "(report_id, video_id, processed_at, score, risk_level, confidence, action, "
            "schema_version, package_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (rid, vid, now, cap_v["score"], "HIGH", cap_v["confidence"], "report",
             "4.0.0", json.dumps(pkg, ensure_ascii=False)))
        c.execute("INSERT OR REPLACE INTO reports (report_id, markdown, generated_at) "
                  "VALUES (?,?,?)", (rid, md, now))
        c.commit()
    finally:
        c.close()


async def main(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("AIMW_GROQ_DAILY_TOKEN_CAP", "5000000")

    from aimw.core.config import get_settings
    get_settings.cache_clear()
    cfg = get_settings()

    from aimw.collection.telegram_search import is_telegram_configured, discover_and_collect
    if not is_telegram_configured():
        LOG.error("Telegram not configured. Set AIMW_TELEGRAM_API_ID / _API_HASH / "
                  "_SESSION in .env (run scripts/telegram_login.py first).")
        return

    import datetime as dt
    from aimw.workers.pipeline import run_pipeline
    from aimw.db.session import get_sessionmaker
    from aimw.db.repositories.videos import VideosRepository
    from aimw.db.repositories.usage import UsageRepository
    from aimw.reasoning.client import build_chat_client
    from aimw.reasoning.judge import classify
    from aimw.core.schema.evidence import EvidencePackage, ExtractedEntities
    from aimw.scoring.registry import register
    register()
    sm = get_sessionmaker()
    videos = VideosRepository(sm)
    db = os.environ.get("AIMW_SQLITE_PATH", "data/aimw.db")

    api_id = int(cfg.telegram_api_id)
    api_hash = cfg.telegram_api_hash.get_secret_value()
    session = cfg.telegram_session.get_secret_value()
    media_dir = cfg.resolved_media_dir

    # ── Pre-screen: the judge reads each video's CAPTION before we download it.
    # Only clips whose caption reads as a fraud promotion get downloaded +
    # transcribed + fully judged. Caption-less clips can't be vetted cheaply, so
    # they're skipped — non-scams never enter the system.
    _judge = build_chat_client(UsageRepository(sm))
    _now = dt.datetime(2026, 6, 15, tzinfo=dt.UTC)
    # url -> caption verdict for clips whose CAPTION the judge confirmed as fraud.
    # A video posted with such a caption in a scam channel is a scam clip even if
    # its audio is just a screen recording. In --fast mode we keep it on the
    # caption alone (no transcription) for speed.
    caption_verdicts: dict[str, dict] = {}

    def _pkg(rid: str) -> "EvidencePackage":
        return EvidencePackage(report_id=rid, video_id=rid, platform="telegram",
                               url="x", collected_at=_now, processed_at=_now,
                               evidence=[], entities=ExtractedEntities())

    async def video_prescreen(caption: str, channel: str, url: str) -> bool:
        cap = (caption or "").strip()
        if len(cap) < 15:
            return False  # nothing to judge from → skip the download
        try:
            v = await classify(
                _pkg("scr-" + url[-12:]), cap, _judge,
                title=f"Telegram video posted in channel @{channel}", channel="telegram")
            if v.is_fraud_promotion:
                caption_verdicts[url] = {
                    "caption": cap, "channel": channel,
                    "score": (getattr(v, "risk_score", 0) or 90) / 100.0,
                    "confidence": float(v.confidence),
                    "rationale": v.rationale,
                }
            ok = v.is_fraud_promotion or v.intent == "promotion"
            LOG.info("  prescreen %s: intent=%s fraud=%s -> %s", url, v.intent,
                     v.is_fraud_promotion, "DOWNLOAD" if ok else "skip")
            return ok
        except Exception as e:
            LOG.warning("  prescreen failed %s: %s", url, str(e)[:80])
            return False

    confirmed: list[dict] = []
    manifest = Path("collected_telegram_scams_manifest.json")
    processed = 0

    for q in QUERIES:
        if len(confirmed) >= args.target:
            break
        LOG.info("Searching Telegram channels: %r", q)
        try:
            items = await discover_and_collect(
                q, api_id=api_id, api_hash=api_hash, session_str=session,
                media_dir=media_dir, channels_per_query=8,
                messages_per_channel=max(8, args.per_query // 2),
                video_prescreen=video_prescreen if args.media in ("video", "both") else None)
        except Exception as e:
            LOG.warning("search failed %r: %s", q, str(e)[:120])
            continue
        LOG.info("  got %d items", len(items))

        for item in items:
            if len(confirmed) >= args.target:
                break
            ctype = item.get("content_type")
            raw = Path(item["raw_path"])
            # --media controls which content types to judge:
            #   video → only videos (download+transcribe), text → only text,
            #   both  → text + video. Photos always skipped (OCR unavailable).
            allowed = {"video"} if args.media == "video" \
                else {"text"} if args.media == "text" \
                else {"text", "video"}
            if ctype not in allowed:
                raw.unlink(missing_ok=True)
                continue
            if ctype == "text":
                try:
                    if len(raw.read_text(encoding="utf-8").strip()) < 40:
                        raw.unlink(missing_ok=True)
                        continue
                except Exception:
                    continue
            processed += 1
            vid = item["video_id"]
            url = item["url"]
            cap_v = caption_verdicts.get(url)
            try:
                await videos.upsert(
                    id=vid, platform=item.get("platform", "telegram"), url=url,
                    collected_at=dt.datetime.now(dt.UTC), raw_path=item["raw_path"])

                # ── FAST PATH: caption already judge-confirmed as fraud → keep
                # the clip on the caption alone, no Whisper transcription. The
                # caption (the scammer's pitch) is stored as the content.
                if args.fast and cap_v is not None:
                    await videos.update_transcript(
                        vid, json.dumps([{"text": cap_v["caption"], "start": 0, "end": 0}],
                                        ensure_ascii=False))
                    _persist_caption_scam(db, vid, url, cap_v)
                    score = round(cap_v["score"], 3)
                    LOG.info("  [%d confirmed] SCAM KEPT (caption, fast) %s score=%.2f %s",
                             len(confirmed) + 1, vid, score, url)
                    confirmed.append({"video_id": vid, "url": url, "risk_level": "HIGH",
                                      "score": score, "action": "report", "type": "video",
                                      "caption": cap_v["caption"][:200]})
                    manifest.write_text(json.dumps(confirmed, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
                    continue

                # ── FULL PATH: transcribe + judge the video audio.
                await run_pipeline(vid)
                row = _verdict(db, vid)
                if not row:
                    continue
                level, score, action = row[0] or "?", row[1] or 0.0, row[2] or "?"
                caption_fraud = cap_v is not None
                is_scam = action == "report" or caption_fraud
                if caption_fraud and action != "report":
                    score = max(score, 0.85); level = "HIGH"; action = "report"
                    wconn = sqlite3.connect(db, timeout=30)
                    try:
                        wconn.execute(
                            "UPDATE evidence_packages SET risk_level='HIGH', "
                            "action='report', score=? WHERE video_id=?", (score, vid))
                        wconn.commit()
                    finally:
                        wconn.close()
                if is_scam:
                    LOG.info("  [%d confirmed] SCAM KEPT %s level=%s score=%.2f %s",
                             len(confirmed) + 1, vid, level, score, url)
                    confirmed.append({"video_id": vid, "url": url, "risk_level": level,
                                      "score": round(score, 3), "action": action,
                                      "type": item.get("content_type")})
                    manifest.write_text(json.dumps(confirmed, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
                else:
                    _purge(db, vid)
            except Exception as e:
                LOG.warning("  item failed %s: %s", vid, str(e)[:120])

    LOG.info("")
    LOG.info("=== Telegram collection complete ===")
    LOG.info("Processed: %d | Confirmed scams: %d / %d", processed, len(confirmed), args.target)
    LOG.info("Manifest: %s", manifest.resolve())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=int, default=40)
    p.add_argument("--per-query", type=int, default=20)
    p.add_argument("--media", choices=["text", "video", "both"], default="both",
                   help="which content to collect (default both; 'video' = videos only)")
    p.add_argument("--fast", action="store_true",
                   help="keep caption-confirmed scam videos without transcribing them (much faster)")
    asyncio.run(main(p.parse_args()))
