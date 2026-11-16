"""Collect scams from ANY platform by URL or account — TikTok, Instagram,
Facebook, YouTube, Telegram clips.

These platforms have NO keyword search (closed to crawlers). What DOES work:
  * Analyze specific video URLs you paste.
  * Expand a TikTok account: give one video/handle, pull the whole catalog.
  * Login-gated platforms (Instagram/Facebook): set AIMW_COOKIES_FILE to a
    cookies.txt exported from your browser.

Each video is downloaded, transcribed, judged, and kept only if the LLM judge
confirms fraud (verified-only, same policy as the other collectors).

Usage:
    # analyze a list of URLs (any platform)
    python scripts/collect_url_scams.py --urls "https://www.tiktok.com/@x/video/1,https://..."
    # expand a TikTok account from one of its videos (or @handle)
    python scripts/collect_url_scams.py --tiktok-account "https://www.tiktok.com/@scammer/video/123" --max 25
    # Instagram/Facebook (needs cookies)
    AIMW_COOKIES_FILE=cookies.txt python scripts/collect_url_scams.py --urls "https://www.instagram.com/reel/.../"
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
LOG = logging.getLogger("collect_url")
for noisy in ("aiosqlite", "httpx", "faster_whisper"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

_CHILD = ("evidence_pieces", "entities", "network_connections", "reports", "analyst_feedback")


def _resolve_urls(args) -> list[str]:
    """Build the list of video URLs to process from --urls and --tiktok-account."""
    import yt_dlp

    urls: list[str] = []
    if args.urls:
        urls += [u.strip() for u in args.urls.split(",") if u.strip()]
    if args.tiktok_account:
        seed = args.tiktok_account.strip()
        try:
            # Resolve the channel_id from the seed (a video URL or @handle), then
            # list the account's recent videos.
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                   "skip_download": True}) as y:
                info = y.extract_info(seed, download=False)
            cid = info.get("channel_id") or info.get("uploader_id")
            if not cid:
                LOG.warning("could not resolve TikTok channel_id from %s", seed)
            else:
                LOG.info("TikTok account: %s (channel_id=%s)", info.get("uploader"), cid[:20])
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                       "extract_flat": True,
                                       "playlist_items": f"1-{args.max}"}) as y:
                    lst = y.extract_info(f"tiktokuser:{cid}", download=False)
                for e in (lst or {}).get("entries") or []:
                    u = e.get("url") or (f"https://www.tiktok.com/@x/video/{e.get('id')}"
                                         if e.get("id") else None)
                    if u:
                        urls.append(u)
        except Exception as e:
            LOG.warning("TikTok account expansion failed: %s", str(e)[:140])
    # dedupe, preserve order
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[: args.max]


def _purge(db: str, vid: str) -> None:
    c = sqlite3.connect(db, timeout=30)
    try:
        for rid in [x[0] for x in c.execute(
                "SELECT report_id FROM evidence_packages WHERE video_id=?", (vid,))]:
            for t in _CHILD:
                c.execute(f"DELETE FROM {t} WHERE report_id=?", (rid,))
            c.execute("UPDATE regression_cases SET frozen_from_report=NULL "
                      "WHERE frozen_from_report=?", (rid,))
        c.execute("DELETE FROM evidence_packages WHERE video_id=?", (vid,))
        c.execute("DELETE FROM videos WHERE id=?", (vid,))
        c.commit()
    finally:
        c.close()


async def main(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("AIMW_GROQ_DAILY_TOKEN_CAP", "5000000")
    if args.cookies:
        os.environ["AIMW_COOKIES_FILE"] = args.cookies

    import datetime as dt
    from aimw.core.config import get_settings
    get_settings.cache_clear()
    from aimw.workers.enqueue import derive_video_id, classify_platform
    from aimw.workers.pipeline import run_pipeline
    from aimw.db.session import get_sessionmaker
    from aimw.db.repositories.videos import VideosRepository
    from aimw.scoring.registry import register
    register()
    sm = get_sessionmaker()
    videos = VideosRepository(sm)
    db = os.environ.get("AIMW_SQLITE_PATH", "data/aimw.db")

    urls = _resolve_urls(args)
    LOG.info("Resolved %d candidate URLs", len(urls))
    if not urls:
        LOG.error("No URLs to process. Pass --urls or --tiktok-account.")
        return

    confirmed: list[dict] = []
    manifest = Path("collected_url_scams_manifest.json")
    for i, url in enumerate(urls, 1):
        try:
            vid = derive_video_id(url)
            await videos.upsert(id=vid, platform=classify_platform(url), url=url,
                                collected_at=dt.datetime.now(dt.UTC))
            LOG.info("[%d/%d] processing %s", i, len(urls), url)
            await run_pipeline(vid)
            rconn = sqlite3.connect(db, timeout=30)
            try:
                row = rconn.execute(
                    "SELECT risk_level, score, action FROM evidence_packages "
                    "WHERE video_id=? ORDER BY processed_at DESC LIMIT 1", (vid,)).fetchone()
            finally:
                rconn.close()
            if not row:
                continue
            level, score, action = row[0] or "?", row[1] or 0.0, row[2] or "?"
            if action == "report" or level in ("HIGH", "CRITICAL"):
                LOG.info("    -> SCAM KEPT %s(%.2f) %s", level, score, url)
                confirmed.append({"url": url, "risk_level": level, "score": round(score, 3)})
                manifest.write_text(json.dumps(confirmed, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
            else:
                LOG.info("    -> not-scam (%s) purged", level)
                _purge(db, vid)
        except Exception as e:
            LOG.warning("    failed %s: %s", url, str(e)[:140])

    LOG.info("")
    LOG.info("=== complete: %d/%d confirmed scams ===", len(confirmed), len(urls))
    LOG.info("Manifest: %s", manifest.resolve())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--urls", help="comma-separated video URLs (any platform)")
    p.add_argument("--tiktok-account", help="a TikTok video URL or @handle to expand into its catalog")
    p.add_argument("--cookies", help="path to a cookies.txt (for Instagram/Facebook)")
    p.add_argument("--max", type=int, default=30, help="max videos to process")
    asyncio.run(main(p.parse_args()))
