"""Collect scam videos from TikTok by searching known scam hashtags/keywords.

TikTok doesn't need login for video downloads. yt-dlp fetches public videos.
We search for crypto/investment scam content, judge each clip, keep only confirmed scams.

Usage:
    python scripts/collect_tiktok_scams.py --target 15
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("collect_tiktok")
for noisy in ("aiosqlite", "httpx", "faster_whisper", "yt_dlp"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

# TikTok scam-related hashtag searches (yt-dlp supports tiktok hashtag pages)
HASHTAG_SEARCHES = [
    "https://www.tiktok.com/tag/cryptoinvestment",
    "https://www.tiktok.com/tag/forextrading",
    "https://www.tiktok.com/tag/passiveincome",
    "https://www.tiktok.com/tag/cryptotrading",
    "https://www.tiktok.com/tag/makemoneyonline",
    "https://www.tiktok.com/tag/bitcoininvestment",
    "https://www.tiktok.com/tag/tradingbot",
    "https://www.tiktok.com/tag/binaryoptions",
]

_CHILD = ("evidence_pieces", "entities", "network_connections", "reports", "analyst_feedback")


def _purge(db: str, vid: str) -> None:
    c = sqlite3.connect(db, timeout=30)
    try:
        rids = [r[0] for r in c.execute(
            "SELECT report_id FROM evidence_packages WHERE video_id=?", (vid,))]
        for rid in rids:
            for t in _CHILD:
                c.execute(f"DELETE FROM {t} WHERE report_id=?", (rid,))
            c.execute("UPDATE regression_cases SET frozen_from_report=NULL WHERE frozen_from_report=?", (rid,))
        c.execute("DELETE FROM evidence_packages WHERE video_id=?", (vid,))
        c.execute("DELETE FROM videos WHERE id=?", (vid,))
        c.commit()
    finally:
        c.close()


def _get_verdict(db: str, vid: str):
    c = sqlite3.connect(db, timeout=30)
    try:
        return c.execute(
            "SELECT risk_level, score, action FROM evidence_packages "
            "WHERE video_id=? ORDER BY processed_at DESC LIMIT 1", (vid,)).fetchone()
    finally:
        c.close()


async def main(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("AIMW_GROQ_DAILY_TOKEN_CAP", "5000000")

    import yt_dlp
    from aimw.core.config import get_settings
    get_settings.cache_clear()
    cfg = get_settings()
    from aimw.workers.pipeline import run_pipeline
    from aimw.workers.enqueue import derive_video_id
    from aimw.db.session import get_sessionmaker
    from aimw.db.repositories.videos import VideosRepository
    from aimw.scoring.registry import register
    register()
    sm = get_sessionmaker()
    videos = VideosRepository(sm)
    db = os.environ.get("AIMW_SQLITE_PATH", "data/aimw.db")
    media_dir = cfg.resolved_media_dir
    media_dir.mkdir(parents=True, exist_ok=True)

    confirmed: list[dict] = []
    manifest = Path("collected_tiktok_scams_manifest.json")
    seen_urls: set[str] = set()

    for tag_url in HASHTAG_SEARCHES:
        if len(confirmed) >= args.target:
            break
        LOG.info("Fetching TikTok hashtag: %s", tag_url)
        try:
            ydl_opts = {
                "quiet": True, "no_warnings": True,
                "extract_flat": True,
                "playlist_items": f"1-{args.per_tag}",
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(tag_url, download=False)
            entries = (info or {}).get("entries") or []
            LOG.info("  found %d entries", len(entries))
        except Exception as e:
            LOG.warning("  hashtag failed: %s", str(e)[:120])
            continue

        for entry in entries:
            if len(confirmed) >= args.target:
                break
            url = entry.get("url") or entry.get("webpage_url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                vid = derive_video_id(url)
                await videos.upsert(id=vid, platform="tiktok", url=url,
                                    collected_at=dt.datetime.now(dt.UTC))
                LOG.info("  processing %s", url[:70])
                await run_pipeline(vid)
                row = _get_verdict(db, vid)
                if not row:
                    LOG.info("    no verdict yet")
                    continue
                level, score, action = row[0] or "?", row[1] or 0.0, row[2] or "?"
                if action == "report" or level in ("HIGH", "CRITICAL"):
                    LOG.info("    -> SCAM KEPT %s(%.2f) %s", level, score, url[:60])
                    confirmed.append({"url": url, "risk_level": level, "score": round(score, 3)})
                    manifest.write_text(json.dumps(confirmed, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
                else:
                    LOG.info("    -> not-scam (%s) purged", level)
                    _purge(db, vid)
            except Exception as e:
                LOG.warning("    failed %s: %s", url[:60], str(e)[:120])

    LOG.info("")
    LOG.info("=== TikTok collection complete: %d/%d confirmed scams ===",
             len(confirmed), args.target)
    if confirmed:
        LOG.info("Manifest: %s", manifest.resolve())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=int, default=15, help="target number of confirmed scams")
    p.add_argument("--per-tag", type=int, default=20, help="videos to check per hashtag")
    asyncio.run(main(p.parse_args()))
