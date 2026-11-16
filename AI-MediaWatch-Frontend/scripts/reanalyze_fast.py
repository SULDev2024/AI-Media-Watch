"""Re-analyze all videos, SMALLEST (shortest) first so verdicts appear fast.

The full pipeline's frame-walk cost scales with video length, so processing
short clips first surfaces HIGH/CRITICAL verdicts in the queue within minutes
instead of waiting hours behind one long video.
"""
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aimw.db.session import get_engine, get_sessionmaker  # noqa: E402
from aimw.workers.pipeline import run_pipeline  # noqa: E402


async def main() -> None:
    get_engine()
    get_sessionmaker()

    con = sqlite3.connect("data/aimw.db")
    cur = con.cursor()

    # Order videos by media file size ascending (short clips first).
    rows = cur.execute("SELECT id, url, platform, raw_path FROM videos").fetchall()
    sized = []
    for vid, url, platform, raw in rows:
        size = os.path.getsize(raw) if raw and os.path.exists(raw) else 1 << 60
        sized.append((size, vid, url, platform))
    sized.sort()

    print(f"Analyzing {len(sized)} videos, smallest-first...\n", flush=True)
    ok = fail = purged = 0
    for i, (size, vid, url, platform) in enumerate(sized, 1):
        mb = size / 1024 / 1024 if size < (1 << 60) else -1
        print(f"[{i}/{len(sized)}] {mb:6.1f}MB {platform} {url[:48]}", flush=True)
        try:
            report_id = await run_pipeline(vid)
            # Was it kept or auto-purged?
            still = cur.execute(
                "SELECT risk_level FROM evidence_packages WHERE report_id=?", (report_id,)
            ).fetchone()
            if still:
                print(f"   -> {still[0]}", flush=True)
                ok += 1
            else:
                print("   -> purged (LOW/CLEAN)", flush=True)
                purged += 1
        except Exception as exc:  # noqa: BLE001
            print(f"   -> ERR {type(exc).__name__}: {str(exc)[:100]}", flush=True)
            fail += 1

    print(f"\nDone: {ok} kept, {purged} purged, {fail} failed", flush=True)
    print("\nFinal verdict distribution:", flush=True)
    for row in cur.execute(
        "SELECT risk_level, COUNT(*) FROM evidence_packages GROUP BY risk_level"
    ):
        print(f"  {row[0]}: {row[1]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
