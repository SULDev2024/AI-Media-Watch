"""Logo and brand detection — flag fraudulent use of official seals.

Scam campaigns frequently embed government logos, bank logos, or
official seals in their video overlays and thumbnails to create false
authority.  This module detects those logos by matching against a
reference library using ORB feature descriptors.

Algorithm:
  1. Load reference logos from ``config/logos/`` (PNG/JPG files named
     by the brand they represent, e.g. ``national_bank.png``).
  2. For each video frame or image, extract ORB keypoints + descriptors.
  3. Match descriptors against every reference logo using brute-force
     Hamming matcher.
  4. If ≥ MIN_GOOD_MATCHES inlier matches survive the ratio test,
     the logo is considered detected.

Graceful degradation: if cv2 is unavailable or no reference logos
exist, returns empty results.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)

MIN_GOOD_MATCHES: int = 15
RATIO_THRESHOLD: float = 0.75
MAX_FEATURES: int = 500
SAMPLE_INTERVAL_SEC: float = 3.0

_HAS_DEPS = False
try:
    import cv2
    import numpy as np

    _HAS_DEPS = True
except (ImportError, AttributeError):
    pass

_LOGOS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config" / "logos"


def _load_reference_logos() -> dict[str, dict]:
    if not _HAS_DEPS or not _LOGOS_DIR.is_dir():
        return {}
    orb = cv2.ORB_create(nfeatures=MAX_FEATURES)
    logos: dict[str, dict] = {}
    for p in sorted(_LOGOS_DIR.iterdir()):
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
            continue
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        kp, des = orb.detectAndCompute(img, None)
        if des is None or len(kp) < 5:
            continue
        brand = p.stem.replace("_", " ").replace("-", " ").title()
        logos[brand] = {
            "path": str(p),
            "keypoints": kp,
            "descriptors": des,
            "brand": brand,
        }
    return logos


_ref_cache: dict[str, dict] | None = None


def _get_references() -> dict[str, dict]:
    global _ref_cache
    if _ref_cache is None:
        _ref_cache = _load_reference_logos()
    return _ref_cache


def reload_references() -> int:
    global _ref_cache
    _ref_cache = _load_reference_logos()
    return len(_ref_cache)


def detect_logos_in_image(
    image_path: str | Path,
    min_matches: int = MIN_GOOD_MATCHES,
) -> list[dict]:
    """Detect reference logos in a single image.

    Returns list of dicts:
      {"brand": str, "n_matches": int, "confidence": float}
    """
    if not _HAS_DEPS:
        return []
    refs = _get_references()
    if not refs:
        return []

    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []

    orb = cv2.ORB_create(nfeatures=MAX_FEATURES)
    kp, des = orb.detectAndCompute(img, None)
    if des is None:
        return []

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    detected: list[dict] = []

    for brand, ref in refs.items():
        try:
            matches_raw = bf.knnMatch(ref["descriptors"], des, k=2)
        except Exception:
            continue
        good = []
        for m_pair in matches_raw:
            if len(m_pair) == 2:
                m, n = m_pair
                if m.distance < RATIO_THRESHOLD * n.distance:
                    good.append(m)
        if len(good) >= min_matches:
            confidence = min(1.0, len(good) / (min_matches * 3))
            detected.append({
                "brand": brand,
                "n_matches": len(good),
                "confidence": round(confidence, 3),
            })

    detected.sort(key=lambda d: -d["confidence"])
    return detected


def detect_logos_in_video(
    video_path: str | Path,
    interval: float = SAMPLE_INTERVAL_SEC,
    min_matches: int = MIN_GOOD_MATCHES,
) -> list[dict]:
    """Detect reference logos across video frames.

    Returns list of dicts:
      {"brand": str, "n_matches": int, "confidence": float,
       "frame_idx": int, "timestamp_sec": float}
    """
    if not _HAS_DEPS:
        return []
    refs = _get_references()
    if not refs:
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(fps * interval))

    orb = cv2.ORB_create(nfeatures=MAX_FEATURES)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    detected: list[dict] = []
    seen_brands: set[str] = set()
    idx = 0

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        kp, des = orb.detectAndCompute(gray, None)
        if des is None:
            idx += step
            continue

        for brand, ref in refs.items():
            if brand in seen_brands:
                continue
            try:
                matches_raw = bf.knnMatch(ref["descriptors"], des, k=2)
            except Exception:
                continue
            good = []
            for m_pair in matches_raw:
                if len(m_pair) == 2:
                    m, n = m_pair
                    if m.distance < RATIO_THRESHOLD * n.distance:
                        good.append(m)
            if len(good) >= min_matches:
                confidence = min(1.0, len(good) / (min_matches * 3))
                detected.append({
                    "brand": brand,
                    "n_matches": len(good),
                    "confidence": round(confidence, 3),
                    "frame_idx": idx,
                    "timestamp_sec": round(idx / fps, 2),
                })
                seen_brands.add(brand)
        idx += step

    cap.release()
    detected.sort(key=lambda d: -d["confidence"])
    return detected


def scan_batch(
    media_paths: dict[str, str | Path],
    min_matches: int = MIN_GOOD_MATCHES,
) -> dict[str, list[dict]]:
    """Scan multiple media files for logos.

    Parameters
    ----------
    media_paths:
        Mapping video_id → file path.

    Returns
    -------
    Mapping video_id → list of detected logos.
    """
    results: dict[str, list[dict]] = {}
    for vid, path in media_paths.items():
        p = Path(path)
        if p.suffix.lower() in (".mp4", ".mkv", ".avi", ".webm", ".mov"):
            results[vid] = detect_logos_in_video(p, min_matches=min_matches)
        else:
            results[vid] = detect_logos_in_image(p, min_matches=min_matches)
    return results


def list_reference_logos() -> list[dict]:
    """Return metadata about loaded reference logos."""
    refs = _get_references()
    return [
        {
            "brand": brand,
            "path": ref["path"],
            "n_keypoints": len(ref["keypoints"]),
        }
        for brand, ref in refs.items()
    ]


__all__ = [
    "detect_logos_in_image",
    "detect_logos_in_video",
    "scan_batch",
    "list_reference_logos",
    "reload_references",
    "MIN_GOOD_MATCHES",
]
