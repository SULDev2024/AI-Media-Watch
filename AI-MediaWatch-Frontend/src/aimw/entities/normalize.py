"""Text normalization for obfuscation recovery.

Implements the §12 normalization pipeline:
1. Translate Cyrillic homoglyphs (lower- and upper-case) to their Latin lookalikes.
2. Remove zero-width (ZW) injections that split tokens.
   A space is collapsed only when a ZW character sits on exactly one side of it
   (the ``bc1​ q9х`` wallet trick). When ZW characters sit on *both* sides of a
   space, the text was ZW-injected between every character and that space is a
   genuine word boundary, so it is kept.
3. Strip any remaining stand-alone ZW characters.
4. Re-join letter-spaced text ("p r o f i t") — runs of three or more
   single-character tokens separated by single spaces. When such a run appears
   alongside multi-space word gaps, shorter spaced words ("t o") are joined too.

The result is compared against patterns *after* normalization so that tricks
like ``bc1​q9х…`` (Cyrillic х, ZW-injected space) still match the
wallet regex while ordinary whitespace between words is left intact.

:func:`deobfuscate` additionally decodes leetspeak. It is meant for keyword and
signal matching only — never for entity extraction, because digits are
legitimate inside wallet addresses and phone numbers.
"""

from __future__ import annotations

import regex

# Cyrillic → Latin lookalike mapping (§12 of AI_MediaWatch_v4.md).
HOMOGLYPHS: dict[str, str] = {
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "х": "x",
    "у": "y",
    "к": "k",
    "в": "b",
    "т": "t",
    "н": "h",
    "м": "m",
    # Upper-case lookalikes (wallets and handles are often mixed-case).
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "Х": "X",
    "У": "Y",
}

_TRANS_TABLE = str.maketrans(HOMOGLYPHS)

# U+200B zero-width space, U+200C zero-width non-joiner, U+2060 word joiner.
_ZW_CHARS = "​‌⁠"

# A real space wrapped in ZW characters on both sides: keep one plain space.
_ZW_WRAPPED_SPACE = regex.compile(rf"[{_ZW_CHARS}]+\s+[{_ZW_CHARS}]+", regex.UNICODE)

# Collapse sequences between word characters that contain AT LEAST ONE ZW char.
# Plain ASCII/Unicode spaces without ZW chars are left alone.
_INTRA_WORD_SPLIT = regex.compile(
    rf"(?<=\w)[\s{_ZW_CHARS}]*[{_ZW_CHARS}][\s{_ZW_CHARS}]*(?=\w)",
    regex.UNICODE,
)

# Stand-alone ZW chars (not between word chars) — strip entirely.
_ZERO_WIDTH = regex.compile(rf"[{_ZW_CHARS}]")

# Letter-spacing: 3+ single non-space characters separated by single spaces.
_SPACED_RUN = regex.compile(r"(?<!\S)\S(?: \S){2,}(?!\S)")
# A whole chunk of 2+ spaced single characters (used once letter-spacing is detected).
_SPACED_CHUNK = regex.compile(r"\S(?: \S)+")
_MULTI_SPACE = regex.compile(r" {2,}")

# Leetspeak decoding, applied only inside tokens that also contain a letter.
_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)
_LEET_TOKEN = regex.compile(r"[\w@$]+")
_HAS_LETTER = regex.compile(r"\p{L}")


def _despace(text: str) -> str:
    if not _SPACED_RUN.search(text):
        return text
    if _MULTI_SPACE.search(text):
        # Letter-spaced text: single spaces are intra-word, runs of spaces are
        # the original word boundaries, so short words ("t o") are joined too.
        chunks = _MULTI_SPACE.split(text)
        return " ".join(
            c.replace(" ", "") if _SPACED_CHUNK.fullmatch(c) else c for c in chunks
        )
    return str(_SPACED_RUN.sub(lambda m: m.group(0).replace(" ", ""), text))


def strip_injections(text: str) -> str:
    """Remove ZW and letter-spacing injections but keep the original script.

    Cyrillic keywords must be matched against Cyrillic text, so signal matching
    uses this alongside :func:`normalize` (which also maps homoglyphs to Latin).
    """
    t = str(_ZW_WRAPPED_SPACE.sub(" ", text))
    t = str(_INTRA_WORD_SPLIT.sub("", t))
    t = str(_ZERO_WIDTH.sub("", t))
    return _despace(t)


def normalize(text: str) -> str:
    """Return text with Cyrillic homoglyphs mapped and ZW/spacing injections removed.

    This is the §12 normalization step that precedes regex matching. The
    original text is never mutated; a new string is returned.
    """
    return strip_injections(str(text.translate(_TRANS_TABLE)))


def _deleet_token(match: regex.Match[str]) -> str:
    tok = match.group(0)
    if not _HAS_LETTER.search(tok):
        return tok  # pure numbers ("100", "24") are left alone
    head = tok[0] if tok[0] == "@" else ""  # keep a leading @handle marker
    return head + tok[len(head):].translate(_LEET)


def deobfuscate(text: str) -> str:
    """:func:`normalize` plus leetspeak decoding — for keyword/signal matching only."""
    return str(_LEET_TOKEN.sub(_deleet_token, normalize(text)))


def is_normalized(original: str, normalised: str) -> bool:
    """Return True if ``normalised`` differs from ``original`` (i.e. was altered)."""
    return original != normalised
