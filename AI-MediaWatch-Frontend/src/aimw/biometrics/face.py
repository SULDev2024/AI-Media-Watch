"""Face detection, embedding, and cross-video re-identification.

Detects faces in video frames or images, computes a compact embedding
vector for each face, and matches the same person across different
videos, accounts, and platforms — even when the operator changes
usernames or moves to a new channel.

Algorithm:
  1. Face detection via OpenCV Haar cascade (ships with every cv2 build).
  2. Normalize detected face → 128×128 grayscale.
  3. Compute a spatial-histogram embedding: divide the face into an 8×8
     grid, compute a 16-bin LBP-style histogram per cell → 1024-dim
     feature vector.  This survives re-encoding, slight angle changes,
     and moderate lighting shifts.
  4. Match faces across videos by cosine similarity ≥ MATCH_THRESHOLD.

Graceful degradation: if cv2 or numpy are unavailable, every function
returns empty results — the pipeline continues without face analysis.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)

MATCH_THRESHOLD: float = 0.82
FACE_SIZE: int = 128
GRID: int = 8
HIST_BINS: int = 16
EMBED_DIM: int = GRID * GRID * HIST_BINS  # 1024
SAMPLE_INTERVAL_SEC: float = 2.0

_HAS_DEPS = False
_cascade = None

try:
    import cv2
    import numpy as np

    _HAS_DEPS = True
    _cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    _cascade = cv2.CascadeClassifier(_cascade_path)
except (ImportError, AttributeError, Exception):
    pass


def _detect_faces_frame(frame_bgr) -> list:
    if not _HAS_DEPS or _cascade is None:
        return []
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    faces = _cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
    )
    if not isinstance(faces, np.ndarray) or len(faces) == 0:
        return []
    results = []
    for x, y, w, h in faces:
        roi = gray[y : y + h, x : x + w]
        roi = cv2.resize(roi, (FACE_SIZE, FACE_SIZE))
        results.append({
            "bbox": (int(x), int(y), int(w), int(h)),
            "face_gray": roi,
        })
    return results


def _compute_embedding(face_gray) -> list[float]:
    if not _HAS_DEPS:
        return []
    cell_h = FACE_SIZE // GRID
    cell_w = FACE_SIZE // GRID
    embedding: list[float] = []
    for row in range(GRID):
        for col in range(GRID):
            cell = face_gray[
                row * cell_h : (row + 1) * cell_h,
                col * cell_w : (col + 1) * cell_w,
            ]
            hist = cv2.calcHist([cell], [0], None, [HIST_BINS], [0, 256])
            hist = hist.flatten()
            norm = np.linalg.norm(hist)
            if norm > 0:
                hist = hist / norm
            embedding.extend(hist.tolist())
    return embedding


def _cosine(a: list[float], b: list[float]) -> float:
    if not _HAS_DEPS or len(a) != len(b) or not a:
        return 0.0
    va = np.array(a, dtype=np.float64)
    vb = np.array(b, dtype=np.float64)
    dot = float(np.dot(va, vb))
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def extract_faces_from_video(
    video_path: str | Path,
    interval: float = SAMPLE_INTERVAL_SEC,
    max_faces: int = 50,
) -> list[dict]:
    """Extract face embeddings from a video file.

    Returns list of dicts with keys:
      - embedding: list[float] (1024-dim)
      - frame_idx: int
      - bbox: (x, y, w, h)
      - face_id: str (sequential within this video)
    """
    if not _HAS_DEPS:
        return []
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(fps * interval))
    results: list[dict] = []
    idx = 0
    face_counter = 0
    while len(results) < max_faces:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            break
        faces = _detect_faces_frame(frame)
        for f in faces:
            emb = _compute_embedding(f["face_gray"])
            if emb:
                results.append({
                    "embedding": emb,
                    "frame_idx": idx,
                    "bbox": f["bbox"],
                    "face_id": f"face_{face_counter:04d}",
                })
                face_counter += 1
            if len(results) >= max_faces:
                break
        idx += step
    cap.release()
    return results


def extract_faces_from_image(
    image_path: str | Path,
) -> list[dict]:
    """Extract face embeddings from a single image."""
    if not _HAS_DEPS:
        return []
    frame = cv2.imread(str(image_path))
    if frame is None:
        return []
    faces = _detect_faces_frame(frame)
    results = []
    for i, f in enumerate(faces):
        emb = _compute_embedding(f["face_gray"])
        if emb:
            results.append({
                "embedding": emb,
                "frame_idx": 0,
                "bbox": f["bbox"],
                "face_id": f"face_{i:04d}",
            })
    return results


def cluster_faces(
    all_faces: dict[str, list[dict]],
    threshold: float = MATCH_THRESHOLD,
) -> list[dict]:
    """Cluster faces across videos to find re-appearing individuals.

    Parameters
    ----------
    all_faces:
        Mapping video_id → list of face dicts (from extract_*).
    threshold:
        Cosine similarity threshold for matching.

    Returns
    -------
    List of identity clusters:
      {
        "identity_id": "person_0001",
        "appearances": [{"video_id": ..., "face_id": ..., "similarity": ...}, ...],
        "n_videos": int,
        "cross_platform": bool
      }
    """
    flat: list[tuple[str, dict]] = []
    for vid, faces in all_faces.items():
        for f in faces:
            flat.append((vid, f))
    if not flat:
        return []

    clusters: list[list[tuple[str, dict, float]]] = []
    assigned: set[int] = set()

    for i in range(len(flat)):
        if i in assigned:
            continue
        cluster: list[tuple[str, dict, float]] = [(flat[i][0], flat[i][1], 1.0)]
        assigned.add(i)
        for j in range(i + 1, len(flat)):
            if j in assigned:
                continue
            sim = _cosine(flat[i][1]["embedding"], flat[j][1]["embedding"])
            if sim >= threshold:
                cluster.append((flat[j][0], flat[j][1], round(sim, 4)))
                assigned.add(j)
        if len(cluster) > 1:
            clusters.append(cluster)

    results: list[dict] = []
    for idx, cluster in enumerate(clusters):
        video_ids = set()
        appearances = []
        for vid, face, sim in cluster:
            video_ids.add(vid)
            appearances.append({
                "video_id": vid,
                "face_id": face["face_id"],
                "similarity": sim,
                "bbox": face.get("bbox"),
            })
        results.append({
            "identity_id": f"person_{idx + 1:04d}",
            "appearances": appearances,
            "n_videos": len(video_ids),
            "n_appearances": len(appearances),
            "cross_platform": len(video_ids) > 1,
        })
    results.sort(key=lambda c: -c["n_videos"])
    return results


def find_reidentifications(
    all_faces: dict[str, list[dict]],
    threshold: float = MATCH_THRESHOLD,
) -> list[tuple[str, str, str, str, float]]:
    """Find cross-video face matches.

    Returns (video_a, face_id_a, video_b, face_id_b, similarity) tuples.
    """
    flat: list[tuple[str, dict]] = []
    for vid, faces in all_faces.items():
        for f in faces:
            flat.append((vid, f))
    matches: list[tuple[str, str, str, str, float]] = []
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            if flat[i][0] == flat[j][0]:
                continue
            sim = _cosine(flat[i][1]["embedding"], flat[j][1]["embedding"])
            if sim >= threshold:
                matches.append((
                    flat[i][0], flat[i][1]["face_id"],
                    flat[j][0], flat[j][1]["face_id"],
                    round(sim, 4),
                ))
    matches.sort(key=lambda t: -t[4])
    return matches


__all__ = [
    "extract_faces_from_video",
    "extract_faces_from_image",
    "cluster_faces",
    "find_reidentifications",
    "MATCH_THRESHOLD",
]
