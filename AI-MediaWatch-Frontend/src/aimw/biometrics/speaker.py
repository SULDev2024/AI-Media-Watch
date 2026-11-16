"""Speaker diarization and cross-video voice linking.

Identifies WHO is speaking in each segment of a video's audio, and
links the same voice across different videos/campaigns — even when the
speaker changes accounts or platforms.

Algorithm:
  1. Load audio (WAV via stdlib wave, or extract from video via cv2).
  2. Frame-level MFCC-like features via scipy FFT (no librosa needed).
  3. Per-segment voice fingerprint: mean + std of spectral features →
     compact 128-dim speaker embedding.
  4. Cosine similarity ≥ VOICE_MATCH_THRESHOLD links speakers across
     videos.
  5. Simple energy-based diarization: segment audio by energy envelope
     and assign each segment a speaker label via embedding clustering.

Graceful degradation: if scipy/numpy are unavailable, returns empty.
"""
from __future__ import annotations

import logging
import struct
import wave
from pathlib import Path

log = logging.getLogger(__name__)

VOICE_MATCH_THRESHOLD: float = 0.88
N_MFCC: int = 13
N_FFT: int = 2048
HOP: int = 512
N_MEL: int = 40
EMBED_DIM: int = N_MEL * 2  # mean + std over mel bands = 80
SEGMENT_MIN_SEC: float = 1.0
ENERGY_THRESHOLD_RATIO: float = 0.1

_HAS_DEPS = False
try:
    import numpy as np
    from scipy.fft import rfft

    _HAS_DEPS = True
except ImportError:
    pass


def _load_wav_samples(path: str | Path) -> tuple[list[float], int] | None:
    try:
        with wave.open(str(path), "rb") as wf:
            n_ch = wf.getnchannels()
            sw = wf.getsampwidth()
            sr = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if sw == 2:
            samples = list(struct.unpack(f"<{len(raw) // 2}h", raw))
        elif sw == 1:
            samples = [s - 128 for s in raw]
        else:
            return None
        if n_ch > 1:
            samples = samples[::n_ch]
        peak = max(abs(s) for s in samples) if samples else 1
        if peak == 0:
            peak = 1
        return [s / peak for s in samples], sr
    except Exception:
        return None


def _mel_filterbank(n_fft: int, sr: int, n_mel: int) -> "np.ndarray":
    fmax = sr / 2.0
    mel_low = 2595.0 * np.log10(1.0 + 0 / 700.0)
    mel_high = 2595.0 * np.log10(1.0 + fmax / 700.0)
    mels = np.linspace(mel_low, mel_high, n_mel + 2)
    freqs = 700.0 * (10.0 ** (mels / 2595.0) - 1.0)
    bins = np.floor((n_fft + 1) * freqs / sr).astype(int)
    n_bins = n_fft // 2 + 1
    fb = np.zeros((n_mel, n_bins))
    for m in range(n_mel):
        f_left, f_center, f_right = bins[m], bins[m + 1], bins[m + 2]
        for k in range(f_left, f_center):
            if f_center != f_left:
                fb[m, k] = (k - f_left) / (f_center - f_left)
        for k in range(f_center, f_right):
            if f_right != f_center:
                fb[m, k] = (f_right - k) / (f_right - f_center)
    return fb


def _spectral_features(samples: list[float], sr: int) -> "np.ndarray":
    arr = np.array(samples, dtype=np.float64)
    fb = _mel_filterbank(N_FFT, sr, N_MEL)
    frames: list["np.ndarray"] = []
    pos = 0
    while pos + N_FFT <= len(arr):
        window = arr[pos : pos + N_FFT] * np.hanning(N_FFT)
        spectrum = np.abs(rfft(window)) ** 2
        mel_spec = np.dot(fb, spectrum[: fb.shape[1]])
        mel_spec = np.log1p(mel_spec)
        frames.append(mel_spec)
        pos += HOP
    if not frames:
        return np.array([])
    return np.array(frames)


def compute_voice_embedding(
    audio_path: str | Path,
) -> list[float]:
    """Compute a speaker embedding from a WAV file.

    Returns an 80-dim vector (mean + std of 40 mel bands), or empty list.
    """
    if not _HAS_DEPS:
        return []
    result = _load_wav_samples(audio_path)
    if result is None:
        return []
    samples, sr = result
    if len(samples) < N_FFT:
        return []
    feats = _spectral_features(samples, sr)
    if feats.size == 0:
        return []
    mean = feats.mean(axis=0)
    std = feats.std(axis=0)
    emb = np.concatenate([mean, std])
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb.tolist()


def _cosine(a: list[float], b: list[float]) -> float:
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


def diarize(
    audio_path: str | Path,
    min_segment_sec: float = SEGMENT_MIN_SEC,
) -> list[dict]:
    """Simple energy-based speaker diarization.

    Returns a list of segments:
      {"start_sec": float, "end_sec": float, "speaker": str, "embedding": list[float]}
    """
    if not _HAS_DEPS:
        return []
    result = _load_wav_samples(audio_path)
    if result is None:
        return []
    samples, sr = result
    if len(samples) < N_FFT:
        return []

    arr = np.array(samples, dtype=np.float64)
    frame_len = int(sr * 0.025)
    frame_hop = int(sr * 0.010)
    energies: list[float] = []
    pos = 0
    while pos + frame_len <= len(arr):
        e = float(np.sum(arr[pos : pos + frame_len] ** 2))
        energies.append(e)
        pos += frame_hop
    if not energies:
        return []

    threshold = max(energies) * ENERGY_THRESHOLD_RATIO
    min_frames = int(min_segment_sec / 0.010)

    segments: list[tuple[int, int]] = []
    in_speech = False
    start = 0
    for i, e in enumerate(energies):
        if e > threshold and not in_speech:
            in_speech = True
            start = i
        elif e <= threshold and in_speech:
            if i - start >= min_frames:
                segments.append((start, i))
            in_speech = False
    if in_speech and len(energies) - start >= min_frames:
        segments.append((start, len(energies)))

    results: list[dict] = []
    embeddings: list[list[float]] = []
    for seg_start, seg_end in segments:
        s_start = seg_start * frame_hop
        s_end = min(seg_end * frame_hop + frame_len, len(arr))
        seg_samples = arr[s_start:s_end].tolist()
        if len(seg_samples) < N_FFT:
            continue
        feats = _spectral_features(seg_samples, sr)
        if feats.size == 0:
            continue
        mean = feats.mean(axis=0)
        std = feats.std(axis=0)
        emb = np.concatenate([mean, std])
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        emb_list = emb.tolist()

        speaker_label = f"speaker_{len(embeddings)}"
        for idx, prev_emb in enumerate(embeddings):
            sim = _cosine(emb_list, prev_emb)
            if sim >= VOICE_MATCH_THRESHOLD:
                speaker_label = f"speaker_{idx}"
                break
        else:
            embeddings.append(emb_list)

        results.append({
            "start_sec": round(seg_start * 0.010, 3),
            "end_sec": round(seg_end * 0.010, 3),
            "speaker": speaker_label,
            "embedding": emb_list,
        })
    return results


def find_voice_matches(
    voice_index: dict[str, list[float]],
    threshold: float = VOICE_MATCH_THRESHOLD,
) -> list[tuple[str, str, float]]:
    """Find cross-video voice matches.

    Parameters
    ----------
    voice_index:
        Mapping video_id → speaker embedding (from compute_voice_embedding).

    Returns
    -------
    List of (video_a, video_b, similarity) sorted by similarity desc.
    """
    ids = sorted(voice_index)
    matches: list[tuple[str, str, float]] = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ea, eb = voice_index[ids[i]], voice_index[ids[j]]
            if not ea or not eb:
                continue
            sim = _cosine(ea, eb)
            if sim >= threshold:
                matches.append((ids[i], ids[j], round(sim, 4)))
    matches.sort(key=lambda t: -t[2])
    return matches


__all__ = [
    "compute_voice_embedding",
    "diarize",
    "find_voice_matches",
    "VOICE_MATCH_THRESHOLD",
]
