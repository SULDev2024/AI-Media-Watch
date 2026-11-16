"""Acoustic fingerprinting for speaker/audio template matching.

Detects that two videos share the same background music, TTS voice, or
audio template — a common signal in scam campaign re-uploads.

Algorithm: short-time spectral centroid fingerprint using scipy+numpy.
Audio is read via ``cv2.VideoCapture`` → raw PCM (if available) or
``wave`` stdlib for .wav files.  The audio is chunked into overlapping
windows, and a compact spectral-centroid feature vector is extracted.
Cosine similarity ≥ SIMILARITY_THRESHOLD triggers a match.

Graceful degradation: if scipy/numpy/cv2 are not installed, ``compute``
returns an empty list and matching never fires.
"""
from __future__ import annotations

import logging
import struct
import wave
from pathlib import Path

log = logging.getLogger(__name__)

SIMILARITY_THRESHOLD: float = 0.85
WINDOW_SIZE: int = 2048
HOP_SIZE: int = 1024
N_FEATURES: int = 64

_HAS_DEPS = False
try:
    import numpy as np
    from scipy.fft import rfft  # type: ignore[import-untyped]

    _HAS_DEPS = True
except ImportError:
    pass


def _load_wav(path: str | Path) -> tuple[list[float], int] | None:
    try:
        with wave.open(str(path), "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if sampwidth == 2:
            fmt = f"<{len(raw) // 2}h"
            samples = list(struct.unpack(fmt, raw))
        elif sampwidth == 1:
            samples = [s - 128 for s in raw]
        else:
            return None
        if n_channels > 1:
            samples = samples[::n_channels]
        peak = max(abs(s) for s in samples) if samples else 1
        if peak == 0:
            peak = 1
        return [s / peak for s in samples], framerate
    except Exception:
        return None


def compute_fingerprint(
    audio_path: str | Path | None = None,
) -> list[float]:
    """Compute a spectral-centroid feature vector from an audio file.

    Returns a list of N_FEATURES floats (the centroid envelope), or
    an empty list if deps are missing or the file can't be read.
    """
    if not _HAS_DEPS or audio_path is None:
        return []

    result = _load_wav(audio_path)
    if result is None:
        return []
    samples, sr = result
    if len(samples) < WINDOW_SIZE:
        return []

    arr = np.array(samples, dtype=np.float64)
    centroids: list[float] = []
    pos = 0
    while pos + WINDOW_SIZE <= len(arr):
        window = arr[pos : pos + WINDOW_SIZE]
        spectrum = np.abs(rfft(window))
        freqs = np.linspace(0, sr / 2, len(spectrum))
        total = spectrum.sum()
        if total > 0:
            centroid = float((freqs * spectrum).sum() / total)
        else:
            centroid = 0.0
        centroids.append(centroid)
        pos += HOP_SIZE

    if not centroids:
        return []

    n = len(centroids)
    if n >= N_FEATURES:
        step = n / N_FEATURES
        features = [centroids[int(i * step)] for i in range(N_FEATURES)]
    else:
        features = centroids + [0.0] * (N_FEATURES - n)

    peak = max(abs(f) for f in features) if features else 1.0
    if peak > 0:
        features = [f / peak for f in features]
    return features


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not _HAS_DEPS or not a or not b or len(a) != len(b):
        return 0.0
    va = np.array(a)
    vb = np.array(b)
    dot = float(np.dot(va, vb))
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def find_acoustic_matches(
    index: dict[str, list[float]],
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[tuple[str, str, float]]:
    """Find video pairs with similar audio fingerprints.

    Parameters
    ----------
    index:
        Mapping video_id → feature vector (from ``compute_fingerprint``).
    threshold:
        Minimum cosine similarity for a match.

    Returns
    -------
    List of (video_a, video_b, similarity) sorted by similarity desc.
    """
    ids = sorted(index)
    matches: list[tuple[str, str, float]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            fa, fb = index[ids[i]], index[ids[j]]
            if not fa or not fb:
                continue
            sim = cosine_similarity(fa, fb)
            if sim >= threshold:
                matches.append((ids[i], ids[j], round(sim, 4)))
    matches.sort(key=lambda t: -t[2])
    return matches


__all__ = [
    "compute_fingerprint",
    "cosine_similarity",
    "find_acoustic_matches",
    "SIMILARITY_THRESHOLD",
]
