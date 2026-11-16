#!/usr/bin/env python
"""Phase 7 end-to-end verification script.

Creates a fixture video with all entity types overlaid across multiple scenes,
runs real PaddleOCR on it (Phase 6), injects a synthetic speech transcript
(Phase 5 shape), then runs Phase 7 entity extraction and writes JSON artifacts.

Usage:
    uv run python scripts/verify_phase7.py

Artifacts written to:
    artifacts/phase7/phase5_transcript.json
    artifacts/phase7/phase6_ocr.json
    artifacts/phase7/phase7_entities.json
    artifacts/phase7/phase7_rawspans.json
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
from pathlib import Path

# Force UTF-8 on Windows consoles that default to cp1252.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_VIDEO = ROOT / "fixtures" / "video" / "phase7_verify.mp4"
ARTIFACTS = ROOT / "artifacts" / "phase7"
VIDEO_ID = "phase7verify0001"

# Entity test data ─ deliberately covering every type the extractor handles.
# OCR scenes: each tuple is (background_rgb, text_lines)
OCR_SCENES = [
    # Scene 0 ─ Telegram handle and t.me link
    ((18, 18, 18), ["@signal_kz_vip", "t.me/signal_kz_vip"]),
    # Scene 1 ─ Bitcoin bech32 wallet
    ((50, 80, 50), ["bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"]),
    # Scene 2 ─ Phone + profit claim
    ((230, 230, 230), ["+7 (701) 234-56-78", "ГАРАНТИЯ 25% в день"]),
    # Scene 3 ─ Referral code + Ethereum wallet
    ((200, 180, 150), ["реферал: CRYPTO2024", "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe"]),
]

# Speech segments ─ synthetic transcript representing Phase 5 output.
# Includes: phone near kaspi keyword (payment tagging), referral in speech,
# and a Bitcoin wallet address dictated aloud.
SPEECH_SEGMENTS = [
    # t=0s ─ Phone mentioned near kaspi → expected payment_phones tag
    {"start": 0.0, "end": 4.0, "text": "Переводи на kaspi +7 701 234 56 78 для оплаты подписки"},
    # t=4s ─ Handle mentioned in speech (exact match)
    {"start": 4.0, "end": 7.5, "text": "Пишите нам @signal_kz_vip получите бонус"},
    # t=7.5s ─ Referral code in speech
    {"start": 7.5, "end": 11.0, "text": "Используй promo CRYPTO2024 для первого депозита"},
    # t=11s ─ Wallet address dictated aloud (common in scam videos)
    {
        "start": 11.0,
        "end": 15.0,
        "text": "Отправляй на bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh только биткоин",
    },
]

# ---------------------------------------------------------------------------
# Step 1: Build the fixture video
# ---------------------------------------------------------------------------


def build_fixture_video() -> None:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    FIXTURE_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    if FIXTURE_VIDEO.exists():
        print(f"[fixture] already exists: {FIXTURE_VIDEO.name}")
        return

    W, H, FPS = 640, 360, 24
    scene_duration = 3.0  # seconds per scene

    # Pick a Cyrillic-capable font.
    font_candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    font = None
    for candidate in font_candidates:
        try:
            f = ImageFont.truetype(candidate, 40)
            if f.getmask("Г").size[0] > 0:
                font = f
                break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(FIXTURE_VIDEO), fourcc, FPS, (W, H))
    if not writer.isOpened():
        raise OSError(f"VideoWriter cannot open {FIXTURE_VIDEO}")

    try:
        for bg_rgb, lines in OCR_SCENES:
            img = Image.new("RGB", (W, H), color=bg_rgb)
            draw = ImageDraw.Draw(img)
            y = 60
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                x = (W - tw) // 2
                # White box for OCR contrast
                draw.rectangle((x - 8, y - 4, x + tw + 8, y + th + 4), fill=(255, 255, 255))
                draw.text((x, y), line, fill=(0, 0, 0), font=font)
                y += th + 24

            bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            n_frames = int(FPS * scene_duration)
            for _ in range(n_frames):
                writer.write(bgr)
    finally:
        writer.release()

    print(f"[fixture] created: {FIXTURE_VIDEO} ({FIXTURE_VIDEO.stat().st_size // 1024} KB)")


# ---------------------------------------------------------------------------
# Step 2: Run PaddleOCR (Phase 6) on the fixture video
# ---------------------------------------------------------------------------


async def run_ocr() -> dict:
    from aimw.extraction.ocr.cache import OcrCache
    from aimw.extraction.ocr.engine import OcrExtractor
    from aimw.extraction.ocr.paddle import OcrEngine

    engine = OcrEngine(requested="paddle_vl")
    cache = OcrCache(ARTIFACTS / "ocr_cache")
    extractor = OcrExtractor(
        engine=engine,
        cache=cache,
        frame_cache_dir=ARTIFACTS / "frames",
        scene_threshold=0.3,
        frames_per_3s=1,
    )
    result = await extractor.extract(FIXTURE_VIDEO, VIDEO_ID)
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Step 3: Build a synthetic Phase 5 transcript
# ---------------------------------------------------------------------------


def build_transcript() -> dict:
    import hashlib

    sha = hashlib.sha256(FIXTURE_VIDEO.read_bytes()).hexdigest()
    return {
        "cache_version": "1",
        "engine": "faster-whisper",
        "engine_version": "1.1.1",
        "model": "large-v3",
        "device": "cpu",
        "compute_type": "int8",
        "source_file_sha256": sha,
        "video_id": VIDEO_ID,
        "language_detected": "ru",
        "segments": [
            {"start": s["start"], "end": s["end"], "text": s["text"], "words": []}
            for s in SPEECH_SEGMENTS
        ],
        "generated_at": "2026-06-13T10:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Step 4: Run Phase 7 entity extraction
# ---------------------------------------------------------------------------


async def run_entities(transcript_dict: dict, ocr_dict: dict) -> tuple[dict, list[dict]]:
    from aimw.entities.extractor import extract_async
    from aimw.extraction.ocr.models import OcrResult
    from aimw.extraction.whisper.models import Transcript

    transcript = Transcript.model_validate(transcript_dict)
    ocr = OcrResult.model_validate(ocr_dict)
    entities, spans = await extract_async(transcript, ocr)
    return entities.model_dump(mode="json"), [s.model_dump(mode="json") for s in spans]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    # ── Step 1: fixture video ──────────────────────────────────────────────
    print("\n=== STEP 1: Build fixture video ===")
    build_fixture_video()

    # ── Step 2: OCR ───────────────────────────────────────────────────────
    print("\n=== STEP 2: Run PaddleOCR (Phase 6) ===")
    t0 = time.monotonic()
    ocr_dict = await run_ocr()
    elapsed_ocr = time.monotonic() - t0
    print(f"  frames processed : {len(ocr_dict['frames'])}")
    total_blocks = sum(len(f["blocks"]) for f in ocr_dict["frames"])
    print(f"  total OCR blocks : {total_blocks}")
    print(f"  runtime          : {elapsed_ocr:.1f}s")
    print("\n  Raw OCR blocks per frame:")
    for f in ocr_dict["frames"]:
        print(f"    frame[{f['frame_index']}] t={f['timestamp_s']:.1f}s  blocks={len(f['blocks'])}")
        for b in f["blocks"]:
            print(f"      conf={b['confidence']:.3f}  text={b['text']!r}")

    # ── Step 3: Transcript ────────────────────────────────────────────────
    print("\n=== STEP 3: Build synthetic transcript (Phase 5 shape) ===")
    transcript_dict = build_transcript()
    print(f"  segments : {len(transcript_dict['segments'])}")
    for seg in transcript_dict["segments"]:
        print(f"    [{seg['start']:.1f}–{seg['end']:.1f}] {seg['text']}")

    # ── Step 4: Phase 7 entities ──────────────────────────────────────────
    print("\n=== STEP 4: Run entity extraction (Phase 7) ===")
    entities_dict, spans = await run_entities(transcript_dict, ocr_dict)

    # ── Write artifacts ───────────────────────────────────────────────────
    def dump(path: Path, obj: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  wrote {path.relative_to(ROOT)}")

    dump(ARTIFACTS / "phase5_transcript.json", transcript_dict)
    dump(ARTIFACTS / "phase6_ocr.json", ocr_dict)
    dump(ARTIFACTS / "phase7_entities.json", entities_dict)
    dump(ARTIFACTS / "phase7_rawspans.json", spans)

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n=== PHASE 7 EXTRACTION SUMMARY ===")
    print(json.dumps(entities_dict, ensure_ascii=False, indent=2))

    print("\n=== RAW SPANS (first 20) ===")
    print(json.dumps(spans[:20], ensure_ascii=False, indent=2))

    print("\n=== COVERAGE CHECK ===")
    checks = [
        ("wallets", bool(entities_dict["crypto_wallets"]), entities_dict["crypto_wallets"]),
        ("handles", bool(entities_dict["telegram_handles"]), entities_dict["telegram_handles"]),
        ("links", bool(entities_dict["telegram_links"]), entities_dict["telegram_links"]),
        ("phones", bool(entities_dict["phone_numbers"]), entities_dict["phone_numbers"]),
        ("payment phones", bool(entities_dict["payment_phones"]), entities_dict["payment_phones"]),
        ("profits", bool(entities_dict["profit_claims"]), entities_dict["profit_claims"]),
        ("referrals", bool(entities_dict["referral_codes"]), entities_dict["referral_codes"]),
    ]
    all_ok = True
    for label, ok, values in checks:
        status = "✓" if ok else "✗ MISSING"
        print(f"  {status:12s} {label}: {values}")
        if not ok:
            all_ok = False

    # Check source attribution
    sources = {s["source"] for s in spans}
    print(f"\n  sources seen     : {sorted(sources)}")
    ocr_spans = [s for s in spans if s["source"] == "ocr"]
    speech_spans = [s for s in spans if s["source"] == "speech"]
    print(f"  ocr spans        : {len(ocr_spans)}")
    print(f"  speech spans     : {len(speech_spans)}")

    # Certainty distribution
    by_method: dict[str, list[float]] = {}
    for s in spans:
        by_method.setdefault(s["recovery_method"], []).append(s["certainty"])
    print("\n  certainty by recovery_method:")
    for method, certs in sorted(by_method.items()):
        print(f"    {method:20s}  n={len(certs):3d}  certainty={set(certs)}")

    # Timestamps
    ts_present = sum(1 for s in spans if s["timestamp"] is not None)
    print(f"\n  spans with timestamp : {ts_present}/{len(spans)}")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
