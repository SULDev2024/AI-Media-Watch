"""Evasion generator — the obfuscations scammers use to dodge keyword filters.

Each technique is a deterministic text transform that preserves human
readability while breaking literal substring matching:

* homoglyph  — swap Latin↔Cyrillic look-alikes (a→а, o→о, e→е, c→с, p→р)
* spacing    — insert thin spaces between characters ("p r o f i t")
* leetspeak  — o→0, i→1, e→3, a→@, s→$
* zero_width — insert U+200B zero-width spaces inside keywords

``mutate(text)`` returns a dict of {technique: mutated_text} so the demo can run
the keyword baseline against each and show it collapse.
"""
from __future__ import annotations

# Latin → Cyrillic homoglyph map (visually identical, different code points).
_HOMOGLYPH = str.maketrans({
    "a": "а", "o": "о", "e": "е", "c": "с", "p": "р", "y": "у", "x": "х",
    "A": "А", "O": "О", "E": "Е", "C": "С", "P": "Р", "X": "Х",
})

_LEET = str.maketrans({"o": "0", "i": "1", "e": "3", "a": "@", "s": "$"})

_ZW = "​"  # zero-width space


def _homoglyph(text: str) -> str:
    return text.translate(_HOMOGLYPH)


def _spacing(text: str) -> str:
    # Space out only alphabetic runs so it stays readable.
    return " ".join(text)


def _leet(text: str) -> str:
    return text.translate(_LEET)


def _zero_width(text: str) -> str:
    # Inject a zero-width space after each letter — invisible, breaks matching.
    return _ZW.join(text)


def mutate(text: str) -> dict[str, str]:
    """Return {technique: evaded_text} for every evasion technique."""
    return {
        "homoglyph": _homoglyph(text),
        "spacing": _spacing(text),
        "leetspeak": _leet(text),
        "zero_width": _zero_width(text),
    }


__all__ = ["mutate"]
