"""Score the SYNTHETIC benchmark with the LLM judge (run on the GPU/Ollama machine).

This could not be executed in the revision sandbox (no LLM server there). Run it
where Ollama is available, then re-run run_revision_eval.py — it picks up
data/revision/llm_scores_<mode>.json automatically and adds the LLM-only and
fused rows to the tables.

Modes
  fast   transcript → speech analyst (mistral) → auditor (llama3); vision skipped.
         This is EXACTLY the configuration evaluated in the submitted paper.
  full   transcript + on-screen text + rendered video frames → speech analyst +
         vision (qwen2.5vl) → auditor.  Needs data/revision/videos (render_videos.py).

Usage (from the "Local Agent" folder, where agents.py lives):
  python AI-MediaWatch-Frontend/scripts/revision/llm_judge_eval.py --mode fast
  python AI-MediaWatch-Frontend/scripts/revision/llm_judge_eval.py --mode full

Each item is scored once; results are cached so the run can be resumed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
FRONTEND = HERE.parents[2]
LOCAL_AGENT = FRONTEND.parent
sys.path.insert(0, str(LOCAL_AGENT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fast", "full"], default="fast")
    ap.add_argument("--corpus", default=str(FRONTEND / "data/revision/synth_corpus.jsonl"))
    ap.add_argument("--manifest", default=str(FRONTEND / "data/revision/videos/manifest.json"))
    ap.add_argument("--per-family", type=int, default=0,
                    help="score only the first N items of each family (0 = all); for CPU-only machines")
    args = ap.parse_args()

    import agents  # Local Agent: mistral speech analyst, qwen2.5vl vision, llama3 auditor

    out_path = FRONTEND / f"data/revision/llm_scores_{args.mode}.json"
    cache = json.loads(out_path.read_text()) if out_path.exists() else {}
    items = [json.loads(line) for line in Path(args.corpus).read_text(encoding="utf-8").splitlines()]

    if args.per_family:
        seen: dict[str, int] = {}
        keep = []
        for it in items:
            if seen.get(it["family"], 0) < args.per_family:
                keep.append(it)
                seen[it["family"]] = seen.get(it["family"], 0) + 1
        items = keep

    if args.mode == "full":
        from vision_engine import extract_frames  # Local Agent frame sampler
        manifest = {m["id"]: m for m in json.loads(Path(args.manifest).read_text())}
        items = [it for it in items if it["id"] in manifest]

    for n, it in enumerate(items, 1):
        if it["id"] in cache:
            continue
        transcript = " ".join(s for _, s in it["speech"])
        t0 = time.time()
        try:
            if args.mode == "fast":
                speech = agents.speech_analyst(transcript)
                res = agents.auditor("", transcript, "Skipped (fast mode)", speech["speech_report"])
            else:
                frames, _ = extract_frames(manifest[it["id"]]["path"], 480, 2.0)
                res = agents.analyze("", transcript, frames)
            score = res.get("risk_score")
            ok = isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 100 \
                and "parse_error" not in res.get("flags", [])
        except Exception as e:  # keep going; record the failure explicitly
            score, ok, res = None, False, {"error": str(e)}
        cache[it["id"]] = {"risk_score": score if ok else None, "valid": ok,
                           "flags": res.get("flags", []), "seconds": round(time.time() - t0, 1)}
        out_path.write_text(json.dumps(cache, indent=1))
        print(f"[{n}/{len(items)}] {it['id']}: {cache[it['id']]['risk_score']} ({cache[it['id']]['seconds']}s)", flush=True)
    print(f"done -> {out_path}")


if __name__ == "__main__":
    main()
