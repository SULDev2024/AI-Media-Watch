"""Vision-based extraction — sends sampled frames to a multimodal LLM.

When the configured LLM supports vision (qwen2.5vl, llava, etc.), this
module replaces PaddleOCR: key frames are sent directly to the model,
which reads all visible text AND describes the visual content. The
downstream signal tagger and entity extractor work on the extracted text
just as they would on PaddleOCR output.

Speed: ~3-8s for up to 5 frames via Ollama vs. 30-60s+ for local
PaddleOCR per video. Whisper runs in parallel with the vision call.

Import boundary: this module lives in ``aimw.extraction`` and must NOT
import ``aimw.db`` or ``aimw.reasoning``. The caller (pipeline) passes
a ``vision_fn`` callable that performs the actual LLM call.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine

from aimw.extraction.ocr.models import OcrBlock, OcrFrameResult, OcrResult

_LOG = logging.getLogger("aimw.extraction.vision")

_MAX_FRAMES = 5
_MAX_IMAGE_DIM = 768

_VISION_SYSTEM = """\
You are an OCR and visual analysis engine for a financial fraud detection system.
You will be shown frames sampled from a video. For EACH frame:
1. Read ALL visible text exactly as written — every word, number, URL, phone \
number, crypto address, username, app name, price, currency symbol.
2. Describe key visual elements: app interfaces, payment screens, QR codes, \
charts, logos, messaging apps, wallets, trading platforms.
Keep output factual and concise. Separate each frame with a blank line."""

VisionFn = Callable[
    [str, list[dict[str, Any]], int],
    Coroutine[Any, Any, str],
]


def _resize_and_encode(path: Path) -> str:
    """Resize to fit within _MAX_IMAGE_DIM and return base64-encoded JPEG."""
    from PIL import Image

    img = Image.open(path)
    img.thumbnail((_MAX_IMAGE_DIM, _MAX_IMAGE_DIM), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


@dataclass
class VisionExtractionResult:
    """Text + visual description from the vision model, plus compatible OcrResult."""

    ocr_result: OcrResult
    vision_description: str


async def extract_with_vision(
    source_path: Path,
    video_id: str,
    frame_cache_dir: Path,
    vision_fn: VisionFn,
    model_name: str = "vision-llm",
    scene_threshold: float = 0.3,
    frames_per_3s: int = 1,
) -> VisionExtractionResult:
    """Sample frames, send to vision model via *vision_fn*, return OCR-compatible result.

    Parameters
    ----------
    vision_fn:
        Async callable ``(system, content, max_tokens) -> str`` that sends a
        multimodal message to the LLM. The pipeline builds this from
        ``GroqClient.complete_vision``.
    """
    from aimw.extraction.ocr.cache import sha256_file
    from aimw.extraction.ocr.frames import FrameMeta, sample

    source_hash = sha256_file(source_path)

    out_dir = frame_cache_dir / video_id
    frames: list[FrameMeta] = await asyncio.to_thread(
        sample,
        source_path,
        out_dir,
        threshold=scene_threshold,
        frames_per_3s=frames_per_3s,
    )

    if not frames:
        _LOG.warning("vision_no_frames", extra={"video_id": video_id})
        return VisionExtractionResult(
            ocr_result=_empty_vision_ocr(video_id, source_hash, model_name),
            vision_description="",
        )

    key_frames = _select_key_frames(frames, _MAX_FRAMES)
    _LOG.info(
        "vision_sending_frames",
        extra={
            "video_id": video_id,
            "total_sampled": len(frames),
            "selected": len(key_frames),
        },
    )

    image_parts: list[dict[str, Any]] = []
    for frame in key_frames:
        b64 = await asyncio.to_thread(_resize_and_encode, frame.path)
        image_parts.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        )

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Analyze these {len(key_frames)} video frames from a potentially "
                f"fraudulent video. For each frame, list all visible text and "
                f"describe the visual content."
            ),
        },
        *image_parts,
    ]

    response_text: str = await vision_fn(_VISION_SYSTEM, content, 4096)

    ocr_frames = _build_ocr_frames(response_text, key_frames)
    ocr_result = OcrResult(
        engine="vision-llm",
        engine_version=model_name,
        source_file_sha256=source_hash,
        video_id=video_id,
        frames=ocr_frames,
        generated_at=dt.datetime.now(dt.UTC),
    )

    _LOG.info(
        "vision_extraction_done",
        extra={
            "video_id": video_id,
            "frames_analyzed": len(key_frames),
            "response_chars": len(response_text),
        },
    )

    return VisionExtractionResult(
        ocr_result=ocr_result,
        vision_description=response_text,
    )


def _select_key_frames(frames: list, max_n: int) -> list:
    """Pick the most informative frames: prefer scene-change, spread uniformly."""
    scene = [f for f in frames if f.kind == "scene"]
    uniform = [f for f in frames if f.kind == "uniform"]

    if len(scene) >= max_n:
        step = len(scene) / max_n
        return [scene[int(i * step)] for i in range(max_n)]

    selected = list(scene)
    remaining = max_n - len(selected)
    if uniform and remaining > 0:
        step = max(1, len(uniform) // remaining)
        selected.extend(uniform[::step][:remaining])

    selected.sort(key=lambda f: f.timestamp_s)
    return selected[:max_n]


def _build_ocr_frames(
    response: str,
    frames: list,
) -> list[OcrFrameResult]:
    """Convert vision model response into OcrFrameResult objects.

    The full response goes into the first frame's block so the signal
    tagger and entity extractor can match patterns in it.
    """
    results = []
    for idx, frame in enumerate(frames):
        blocks: list[OcrBlock] = []
        if idx == 0 and response.strip():
            blocks.append(
                OcrBlock(
                    text=response.strip(),
                    confidence=0.95,
                    bbox=(0, 0, 100, 30),
                )
            )
        results.append(
            OcrFrameResult(
                frame_index=idx,
                timestamp_s=frame.timestamp_s,
                image_path=str(frame.path),
                blocks=blocks,
            )
        )
    return results


def _empty_vision_ocr(video_id: str, source_hash: str, model: str) -> OcrResult:
    return OcrResult(
        engine="vision-llm",
        engine_version=model,
        source_file_sha256=source_hash,
        video_id=video_id,
        frames=[],
        generated_at=dt.datetime.now(dt.UTC),
    )
