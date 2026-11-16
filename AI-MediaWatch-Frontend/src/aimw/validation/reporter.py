"""Generate validation reports from evaluated cases."""
from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from aimw.validation.evaluator import EvaluationResult, case_verdict, evaluate
from aimw.validation.models import ValidationCase, load_cases

_OUT_DIR = Path("data/validation")


def generate_all(out_dir: Path | None = None) -> dict[str, Path]:
    """Generate all five validation artefacts. Returns {filename: path}."""
    _dir = out_dir or _OUT_DIR
    _dir.mkdir(parents=True, exist_ok=True)

    cases = load_cases()
    result = evaluate(cases)
    done = [c for c in cases if c.processing_status == "done"]

    json_path = _write_json(_dir, result)
    md_path = _write_md(_dir, result, done)
    csv_path = _write_failures_csv(_dir, done)
    eq_path = _write_entity_quality(_dir, done)
    cq_path = _write_campaign_quality(_dir, done)

    return {
        "validation_report.json": json_path,
        "validation_report.md": md_path,
        "validation_failures.csv": csv_path,
        "entity_quality_report.md": eq_path,
        "campaign_quality_report.md": cq_path,
    }


def _write_json(d: Path, result: EvaluationResult) -> Path:
    p = d / "validation_report.json"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "metrics": result.as_dict(),
    }
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return p


def _write_md(d: Path, result: EvaluationResult, done: list[ValidationCase]) -> Path:
    p = d / "validation_report.md"
    b = result.binary
    lines: list[str] = [
        "# Validation Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Binary Classification Metrics",
        "_(HIGH/CRITICAL = positive; gambling/pyramid/scam = expected positive)_",
        "",
        "| Metric    | Value |",
        "|-----------|-------|",
        f"| Precision | {b.precision:.3f} |",
        f"| Recall    | {b.recall:.3f} |",
        f"| F1        | {b.f1:.3f} |",
        f"| FPR       | {b.fpr:.3f} |",
        f"| FNR       | {b.fnr:.3f} |",
        f"| TP        | {b.tp} |",
        f"| FP        | {b.fp} |",
        f"| FN        | {b.fn} |",
        f"| TN        | {b.tn} |",
        "",
        "## Case Counts",
        f"- Total: {result.n_total}",
        f"- Evaluated (binary): {result.n_evaluated}",
        f"- Skipped (uncertain): {result.n_skipped}",
        f"- Pending: {result.n_pending}",
        f"- Error: {result.n_error}",
        "",
    ]

    if result.confusion_matrix:
        levels = ["CLEAN", "LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"]
        lines += [
            "## Confusion Matrix",
            "",
            "| Expected \\ Predicted | " + " | ".join(levels) + " |",
            "|---------------------|" + "|".join("---" for _ in levels) + "|",
        ]
        for label in sorted(result.confusion_matrix.keys()):
            row = result.confusion_matrix[label]
            lines.append(
                f"| **{label}** | "
                + " | ".join(str(row.get(lvl, 0)) for lvl in levels)
                + " |"
            )
        lines.append("")

    if result.per_class:
        lines.append("## Per-label breakdown")
        lines.append("")
        for label, counts in sorted(result.per_class.items()):
            tp, fp, fn, tn = counts["tp"], counts["fp"], counts["fn"], counts["tn"]
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            lines += [
                f"### {label}",
                f"- TP={tp}, FP={fp}, FN={fn}, TN={tn}, P={prec:.2f}, R={rec:.2f}",
                "",
            ]

    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _write_failures_csv(d: Path, done: list[ValidationCase]) -> Path:
    p = d / "validation_failures.csv"
    failures = [c for c in done if case_verdict(c) in ("FP", "FN")]
    with open(p, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["case_id", "source_url", "expected_label", "risk_level",
                        "verdict", "system_score", "notes"],
        )
        writer.writeheader()
        for c in failures:
            writer.writerow({
                "case_id": c.case_id,
                "source_url": c.source_url,
                "expected_label": c.expected_label,
                "risk_level": c.risk_level or "",
                "verdict": case_verdict(c),
                "system_score": f"{c.system_score:.4f}" if c.system_score is not None else "",
                "notes": c.notes or "",
            })
    return p


def _write_entity_quality(d: Path, done: list[ValidationCase]) -> Path:
    p = d / "entity_quality_report.md"
    lines: list[str] = [
        "# Entity Extraction Quality",
        "",
        "Analysis of entity types extracted per case.",
        "",
        "| Case ID   | Expected Label | Handles | Wallets | Phones | Websites |",
        "|-----------|----------------|---------|---------|--------|----------|",
    ]
    for c in done:
        ec = c.entity_count
        lines.append(
            f"| `{c.case_id[:8]}` | {c.expected_label} "
            f"| {ec.get('telegram_handles', 0)} "
            f"| {ec.get('crypto_wallets', 0)} "
            f"| {ec.get('phone_numbers', 0)} "
            f"| {ec.get('websites', 0)} |"
        )
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _write_campaign_quality(d: Path, done: list[ValidationCase]) -> Path:
    p = d / "campaign_quality_report.md"
    _POSITIVE_LABELS = frozenset({"gambling", "pyramid", "scam"})
    _POSITIVE_LEVELS = frozenset({"HIGH", "CRITICAL"})
    scam_cases = [c for c in done if c.expected_label in _POSITIVE_LABELS]
    flagged = [c for c in scam_cases if (c.risk_level or "") in _POSITIVE_LEVELS]
    detection_rate = len(flagged) / len(scam_cases) if scam_cases else 0.0
    lines: list[str] = [
        "# Campaign Detection Quality",
        "",
        f"Scam/pyramid/gambling cases processed: **{len(scam_cases)}**",
        f"System flagged (HIGH/CRITICAL): **{len(flagged)}**",
        f"Detection rate: **{detection_rate:.1%}**",
        "",
        "## Notes",
        "Campaign graph promotion requires multiple co-occurring videos sharing entities.",
        "Single-video detection is captured above via binary risk_level.",
    ]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p
