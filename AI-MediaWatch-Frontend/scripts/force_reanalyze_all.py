"""Force re-analyze all non-FAILED videos with the current LLM model (70b).

Bypasses the idempotency guard by deleting existing evidence packages first,
then runs run_pipeline for each video. Also:
- Removes duplicate videos (same URL, keep the one with a package)
- Removes stale FAILED packages
"""
import asyncio
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aimw.db.session import get_engine, get_sessionmaker, writer_lock
from aimw.db.models import EvidencePackageRow
from aimw.workers.pipeline import run_pipeline
from sqlalchemy import delete, select


async def main() -> None:
    get_engine()
    sm = get_sessionmaker()

    con = sqlite3.connect("data/aimw.db")
    cur = con.cursor()

    # --- 1. Remove duplicate YouTube videos (keep the one with a package) ---
    cur.execute("SELECT url, GROUP_CONCAT(id) FROM videos GROUP BY url HAVING COUNT(*) > 1")
    for url, ids_str in cur.fetchall():
        ids = ids_str.split(",")
        # Keep the id that has a non-FAILED package
        cur.execute(
            f"SELECT video_id FROM evidence_packages WHERE video_id IN ({','.join('?'*len(ids))}) AND risk_level != 'FAILED' LIMIT 1",
            ids
        )
        row = cur.fetchone()
        keeper = row[0] if row else ids[0]
        to_remove = [i for i in ids if i != keeper]
        for vid in to_remove:
            cur.execute("DELETE FROM evidence_packages WHERE video_id=?", (vid,))
            cur.execute("DELETE FROM videos WHERE id=?", (vid,))
            print(f"  Removed duplicate: {vid} ({url[:60]})")
    con.commit()

    # --- 2. Delete all FAILED packages (pipeline fix makes them retryable) ---
    cur.execute("DELETE FROM evidence_packages WHERE risk_level='FAILED'")
    n_failed = cur.rowcount
    con.commit()
    print(f"Removed {n_failed} FAILED packages")

    # --- 3. Force re-analyze all remaining videos ---
    cur.execute("SELECT id, url, platform FROM videos ORDER BY platform, id")
    all_videos = cur.fetchall()
    print(f"Re-analyzing {len(all_videos)} video(s) with 70b model...\n")

    # Delete existing packages so pipeline runs fresh
    for vid, url, platform in all_videos:
        cur.execute("DELETE FROM evidence_packages WHERE video_id=?", (vid,))
    con.commit()

    ok, fail = 0, 0
    for i, (vid, url, platform) in enumerate(all_videos, 1):
        print(f"[{i}/{len(all_videos)}] {platform} {url[:55]}")
        try:
            report_id = await run_pipeline(vid)
            print(f"  -> OK {report_id[:28]}")
            ok += 1
        except Exception as exc:
            print(f"  -> ERR {type(exc).__name__}: {str(exc)[:120]}")
            fail += 1

    print(f"\nDone: {ok} OK, {fail} failed")

    # --- 4. Final verdict distribution ---
    cur.execute("SELECT risk_level, COUNT(*) FROM evidence_packages GROUP BY risk_level ORDER BY risk_level")
    print("\nFinal verdict distribution:")
    for row in cur.fetchall():
        print(f"  {row[0]:10s}  {row[1]}")


if __name__ == "__main__":
    asyncio.run(main())
