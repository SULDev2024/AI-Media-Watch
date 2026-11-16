"""Decoder regression tests using generated PCM, not additional video files."""
import io
import unittest
import wave

import numpy as np
from faster_whisper.audio import decode_audio


class AudioCompatibilityTests(unittest.TestCase):
    def test_whisper_decoder_accepts_pcm_and_preserves_samples(self):
        samples = np.array([0, 8192, -8192, 16384, -16384] * 3200, dtype=np.int16)
        stream = io.BytesIO()
        with wave.open(stream, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(samples.tobytes())
        stream.seek(0)
        decoded = decode_audio(stream, sampling_rate=16000)
        self.assertEqual(decoded.dtype, np.float32)
        np.testing.assert_array_equal(decoded, samples.astype(np.float32) / 32768.0)


if __name__ == "__main__":
    unittest.main()
