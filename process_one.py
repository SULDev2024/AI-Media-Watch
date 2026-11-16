"""Generate an explicit local prediction into a new hash-keyed JSON file.

The historical eval_results.json is never read or written.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from current_evaluation import ROOT, inventory, sha256, valid_score


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New output file; never overwritten")
    args = parser.parse_args(argv)
    path = args.video.resolve()
    if not any((ROOT / row["path"]).resolve() == path for row in inventory()):
        parser.error("Video must belong to the active dataset")
    if args.output.exists():
        parser.error("Prediction output already exists; choose a new file")
    protected = [ROOT / p for p in ("REVISION", "eval_charts", "scam videos", "safe_videos", "AI-MediaWatch-Frontend/data")]
    if any(args.output.resolve().is_relative_to(p) for p in protected):
        parser.error("Choose an output outside research records and dataset folders")
    record = {"status": "error", "score": None, "filename": path.name,
              "model": "Whisper-tiny + mistral speech analyst + llama3 auditor (fast)"}
    try:
        from faster_whisper import WhisperModel
        from agents import speech_analyst, auditor
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "audio.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path),
                            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(audio)],
                           capture_output=True, check=True)
            model = WhisperModel("tiny", device="cuda", compute_type="float16", local_files_only=True)
            segments, _ = model.transcribe(str(audio), beam_size=1, best_of=1, vad_filter=False)
            transcript = " ".join(s.text for s in segments)
        speech = speech_analyst(transcript)
        result = auditor("", transcript, "Skipped (fast mode)", speech["speech_report"])
        candidate = {"status": "ok", "score": result.get("risk_score"), "flags": result.get("flags", [])}
        score = valid_score(candidate)
        if score is None:
            raise ValueError("Auditor returned a missing, failed or invalid score")
        record.update(status="ok", score=score)
    except Exception as exc:
        record["error"] = str(exc)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({sha256(path): record}, stream, ensure_ascii=False, indent=2)
    print(f"Prediction status: {record['status']}; saved to {args.output}")
    return 0 if record["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
