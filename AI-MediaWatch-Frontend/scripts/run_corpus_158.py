"""Phase 15.8 blind evaluation — release-candidate generalization run.

Scores the FRESH phase_15_8 corpus with the FROZEN production pipeline.
Nothing about signals.yaml / thresholds / weights / referee is changed; this
script only reads them. Headline metrics use the SAME scoring basis as the
Phase 15.7 corpus runner (empty entities into tag/score) so the generalization
comparison is apples-to-apples. The REAL entity extractor is additionally run
to produce per-video entity counts for the entity stability audit.

Outputs (all under data/validation/phase_15_8/):
    validation_report.json
    validation_report.md
    validation_failures.csv
    entity_extraction.json
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from aimw.core.schema.evidence import EvidencePackage, ExtractedEntities
from aimw.entities.extractor import extract
from aimw.entities.models import RawSpan
from aimw.extraction.ocr.models import OcrResult
from aimw.extraction.whisper.models import Transcript
from aimw.scoring.engine import score
from aimw.scoring.signals import _load_specs, tag
from aimw.validation.evaluator import case_verdict, evaluate
from aimw.validation.models import ValidationCase, load_cases

_OUT_DIR = _ROOT / "data" / "validation" / "phase_15_8"
_RAW_DIR = _OUT_DIR / "raw"
_CASES_PATH = _OUT_DIR / "cases.jsonl"

_ENTITY_FIELDS = [
    "telegram_handles", "telegram_links", "crypto_wallets", "phone_numbers",
    "websites", "referral_codes", "profit_claims",
]


def _load_fixture(video_id: str) -> tuple[Transcript | None, OcrResult | None]:
    fp = _RAW_DIR / f"{video_id}.fixture.json"
    if not fp.exists():
        return None, None
    raw = json.loads(fp.read_text(encoding="utf-8"))
    t = Transcript.model_validate(raw["transcript"]) if "transcript" in raw else None
    o = OcrResult.model_validate(raw["ocr"]) if "ocr" in raw else None
    return t, o


def run() -> None:
    _load_specs.cache_clear()
    cases = load_cases(_CASES_PATH)
    print(f"Loaded {len(cases)} phase_15_8 cases from {_CASES_PATH}")

    results: list[ValidationCase] = []
    scores_by_video: dict[str, dict] = {}
    entity_by_video: dict[str, dict] = {}
    first_error = False

    for case in cases:
        try:
            transcript, ocr = _load_fixture(case.video_id)

            # Headline scoring: same basis as Phase 15.7 (empty entities).
            pieces = tag(raw_spans=[], entities=ExtractedEntities(), ocr=ocr, transcript=transcript)
            now = datetime.now(UTC)
            pkg = EvidencePackage(
                report_id=f"corpus158-{case.video_id}",
                video_id=case.video_id,
                platform=case.source_type,
                url=case.source_url,
                collected_at=now,
                processed_at=now,
                evidence=pieces,
                entities=ExtractedEntities(),
            )
            bd = score(pkg)

            results.append(case.model_copy(update={
                "processing_status": "done",
                "risk_level": bd.level,
                "system_score": bd.final_score,
                "processed_at": now,
            }))
            scores_by_video[case.video_id] = {
                "score": bd.final_score, "level": bd.level, "n_signals": len(pieces),
            }

            # Real entity extraction (for the entity stability audit only).
            ents, spans = extract(transcript, ocr)
            entity_by_video[case.video_id] = {
                f: len(getattr(ents, f, []) or []) for f in _ENTITY_FIELDS
            }
            entity_by_video[case.video_id]["n_raw_spans"] = len(spans)

        except Exception as exc:
            if not first_error:
                import traceback
                traceback.print_exc()
                first_error = True
            results.append(case.model_copy(update={
                "processing_status": "error",
                "error_message": str(exc)[:500],
            }))

    eval_result = evaluate(results)
    b = eval_result.binary
    print(f"\nTP={b.tp} FP={b.fp} FN={b.fn} TN={b.tn} n_error={eval_result.n_error}")
    print(f"P={b.precision:.3f} R={b.recall:.3f} F1={b.f1:.3f}")

    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    import yaml
    tp_path = _ROOT / "config" / "level_thresholds.yaml"
    thresholds = yaml.safe_load(tp_path.read_text(encoding="utf-8")) if tp_path.exists() else {}

    (_OUT_DIR / "validation_report.json").write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        "phase": "15.8",
        "corpus": "fresh / disjoint from 95-case corpus",
        "labeling_method": "search-query-derived weak labels",
        "scoring_basis": "frozen pipeline, empty-entity tag/score (same as Phase 15.7)",
        "threshold_config": thresholds,
        "metrics": eval_result.as_dict(),
        "scores_by_video": scores_by_video,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    (_OUT_DIR / "entity_extraction.json").write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(),
        "per_video": entity_by_video,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    # Markdown
    p_ok, r_ok, f_ok = b.precision >= 0.85, b.recall >= 0.50, b.f1 >= 0.60
    verdict = "PROCEED_TO_PHASE_16" if (p_ok and r_ok and f_ok) else "REMAIN_IN_PHASE_15"
    lines = [
        "# Phase 15.8 Blind Validation Report (fresh corpus)",
        "",
        f"**Generated:** {datetime.now(UTC).isoformat()}",
        f"**Corpus:** fresh, disjoint from 95-case corpus ({len(cases)} videos)",
        f"**Threshold high=** {thresholds.get('high','?')}",
        "**Pipeline:** FROZEN (no changes to signals/thresholds/weights/referee)",
        "",
        "## Binary Metrics", "",
        "| Metric | Value |", "|--------|-------|",
        f"| Precision | {b.precision:.3f} |",
        f"| Recall | {b.recall:.3f} |",
        f"| F1 | {b.f1:.3f} |",
        f"| TP | {b.tp} |", f"| FP | {b.fp} |", f"| FN | {b.fn} |", f"| TN | {b.tn} |",
        f"| n_error | {eval_result.n_error} |",
        "",
        "## Per-Class", "", "| Class | TP | FP | FN | TN |", "|-------|----|----|----|----|",
    ]
    for cls, c in eval_result.per_class.items():
        lines.append(f"| {cls} | {c.get('tp',0)} | {c.get('fp',0)} | {c.get('fn',0)} | {c.get('tn',0)} |")
    lines += ["", "## Success Criteria", "",
              f"- Precision ≥ 0.85: {'PASS' if p_ok else 'FAIL'} ({b.precision:.3f})",
              f"- Recall ≥ 0.50: {'PASS' if r_ok else 'FAIL'} ({b.recall:.3f})",
              f"- F1 ≥ 0.60: {'PASS' if f_ok else 'FAIL'} ({b.f1:.3f})",
              "", f"**Verdict: {verdict}**", ""]
    (_OUT_DIR / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")

    # Failures CSV
    with (_OUT_DIR / "validation_failures.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["video_id", "expected_label", "system_score", "risk_level", "verdict", "n_signals", "error_message"])
        for r in results:
            v = case_verdict(r)
            if v in ("FP", "FN") or r.processing_status == "error":
                w.writerow([
                    r.video_id, r.expected_label,
                    f"{r.system_score:.4f}" if r.system_score is not None else "",
                    r.risk_level or "", v,
                    scores_by_video.get(r.video_id, {}).get("n_signals", 0),
                    r.error_message or "",
                ])

    print(f"\nVERDICT: {verdict}")
    print(f"Wrote reports to {_OUT_DIR}")


if __name__ == "__main__":
    run()
