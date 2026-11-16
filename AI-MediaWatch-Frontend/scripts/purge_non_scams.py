"""Purge non-scam videos so the corpus holds ONLY judge-verified scams.

Deletes every video whose latest verdict is NOT HIGH/CRITICAL (i.e. CLEAN, LOW,
MEDIUM, FAILED, or unscored) along with all rows that reference it. Verified
scams (HIGH/CRITICAL) are kept.

    python scripts/purge_non_scams.py            # purge
    python scripts/purge_non_scams.py --dry-run  # show what would go
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

KEEP_LEVELS = ("HIGH", "CRITICAL")
_CHILD_TABLES = ("evidence_pieces", "entities", "network_connections",
                 "reports", "analyst_feedback")


def main(dry_run: bool) -> None:
    db = os.environ.get("AIMW_SQLITE_PATH", "data/aimw.db")
    conn = sqlite3.connect(db, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")

    # Latest verdict per video; keep only HIGH/CRITICAL.
    rows = conn.execute(
        """
        SELECT v.id, ep.risk_level
        FROM videos v
        LEFT JOIN evidence_packages ep ON ep.video_id = v.id
        """
    ).fetchall()
    # A video is a "scam" if ANY of its packages is HIGH/CRITICAL.
    scam_ids = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT video_id FROM evidence_packages "
            "WHERE risk_level IN ('HIGH','CRITICAL')"
        )
    }
    all_ids = {r[0] for r in rows}
    purge_ids = sorted(all_ids - scam_ids)

    print(f"total videos: {len(all_ids)}  | verified scams kept: {len(scam_ids)}  "
          f"| to purge: {len(purge_ids)}")
    if dry_run:
        print("(dry-run — nothing deleted)")
        conn.close()
        return

    purged = 0
    for vid in purge_ids:
        rids = [r[0] for r in conn.execute(
            "SELECT report_id FROM evidence_packages WHERE video_id=?", (vid,))]
        for rid in rids:
            for tbl in _CHILD_TABLES:
                conn.execute(f"DELETE FROM {tbl} WHERE report_id=?", (rid,))
            conn.execute(
                "UPDATE regression_cases SET frozen_from_report=NULL "
                "WHERE frozen_from_report=?", (rid,))
        conn.execute("DELETE FROM evidence_packages WHERE video_id=?", (vid,))
        conn.execute("DELETE FROM videos WHERE id=?", (vid,))
        purged += 1
    conn.commit()

    remaining = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    kept_scams = conn.execute(
        "SELECT COUNT(DISTINCT video_id) FROM evidence_packages "
        "WHERE risk_level IN ('HIGH','CRITICAL')").fetchone()[0]
    conn.close()
    print(f"purged {purged} non-scam videos. remaining videos: {remaining} "
          f"(verified scams: {kept_scams})")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    main(p.parse_args().dry_run)
