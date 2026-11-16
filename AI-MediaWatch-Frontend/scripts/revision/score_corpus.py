"""Score a JSONL corpus with the deterministic AIMW engine (no LLM).

Run with PYTHONPATH pointing at the engine version to evaluate, e.g.

    PYTHONPATH=src python scripts/revision/score_corpus.py \
        --corpus data/revision/synth_corpus.jsonl --out data/revision/scores_v2.json \
        [--ablations] [--speech-only] [--ocr-field ocr]

Writes {item_id: {"score": float, "level": str, "ablations": {...}}}.
Compatible with the pre-revision engine (v1), which lacks ablate/linkage:
ablations are then skipped.
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("AIMW_LOG_LEVEL", "WARNING")
logging.disable(logging.INFO)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _package_builder():
    """Build packages with whatever engine version is on PYTHONPATH."""
    import datetime as dt

    from aimw.core.schema.evidence import EvidencePackage
    from aimw.entities.extractor import extract
    from aimw.extraction.ocr.models import OcrBlock, OcrFrameResult, OcrResult
    from aimw.extraction.whisper.models import Segment, Transcript
    from aimw.scoring.signals import tag

    epoch = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    def build(item_id, speech, ocr):
        tr = None
        if speech:
            tr = Transcript(engine_version="x", model="x", device="cpu", compute_type="x",
                            source_file_sha256="0" * 64, video_id=item_id, language_detected="en",
                            segments=[Segment(start=t, end=t + 4, text=s) for t, s in speech],
                            generated_at=epoch)
        oc = None
        if ocr:
            oc = OcrResult(engine="x", engine_version="x", source_file_sha256="0" * 64,
                           video_id=item_id, generated_at=epoch,
                           frames=[OcrFrameResult(frame_index=i, timestamp_s=t, image_path="x",
                                                  blocks=[OcrBlock(text=s, bbox=(0, 0, 1, 1), confidence=1.0)])
                                   for i, (t, s) in enumerate(ocr)])
        if tr is None and oc is None:
            return EvidencePackage(report_id=item_id, video_id=item_id, platform="synth", url="x",
                                   collected_at=epoch, processed_at=epoch)
        ents, spans = extract(tr, oc)
        pieces = tag(spans, ents, ocr=oc, transcript=tr)
        return EvidencePackage(report_id=item_id, video_id=item_id, platform="synth", url="x",
                               collected_at=epoch, processed_at=epoch, evidence=pieces, entities=ents)

    return build


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ablations", action="store_true")
    ap.add_argument("--speech-only", action="store_true")
    ap.add_argument("--ocr-field", default="ocr")
    ap.add_argument("--speech-field", default="speech")
    args = ap.parse_args()

    os.chdir(ROOT)  # v1 engine reads thresholds relative to CWD
    from aimw.scoring import engine

    build = _package_builder()
    supports_ablate = "ablate" in inspect.signature(engine.score).parameters
    rules = sorted(getattr(engine, "ABLATABLE_RULES", []))

    out: dict[str, dict] = {}
    for line in Path(args.corpus).read_text(encoding="utf-8").splitlines():
        it = json.loads(line)
        speech = [tuple(x) for x in it.get(args.speech_field, [])]
        ocr = [] if args.speech_only else [tuple(x) for x in it.get(args.ocr_field, [])]
        pkg = build(it["id"], speech, ocr)
        b = engine.score(pkg)
        rec = {
            "score": b.final_score,
            "level": b.level,
            "ceiling": b.single_source_ceiling_applied,
            "gate": b.applied_entity_gate,
            "pieces": [[p.indicator_type, p.source, p.applied_weight] for p in b.per_piece],
            "linkage": dict(getattr(pkg.entities, "payment_linkage", {}) or {}),
        }
        if args.ablations and supports_ablate:
            rec["ablations"] = {}
            for r in rules:
                ab = engine.score(pkg, ablate=frozenset({r}))
                rec["ablations"][r] = {"score": ab.final_score, "level": ab.level}
        out[it["id"]] = rec

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"scored {len(out)} items -> {args.out} (ablations={'yes' if args.ablations and supports_ablate else 'no'})")


if __name__ == "__main__":
    main()
