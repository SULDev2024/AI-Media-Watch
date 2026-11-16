"""Force-rerun the pipeline for every video so verdicts use the current LLM.

When AIMW_LLM_BASE_URL points at your private Ollama server, run this once
to refresh existing queue verdicts from whatever the old judge produced
(Groq, rules-only, etc.) to the qwen2.5vl-backed verdict.

The pipeline's idempotency guard skips already-judged videos, so we delete
the existing evidence_packages row for each video first, then re-invoke
run_pipeline — which will land HIGH/CRITICAL verdicts back on the queue
and auto-purge LOW/CLEAN per the standard policy.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
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

    # Order by file size ascending → shortest videos first → fast first feedback.
    rows = cur.execute(
        "SELECT id, url, platform, raw_path FROM videos"
    ).fetchall()
    import os as _os
    sized = []
    for vid, url, platform, raw in rows:
        size = _os.path.getsize(raw) if raw and _os.path.exists(raw) else 1 << 60
        sized.append((size, vid, url, platform))
    sized.sort()

    print(f"Re-judging {len(sized)} videos with current LLM...", flush=True)
    ok = fail = purged = 0
    for i, (size, vid, url, platform) in enumerate(sized, 1):
        mb = size / 1024 / 1024 if size < (1 << 60) else -1
        print(f"\n[{i}/{len(sized)}] {mb:6.1f}MB {platform} {url[:50]}", flush=True)

        # Drop the existing package so the idempotency guard re-runs the judge.
        cur.execute("DELETE FROM evidence_packages WHERE video_id=?", (vid,))
        con.commit()

        t0 = time.perf_counter()
        try:
            rid = await run_pipeline(vid)
            dt = time.perf_counter() - t0
            still = cur.execute(
                "SELECT risk_level, action FROM evidence_packages WHERE report_id=?",
                (rid,),
            ).fetchone()
            if still:
                print(f"   -> {still[0]} ({still[1]}) in {dt:.1f}s", flush=True)
                ok += 1
            else:
                print(f"   -> purged in {dt:.1f}s", flush=True)
                purged += 1
        except Exception as exc:  # noqa: BLE001
            dt = time.perf_counter() - t0
            print(f"   -> ERR {type(exc).__name__}: {str(exc)[:120]} ({dt:.1f}s)", flush=True)
            fail += 1

    print(f"\nDone: {ok} kept, {purged} purged, {fail} failed", flush=True)
    for row in cur.execute(
        "SELECT risk_level, COUNT(*) FROM evidence_packages GROUP BY risk_level"
    ):
        print(f"  {row[0]}: {row[1]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
