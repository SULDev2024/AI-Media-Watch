"""Biometric analysis — face, voice, and logo identification.

Three capabilities for government-grade media intelligence:

1. **Face re-identification** — detect faces in video frames, compute
   embedding vectors, and match the same person across different
   videos/accounts/platforms.

2. **Speaker diarization & voice linking** — extract voice fingerprints
   from audio, identify speaker segments, and link the same voice
   across campaigns.

3. **Logo & brand detection** — detect government/bank logos being used
   fraudulently in scam content via ORB feature matching against a
   reference library.
"""
from __future__ import annotations

__all__ = ["face", "speaker", "logo"]
