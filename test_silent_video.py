"""Regression coverage for videos with no audio stream."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio_engine import transcribe


class SilentVideoTests(unittest.TestCase):
    def test_video_without_audio_skips_extraction_and_whisper(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "silent.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "color=c=blue:s=32x32:d=0.2", "-an", str(path),
            ], check=True, capture_output=True)
            with patch("audio_engine.extract_audio") as extract, patch("audio_engine.get_model") as model:
                self.assertEqual(transcribe(str(path)),
                                 {"text": "", "language": "unknown", "duration": 0})
                extract.assert_not_called()
                model.assert_not_called()

    def test_corrupt_media_still_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.mp4"
            path.write_bytes(b"not a video")
            with self.assertRaises(Exception):
                transcribe(str(path))


if __name__ == "__main__":
    unittest.main()
