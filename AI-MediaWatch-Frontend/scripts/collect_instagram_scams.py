"""Collect scam reels from Instagram by hashtag, using Instaloader.

Instagram blocks ALL anonymous access (hashtag browsing returns
"login_required"), so this needs a logged-in session — exactly like the
Telegram collector. ONE-TIME setup (you do this, never share the password):

    uv run --no-project --with instaloader instaloader --login YOUR_IG_USERNAME

That saves a session file Instaloader reuses. Then:

    python scripts/collect_instagram_scams.py --login YOUR_IG_USERNAME --target 15

For each scam-hashtag video reel it judges the CAPTION (fast); clips the LLM
judge confirms as fraud are downloaded + kept (verified-only, same policy as the
other collectors). The judge reads the caption + hashtag context.
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
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("collect_ig")
for noisy in ("aiosqlite", "httpx", "instaloader"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

HASHTAGS = [
    "cryptotrading", "forex", "investment", "binaryoptions", "forexsignals",
    "cryptoinvestment", "tradingbot", "passiveincome", "makemoneyonline",
    "bitcoininvestment", "forextrader", "investmentopportunity",
]
_CHILD = ("evidence_pieces", "entities", "network_connections", "reports", "analyst_feedback")


def _persist_caption_scam(db, vid, url, caption, score, conf, rationale, raw_path):
    rid = "rpt-" + hashlib.sha256(vid.encode()).hexdigest()[:16]
    now = dt.datetime.now(dt.UTC).isoformat()
    pkg = {
        "report_id": rid, "video_id": vid, "platform": "instagram", "url": url,
        "collected_at": now, "processed_at": now, "schema_version": "4.0.0",
        "evidence": [{"source": "speech", "polarity": "incriminating", "strength": "strong",
                      "indicator_type": "caption_fraud_promotion", "raw_value": caption[:300],
                      "timestamp": 0.0, "content": caption[:300], "regulation_ref": None,
                      "recovery_method": "raw"}],
        "entities": {"crypto_wallets": [], "payment_phones": [], "phone_numbers": [],
                     "phone_purposes": {}, "profit_claims": [], "referral_codes": [],
                     "telegram_handles": [], "telegram_links": []},
        "network_connections": [],
    }
    md = (f"## AI judge verdict — HIGH\n\n**Intent:** promotion  ·  **Fraud promotion:** YES  ·  "
          f"**Confidence:** {round(conf*100)}%\n\n{rationale}\n\n**Flagged caption:** \"{caption[:400]}\"")
    c = sqlite3.connect(db, timeout=30)
    try:
        c.execute("INSERT OR REPLACE INTO evidence_packages (report_id, video_id, processed_at, "
                  "score, risk_level, confidence, action, schema_version, package_json) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (rid, vid, now, score, "HIGH", conf, "report", "4.0.0",
                   json.dumps(pkg, ensure_ascii=False)))
        c.execute("INSERT OR REPLACE INTO reports (report_id, markdown, generated_at) VALUES (?,?,?)",
                  (rid, md, now))
        c.commit()
    finally:
        c.close()


async def main(args):
    from dotenv import load_dotenv
    load_dotenv()
    os.environ.setdefault("AIMW_GROQ_DAILY_TOKEN_CAP", "5000000")
    import instaloader
    from aimw.core.config import get_settings
    get_settings.cache_clear()
    cfg = get_settings()
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
    media_dir = cfg.resolved_media_dir
    media_dir.mkdir(parents=True, exist_ok=True)

    L = instaloader.Instaloader(quiet=True, download_videos=True, save_metadata=False,
                                download_comments=False, post_metadata_txt_pattern="")
    try:
        L.load_session_from_file(args.login)
        LOG.info("Loaded Instagram session for @%s", args.login)
    except Exception as e:
        LOG.error("No saved session for @%s — run first:\n"
                  "  uv run --no-project --with instaloader instaloader --login %s\n(%s)",
                  args.login, args.login, str(e)[:80])
        return

    judge = build_chat_client(UsageRepository(sm))
    now = dt.datetime(2026, 6, 15, tzinfo=dt.UTC)

    def pkg(rid):
        return EvidencePackage(report_id=rid, video_id=rid, platform="instagram", url="x",
                               collected_at=now, processed_at=now, evidence=[],
                               entities=ExtractedEntities())

    confirmed = []
    manifest = Path("collected_instagram_scams_manifest.json")
    for tag in HASHTAGS:
        if len(confirmed) >= args.target:
            break
        LOG.info("Hashtag #%s", tag)
        try:
            posts = instaloader.Hashtag.from_name(L.context, tag).get_posts()
        except Exception as e:
            LOG.warning("  hashtag failed: %s", str(e)[:100])
            continue
        seen = 0
        for post in posts:
            if len(confirmed) >= args.target or seen >= args.per_tag:
                break
            seen += 1
            if not post.is_video:
                continue
            caption = (post.caption or "").strip()
            if len(caption) < 15:
                continue
            url = f"https://www.instagram.com/reel/{post.shortcode}/"
            try:
                v = await classify(pkg("scr-" + post.shortcode), caption, judge,
                                   title=f"Instagram reel tagged #{tag}", channel="instagram")
                if not v.is_fraud_promotion:
                    LOG.info("  skip %s: intent=%s", post.shortcode, v.intent)
                    continue
                # caption confirmed fraud → download the reel + keep
                with tempfile.TemporaryDirectory() as tmp:
                    L.download_post(post, target=Path(tmp).name) if False else None
                    # download just the video file
                    vurl = post.video_url
                    import urllib.request
                    data = urllib.request.urlopen(vurl, timeout=30).read()
                vid = "vid-" + hashlib.sha256(data).hexdigest()[:16]
                fpath = media_dir / f"{vid}.mp4"
                fpath.write_bytes(data)
                await videos.upsert(id=vid, platform="instagram", url=url,
                                    collected_at=dt.datetime.now(dt.UTC), raw_path=str(fpath))
                await videos.update_transcript(vid, json.dumps(
                    [{"text": caption, "start": 0, "end": 0}], ensure_ascii=False))
                score = (getattr(v, "risk_score", 0) or 90) / 100.0
                _persist_caption_scam(db, vid, url, caption, score, float(v.confidence),
                                      v.rationale, str(fpath))
                LOG.info("  [%d] SCAM KEPT %s score=%.2f %s", len(confirmed) + 1,
                         post.shortcode, score, url)
                confirmed.append({"url": url, "score": round(score, 3), "caption": caption[:200]})
                manifest.write_text(json.dumps(confirmed, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
            except Exception as e:
                LOG.warning("  item failed %s: %s", post.shortcode, str(e)[:100])

    LOG.info("=== complete: %d Instagram scams ===", len(confirmed))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--login", required=True, help="your Instagram username (session must exist)")
    p.add_argument("--target", type=int, default=15)
    p.add_argument("--per-tag", type=int, default=30)
    asyncio.run(main(p.parse_args()))
