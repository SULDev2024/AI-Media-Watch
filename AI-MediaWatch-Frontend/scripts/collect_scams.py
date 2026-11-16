"""Collect candidate scam videos from YouTube and confirm them with the judge.

Searches scam-targeting queries via yt-dlp, runs each candidate through the
FULL pipeline (download -> Whisper transcribe -> entities -> signals -> score ->
LLM judge), and keeps the ones the judge confirms as fraud *promotions*.

"Really scam" is decided by the LLM judge (intent=promotion / risk HIGH-CRITICAL),
never asserted by hand. Usage:

    python scripts/collect_scams.py --target 40 --max-candidates 120
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("collect_scams")
# Quiet the noisy libraries
for noisy in ("aiosqlite", "httpx", "faster_whisper", "aimw.collection.ytdlp"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

# Scam-targeting search queries across the genres + languages the system handles.
QUERIES = [
    "elon musk bitcoin giveaway live",
    "double your bitcoin send crypto",
    "guaranteed daily profit crypto investment",
    "forex trading bot guaranteed profit",
    "crypto trading signals telegram join",
    "passive income crypto guaranteed returns",
    "earn 500 dollars a day online easy money",
    "binary options guaranteed win strategy",
    "usdt arbitrage bot passive income",
    "join my mlm team financial freedom",
    "pyramid scheme recruit downline earn",
    "free cash app money flip legit",
    "инвестиции крипто гарантированный доход",
    "пассивный доход крипто схема заработка",
    "earn money online investment app guaranteed",
    "telegram crypto pump signal profit",
]


async def main(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("AIMW_GROQ_DAILY_TOKEN_CAP", "5000000")
    # Cap media length so a stray long stream can't stall the crawl; scam
    # promos are short. 15 min default, overridable via --max-duration.
    os.environ["AIMW_MAX_DOWNLOAD_DURATION_S"] = str(args.max_duration)

    from aimw.core.config import get_settings
    get_settings.cache_clear()

    import datetime as dt
    from aimw.collection.collector import search_candidates
    from aimw.workers.enqueue import derive_video_id, classify_platform
    from aimw.workers.pipeline import run_pipeline
    from aimw.db.session import get_sessionmaker
    from aimw.db.repositories.packages import PackagesRepository
    from aimw.db.repositories.videos import VideosRepository
    from aimw.scoring.registry import register

    register()
    sm = get_sessionmaker()
    packages = PackagesRepository(sm)
    videos = VideosRepository(sm)

    # ── Phase 1: discover candidate URLs ────────────────────────────────────
    LOG.info("Searching %d queries for candidates...", len(QUERIES))
    candidates: list[str] = []
    seen: set[str] = set()
    per_query = max(5, args.max_candidates // len(QUERIES) + 2)
    for q in QUERIES:
        try:
            urls = await asyncio.get_event_loop().run_in_executor(
                None, lambda q=q: search_candidates(q, limit=per_query)
            )
        except Exception as e:
            LOG.warning("search failed for %r: %s", q, e)
            urls = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                candidates.append(u)
        if len(candidates) >= args.max_candidates:
            break
    LOG.info("Discovered %d unique candidate URLs", len(candidates))

    # ── Phase 2: run each through the pipeline, keep judge-confirmed scams ───
    confirmed: list[dict] = []
    processed = 0
    manifest_path = Path("collected_scams_manifest.json")

    for url in candidates:
        if len(confirmed) >= args.target:
            break
        processed += 1
        import sqlite3
        db_path = os.environ.get("AIMW_SQLITE_PATH", "data/aimw.db")

        def _verdict(vid: str):
            rconn = sqlite3.connect(db_path, timeout=30)
            try:
                cur = rconn.execute(
                    "SELECT risk_level, score, action FROM evidence_packages "
                    "WHERE video_id=? ORDER BY processed_at DESC LIMIT 1", (vid,))
                return cur.fetchone()
            finally:
                rconn.close()

        def _purge(vid: str) -> None:
            """Remove a non-scam video and every row that references it, so the
            collected corpus holds ONLY judge-verified scams."""
            conn = sqlite3.connect(db_path, timeout=30)
            try:
                rids = [r[0] for r in conn.execute(
                    "SELECT report_id FROM evidence_packages WHERE video_id=?", (vid,))]
                for rid in rids:
                    for tbl in ("evidence_pieces", "entities", "network_connections",
                                "reports", "analyst_feedback"):
                        conn.execute(f"DELETE FROM {tbl} WHERE report_id=?", (rid,))
                    conn.execute(
                        "UPDATE regression_cases SET frozen_from_report=NULL "
                        "WHERE frozen_from_report=?", (rid,))
                conn.execute("DELETE FROM evidence_packages WHERE video_id=?", (vid,))
                conn.execute("DELETE FROM videos WHERE id=?", (vid,))
                conn.commit()
            finally:
                conn.close()

        try:
            video_id = derive_video_id(url)
            existing = _verdict(video_id)
            if existing is not None:
                LOG.info("[%d/%d | confirmed %d] cached %s", processed, len(candidates),
                         len(confirmed), video_id)
                rrow = existing
            else:
                # Direct upsert (no Celery broker kick → avoids Redis retry stalls).
                await videos.upsert(
                    id=video_id, platform=classify_platform(url), url=url,
                    collected_at=dt.datetime.now(dt.UTC),
                )
                LOG.info("[%d/%d | confirmed %d] processing %s (%s)",
                         processed, len(candidates), len(confirmed), video_id, url)
                await run_pipeline(video_id)
                rrow = _verdict(video_id)
            if not rrow:
                continue
            level = rrow[0] or "?"
            score = rrow[1] or 0.0
            action = rrow[2] or "?"
            # Only the LLM judge "verifies" fraud (action='report'); a rules-only
            # HIGH is a keyword match that over-flags education/news → not kept.
            is_scam = action == "report"
            if is_scam:
                LOG.info("    -> SCAM KEPT level=%s score=%.2f action=%s", level, score, action)
                confirmed.append({
                    "video_id": video_id, "url": url,
                    "risk_level": level, "score": round(score, 3), "action": action,
                })
                manifest_path.write_text(
                    json.dumps(confirmed, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            else:
                # Not a verified scam → purge it so the corpus holds only scams.
                _purge(video_id)
                LOG.info("    -> not-scam PURGED level=%s score=%.2f", level, score)
        except Exception as e:
            LOG.warning("    pipeline failed for %s: %s", url, str(e)[:140])

    # ── Report ──────────────────────────────────────────────────────────────
    LOG.info("")
    LOG.info("=== Collection complete ===")
    LOG.info("Candidates processed: %d", processed)
    LOG.info("Confirmed scams: %d / target %d", len(confirmed), args.target)
    LOG.info("Manifest: %s", manifest_path.resolve())
    for c in confirmed:
        LOG.info("  %s %s(%.2f) %s", c["video_id"], c["risk_level"], c["score"], c["url"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=int, default=40, help="confirmed scams to collect")
    p.add_argument("--max-candidates", type=int, default=120, help="candidate URLs cap")
    p.add_argument("--max-duration", type=float, default=900.0,
                   help="skip videos longer than this many seconds (default 900 = 15 min)")
    asyncio.run(main(p.parse_args()))
