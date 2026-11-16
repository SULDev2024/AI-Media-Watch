"""Entity extraction orchestrator (Phase 7).

Converts raw speech + OCR artifacts into:
  * :class:`~aimw.core.schema.evidence.ExtractedEntities` — structured, typed
    entities (wallets, handles, phones, etc.) ready for the canonical schema.
  * ``list[RawSpan]`` — untyped spans covering everything that *might* become
    an ``EvidencePiece`` after Phase 8 signal tagging.

The pipeline:
  1. Collect text from Transcript segments (source="speech") and OCR blocks
     (source="ocr"), preserving per-token timestamps.
  2. For each text span, run §12 normalization then apply all regex patterns
     on *both* the raw and the normalized form.  Spans that only match
     normalized text get ``recovery_method="normalized"`` and ``certainty=0.9``.
  3. Run rapidfuzz watchlist recovery on candidate tokens.
  4. Run spaCy recall net (returns ``certainty=0.5``, never originates STRONG).
  5. For frames with ≥1 OCR block, optionally call the VLM to recover text
     the primary OCR missed.  VLM outputs get ``recovery_method="vlm_recovered"``
     and ``certainty=0.6``.
  6. Tag payment phones (within 30 chars of a payment-rail keyword).
  7. Assemble ``ExtractedEntities`` from all confirmed entity values.

Nothing in this module assigns ``indicator_type``, ``polarity``, or
``strength`` — those belong to Phase 8.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from aimw.core.logging import get_logger
from aimw.core.schema.evidence import ExtractedEntities
from aimw.core.schema.types import Source
from aimw.entities import fuzzy as fuzz_mod
from aimw.entities import patterns as pat
from aimw.entities import spacy_ner
from aimw.entities.linkage import classify_linkage
from aimw.entities.models import RawSpan
from aimw.entities.normalize import is_normalized, normalize

if TYPE_CHECKING:
    from aimw.entities.vlm.qwen import QwenWrapper
    from aimw.extraction.ocr.models import OcrResult
    from aimw.extraction.whisper.models import Transcript

log = get_logger("aimw.entities.extractor")

# Keywords whose proximity to a phone number flags it as a payment rail.
_PAYMENT_KEYWORDS = frozenset({"kaspi", "halyk", "перевод", "qiwi", "каспи", "халык", "переводи"})
_PAYMENT_WINDOW = 30  # characters

# Certainty scores by provenance.
_CERTAINTY_RAW = 1.0
_CERTAINTY_NORMALIZED = 0.9


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract(
    transcript: Transcript | None,
    ocr: OcrResult | None,
    *,
    vlm: QwenWrapper | None = None,
    watchlist: dict[str, list[str]] | None = None,
) -> tuple[ExtractedEntities, list[RawSpan]]:
    """Extract entities from *transcript* and *ocr*, returning typed entities + raw spans.

    At least one of *transcript* or *ocr* must be non-None; passing both None
    raises ``ValueError``.

    *watchlist* is a ``{"handles": [...], "wallets": [...]}`` dict. If omitted,
    fuzzy recovery is skipped (pass ``fuzz_mod.load_watchlist(path)`` to enable).
    """
    if transcript is None and ocr is None:
        raise ValueError("At least one of transcript or ocr must be provided.")

    all_spans: list[RawSpan] = []
    entity_acc = _EntityAccumulator()

    # 1. Process speech transcript.
    if transcript is not None:
        for seg in transcript.segments:
            _process_text_block(
                seg.text,
                source="speech",
                timestamp=seg.start,
                spans_out=all_spans,
                entity_acc=entity_acc,
                watchlist=watchlist or {},
            )

    # 2. Process OCR frame blocks + optional VLM recovery.
    if ocr is not None:
        for frame in ocr.frames:
            # Primary OCR text.
            for block in frame.blocks:
                _process_text_block(
                    block.text,
                    source="ocr",
                    timestamp=frame.timestamp_s,
                    spans_out=all_spans,
                    entity_acc=entity_acc,
                    watchlist=watchlist or {},
                )

            # VLM recovery: frames with ≥1 OCR block get an additional VLM pass.
            if frame.blocks and vlm is not None and vlm.is_available():
                _vlm_recover(
                    vlm=vlm,
                    image_path=Path(frame.image_path),
                    timestamp=frame.timestamp_s,
                    spans_out=all_spans,
                    entity_acc=entity_acc,
                )

    # 3. spaCy recall net over concatenated speech text.
    if transcript is not None:
        full_speech = " ".join(seg.text for seg in transcript.segments)
        spacy_spans = spacy_ner.recall_net(full_speech, source="speech", timestamp=None)
        all_spans.extend(spacy_spans)

    # 4. Tag payment phones.
    phone_purposes = _tag_payment_phones(entity_acc.phones, transcript, ocr)

    # 4b. Promoter linkage of payment-type entities (revision, R1/R2).
    texts: list[str] = []
    if transcript is not None:
        texts.extend(seg.text for seg in transcript.segments)
    if ocr is not None:
        texts.extend(block.text for frame in ocr.frames for block in frame.blocks)
    wallets = _dedup(entity_acc.wallets)
    payment_linkage = classify_linkage(
        wallets=wallets,
        payment_values=(
            _dedup(entity_acc.referrals)
            + _dedup(entity_acc.links)
            + _dedup(entity_acc.handles)
            + [ph for ph, purpose in phone_purposes.items() if purpose == "payment"]
        ),
        texts=texts,
    )

    # 5. Build canonical ExtractedEntities.
    entities = ExtractedEntities(
        telegram_handles=_dedup(entity_acc.handles),
        telegram_links=_dedup(entity_acc.links),
        crypto_wallets=_dedup(entity_acc.wallets),
        phone_numbers=_dedup(entity_acc.phones),
        referral_codes=_dedup(entity_acc.referrals),
        profit_claims=_dedup(entity_acc.profits),
        phone_purposes=phone_purposes,
        payment_linkage=payment_linkage,
    )

    log.info(
        "entities_extracted",
        handles=len(entities.telegram_handles),
        wallets=len(entities.crypto_wallets),
        phones=len(entities.phone_numbers),
        profits=len(entities.profit_claims),
        raw_spans=len(all_spans),
    )
    return entities, all_spans


async def extract_async(
    transcript: Transcript | None,
    ocr: OcrResult | None,
    *,
    vlm: QwenWrapper | None = None,
    watchlist: dict[str, list[str]] | None = None,
) -> tuple[ExtractedEntities, list[RawSpan]]:
    """Async wrapper — offloads the CPU-bound extraction to a thread."""
    return await asyncio.to_thread(extract, transcript, ocr, vlm=vlm, watchlist=watchlist)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _EntityAccumulator:
    """Mutable collector for each entity category during extraction."""

    def __init__(self) -> None:
        self.wallets: list[str] = []
        self.phones: list[str] = []
        self.handles: list[str] = []
        self.links: list[str] = []
        self.profits: list[str] = []
        self.referrals: list[str] = []


def _process_text_block(
    text: str,
    *,
    source: Source,
    timestamp: float | None,
    spans_out: list[RawSpan],
    entity_acc: _EntityAccumulator,
    watchlist: dict[str, list[str]],
) -> None:
    """Run all extractors on *text* (raw then normalized); accumulate results."""
    normed = normalize(text)
    did_normalize = is_normalized(text, normed)

    # Run patterns on raw text first, then on normalized if it differs.
    for version, recovery, certainty in (
        (text, "raw", _CERTAINTY_RAW),
        (normed, "normalized", _CERTAINTY_NORMALIZED) if did_normalize else (None, None, None),
    ):
        if version is None:
            continue

        for value in pat.extract_wallets(version):
            entity_acc.wallets.append(value)
            spans_out.append(
                _span(source, timestamp, text, value, recovery, certainty)  # type: ignore[arg-type]
            )
        for value in pat.extract_phones(version):
            entity_acc.phones.append(value)
            spans_out.append(
                _span(source, timestamp, text, value, recovery, certainty)  # type: ignore[arg-type]
            )
        for value in pat.extract_handles(version):
            entity_acc.handles.append(value)
            spans_out.append(
                _span(source, timestamp, text, value, recovery, certainty)  # type: ignore[arg-type]
            )
        for value in pat.extract_links(version):
            entity_acc.links.append(value)
            spans_out.append(
                _span(source, timestamp, text, value, recovery, certainty)  # type: ignore[arg-type]
            )
        for value in pat.extract_profits(version):
            entity_acc.profits.append(value)
            spans_out.append(
                _span(source, timestamp, text, value, recovery, certainty)  # type: ignore[arg-type]
            )
        for value in pat.extract_referrals(version):
            entity_acc.referrals.append(value)
            spans_out.append(
                _span(source, timestamp, text, value, recovery, certainty)  # type: ignore[arg-type]
            )

    # Fuzzy watchlist recovery (on raw tokens only — fuzzy already degrades certainty).
    _fuzzy_recover(
        text,
        source=source,
        timestamp=timestamp,
        spans_out=spans_out,
        entity_acc=entity_acc,
        watchlist=watchlist,
    )


def _fuzzy_recover(
    text: str,
    *,
    source: Source,
    timestamp: float | None,
    spans_out: list[RawSpan],
    entity_acc: _EntityAccumulator,
    watchlist: dict[str, list[str]],
) -> None:
    """Try fuzzy watchlist recovery for each whitespace token in *text*."""
    if not watchlist:
        return
    tokens = text.split()
    handle_spans = fuzz_mod.recover_handles(
        tokens, watchlist, source=source, timestamp=timestamp, context=text
    )
    for span in handle_spans:
        entity_acc.handles.append(span.raw_value)
        spans_out.append(span)

    wallet_spans = fuzz_mod.recover_wallets(
        tokens, watchlist, source=source, timestamp=timestamp, context=text
    )
    for span in wallet_spans:
        entity_acc.wallets.append(span.raw_value)
        spans_out.append(span)


def _vlm_recover(
    *,
    vlm: QwenWrapper,
    image_path: Path,
    timestamp: float | None,
    spans_out: list[RawSpan],
    entity_acc: _EntityAccumulator,
) -> None:
    """Run VLM on *image_path* and extract entities from the recovered lines."""
    lines = vlm.recover_in_image_text(image_path)
    for line in lines:
        for value in pat.extract_wallets(line):
            entity_acc.wallets.append(value)
            spans_out.append(_span("vision", timestamp, line, value, "vlm_recovered", 0.6))
        for value in pat.extract_handles(line):
            entity_acc.handles.append(value)
            spans_out.append(_span("vision", timestamp, line, value, "vlm_recovered", 0.6))
        for value in pat.extract_phones(line):
            entity_acc.phones.append(value)
            spans_out.append(_span("vision", timestamp, line, value, "vlm_recovered", 0.6))


def _tag_payment_phones(
    phones: list[str],
    transcript: Transcript | None,
    ocr: OcrResult | None,
) -> dict[str, str]:
    """Return ``{phone: "payment"}`` for phones within 30 chars of a payment keyword.

    Checks all speech segments and OCR blocks for payment-rail proximity.
    """
    if not phones:
        return {}

    # Collect all searchable text with phone positions.
    all_text = ""
    if transcript is not None:
        all_text += " ".join(seg.text for seg in transcript.segments)
    if ocr is not None:
        all_text += " " + " ".join(block.text for frame in ocr.frames for block in frame.blocks)
    all_text_lower = all_text.lower()

    result: dict[str, str] = {}
    for phone in phones:
        idx = all_text_lower.find(phone)
        if idx == -1:
            continue
        window = all_text_lower[max(0, idx - _PAYMENT_WINDOW) : idx + len(phone) + _PAYMENT_WINDOW]
        if any(kw in window for kw in _PAYMENT_KEYWORDS):
            result[phone] = "payment"
    return result


def _span(
    source: Source,
    timestamp: float | None,
    text: str,
    raw_value: str,
    recovery_method: str,
    certainty: float,
) -> RawSpan:
    # Context window: 30 chars either side of the value within the text.
    idx = text.find(raw_value)
    ctx = text[max(0, idx - 30) : idx + len(raw_value) + 30] if idx >= 0 else text[:60]
    return RawSpan(
        source=source,
        timestamp=timestamp,
        text=ctx,
        raw_value=raw_value,
        recovery_method=recovery_method,
        certainty=certainty,
    )


def _dedup(values: list[str]) -> list[str]:
    """Deduplicate while preserving insertion order."""
    seen: set[str] = set()
    result: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result
