import cv2
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

reader = None
_ocr_lock = Lock()

def get_reader():
    global reader
    if reader is None:
        import easyocr
        reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    return reader

def preload():
    get_reader()

def _resize_to_max_height(frame, max_height=480):
    h, w = frame.shape[:2]
    if h <= max_height:
        return frame
    scale = max_height / h
    new_w = int(w * scale)
    return cv2.resize(frame, (new_w, int(max_height)), interpolation=cv2.INTER_LINEAR)

def extract_frames(video_path: str, max_height=480, interval=2.0):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30
    frame_interval = int(fps * interval)
    frames = []
    frame_positions = []
    count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if count % frame_interval == 0:
            resized = _resize_to_max_height(frame, max_height)
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            frames.append(rgb)
            frame_positions.append(count / fps)
        count += 1
    cap.release()
    return frames, frame_positions


FRAME_SELECTION_VERSION = "visual-v2-content-diversity-3"


def select_informative_frames(frames, budget=3):
    """CPU heuristics only, at most three RGB frames; never OCR/model inference.

    Score text-like edges/components and contrast, not financial meaning. Reject
    near-blank frames using BOTH low detail and contrast (dark text slides survive).
    Deduplicate conservatively, prefer one useful frame per temporal third, then
    fill unused slots with the strongest remaining distinct candidates. Return
    indices into the original candidate list, with auditable quality decisions.
    """
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        raise ValueError("Frame budget must be a positive integer")
    budget = min(budget, 3)
    details, thumbs, hashes = [], [], []
    for index, frame in enumerate(frames):
        if frame.ndim != 3 or frame.shape[2] != 3 or not frame.size:
            raise ValueError("Expected nonempty RGB frames")
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        scale = min(1.0, 320 / gray.shape[1], 180 / gray.shape[0])
        small = cv2.resize(gray, (max(1, round(gray.shape[1]*scale)),
                                  max(1, round(gray.shape[0]*scale))), interpolation=cv2.INTER_AREA)
        edges = cv2.Canny(small, 40, 120)
        density = float(np.mean(edges > 0))
        contrast = float(small.std())
        # Edges are a readability proxy, not a claim that text was recognized.
        count, _, stats, _ = cv2.connectedComponentsWithStats(edges, 8)
        components = sum(2 <= w <= 60 and 3 <= h <= 35 and 3 <= area <= 600
                         for _, _, w, h, area in stats[1:count])
        blank = contrast < 5 and density < 0.002
        score = (0.55 * min(components / 35, 1.0)
                 + 0.30 * min(density / 0.15, 1.0)
                 + 0.15 * min(contrast / 64, 1.0))
        thumb = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA)
        dh = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
        thumbs.append(thumb.astype(np.int16))
        hashes.append(dh[:, 1:] > dh[:, :-1])
        details.append(dict(index=index, mean_gray=float(small.mean()),
                            contrast=contrast, edge_density=density,
                            text_like_components=int(components), score=float(score),
                            blank=bool(blank), duplicate_of=None))
    unique = []
    for index in sorted(range(len(frames)), key=lambda i: (-details[i]['score'], i)):
        if details[index]['blank']:
            continue
        duplicate = next((j for j in unique
                          if np.mean(np.abs(thumbs[index]-thumbs[j])) <= 1.0
                          and np.count_nonzero(hashes[index] != hashes[j]) <= 1), None)
        if duplicate is not None:
            details[index]['duplicate_of'] = duplicate
        else:
            unique.append(index)
    selected = []
    if frames:
        for band in np.array_split(np.arange(len(frames)), budget):
            eligible = [i for i in unique if i in band]
            if eligible:
                selected.append(max(eligible, key=lambda i: (details[i]['score'], -i)))
        for index in unique:
            if len(selected) >= budget:
                break
            if index not in selected:
                selected.append(index)
    selected.sort()
    return selected, dict(version=FRAME_SELECTION_VERSION, budget=budget,
                          candidate_count=len(frames), selected_indices=selected,
                          useful_distinct_count=len(unique), candidates=details)

def ocr_frames_batch(frames, positions):
    if not frames:
        return {"ocr_results": []}
    ocr_out = []
    with _ocr_lock:
        ocr = get_reader()
        for i, sec in enumerate(positions):
            results = ocr.readtext(frames[i])
            blocks = []
            for quad, text, confidence in results:
                if not text.strip():
                    continue
                xs, ys = zip(*quad)
                blocks.append({"text": text, "confidence": float(confidence),
                               "bbox": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]})
            ocr_out.append({"time": round(sec, 1), "texts": [b["text"] for b in blocks],
                            "blocks": blocks})
    return {"ocr_results": ocr_out}

def extract_audio_frames_parallel(video_path: str, max_height=480, interval=2.0):
    with ThreadPoolExecutor(max_workers=2) as ex:
        audio_future = ex.submit(_extract_audio_ffmpeg, video_path)
        frames_future = ex.submit(extract_frames, video_path, max_height, interval)
        audio_path = audio_future.result()
        frames, positions = frames_future.result()
    return audio_path, frames, positions

def _extract_audio_ffmpeg(video_path: str) -> str:
    import subprocess, tempfile, os
    audio_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        audio_path
    ]
    subprocess.run(cmd, capture_output=True)
    return audio_path

def process_video_optimized(video_path: str, max_height=480, interval=2.0):
    from audio_engine import get_model as get_whisper
    audio_path, frames, positions = extract_audio_frames_parallel(video_path, max_height, interval)
    with ThreadPoolExecutor(max_workers=2) as ex:
        transcribe_future = ex.submit(_transcribe_path, audio_path)
        ocr_future = ex.submit(ocr_frames_batch, frames, positions)
        transcript_data = transcribe_future.result()
        ocr_data = ocr_future.result()
    return {
        "frames": frames,
        "positions": positions,
        "transcript": transcript_data,
        "ocr": ocr_data,
    }

def _transcribe_path(audio_path: str) -> dict:
    import os
    from audio_engine import get_model
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
        return {"text": "", "language": "unknown", "duration": 0}
    whisper = get_model()
    segments, info = whisper.transcribe(
        audio_path,
        beam_size=1,
        best_of=1,
        vad_filter=True,
        vad_parameters={"threshold": 0.5, "min_speech_duration_ms": 500},
    )
    text = " ".join(seg.text for seg in segments)
    return {"text": text, "language": info.language, "duration": info.duration}
