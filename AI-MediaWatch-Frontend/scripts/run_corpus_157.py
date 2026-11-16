"""Phase 15.7 corpus runner.

Loads all 95 validation cases, re-scores them with current signals.yaml
(which has the Phase 15.7 additions) and the high=0.40 threshold, then
writes validation_report.json/md/csv to data/validation/phase_15_7/.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure project root is on path when run from any directory.
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from aimw.core.schema.evidence import EvidencePackage, ExtractedEntities
from aimw.extraction.ocr.models import OcrResult
from aimw.extraction.whisper.models import Transcript
from aimw.scoring.engine import risk_level, score
from aimw.scoring.signals import _load_specs, tag
from aimw.entities.models import RawSpan
from aimw.validation.evaluator import evaluate
from aimw.validation.models import ValidationCase, load_cases

_RAW_DIR = _ROOT / "data" / "validation" / "raw"
_OUT_DIR = _ROOT / "data" / "validation" / "phase_15_7"
_CASES_PATH = _ROOT / "data" / "validation" / "cases.jsonl"


def _load_fixture(video_id: str) -> tuple[Transcript | None, OcrResult | None]:
    """Load transcript and OCR from the raw fixture file."""
    fixture_path = _RAW_DIR / f"{video_id}.fixture.json"
    if not fixture_path.exists():
        return None, None
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    transcript = Transcript.model_validate(raw["transcript"]) if "transcript" in raw else None
    ocr = OcrResult.model_validate(raw["ocr"]) if "ocr" in raw else None
    return transcript, ocr


def run() -> None:
    # Invalidate the lru_cache so we pick up the current signals.yaml.
    _load_specs.cache_clear()

    cases = load_cases(_CASES_PATH)
    print(f"Loaded {len(cases)} cases from {_CASES_PATH}")

    results: list[ValidationCase] = []
    scores_by_video: dict[str, dict] = {}
    first_error_shown = False

    for case in cases:
        try:
            transcript, ocr = _load_fixture(case.video_id)

            entities = ExtractedEntities()
            raw_spans: list[RawSpan] = []

            pieces = tag(
                raw_spans=raw_spans,
                entities=entities,
                ocr=ocr,
                transcript=transcript,
            )

            now = datetime.now(UTC)
            package = EvidencePackage(
                report_id=f"corpus-{case.video_id}",
                video_id=case.video_id,
                platform=case.source_type,
                url=case.source_url,
                collected_at=now,
                processed_at=now,
                evidence=pieces,
                entities=entities,
            )

            breakdown = score(package)
            level = breakdown.level
            final_score = breakdown.final_score

            updated = case.model_copy(
                update={
                    "processing_status": "done",
                    "risk_level": level,
                    "system_score": final_score,
                    "processed_at": now,
                }
            )
            results.append(updated)
            scores_by_video[case.video_id] = {
                "score": final_score,
                "level": level,
                "n_signals": len(pieces),
            }

        except Exception as exc:
            if not first_error_shown:
                import traceback
                traceback.print_exc()
                first_error_shown = True
            updated = case.model_copy(
                update={
                    "processing_status": "error",
                    "error_message": str(exc)[:500],
                }
            )
            results.append(updated)

    # Evaluate.
    eval_result = evaluate(results)
    b = eval_result.binary
    print(
        f"\nProcessed: {len(results)} cases  "
        f"TP={b.tp} FP={b.fp} FN={b.fn} TN={b.tn}  "
        f"n_error={eval_result.n_error}"
    )
    print(
        f"P={b.precision:.3f}  R={b.recall:.3f}  F1={b.f1:.3f}"
    )

    # ── Write outputs ────────────────────────────────────────────────────────
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load threshold config for the report.
    import yaml
    threshold_path = _ROOT / "config" / "level_thresholds.yaml"
    thresholds = yaml.safe_load(threshold_path.read_text(encoding="utf-8")) if threshold_path.exists() else {}

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "threshold_config": thresholds,
        "signals_version": "phase_15_7",
        "metrics": eval_result.as_dict(),
        "scores_by_video": scores_by_video,
    }
    (_OUT_DIR / "validation_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Wrote {_OUT_DIR / 'validation_report.json'}")

    # ── Markdown report ──────────────────────────────────────────────────────
    lines = [
        "# Phase 15.7 Corpus Validation Report",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Threshold high=** {thresholds.get('high', '?')}",
        f"**Signals version:** phase_15_7",
        "",
        "## Binary Metrics",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Precision | {b.precision:.3f} |",
        f"| Recall | {b.recall:.3f} |",
        f"| F1 | {b.f1:.3f} |",
        f"| TP | {b.tp} |",
        f"| FP | {b.fp} |",
        f"| FN | {b.fn} |",
        f"| TN | {b.tn} |",
        f"| n_error | {eval_result.n_error} |",
        "",
        "## Per-Class",
        "",
        "| Class | TP | FP | FN | TN |",
        "|-------|----|----|----|----|",
    ]
    for cls, counts in eval_result.per_class.items():
        lines.append(
            f"| {cls} | {counts.get('tp',0)} | {counts.get('fp',0)} | "
            f"{counts.get('fn',0)} | {counts.get('tn',0)} |"
        )
    lines += [
        "",
        "## Confusion Matrix (expected → predicted level)",
        "",
        "| Expected \\ Predicted | CLEAN | LOW | MEDIUM | HIGH | CRITICAL | UNKNOWN |",
        "|----------------------|-------|-----|--------|------|----------|---------|",
    ]
    for exp_label, predicted in eval_result.confusion_matrix.items():
        row = f"| {exp_label} |"
        for lvl in ["CLEAN", "LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"]:
            row += f" {predicted.get(lvl, 0)} |"
        lines.append(row)
    lines += ["", "## Success Criteria", "", ""]

    target_p, target_r, target_f = 0.85, 0.50, 0.60
    p_ok = b.precision >= target_p
    r_ok = b.recall >= target_r
    f_ok = b.f1 >= target_f
    lines.append(f"- Precision ≥ {target_p}: {'✅' if p_ok else '❌'} ({b.precision:.3f})")
    lines.append(f"- Recall ≥ {target_r}: {'✅' if r_ok else '❌'} ({b.recall:.3f})")
    lines.append(f"- F1 ≥ {target_f}: {'✅' if f_ok else '❌'} ({b.f1:.3f})")

    verdict = "PROCEED_TO_PHASE_16" if (p_ok and r_ok and f_ok) else "REMAIN_IN_PHASE_15"
    lines += ["", f"**Verdict: {verdict}**", ""]

    (_OUT_DIR / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {_OUT_DIR / 'validation_report.md'}")

    # ── Failures CSV ─────────────────────────────────────────────────────────
    failures_path = _OUT_DIR / "validation_failures.csv"
    with failures_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["video_id", "expected_label", "system_score", "risk_level",
             "verdict", "n_signals", "error_message"]
        )
        for r in results:
            from aimw.validation.evaluator import case_verdict
            v = case_verdict(r)
            if v in ("FP", "FN") or r.processing_status == "error":
                n_sig = scores_by_video.get(r.video_id, {}).get("n_signals", 0)
                writer.writerow([
                    r.video_id,
                    r.expected_label,
                    f"{r.system_score:.4f}" if r.system_score is not None else "",
                    r.risk_level or "",
                    v,
                    n_sig,
                    r.error_message or "",
                ])
    print(f"Wrote {failures_path}")

    # ── Final summary ────────────────────────────────────────────────────────
    all_ok = p_ok and r_ok and f_ok
    print(f"\nVERDICT: {verdict}")
    if not all_ok:
        fails = []
        if not p_ok:
            fails.append(f"Precision={b.precision:.3f} < {target_p}")
        if not r_ok:
            fails.append(f"Recall={b.recall:.3f} < {target_r}")
        if not f_ok:
            fails.append(f"F1={b.f1:.3f} < {target_f}")
        print(f"Missing: {'; '.join(fails)}")


if __name__ == "__main__":
    run()
