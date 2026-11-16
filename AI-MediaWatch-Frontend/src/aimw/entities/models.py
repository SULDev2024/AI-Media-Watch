"""Entity extraction output types.

``RawSpan`` is an untyped, pre-classification text span produced by Phase 7.
Phase 8's signal tagger reads ``RawSpan`` objects and promotes them to
``EvidencePiece`` rows with ``indicator_type``, ``polarity``, and ``strength``.
Nothing in Phase 7 classifies — it only extracts and annotates provenance.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aimw.core.schema.types import Source


class RawSpan(BaseModel):
    """One candidate entity extracted from speech, OCR, or VLM output.

    Certainty reflects extraction confidence before Phase 8 scoring:

    * ``1.0`` — clean regex match on raw text (highest confidence)
    * ``0.9`` — regex match on normalized text (homoglyph/ZW-stripping applied)
    * ``0.6`` — fuzzy watchlist recovery or VLM-assisted recovery
    * ``0.5`` — spaCy recall-net entity (supplementary; never originates STRONG)
    """

    model_config = ConfigDict(frozen=True)

    source: Source
    timestamp: float | None
    text: str = Field(description="Surrounding context window (~60 chars).")
    raw_value: str = Field(description="The extracted token (wallet, handle, etc.).")
    recovery_method: str = Field(
        description=("Provenance: 'raw' | 'normalized' | 'fuzzy' | 'spacy' | 'vlm_recovered'."),
    )
    certainty: float = Field(default=1.0, ge=0.0, le=1.0)
