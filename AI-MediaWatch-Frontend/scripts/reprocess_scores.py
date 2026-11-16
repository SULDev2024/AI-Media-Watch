"""Reprocess all evidence packages: rescore with current engine + run LLM judge.

Usage:
    python scripts/reprocess_scores.py [--judge] [--dry-run] [--limit N]

Without --judge: only rescores using the current engine rules (fast, no API calls).
With --judge: also runs the LLM fraud-intent judge on each video's transcript.
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

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOG = logging.getLogger("reprocess")


async def main(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    import sqlite3
    from aimw.core.schema.evidence import EvidencePackage
    from aimw.scoring.engine import score as score_pkg
    from aimw.scoring.registry import register

    register()

    db_path = os.environ.get("AIMW_SQLITE_PATH", "data/aimw.db")

    # Phase 1: Read all data into memory, then CLOSE the connection.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = """
        SELECT ep.report_id, ep.video_id, ep.score, ep.risk_level, ep.action,
               ep.package_json, v.transcript_segments, v.url
        FROM evidence_packages ep
        JOIN videos v ON ep.video_id = v.id
        WHERE v.url LIKE 'https://www.youtube.com%'
        AND ep.package_json IS NOT NULL
    """
    if args.limit:
        query += f" LIMIT {args.limit}"

    cur.execute(query)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()  # CLOSE before any async SQLAlchemy work
    LOG.info("Loaded %d YouTube evidence packages", len(rows))

    # Prepare LLM judge if requested
    judge_client = None
    if args.judge:
        groq_key = os.environ.get("AIMW_GROQ_API_KEY", "")
        if not groq_key:
            LOG.warning("--judge requested but AIMW_GROQ_API_KEY not set; skipping judge")
        else:
            try:
                from aimw.core.config import get_settings
                get_settings.cache_clear()
                from aimw.db.session import get_sessionmaker
                from aimw.db.repositories.usage import UsageRepository
                from aimw.reasoning.client import build_chat_client
                judge_client = build_chat_client(UsageRepository(get_sessionmaker()))
                LOG.info("LLM judge client initialized (model: %s)", get_settings().groq_model)
            except Exception as e:
                LOG.error("Failed to init judge client: %s", e)

    updates: list[tuple] = []
    judge_count = 0
    errors = 0
    level_changes: dict[str, int] = {}

    for i, row in enumerate(rows):
        report_id = row["report_id"]
        video_id = row["video_id"]
        db_level = row["risk_level"]
        db_score = row["score"]
        pkg_json = row["package_json"]
        transcript_segs = row["transcript_segments"]
        url = row["url"]

        try:
            pkg_data = json.loads(pkg_json)
            for key in ["schema_version", "score", "risk_level", "confidence",
                        "action", "status_note", "llm_verdict", "llm_reasoning",
                        "referee_result"]:
                pkg_data.pop(key, None)

            ep = EvidencePackage.model_validate(pkg_data)
            bd = score_pkg(ep)

            new_level = bd.level
            new_score = round(bd.final_score, 6)
            new_confidence = None
            is_fraud = None

            # Run LLM judge if requested and transcript available
            verdict = None
            if judge_client and transcript_segs:
                try:
                    segs = json.loads(transcript_segs)
                    text = " ".join(s.get("text", "") for s in segs if s.get("text"))
                    if text.strip() and len(text) > 20:
                        from aimw.reasoning.judge import classify
                        for attempt in range(4):
                            try:
                                verdict = await classify(
                                    ep, text, judge_client,
                                    title="", channel="youtube"
                                )
                                break
                            except Exception as retry_err:
                                err_str = str(retry_err)
                                if ("429" in err_str or "database is locked" in err_str) and attempt < 3:
                                    wait = 15 * (attempt + 1)
                                    LOG.info("  [%d/%d] Retrying in %ds (%s)...",
                                             i+1, len(rows), wait, "429" if "429" in err_str else "db_lock")
                                    await asyncio.sleep(wait)
                                else:
                                    raise
                        if verdict:
                            judge_count += 1
                            new_level = verdict.risk_level
                            rs = getattr(verdict, "risk_score", 0) or 0
                            new_score = rs / 100.0 if rs else new_score
                            new_confidence = float(verdict.confidence)
                            is_fraud = verdict.is_fraud_promotion
                            LOG.info(
                                "  [%d/%d] JUDGE %s: intent=%s level=%s score=%d conf=%.0f%% — %s",
                                i+1, len(rows), video_id, verdict.intent,
                                verdict.risk_level, verdict.risk_score,
                                verdict.confidence * 100,
                                verdict.rationale[:80],
                            )
                            await asyncio.sleep(8)
                except Exception as e:
                    LOG.warning("  [%d/%d] Judge failed %s: %s", i+1, len(rows), video_id, str(e)[:120])

            # Determine action
            if verdict:
                action = "report" if is_fraud else "clear"
            elif new_level in ("HIGH", "CRITICAL"):
                action = "report"
            elif new_level == "MEDIUM":
                action = "monitor"
            else:
                action = "suppress"

            if db_level != new_level or verdict:
                change = f"{db_level or 'NULL'}->{new_level}"
                if db_level != new_level:
                    level_changes[change] = level_changes.get(change, 0) + 1
                updates.append((new_score, new_level, new_confidence, action, report_id))

                if not verdict and db_level != new_level:
                    LOG.info(
                        "  [%d/%d] %s: %s(%.2f) -> %s(%.2f) [RULES] %s",
                        i+1, len(rows), video_id, db_level, db_score or 0,
                        new_level, new_score, url,
                    )

        except Exception as e:
            LOG.error("  ERROR %s: %s", video_id, e)
            errors += 1

    # Phase 3: Write all updates in one batch (with retry for DB locking)
    if updates and not args.dry_run:
        for write_attempt in range(5):
            try:
                wconn = sqlite3.connect(db_path, timeout=30)
                wconn.execute("PRAGMA journal_mode=WAL")
                for new_score, new_level, new_conf, action, report_id in updates:
                    if new_conf is not None:
                        wconn.execute(
                            "UPDATE evidence_packages SET score=?, risk_level=?, confidence=?, action=? WHERE report_id=?",
                            (new_score, new_level, new_conf, action, report_id),
                        )
                    else:
                        wconn.execute(
                            "UPDATE evidence_packages SET score=?, risk_level=?, action=? WHERE report_id=?",
                            (new_score, new_level, action, report_id),
                        )
                wconn.commit()
                wconn.close()
                LOG.info("Wrote %d updates to DB", len(updates))
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and write_attempt < 4:
                    LOG.warning("DB locked on write, retrying in 5s (attempt %d)...", write_attempt + 1)
                    await asyncio.sleep(5)
                else:
                    raise

    LOG.info("")
    LOG.info("=== Reprocessing Summary ===")
    LOG.info("Total packages: %d", len(rows))
    LOG.info("DB updates: %d", len(updates))
    LOG.info("Judge verdicts: %d", judge_count)
    LOG.info("Errors: %d", errors)
    if level_changes:
        LOG.info("Level changes:")
        for change, count in sorted(level_changes.items()):
            LOG.info("  %s: %d", change, count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reprocess evidence packages")
    parser.add_argument("--judge", action="store_true", help="Run LLM fraud-intent judge")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    parser.add_argument("--limit", type=int, help="Process only N packages")
    args = parser.parse_args()
    asyncio.run(main(args))
