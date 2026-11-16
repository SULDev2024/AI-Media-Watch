"""Signal tagger — Phase 8 bridge between extraction and scoring.

Converts raw extraction artifacts (Transcript, OcrResult, ExtractedEntities,
list[RawSpan]) into a list[EvidencePiece] ready for the scoring engine.

Design invariants
-----------------
* One EvidencePiece per (indicator_type, source, segment/frame) — keywords
  appearing multiple times in the same segment do not double-count.
* Entity-driven signals (``requires`` in signals.yaml) fire at most once per
  package; source is set to ``"entity"``.
* §6.4 evidence-gating is applied in engine.score(), not here — the tagger
  produces everything it can detect; the engine decides what counts.
* VLM cap (§0.2 issue #12): after all pieces are assembled, any
  ``source="vision"`` piece is downgraded to at most ``"medium"`` unless the
  same indicator_type is also corroborated by ``"speech"`` or ``"ocr"``.
* Corroborated_by is populated when the same indicator fires from two distinct
  sources within a ±10 s window.
* The normalize() call from Phase 7 is applied to text before keyword/regex
  matching so homoglyph obfuscation doesn't escape detection.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from aimw.core.schema.evidence import EvidencePiece, ExtractedEntities
from aimw.core.schema.types import EvidenceStrength, Polarity, Source
from aimw.entities.models import RawSpan
from aimw.entities.normalize import deobfuscate, normalize, strip_injections
from aimw.extraction.ocr.models import OcrResult
from aimw.extraction.whisper.models import Transcript
from aimw.observability.metrics import (
    emit_entity_extraction_counts,
    emit_ocr_confidence_stats,
    emit_signal_distribution,
)

_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"

# Regex for verifiable licence identifiers (reused in discount validation).
LICENSE_RE: re.Pattern[str] = re.compile(
    r"(АФН|AFN|CFP|АРРФР|лицензия|лицензир)\s*[№#]?\s*[\w\-]{4,}",
    re.UNICODE,
)


@dataclass(frozen=True)
class _SignalSpec:
    """Parsed entry from signals.yaml."""

    id: str
    polarity: Polarity
    default_strength: EvidenceStrength
    keywords: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...]
    requires: tuple[str, ...]  # e.g. "entities.crypto_wallets"
    regulation_ref: str | None


@lru_cache(maxsize=1)
def _load_specs() -> tuple[_SignalSpec, ...]:
    path = _CONFIG_DIR / "signals.yaml"
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    specs = []
    for entry in data["indicators"]:
        kws = tuple(str(k).lower() for k in entry.get("match", {}).get("keywords", []))
        pats = tuple(
            re.compile(r, re.IGNORECASE | re.UNICODE)
            for r in entry.get("match", {}).get("regex", [])
        )
        specs.append(
            _SignalSpec(
                id=entry["id"],
                polarity=entry["polarity"],
                default_strength=entry["default_strength"],
                keywords=kws,
                patterns=pats,
                requires=tuple(entry.get("requires", [])),
                regulation_ref=entry.get("regulation_ref"),
            )
        )
    return tuple(specs)


def _text_matches(spec: _SignalSpec, text: str) -> bool:
    """True if *text* (or its normalized form) matches any keyword or regex."""
    variants = (text, normalize(text), strip_injections(text), deobfuscate(text))
    lowered = [v.lower() for v in variants]
    for kw in spec.keywords:
        if any(kw in v for v in lowered):
            return True
    return any(pat.search(v) for pat in spec.patterns for v in variants)


def _resolve_entity_field(field_path: str, entities: ExtractedEntities) -> list[str]:
    """Return the entity list for a path like 'entities.crypto_wallets'."""
    attr = field_path.split(".", 1)[-1]
    val = getattr(entities, attr, None)
    if isinstance(val, list):
        return val
    return []


def _best_certainty_for(raw_value: str, raw_spans: list[RawSpan]) -> float:
    """Return the highest certainty among spans whose raw_value matches."""
    matches = [s.certainty for s in raw_spans if s.raw_value == raw_value]
    return max(matches, default=1.0)


def _strength_from_certainty(
    default: EvidenceStrength,
    certainty: float,
) -> EvidenceStrength:
    """Downgrade default strength when entity was recovered (certainty < 1.0)."""
    if certainty < 1.0 and default == "strong":
        return "medium"
    # medium stays medium; weak stays weak
    return default


def _downgrade(strength: EvidenceStrength) -> EvidenceStrength:
    """Return the next-weaker strength (strong→medium→weak→weak)."""
    return "medium" if strength == "strong" else "weak"


def _build_piece(
    *,
    indicator_type: str,
    polarity: Polarity,
    strength: EvidenceStrength,
    source: Source,
    timestamp: float | None,
    raw_value: str,
    content: str,
    regulation_ref: str | None,
    recovery_method: str | None,
) -> EvidencePiece:
    return EvidencePiece(
        source=source,
        polarity=polarity,
        timestamp=timestamp,
        content=content,
        raw_value=raw_value,
        indicator_type=indicator_type,
        strength=strength,
        recovery_method=recovery_method,
        regulation_ref=regulation_ref,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def tag(
    raw_spans: list[RawSpan],
    entities: ExtractedEntities,
    ocr: OcrResult | None = None,
    transcript: Transcript | None = None,
) -> list[EvidencePiece]:
    """Convert extraction artifacts into a list of EvidencePiece.

    Parameters
    ----------
    raw_spans:
        Phase 7 output — carries per-entity certainty and recovery_method.
    entities:
        Structured entity lists (wallets, phones, handles, referral codes …).
    ocr:
        PaddleOCR result; each frame's blocks are scanned for keyword/regex.
    transcript:
        Whisper transcript; each segment is scanned for keyword/regex.

    Returns
    -------
    list[EvidencePiece]
        Unordered; ordering is not meaningful.  The engine applies §6 rules.
    """
    specs = _load_specs()
    pieces: list[EvidencePiece] = []

    # ── 1. Text matching against speech segments ────────────────────────────
    if transcript is not None:
        for seg in transcript.segments:
            fired: set[str] = set()
            for spec in specs:
                if spec.requires:
                    continue  # entity-only signal, skip text scan
                if spec.id in fired:
                    continue
                if _text_matches(spec, seg.text):
                    fired.add(spec.id)
                    pieces.append(
                        _build_piece(
                            indicator_type=spec.id,
                            polarity=spec.polarity,
                            strength=spec.default_strength,
                            source="speech",
                            timestamp=seg.start,
                            raw_value=_first_match_snippet(spec, seg.text),
                            content=(
                                f"{spec.id} detected in speech: "
                                f"'{seg.text[:80]}' (t={seg.start:.1f}s)"
                            ),
                            regulation_ref=spec.regulation_ref,
                            recovery_method="raw",
                        )
                    )

    # ── 2. Text matching against OCR blocks ─────────────────────────────────
    if ocr is not None:
        for frame in ocr.frames:
            for block in frame.blocks:
                fired_frame: set[str] = set()
                for spec in specs:
                    if spec.requires:
                        continue
                    if spec.id in fired_frame:
                        continue
                    if _text_matches(spec, block.text):
                        fired_frame.add(spec.id)
                        pieces.append(
                            _build_piece(
                                indicator_type=spec.id,
                                polarity=spec.polarity,
                                strength=spec.default_strength,
                                source="ocr",
                                timestamp=frame.timestamp_s,
                                raw_value=_first_match_snippet(spec, block.text),
                                content=(
                                    f"{spec.id} detected in OCR: "
                                    f"'{block.text[:80]}' "
                                    f"(frame t={frame.timestamp_s:.1f}s)"
                                ),
                                regulation_ref=spec.regulation_ref,
                                recovery_method="raw",
                            )
                        )

    # ── 3. Entity-driven signals ─────────────────────────────────────────────
    # Each signal with requires fires at most once per package.
    for spec in specs:
        if not spec.requires:
            continue
        # OR logic: any one satisfied field fires the signal.
        # Revision (R1/R2): entities reproduced in a warning/report context
        # ("reported") never fire an incriminating payment signal; promoter-
        # linked values are preferred over "unlinked" ones.
        matched_value: str | None = None
        for req in spec.requires:
            values = entities.not_reported(_resolve_entity_field(req, entities))
            if values:
                promoted = entities.promoter_linked(values)
                matched_value = (promoted or values)[0]
                break

        if matched_value is None:
            continue

        # Determine strength based on recovery certainty.
        certainty = _best_certainty_for(matched_value, raw_spans)
        strength = _strength_from_certainty(spec.default_strength, certainty)
        if entities.linkage_of(matched_value) == "unlinked":
            # No call-to-action ties the rail to the promoter: one level weaker.
            strength = _downgrade(strength)
        recovery = "raw" if certainty >= 1.0 else "normalized" if certainty >= 0.9 else "fuzzy"

        pieces.append(
            _build_piece(
                indicator_type=spec.id,
                polarity=spec.polarity,
                strength=strength,
                source="entity",
                timestamp=None,
                raw_value=matched_value,
                content=f"{spec.id}: '{matched_value}' disclosed (entity extraction)",
                regulation_ref=spec.regulation_ref,
                recovery_method=recovery,
            )
        )

    # ── 4. VLM cap — §0.2 issue #12 ─────────────────────────────────────────
    pieces = _apply_vlm_cap(pieces)

    # ── 5. Corroboration within ±10 s ────────────────────────────────────────
    pieces = _apply_corroboration(pieces)

    # ── 6. Observability ─────────────────────────────────────────────────────
    _counts: dict[str, int] = {}
    for _p in pieces:
        _counts[_p.indicator_type] = _counts.get(_p.indicator_type, 0) + 1
    emit_signal_distribution(_counts, total=len(pieces))

    if ocr is not None:
        _confs = [b.confidence for fr in ocr.frames for b in fr.blocks]
        emit_ocr_confidence_stats(_confs)

    emit_entity_extraction_counts(
        n_wallets=len(entities.crypto_wallets),
        n_phones=len(entities.phone_numbers),
        n_handles=len(entities.telegram_handles),
        n_links=len(entities.telegram_links),
        n_referral_codes=len(entities.referral_codes),
    )

    return pieces


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_match_snippet(spec: _SignalSpec, text: str) -> str:
    """Return the first matching keyword or regex snippet (truncated)."""
    low = text.lower()
    for kw in spec.keywords:
        idx = low.find(kw)
        if idx >= 0:
            return text[idx : idx + len(kw) + 20].strip()
    normed = normalize(text)
    decoded = deobfuscate(text)
    for variant in (normed, strip_injections(text), decoded):
        low_v = variant.lower()
        for kw in spec.keywords:
            idx = low_v.find(kw)
            if idx >= 0:
                return variant[idx : idx + len(kw) + 20].strip()
    for pat in spec.patterns:
        m = pat.search(text) or pat.search(normed) or pat.search(decoded)
        if m:
            return m.group(0)[:40]
    return text[:40]


def _apply_vlm_cap(pieces: list[EvidencePiece]) -> list[EvidencePiece]:
    """Downgrade vision-only STRONG pieces to MEDIUM (§0.2 issue #12)."""
    by_type: dict[str, set[str]] = defaultdict(set)
    for p in pieces:
        by_type[p.indicator_type].add(p.source)

    result: list[EvidencePiece] = []
    for p in pieces:
        if (
            p.source == "vision"
            and p.strength == "strong"
            and "speech" not in by_type[p.indicator_type]
            and "ocr" not in by_type[p.indicator_type]
        ):
            p = p.model_copy(update={"strength": "medium"})
        result.append(p)
    return result


def _apply_corroboration(pieces: list[EvidencePiece]) -> list[EvidencePiece]:
    """Populate corroborated_by when same indicator fires from multiple
    sources within ±10 s."""
    by_type: dict[str, list[EvidencePiece]] = defaultdict(list)
    for p in pieces:
        by_type[p.indicator_type].append(p)

    result: list[EvidencePiece] = []
    for p in pieces:
        group = by_type[p.indicator_type]
        other_sources: set[str] = set()
        for q in group:
            if q.source == p.source:
                continue
            ts_p = p.timestamp
            ts_q = q.timestamp
            if ts_p is None or ts_q is None or abs(ts_p - ts_q) <= 10.0:
                other_sources.add(q.source)
        if other_sources:
            corroborated_by = sorted(other_sources)
            p = p.model_copy(update={"corroborated_by": corroborated_by})
        result.append(p)
    return result
