"""Render SYNTHETIC benchmark items as real video files (audio + on-screen text).

!!! SYNTHETIC — every file is watermarked "SYNTHETIC TEST MEDIA" in a corner
and its metadata title says so; never mix these with real collected media. !!!

Audio: espeak-ng text-to-speech of the item's speech script (en / ru voice).
Video: Pillow-rendered frames at 5 fps with the item's overlay lines shown at
their timestamps, drawn with varied fonts/sizes/colours, background gradients,
JPEG noise and slight blur so that OCR is a real (imperfect) extraction step.

Usage:
  python scripts/revision/render_videos.py --corpus data/revision/synth_corpus.jsonl \
      --out data/revision/videos --per-family 6
"""

from __future__ import annotations

import argparse
import io
import json
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 960, 540, 5
FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
]
WATERMARK = "SYNTHETIC TEST MEDIA"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _background(rng: random.Random) -> Image.Image:
    c1 = tuple(rng.randint(0, 255) for _ in range(3))
    c2 = tuple(rng.randint(0, 255) for _ in range(3))
    img = Image.new("RGB", (W, H), c1)
    d = ImageDraw.Draw(img)
    for y in range(H):
        a = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(c1[i] * (1 - a) + c2[i] * a) for i in range(3)))
    for _ in range(rng.randint(3, 8)):  # clutter shapes
        x, y = rng.randint(0, W), rng.randint(0, H)
        r = rng.randint(20, 120)
        d.ellipse([x - r, y - r, x + r, y + r], outline=tuple(rng.randint(0, 255) for _ in range(3)), width=3)
    return img


def _wrap(text: str, font: ImageFont.FreeTypeFont, maxw: int, d: ImageDraw.ImageDraw) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=font) <= maxw:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_item(item: dict, out_path: Path, rng: random.Random) -> dict:
    speech_text = " ".join(s for _, s in item["speech"])
    voice = "ru" if item["language"] == "ru" else rng.choice(["en-us", "en", "en-us+m3", "en+f3"])
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        wav = td / "a.wav"
        subprocess.run(["espeak-ng", "-v", voice, "-s", str(rng.randint(140, 170)), "-w", str(wav), speech_text],
                       check=True, capture_output=True)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", str(wav)], capture_output=True, text=True).stdout.strip())
        dur = max(dur, 4.0 * len(item["speech"]))
        bg = _background(rng)
        font_path = rng.choice(FONTS)
        size = rng.randint(26, 40)
        font = _font(font_path, size)
        wm_font = _font(FONTS[1], 14)
        color = rng.choice([(255, 255, 255), (255, 230, 0), (0, 0, 0), (255, 60, 60)])
        box = rng.random() < 0.6
        frames_dir = td / "f"
        frames_dir.mkdir()
        n = int(dur * FPS) + 1
        y = rng.randint(40, 80)
        for k in range(n):
            t = k / FPS
            img = bg.copy()
            d = ImageDraw.Draw(img)
            visible = [txt for (ts, txt) in item["ocr"] if ts <= t < ts + 4.0]
            yy = y
            for txt in visible:
                for line in _wrap(txt, font, W - 80, d):
                    tw = d.textlength(line, font=font)
                    x = (W - tw) / 2
                    if box:
                        d.rectangle([x - 10, yy - 6, x + tw + 10, yy + size + 8],
                                    fill=(0, 0, 0) if color != (0, 0, 0) else (255, 255, 255))
                    d.text((x, yy), line, font=font, fill=color)
                    yy += size + 16
            d.text((W - 190, H - 22), WATERMARK, font=wm_font, fill=(200, 200, 200))
            img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=rng.randint(55, 85))
            (frames_dir / f"{k:05d}.jpg").write_bytes(buf.getvalue())
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", str(frames_dir / "%05d.jpg"),
            "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", "-metadata", f"title={WATERMARK} {item['id']}",
            "-metadata", "comment=Synthetic benchmark item generated for AIMW revision; label by construction",
            str(out_path),
        ], check=True)
    return {"id": item["id"], "path": str(out_path), "voice": voice, "font": Path(font_path).name, "size": size}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/revision/synth_corpus.jsonl")
    ap.add_argument("--out", default="data/revision/videos")
    ap.add_argument("--per-family", type=int, default=6)
    args = ap.parse_args()
    rng = random.Random(7)
    items = [json.loads(line) for line in Path(args.corpus).read_text(encoding="utf-8").splitlines()]
    by_fam: dict[str, list[dict]] = {}
    for it in items:
        by_fam.setdefault(it["family"], []).append(it)
    manifest = []
    for fam, its in by_fam.items():
        # take items WITH on-screen text so OCR is exercised (speech-only kept in text eval)
        chosen = [i for i in its if i["has_ocr"]][: args.per_family]
        for it in chosen:
            label = "scam" if it["label"] else "legit"
            meta = render_item(it, Path(args.out) / label / f"{it['id']}.mp4", rng)
            meta.update({"label": it["label"], "family": fam})
            manifest.append(meta)
            print("rendered", meta["path"])
    Path(args.out, "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"{len(manifest)} SYNTHETIC videos written to {args.out}")


if __name__ == "__main__":
    main()
