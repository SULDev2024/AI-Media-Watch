"""spaCy recall-net wrapper for supplementary NER (§12).

spaCy's ``ru_core_news_sm`` is used as a *recall net* only:
* Its outputs are always tagged ``recovery_method="spacy"`` and ``certainty=0.5``.
* It can never originate a STRONG verdict — Phase 8 enforces this.
* Install: ``python -m spacy download ru_core_news_sm`` (after ``uv sync --extra entities``).

If spaCy is not installed, or the model is not downloaded, this module returns
empty spans silently — spaCy is supplementary, not load-bearing.
"""

from __future__ import annotations

from typing import Any

from aimw.core.logging import get_logger
from aimw.core.schema.types import Source
from aimw.entities.models import RawSpan

log = get_logger("aimw.entities.spacy_ner")

# Entity label set that can become raw spans for Phase 8.
_RECALL_LABELS = frozenset({"ORG", "MONEY", "PERSON"})
_SPACY_CERTAINTY = 0.5

_nlp: Any | None = None
_nlp_tried: bool = False


def _get_nlp() -> Any | None:
    """Lazy-load ``ru_core_news_sm``; return None if unavailable."""
    global _nlp, _nlp_tried
    if _nlp_tried:
        return _nlp
    _nlp_tried = True
    try:
        import spacy

        _nlp = spacy.load("ru_core_news_sm")
        log.info("spacy_model_loaded", model="ru_core_news_sm")
    except ImportError:
        log.debug("spacy_not_installed")
    except OSError:
        log.warning(
            "spacy_model_missing",
            hint="Run: python -m spacy download ru_core_news_sm",
        )
    return _nlp


def reset_spacy() -> None:
    """Clear the cached model — used in tests that need isolation."""
    global _nlp, _nlp_tried
    _nlp = None
    _nlp_tried = False


def recall_net(
    text: str,
    *,
    source: Source,
    timestamp: float | None,
) -> list[RawSpan]:
    """Run spaCy NER over *text* and return spans for ORG/MONEY/PERSON entities.

    Returns an empty list if spaCy is unavailable or the text is empty.
    These spans must never be used to originate a STRONG verdict (Phase 8 rule).
    """
    if not text.strip():
        return []
    nlp = _get_nlp()
    if nlp is None:
        return []

    try:
        doc = nlp(text)
    except Exception as exc:
        log.error("spacy_inference_failed", error=str(exc))
        return []

    spans: list[RawSpan] = []
    for ent in doc.ents:
        if ent.label_ not in _RECALL_LABELS:
            continue
        # Context window: up to 30 chars before and after.
        start = max(0, ent.start_char - 30)
        end = min(len(text), ent.end_char + 30)
        spans.append(
            RawSpan(
                source=source,
                timestamp=timestamp,
                text=text[start:end],
                raw_value=ent.text,
                recovery_method="spacy",
                certainty=_SPACY_CERTAINTY,
            )
        )
    return spans
