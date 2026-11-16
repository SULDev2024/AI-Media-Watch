"""Re-analyze FAILED pipeline entries — run after fixing the Whisper IndexError bug."""
import asyncio
import sqlite3
from pathlib import Path

# Load .env before anything else imports settings
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aimw.workers.pipeline import run_pipeline
from aimw.db.session import get_engine, get_sessionmaker


async def main() -> None:
    # Ensure engine is initialized
    get_engine()
    get_sessionmaker()

    con = sqlite3.connect("data/aimw.db")
    cur = con.cursor()
    cur.execute("SELECT DISTINCT video_id FROM evidence_packages WHERE risk_level='FAILED'")
    ids = [r[0] for r in cur.fetchall()]
    print(f"Re-analyzing {len(ids)} failed video(s)...")

    for vid in ids:
        try:
            report_id = await run_pipeline(vid)
            print(f"  OK  {vid} -> {report_id[:24]}")
        except Exception as exc:
            print(f"  ERR {vid}: {exc}")

    # Show new verdict distribution
    cur.execute(
        "SELECT risk_level, COUNT(*) FROM evidence_packages GROUP BY risk_level ORDER BY risk_level"
    )
    print("\nVerdict distribution after re-analysis:")
    for row in cur.fetchall():
        print(f"  {row[0]:10s}  {row[1]}")


if __name__ == "__main__":
    asyncio.run(main())
