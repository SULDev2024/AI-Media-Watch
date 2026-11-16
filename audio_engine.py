
import subprocess
import tempfile
import os
import wave
import av
from faster_whisper import WhisperModel

# Global Whisper model
model = None


def get_model():
    """
    Load Whisper optimized for CPU processing.
    """
    global model

    if model is None:
        print("Loading Whisper model on CPU...")

        model = WhisperModel(
            "small",
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            num_workers=1
        )

        print("Whisper model loaded successfully!")

    return model


def preload():
    """
    Preload Whisper model.
    """
    get_model()


def extract_audio(video_path: str) -> str:
    """
    Extract audio from video using FFmpeg.
    """

    audio_path = tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False
    ).name

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        audio_path
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg audio extraction failed: {result.stderr[-1000:]}"
            )

        if os.path.getsize(audio_path) < 100:
            os.unlink(audio_path)

            audio_path = tempfile.NamedTemporaryFile(
                suffix=".wav",
                delete=False
            ).name

            with wave.open(audio_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"")

        return audio_path

    except Exception:
        if os.path.exists(audio_path):
            os.unlink(audio_path)
        raise


def transcribe(video_path: str) -> dict:
    """
    Convert video speech into text using Whisper.
    """

    # A valid silent video can contain no audio stream at all. Inspect the
    # container first so extraction errors on damaged media still propagate.
    with av.open(video_path) as container:
        if not container.streams.audio:
            return {"text": "", "language": "unknown", "duration": 0}

    audio_path = extract_audio(video_path)

    try:
        if os.path.getsize(audio_path) < 1000:
            return {
                "text": "",
                "language": "unknown",
                "duration": 0
            }

        whisper = get_model()

        segments, info = whisper.transcribe(
            audio_path,
            beam_size=1,
            best_of=1,
            vad_filter=True,
            vad_parameters={
                "threshold": 0.5,
                "min_speech_duration_ms": 500
            }
        )

        text = " ".join(
            seg.text for seg in segments
        )

        return {
            "text": text,
            "language": info.language,
            "duration": info.duration
        }

    finally:
        if os.path.exists(audio_path):
            os.unlink(audio_path)
