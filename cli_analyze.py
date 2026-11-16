import sys
import os
import json
import argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vision_engine import process_video_optimized
from agents import analyze

def run_analysis(video_path: str):
    print("=" * 60)
    print("  SCAM VIDEO DETECTOR - OPTIMIZED")
    print("=" * 60)

    print("\nPhase 1: Parallel extraction (i7-14700KF, 28 cores)")
    print("  Stream A: Audio extraction (ffmpeg)")
    print("  Stream B: Frame sampling at 360p, every 3s")
    print("  Running both simultaneously...")

    result_opt = process_video_optimized(video_path, max_height=360, interval=3.0)

    frames = result_opt["frames"]
    transcript_data = result_opt["transcript"]
    ocr_data = result_opt["ocr"]
    print(f"  Frames: {len(frames)} at 480p")
    print(f"  Audio: {transcript_data.get('duration', 0):.1f}s")

    print("\nPhase 2: GPU Inference (RTX 5080)")
    print("  Whisper large-v3 + EasyOCR batch")
    transcript = transcript_data["text"]
    if transcript.strip():
        print(f"  Transcript: {transcript[:200]}")
    else:
        print("  (no speech detected)")
    print(f"  OCR: {len(ocr_data['ocr_results'])} frames with text")

    print("\nPhase 3: 3-model analysis")
    print("  mistral + qwen2.5vl (parallel) -> llama3 (auditor)")
    result = analyze("", transcript, frames)

    risk = result["risk_score"]
    print("\n" + "=" * 60)
    if risk >= 70:
        print(f"  RISK SCORE: {risk}/100  - HIGH RISK")
    elif risk >= 40:
        print(f"  RISK SCORE: {risk}/100  - MEDIUM RISK")
    else:
        print(f"  RISK SCORE: {risk}/100  - LOW RISK")
    print("=" * 60)

    if result.get("flags"):
        print("\nFlags:")
        for flag in result["flags"]:
            print(f"   - {flag}")
    print(f"\nReasoning:\n   {result.get('reasoning', 'N/A')}")
    if transcript.strip():
        print(f"\nFull Transcript:\n   {transcript}")
    print()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scam Video Detector CLI")
    parser.add_argument("video", help="Path to video file")
    args = parser.parse_args()
    if not os.path.exists(args.video):
        print(f"Error: file not found: {args.video}")
        sys.exit(1)
    run_analysis(args.video)
