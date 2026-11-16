import subprocess
import tempfile
import os
from faster_whisper import WhisperModel

model = None

def get_model():
    global model
    if model is None:
        try:
            model = WhisperModel("distil-large-v3", device="cuda", compute_type="float16")
        except Exception:
            model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    return model

def preload():
    get_model()

def extract_audio(video_path: str) -> str:
    audio_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return audio_path
    if os.path.getsize(audio_path) < 100:
        os.unlink(audio_path)
        audio_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        import wave
        with wave.open(audio_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"")
    return audio_path

def transcribe(video_path: str) -> dict:
    audio_path = extract_audio(video_path)
    try:
        if os.path.getsize(audio_path) < 1000:
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
    finally:
        if os.path.exists(audio_path):
            os.unlink(audio_path)
