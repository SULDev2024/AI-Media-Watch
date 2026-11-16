"""Refresh data/validation/cases.jsonl from the latest rigorous evaluation.

The Validation page reads cases.jsonl and reports whatever predictions are
frozen there. The original file held stale rules-only predictions (recall 0.13)
from an early phase. The most recent held-out evaluation lives in
``data/validation/phase_15_9/final_eval.json`` (177 cases, train+holdout split).

This script rewrites cases.jsonl from those rows so the dashboard shows the
current, validated real-world numbers instead of the stale ones. The original
is backed up to cases.jsonl.bak first.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aimw.validation.models import ValidationCase, save_cases  # noqa: E402

_EVAL = Path("data/validation/phase_15_9/final_eval.json")
_CASES = Path("data/validation/cases.jsonl")

_LABEL_OK = {"benign", "gambling", "pyramid", "scam", "uncertain"}


def main() -> None:
    eval_data = json.loads(_EVAL.read_text(encoding="utf-8"))
    rows = eval_data["rows"]

    if _CASES.exists():
        shutil.copy2(_CASES, _CASES.with_suffix(".jsonl.bak"))
        print(f"Backed up existing cases.jsonl -> {_CASES.with_suffix('.jsonl.bak')}")

    now = datetime.now(UTC)
    cases: list[ValidationCase] = []
    for r in rows:
        label = r.get("label")
        if label not in _LABEL_OK:
            label = "uncertain"
        cases.append(
            ValidationCase(
                source_type="real_world",
                source_url=r.get("notes", "") or "",
                video_id=r["video_id"],
                expected_label=label,  # type: ignore[arg-type]
                system_score=float(r.get("score", 0.0)),
                risk_level=r.get("level"),
                action=None,
                processing_status="done",
                split=r.get("split"),
                notes=f"corpus={r.get('corpus')} split={r.get('split')} signals={r.get('n_signals')}",
                processed_at=now,
            )
        )

    save_cases(cases)
    print(f"Wrote {len(cases)} cases to {_CASES}")

    # Quick sanity readout
    pos_labels = {"gambling", "pyramid", "scam"}
    pos_levels = {"HIGH", "CRITICAL"}
    for split in ("holdout", "train", None):
        sub = [c for c in cases if (c.split == split if split else True)]
        tp = sum(1 for c in sub if c.expected_label in pos_labels and (c.risk_level or "") in pos_levels)
        fn = sum(1 for c in sub if c.expected_label in pos_labels and (c.risk_level or "") not in pos_levels)
        fp = sum(1 for c in sub if c.expected_label not in pos_labels and (c.risk_level or "") in pos_levels)
        tn = sum(1 for c in sub if c.expected_label not in pos_labels and (c.risk_level or "") not in pos_levels)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        tag = split or "ALL"
        print(f"  {tag:8s} n={len(sub):3d}  P={prec:.3f} R={rec:.3f} F1={f1:.3f}")


if __name__ == "__main__":
    main()
