"""Offline evaluation of the active real-video dataset; never calls an AI model.

eval_results.json and eval_charts belong to the historical 33-video experiment.
Current predictions must be a separate JSON object keyed by video SHA-256:
{"<sha256>": {"status": "ok", "score": 75, "model": "..."}}.
Failed predictions use status="error" and no score. No legacy score migration
is implicit: the old cache does not record whether a score of 50 was a failure.
"""
import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parent
FORMATS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}
LABELS = {"scam": 1, "safe": 0, "promotion": 1, "not_promotion": 0}


def name_key(value):
    """Normalize Unicode typography only; never remove meaningful title text."""
    return unicodedata.normalize("NFC", value).translate(str.maketrans({"’": "'", "‘": "'"}))


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def label_index(path):
    index = {}
    if not path.exists():
        return index
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            for field in ("file_name", "video"):
                key = name_key(row.get(field, "").strip())
                if not key:
                    continue
                if key in index and index[key] != row:
                    raise ValueError(f"Ambiguous label filename in {path}: {key}")
                index[key] = row
    return index


def inventory(root=ROOT):
    root = Path(root).resolve()
    annotation = root / "REVISION" / "annotation"
    author_path = annotation / "author_labels.csv"
    current_author_path = root / "current_author_labels.csv"
    adjudicated_path = annotation / "adjudicated_labels.csv"
    author = label_index(author_path)
    current_author = label_index(current_author_path)
    adjudicated = label_index(adjudicated_path)
    rows = []
    seen_names = set()
    for folder in ("scam videos", "safe_videos"):
        directory = root / folder
        if not directory.is_dir():
            raise FileNotFoundError(f"Required active dataset folder is missing: {directory}")
        files = sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in FORMATS)
        if not files:
            raise ValueError(f"Active dataset folder contains no supported videos: {directory}")
        for path in files:
            key = name_key(path.name)
            if key in seen_names:
                raise ValueError(f"Ambiguous dataset filename: {path.name}; use unique source IDs before labeling")
            seen_names.add(key)
            a = current_author.get(key, author.get(key))
            content_hash = sha256(path)
            if key in current_author and a.get("sha256") != content_hash:
                raise ValueError(f"Confirmed label hash does not match video: {path.name}")
            author_record = current_author_path if key in current_author else author_path
            independent = adjudicated.get(key)
            # An explicitly uncertain adjudication overrides the author label.
            chosen = independent if independent is not None else a
            value = (chosen or {}).get("final_label", "").strip().lower()
            source = "independent_adjudicated" if independent is not None else "author_manual" if a is not None else "provisional_folder"
            label = LABELS.get(value)
            rows.append({"filename": path.name, "path": str(path.relative_to(root)),
                         "sha256": content_hash, "folder": folder,
                         "label": label, "label_source": source,
                         "label_status": "labeled" if label is not None else "uncertain" if chosen is not None else "provisional",
                         "label_record": str((adjudicated_path if independent is not None else author_record).relative_to(root)) if chosen is not None else None,
                         "author_label": a.get("final_label") if a else None,
                         "author_labelled_by": a.get("labelled_by") if a else None})
    return rows


def summary(rows):
    return {"dataset": "active_real_videos", "total_videos": len(rows),
            "folders": dict(Counter(r["folder"] for r in rows)),
            "human_labeled": sum(r["label"] is not None for r in rows),
            "independent_adjudicated": sum(r["label"] is not None and r["label_source"] == "independent_adjudicated" for r in rows),
            "provisional_or_uncertain": sum(r["label"] is None for r in rows),
            "historical_cache_used": False}


def valid_score(record):
    if not isinstance(record, dict) or record.get("status") != "ok":
        return None
    flags = record.get("flags", [])
    if not isinstance(flags, list) or any("error" in str(f).lower() or "failed" in str(f).lower() for f in flags):
        return None
    score = record.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return float(score) if math.isfinite(score) and 0 <= score <= 100 else None


def evaluate(rows, predictions, threshold=50, independent_only=False):
    if isinstance(threshold, bool) or not math.isfinite(threshold) or not 0 <= threshold <= 100:
        raise ValueError("Threshold must be a fixed number between 0 and 100")
    if not isinstance(predictions, dict):
        raise ValueError("Predictions must be an object keyed by video SHA-256")
    counts = Counter(tp=0, tn=0, fp=0, fn=0)
    excluded = []; included = []; seen = set()
    known_labels = {}
    for row in rows:
        if row["label"] is not None:
            if row["sha256"] in known_labels and known_labels[row["sha256"]] != row["label"]:
                raise ValueError("Conflicting human labels for identical video content; adjudicate before evaluation")
            known_labels[row["sha256"]] = row["label"]
    for row in rows:
        reason = None
        if row["label"] is None:
            reason = "missing_or_uncertain_human_label"
        elif independent_only and row["label_source"] != "independent_adjudicated":
            reason = "no_independent_annotation"
        score = valid_score(predictions.get(row["sha256"]))
        if reason is None and score is None:
            reason = "missing_or_failed_prediction"
        if reason is None and row["sha256"] in seen:
            reason = "exact_duplicate"
        if reason:
            excluded.append({"filename": row["filename"], "reason": reason})
            continue
        seen.add(row["sha256"])
        pred = int(score >= threshold)
        counts[("tp" if pred else "fn") if row["label"] == 1 else ("fp" if pred else "tn")] += 1
        included.append({"filename": row["filename"], "sha256": row["sha256"],
                         "label": row["label"], "label_source": row["label_source"], "score": score})
    def ratio(n, d):
        return n / d if d else None
    tp, tn, fp, fn = (counts[k] for k in ("tp", "tn", "fp", "fn"))
    return {"threshold": threshold, "threshold_policy": "fixed; no test-set tuning",
            "independent_only": independent_only, "n_evaluated": len(included),
            "metrics": {**counts, "accuracy": ratio(tp+tn, len(included)),
                        "precision": ratio(tp, tp+fp), "recall": ratio(tp, tp+fn),
                        "f1": ratio(2*tp, 2*tp+fp+fn)} if included else None,
            "included": included, "excluded": excluded}


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", action="store_true", help="Inspect current dataset and labels without evaluating")
    parser.add_argument("--predictions", type=Path, help="Separate SHA-256-keyed current prediction JSON (never the legacy cache)")
    parser.add_argument("--threshold", type=float, default=50, help="Fixed operating threshold; default 50")
    parser.add_argument("--independent-only", action="store_true")
    parser.add_argument("--output", type=Path, help="New report path; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        rows = inventory()
        report = {**summary(rows), "videos": rows,
                  "note": "Author labels are single-author annotations, not completed independent review. Historical 33-video results are not used."}
        if args.predictions and not args.inventory:
            if args.predictions.resolve() == (ROOT / "eval_results.json").resolve():
                raise ValueError("eval_results.json belongs to the historical 33-video experiment; use a separate hash-keyed current prediction file")
            predictions = json.loads(args.predictions.read_text(encoding="utf-8-sig"))
            report["evaluation"] = evaluate(rows, predictions, args.threshold, args.independent_only)
        else:
            report["evaluation"] = None
            report["note"] += " Inventory only; no AI models or accuracy calculations were run."
        output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            destination = args.output.resolve()
            protected = [ROOT / p for p in ("REVISION", "eval_charts", "scam videos", "safe_videos", "AI-MediaWatch-Frontend/data")]
            if any(destination.is_relative_to(p) for p in protected):
                raise ValueError("Choose a new current-evaluation report path outside research records and dataset folders")
            with destination.open("x", encoding="utf-8") as stream:
                stream.write(output + "\n")
        print(output)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"Evaluation error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
