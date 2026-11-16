import os
import hashlib
import json
import tempfile
import asyncio
import traceback
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import uvicorn

from audio_engine import transcribe
from vision_engine import extract_frames, ocr_frames_batch
from agents import analyze
from cache import compute_hash, get_cached, set_cached

app = FastAPI(title="Scam Detector API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
@app.get("/health")
async def health():
    return {"status": "ok", "service": "Scam Detector API"}

executor = ThreadPoolExecutor(max_workers=4)

async def process_video(tmp_path: str, caption: str, platform: str) -> dict:
    loop = asyncio.get_event_loop()
    video_hash = await loop.run_in_executor(executor, compute_hash, tmp_path)
    cache_key = hashlib.sha256(json.dumps(["aimw-v2", video_hash, caption, platform]).encode()).hexdigest()
    cached = get_cached(cache_key)
    if cached and "ocr_results" in cached:
        cached["cached"] = True
        return cached

    if os.path.splitext(tmp_path)[1].lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"}:
        def load_image():
            import numpy as np
            from PIL import Image, ImageOps
            with Image.open(tmp_path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((1280, 1280))
                return np.array(im)
        frames = [await loop.run_in_executor(executor, load_image)]
        positions = [0.0]
        transcript_result = {"text": ""}
    else:
        audio_task = loop.run_in_executor(executor, transcribe, tmp_path)
        frames_task = loop.run_in_executor(executor, extract_frames, tmp_path, 480, 2.0)
        transcript_result, (frames, positions) = await asyncio.gather(audio_task, frames_task)
        if not frames and not transcript_result["text"].strip():
            raise ValueError("No readable video frames or speech found in this file")

    ocr_data = await loop.run_in_executor(executor, ocr_frames_batch, frames, positions)
    result = dict(cached) if cached else await loop.run_in_executor(executor, analyze, caption, transcript_result["text"], frames)
    result.update(ocr_data)
    score = result.get("risk_score")
    if (isinstance(score, bool) or not isinstance(score, (int, float))
            or not 0 <= score <= 100 or "parse_error" in result.get("flags", [])):
        raise ValueError("The auditor did not return a valid risk assessment; please retry")
    result["transcript"] = transcript_result["text"]
    result["platform"] = platform
    result["cached"] = False
    set_cached(cache_key, result)
    return result

@app.post("/analyze")
async def analyze_video(
    file: UploadFile = File(...),
    caption: str = Form(""),
    platform: str = Form("unknown")
):
    suffix = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        return await process_video(tmp_path, caption, platform)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except:
            pass

@app.post("/analyze-url")
async def analyze_url(
    video_url: str = Form(...),
    caption: str = Form(""),
    platform: str = Form("unknown")
):
    parsed = urlparse(video_url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail=f"Invalid URL scheme '{parsed.scheme}'. Only http/https allowed.")

    tmp_path = None
    try:
        suffix = ".mp4"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(video_url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type:
                    raise HTTPException(status_code=400,
                        detail="URL points to a webpage, not a video file. Direct video URL required (e.g. .mp4).")
                tmp.write(resp.content)
            tmp_path = tmp.name

        return await process_video(tmp_path, caption, platform)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    finally:
        if tmp_path:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except:
                pass

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001)
