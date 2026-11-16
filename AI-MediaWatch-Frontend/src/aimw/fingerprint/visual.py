"""Visual perceptual-hash fingerprinting for template detection.

Scam campaigns reuse the same visual template (overlay graphics, text
layout, branded backgrounds) across throwaway accounts.  Perceptual
hashing compresses each frame into a short bitstring that survives
re-encoding, slight crops, and colour shifts — matching templates even
when the underlying video is re-uploaded to a different platform.

Algorithm: pHash from ``imagehash`` → 64-bit hash per frame.
Two videos share a visual_match when the minimum Hamming distance
between any pair of their frame hashes is ≤ HAMMING_THRESHOLD.

Optional (best-effort): if cv2 or PIL are missing the module degrades
gracefully — ``compute`` returns an empty list and ``find_matches``
never fires.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)

HAMMING_THRESHOLD: int = 10
SAMPLE_INTERVAL_SEC: float = 5.0

_HAS_DEPS = False
try:
    import cv2  # type: ignore[import-untyped]
    import imagehash  # type: ignore[import-untyped]
    from PIL import Image

    _HAS_DEPS = True
except ImportError:
    pass


def _frames_from_video(path: str | Path, interval: float = SAMPLE_INTERVAL_SEC) -> list:
    if not _HAS_DEPS:
        return []
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(fps * interval))
    frames: list = []
    idx = 0
    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames.append(Image.fromarray(rgb))
        idx += step
    cap.release()
    return frames


def _frames_from_images(paths: Sequence[str | Path]) -> list:
    if not _HAS_DEPS:
        return []
    out: list = []
    for p in paths:
        try:
            out.append(Image.open(str(p)).convert("RGB"))
        except Exception:
            continue
    return out


def compute_hashes(
    video_path: str | Path | None = None,
    image_paths: Sequence[str | Path] | None = None,
) -> list[str]:
    """Return pHash hex strings for sampled frames or images."""
    if not _HAS_DEPS:
        return []
    frames: list = []
    if video_path:
        frames = _frames_from_video(video_path)
    elif image_paths:
        frames = _frames_from_images(image_paths)
    if not frames:
        return []
    hashes: list[str] = []
    seen: set[str] = set()
    for img in frames:
        try:
            h = str(imagehash.phash(img))
            if h not in seen:
                hashes.append(h)
                seen.add(h)
        except Exception:
            continue
    return hashes


def hamming(a: str, b: str) -> int:
    """Hamming distance between two hex-encoded hashes."""
    if len(a) != len(b):
        return 64
    ia, ib = int(a, 16), int(b, 16)
    return bin(ia ^ ib).count("1")


def find_visual_matches(
    index: dict[str, list[str]],
    threshold: int = HAMMING_THRESHOLD,
) -> list[tuple[str, str, int]]:
    """Find video pairs with visually similar frames.

    Parameters
    ----------
    index:
        Mapping video_id → list of pHash hex strings.
    threshold:
        Max Hamming distance to consider a match.

    Returns
    -------
    List of (video_a, video_b, min_hamming) sorted by distance asc.
    """
    ids = sorted(index)
    matches: list[tuple[str, str, int]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ha, hb = index[ids[i]], index[ids[j]]
            if not ha or not hb:
                continue
            min_d = 64
            for a in ha:
                for b in hb:
                    d = hamming(a, b)
                    if d < min_d:
                        min_d = d
            if min_d <= threshold:
                matches.append((ids[i], ids[j], min_d))
    matches.sort(key=lambda t: t[2])
    return matches


__all__ = ["compute_hashes", "find_visual_matches", "hamming", "HAMMING_THRESHOLD"]
