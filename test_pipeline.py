import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_engine import transcribe
from vision_engine import extract_frames
from agents import analyze

transcript_result = transcribe('test.mp4')
frames, positions = extract_frames('test.mp4', max_height=480, interval=2.0)
print(f'Transcript: {len(transcript_result["text"])} chars')
print(f'Frames: {len(frames)}')
result = analyze('', transcript_result['text'], frames)
print(f'Analyze OK: risk_score={result.get("risk_score")}')
