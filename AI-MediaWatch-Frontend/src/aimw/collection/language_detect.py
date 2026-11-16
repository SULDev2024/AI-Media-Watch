"""Language hint heuristic for RU / KK / code-switched captions.

Returns one of ``ru``, ``kk``, ``mixed``, ``other``. Short strings (< 20 chars)
are ``other`` — too little signal to classify. Kazakh-specific Cyrillic letters
are the deterministic discriminator for ``kk``/``mixed`` (independent of the
statistical classifier, which is weak on KK); ``langid`` distinguishes Russian
from everything else.

This is a routing/UX hint only — never evidence.
"""

from __future__ import annotations

import langid

# Letters used in Kazakh Cyrillic but not in Russian.
_KK_CHARS = frozenset("әғқңөұүһі")
_MIN_CHARS = 20


def detect(text: str) -> str:
    """Return ``ru`` | ``kk`` | ``mixed`` | ``other`` for the given text."""
    stripped = text.strip()
    if len(stripped) < _MIN_CHARS:
        return "other"

    has_kazakh = any(ch in _KK_CHARS for ch in stripped.lower())
    lang, _confidence = langid.classify(stripped)

    if has_kazakh:
        # Kazakh letters amid otherwise-Russian text => code-switching.
        return "mixed" if lang == "ru" else "kk"
    if lang == "ru":
        return "ru"
    return "other"
