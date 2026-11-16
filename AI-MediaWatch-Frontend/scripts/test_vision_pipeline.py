"""Quick test: run the vision extraction pipeline on a video file.

Usage:
    python scripts/test_vision_pipeline.py [video_path]

If no video_path is given, picks the smallest video in data/media/.
Requires AIMW_LLM_VISION=true and a working Ollama tunnel in .env.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def main() -> None:
    from aimw.core.config import get_settings
    from aimw.db.repositories.usage import UsageRepository
    from aimw.db.session import get_engine, get_sessionmaker
    from aimw.extraction.vision import extract_with_vision
    from aimw.reasoning.client import build_chat_client

    get_engine()
    get_sessionmaker()
    settings = get_settings()

    print(f"LLM provider : {settings.llm_provider}")
    print(f"LLM model    : {settings.resolved_llm_model}")
    print(f"LLM base URL : {settings.resolved_llm_base_url}")
    print(f"LLM vision   : {settings.llm_vision}")
    print()

    if not settings.llm_vision:
        print("ERROR: AIMW_LLM_VISION is not enabled. Set it to true in .env")
        return

    # Find a video to test
    if len(sys.argv) > 1:
        video_path = Path(sys.argv[1])
    else:
        media_dir = settings.resolved_media_dir
        videos = sorted(media_dir.glob("*.*"), key=lambda p: p.stat().st_size)
        videos = [v for v in videos if v.suffix.lower() in (".mp4", ".mkv", ".webm", ".avi", ".mov")]
        if not videos:
            print(f"No videos found in {media_dir}")
            return
        video_path = videos[0]

    print(f"Video: {video_path} ({video_path.stat().st_size / 1024 / 1024:.1f} MB)")
    print()

    client = build_chat_client(UsageRepository(get_sessionmaker()))

    t0 = time.perf_counter()
    result = await extract_with_vision(
        source_path=video_path,
        video_id="test-vision",
        frame_cache_dir=settings.resolved_frame_cache_dir,
        vision_fn=client.complete_vision,
        model_name=settings.resolved_llm_model,
        scene_threshold=settings.scene_change_threshold,
        frames_per_3s=settings.frames_per_3s,
    )
    dt = time.perf_counter() - t0

    print(f"=== Vision extraction done in {dt:.1f}s ===")
    print(f"OCR frames: {len(result.ocr_result.frames)}")
    total_blocks = sum(len(f.blocks) for f in result.ocr_result.frames)
    print(f"OCR blocks: {total_blocks}")
    print(f"Vision description length: {len(result.vision_description)} chars")
    print()
    print("--- Vision model response ---")
    print(result.vision_description[:2000])
    if len(result.vision_description) > 2000:
        print(f"\n... ({len(result.vision_description) - 2000} more chars)")


if __name__ == "__main__":
    asyncio.run(main())
