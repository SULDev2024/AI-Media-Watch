"""Cross-platform content fingerprinting for campaign linking.

Detects that videos from DIFFERENT accounts are produced by the SAME operator
by measuring text and entity similarity — no video files or audio processing
required.  Scam campaigns reuse identical scripted pitches and entity values
across throwaway accounts; these similarities persist in the extracted data.

Two link types:
  entity_match  — videos share ≥50 % of their entity value set (wallets,
                  handles, referral codes).  High confidence — these are
                  almost certainly the same operation.
  content_match — videos share high MinHash Jaccard on transcript + OCR text.
                  Catches same scripted pitch, different entity values (new
                  "burn" accounts).

Algorithm: MinHash with N_HASHES=32 hash functions over (bigram, trigram)
token sets.  Jaccard estimation error ≈ 1/√N ≈ 17 % which is acceptable
for the threshold used (>= 0.60).

Pure Python stdlib — no external dependencies.
"""
from __future__ import annotations

import hashlib
import re
from typing import Sequence

CONTENT_THRESHOLD: float = 0.60   # MinHash Jaccard for content_match
ENTITY_THRESHOLD: float = 0.50    # Jaccard for entity_match
N_HASHES: int = 32


# ---------------------------------------------------------------------------
# Text tokenisation
# ---------------------------------------------------------------------------

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def _tokens(text: str) -> set[str]:
    """Extract bigram+trigram tokens from normalised text."""
    text = _NON_WORD.sub(" ", text.lower())
    words = text.split()
    out: set[str] = set()
    for i in range(len(words) - 1):
        if len(words[i]) >= 2 and len(words[i + 1]) >= 2:
            out.add(f"{words[i]}\x00{words[i + 1]}")
    for i in range(len(words) - 2):
        if len(words[i]) >= 2:
            out.add(f"{words[i]}\x00{words[i + 1]}\x00{words[i + 2]}")
    return out


def _minhash(tokens: set[str]) -> list[int]:
    """32-bucket MinHash signature."""
    if not tokens:
        return [2**32] * N_HASHES
    sigs: list[int] = []
    for seed in range(N_HASHES):
        min_h = 2**32
        seed_bytes = seed.to_bytes(4, "little")
        for tok in tokens:
            h = int.from_bytes(
                hashlib.blake2b(tok.encode(), digest_size=4, key=seed_bytes).digest(),
                "little",
            )
            if h < min_h:
                min_h = h
        sigs.append(min_h)
    return sigs


def _jaccard_minhash(s1: list[int], s2: list[int]) -> float:
    matches = sum(1 for a, b in zip(s1, s2) if a == b)
    return matches / N_HASHES


# ---------------------------------------------------------------------------
# Per-video fingerprint
# ---------------------------------------------------------------------------


def compute(
    transcript: str,
    ocr_text: str,
    entities: dict[str, Sequence[str]],
) -> dict:
    """Compute a multi-signal fingerprint for one video.

    Parameters
    ----------
    transcript:
        Full transcript text (may be empty string if ASR did not run).
    ocr_text:
        Concatenated OCR text from all frames (may be empty).
    entities:
        Extracted entity dict with keys crypto_wallets, telegram_handles,
        phone_numbers, referral_codes, websites, etc.

    Returns
    -------
    dict with keys:
        minhash     list[int]   — text similarity signature
        entity_set  list[str]   — sorted canonical entity values
    """
    text = f"{transcript} {ocr_text}".strip()
    toks = _tokens(text)
    minhash = _minhash(toks)

    entity_vals: list[str] = []
    for field in ("crypto_wallets", "telegram_handles", "phone_numbers",
                  "referral_codes", "websites"):
        for v in (entities.get(field) or []):
            entity_vals.append(str(v).lower().strip())
    entity_set = sorted(set(entity_vals))

    return {"minhash": minhash, "entity_set": entity_set}


# ---------------------------------------------------------------------------
# Pair-wise matching
# ---------------------------------------------------------------------------


def find_matches(
    fingerprints: dict[str, dict],
) -> list[tuple[str, str, float, str]]:
    """Find similar video pairs across the fingerprint index.

    Parameters
    ----------
    fingerprints:
        Mapping video_id → fingerprint dict (from ``compute``).

    Returns
    -------
    List of (video_id_a, video_id_b, similarity, link_type) tuples.
    link_type is "entity_match" or "content_match".
    Sorted by similarity descending.
    """
    video_ids = sorted(fingerprints)  # sorted for determinism
    matches: list[tuple[str, str, float, str]] = []

    for i in range(len(video_ids)):
        for j in range(i + 1, len(video_ids)):
            va, vb = video_ids[i], video_ids[j]
            fpa, fpb = fingerprints[va], fingerprints[vb]

            ea = set(fpa.get("entity_set") or [])
            eb = set(fpb.get("entity_set") or [])

            if ea and eb:
                union = ea | eb
                overlap = len(ea & eb) / len(union) if union else 0.0
                if overlap >= ENTITY_THRESHOLD:
                    matches.append((va, vb, round(overlap, 3), "entity_match"))
                    continue

            sa = fpa.get("minhash") or []
            sb = fpb.get("minhash") or []
            if sa and sb and len(sa) == len(sb):
                sim = _jaccard_minhash(sa, sb)
                if sim >= CONTENT_THRESHOLD:
                    matches.append((va, vb, round(sim, 3), "content_match"))

    matches.sort(key=lambda t: -t[2])
    return matches


__all__ = ["compute", "find_matches", "CONTENT_THRESHOLD", "ENTITY_THRESHOLD"]
