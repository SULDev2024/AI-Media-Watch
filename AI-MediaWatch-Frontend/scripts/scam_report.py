"""Generate a human-readable report of all judge-verified scams in the corpus.

Outputs SCAM_REPORT.md: every HIGH/CRITICAL video with its platform, URL,
risk score, judge verdict (intent / fraud / confidence), and the actual
flagged text — so a reviewer can confirm each is a real scam at a glance.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

DB = os.environ.get("AIMW_SQLITE_PATH", "data/aimw.db")
OUT = Path("SCAM_REPORT.md")


def _text_for(raw_path: str | None) -> str:
    if not raw_path:
        return ""
    p = Path(raw_path)
    # text message
    if p.suffix == ".txt" and p.exists():
        try:
            return p.read_text(encoding="utf-8").strip().replace("\n", " ")
        except Exception:
            return ""
    return ""


def _verdict_line(markdown: str | None) -> str:
    if not markdown:
        return ""
    for line in markdown.split("\n"):
        if "Intent:" in line and "Fraud promotion:" in line:
            return re.sub(r"\*\*", "", line).strip()
    return ""


def _rationale(markdown: str | None) -> str:
    if not markdown:
        return ""
    lines = markdown.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("## AI judge verdict"):
            # rationale is a few lines below the verdict header
            for j in range(i + 1, min(i + 8, len(lines))):
                s = lines[j].strip()
                if s and not s.startswith("**") and not s.startswith("#") and "Intent:" not in s:
                    return s[:300]
    return ""


def main() -> None:
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """
        SELECT v.platform, v.url, ep.score, ep.risk_level, ep.report_id, v.raw_path,
               v.transcript_segments
        FROM evidence_packages ep
        JOIN videos v ON ep.video_id = v.id
        WHERE ep.risk_level IN ('HIGH','CRITICAL')
        ORDER BY v.platform, ep.score DESC
        """
    ).fetchall()

    by_plat: dict[str, list] = {}
    for r in rows:
        by_plat.setdefault(r[0], []).append(r)

    lines = ["# Verified Scam Corpus", "",
             f"**{len(rows)} judge-verified scams** (HIGH/CRITICAL only). "
             "Each was classified by the LLM fraud-intent judge as a fraud promotion. "
             "The actual flagged text is shown so every entry can be confirmed by hand.", ""]

    for plat in sorted(by_plat):
        items = by_plat[plat]
        lines.append(f"## {plat.title()} — {len(items)} scams")
        lines.append("")
        for i, (p, url, score, level, rid, raw, segs) in enumerate(items, 1):
            md = conn.execute("SELECT markdown FROM reports WHERE report_id=?", (rid,)).fetchone()
            md = md[0] if md else None
            text = _text_for(raw)
            if not text and segs:
                try:
                    import json
                    text = " ".join(s.get("text", "") for s in json.loads(segs))[:280]
                except Exception:
                    text = ""
            verdict = _verdict_line(md)
            rat = _rationale(md)
            lines.append(f"### {i}. {level} · score {score:.2f}")
            lines.append(f"- **URL:** {url}")
            if verdict:
                lines.append(f"- **Judge:** {verdict}")
            if text:
                lines.append(f"- **Flagged text:** \"{text[:300]}\"")
            if rat:
                lines.append(f"- **Why:** {rat}")
            lines.append("")

    conn.close()
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.resolve()} ({len(rows)} scams)")


if __name__ == "__main__":
    main()
