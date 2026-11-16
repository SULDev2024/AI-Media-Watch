import sys, os, asyncio, tempfile, traceback
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_engine import transcribe
from vision_engine import extract_frames
from agents import analyze
from cache import compute_hash, get_cached, set_cached

executor = ThreadPoolExecutor(max_workers=4)

async def process_video(tmp_path: str, caption: str = "", platform: str = "unknown"):
    loop = asyncio.get_event_loop()
    video_hash = await loop.run_in_executor(executor, compute_hash, tmp_path)
    cached = get_cached(video_hash)
    if cached:
        cached["cached"] = True
        return cached

    audio_task = loop.run_in_executor(executor, transcribe, tmp_path)
    frames_task = loop.run_in_executor(executor, extract_frames, tmp_path, 2.0)

    transcript_result, (frames, _) = await asyncio.gather(audio_task, frames_task)
    print(f"Transcript: {len(transcript_result['text'])} chars")
    print(f"Frames: {len(frames)}")

    result = analyze(caption, transcript_result["text"], frames)
    result["transcript"] = transcript_result["text"]
    result["platform"] = platform
    result["cached"] = False
    set_cached(video_hash, result)
    return result

async def main():
    try:
        result = await process_video("test.mp4")
        print(f"SUCCESS: risk_score={result.get('risk_score')}")
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()

asyncio.run(main())
