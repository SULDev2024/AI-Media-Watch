"""Run the extraction stage on real video files and emit a scoring-ready JSONL.

For each video: frames are sampled (1 fps) and OCR'd; the audio track is
transcribed.  Output rows have the same shape as synth_corpus.jsonl but with
``speech`` / ``ocr`` coming from *extraction*, not from the script.

OCR engine
  --ocr tesseract   (default here; Tesseract 5, eng+rus).  The production system
                    uses PaddleOCR or the qwen2.5-VL vision path; Tesseract is
                    used in the revision sandbox because those models could not
                    be downloaded there. Report it as such.
ASR engine
  --asr whisper     faster-whisper (the production ASR; needs the model locally)
  --asr script-noisy  the TTS script with seeded word-level corruption at a
                    target word-error-rate (default 15%) — a stand-in used ONLY
                    when Whisper weights are unavailable; disclose it.
  --asr script      oracle transcript (upper bound on the speech channel)

Usage:
  python scripts/revision/multimodal_extract.py --manifest data/revision/videos/manifest.json \
      --corpus data/revision/synth_corpus.jsonl --out data/revision/mm_extracted.jsonl --asr script-noisy
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path


def sample_frames(video: Path, td: Path, fps: float = 1.0) -> list[tuple[float, Path]]:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf", f"fps={fps}",
                    str(td / "f_%04d.png")], check=True)
    frames = sorted(td.glob("f_*.png"))
    return [((i + 0.5) / fps, p) for i, p in enumerate(frames)]


def ocr_tesseract(img: Path, lang: str) -> list[str]:
    import pytesseract
    from PIL import Image, ImageOps

    im = Image.open(img).convert("L")
    texts = []
    for variant in (im, ImageOps.invert(im)):  # light-on-dark and dark-on-light
        txt = pytesseract.image_to_string(variant, lang=lang, config="--psm 6")
        texts.extend(line.strip() for line in txt.splitlines())
    keep = []
    for t in texts:
        alnum = sum(c.isalnum() for c in t)
        if len(t) >= 4 and alnum / max(len(t), 1) > 0.6 and "SYNTHETIC TEST" not in t.upper():
            keep.append(t)
    return keep


def dedupe_blocks(blocks: list[tuple[float, str]]) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for t, txt in blocks:
        if any(SequenceMatcher(None, txt.lower(), o.lower()).ratio() > 0.85 for _, o in out[-8:]):
            continue
        out.append((t, txt))
    return out


def asr_whisper(video: Path, model_size: str = "small") -> list[tuple[float, str]]:
    from faster_whisper import WhisperModel  # production ASR

    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segs, _ = model.transcribe(str(video), vad_filter=True)
    return [(s.start, s.text.strip()) for s in segs]


_VOCAB = ("the a and to of is it you we this that for on with get now day".split())


def corrupt(text: str, wer: float, rng: random.Random) -> str:
    """Seeded word-level corruption (substitution/deletion/insertion ≈ wer)."""
    out = []
    for w in text.split():
        r = rng.random()
        if r < wer * 0.5:  # substitution: perturb characters
            chars = list(w)
            if chars:
                j = rng.randrange(len(chars))
                chars[j] = rng.choice("aeioustnrl")
            out.append("".join(chars))
        elif r < wer * 0.8:  # deletion
            continue
        elif r < wer:  # insertion
            out.extend([w, rng.choice(_VOCAB)])
        else:
            out.append(w)
    return " ".join(out)


def cer(ref: str, hyp: str) -> float:
    ref, hyp = re.sub(r"\s+", " ", ref.lower()), re.sub(r"\s+", " ", hyp.lower())
    if not ref:
        return 0.0
    return 1.0 - SequenceMatcher(None, ref, hyp).ratio()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/revision/videos/manifest.json")
    ap.add_argument("--corpus", default="data/revision/synth_corpus.jsonl")
    ap.add_argument("--out", default="data/revision/mm_extracted.jsonl")
    ap.add_argument("--ocr", default="tesseract", choices=["tesseract"])
    ap.add_argument("--asr", default="script-noisy", choices=["whisper", "script", "script-noisy"])
    ap.add_argument("--wer", type=float, default=0.15)
    ap.add_argument("--whisper-model", default="small")
    args = ap.parse_args()

    corpus = {json.loads(line)["id"]: json.loads(line)
              for line in Path(args.corpus).read_text(encoding="utf-8").splitlines()}
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    rng = random.Random(99)
    rows = []
    for m in manifest:
        it = corpus[m["id"]]
        video = Path(m["path"])
        lang = "rus+eng" if it["language"] == "ru" else "eng"
        with tempfile.TemporaryDirectory() as td:
            blocks = []
            for t, fp in sample_frames(video, Path(td)):
                blocks.extend((t, txt) for txt in ocr_tesseract(fp, lang))
        blocks = dedupe_blocks(blocks)
        if args.asr == "whisper":
            speech = asr_whisper(video, args.whisper_model)
        elif args.asr == "script":
            speech = [tuple(s) for s in it["speech"]]
        else:
            speech = [(t, corrupt(s, args.wer, rng)) for t, s in it["speech"]]
        ocr_ref = " ".join(s for _, s in it["ocr"])
        ocr_hyp = " ".join(s for _, s in blocks)
        rows.append({
            "id": it["id"], "family": it["family"], "label": it["label"], "hard": it["hard"],
            "language": it["language"], "synthetic": True,
            "speech": [list(x) for x in speech], "ocr": [list(x) for x in blocks],
            "ocr_cer": round(cer(ocr_ref, ocr_hyp), 4),
            "extraction": {"ocr": args.ocr, "asr": args.asr, "wer_injected": args.wer if args.asr == "script-noisy" else None},
        })
        print(f"{it['id']}: {len(blocks)} OCR blocks, OCR CER={rows[-1]['ocr_cer']:.2f}")
    Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
