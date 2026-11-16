"""Prosecutor + defense brief callers -- Phase 10.

Both functions build a compact JSON user message from the EvidencePackage,
send it through the GroqClient with the appropriate system prompt, and parse
the response into a typed ``BriefShape``.

The serialiser intentionally omits fields the model does not need (corroborated_by
is internal to scoring; collected_at timestamps add noise). Keeping the user
message short is the cheapest way to stay under the 200K/day token cap.

Phase 19B remediation: when an EvidencePackage carries many pieces (long-form
videos can fire 20-65 indicators), the JSON-mode response payload truncates
before all arguments are written. ``_select_pieces_for_brief`` caps the list at
``_MAX_EVIDENCE_PIECES`` keeping strong-first then chronological order, and the
brief callers raise the response budget to ``_BRIEF_MAX_TOKENS``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from aimw.confidence.models import BriefShape
from aimw.core.schema.evidence import EvidencePackage, EvidencePiece
from aimw.reasoning.client import GroqClient

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Phase 19B remediation knobs.
_MAX_EVIDENCE_PIECES = 30
_BRIEF_MAX_TOKENS = 4096

_STRENGTH_RANK = {"strong": 0, "medium": 1, "weak": 2}


def _read_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _select_pieces_for_brief(pieces: list[EvidencePiece]) -> list[EvidencePiece]:
    """Cap the evidence list passed to the LLM at ``_MAX_EVIDENCE_PIECES``.

    Ordering preserves analytical value: strong indicators first, then medium,
    then weak; ties broken by timestamp so the brief reads chronologically.
    The cap exists because the JSON-mode response would otherwise truncate on
    packages with 20+ pieces (the failure mode that produced the 4 erroring
    educational FPs in Phase 19B).
    """
    if len(pieces) <= _MAX_EVIDENCE_PIECES:
        return list(pieces)
    ordered = sorted(
        pieces,
        key=lambda p: (
            _STRENGTH_RANK.get(p.strength, 99),
            float(p.timestamp) if p.timestamp is not None else 0.0,
        ),
    )
    return ordered[:_MAX_EVIDENCE_PIECES]


def _serialize_package(pkg: EvidencePackage) -> dict[str, Any]:
    """Compact JSON view of *pkg* for the LLM brief callers.

    Includes only the fields the brief callers need: evidence pieces (without
    corroborated_by, which is scoring-internal), entities, and identifiers.
    """
    selected = _select_pieces_for_brief(list(pkg.evidence))
    return {
        "video_id": pkg.video_id,
        "platform": pkg.platform,
        "url": pkg.url,
        "evidence_total": len(pkg.evidence),
        "evidence_shown": len(selected),
        "evidence": [
            {
                "source": p.source,
                "polarity": p.polarity,
                "timestamp": p.timestamp,
                "indicator_type": p.indicator_type,
                "strength": p.strength,
                "raw_value": p.raw_value,
                "content": p.content,
                "regulation_ref": p.regulation_ref,
            }
            for p in selected
        ],
        "entities": {
            "telegram_handles": list(pkg.entities.telegram_handles),
            "telegram_links": list(pkg.entities.telegram_links),
            "crypto_wallets": list(pkg.entities.crypto_wallets),
            "phone_numbers": list(pkg.entities.phone_numbers),
            "websites": list(pkg.entities.websites),
            "referral_codes": list(pkg.entities.referral_codes),
            "profit_claims": list(pkg.entities.profit_claims),
        },
    }


def _safe_parse_brief(raw: dict) -> BriefShape:
    raw.setdefault("arguments", [])
    raw.setdefault("discount_requests", [])
    return BriefShape.model_validate(raw)


async def prosecutor(pkg: EvidencePackage, client: GroqClient) -> BriefShape:
    """Build the prosecutor brief for *pkg* using the Groq API."""
    import json

    user_message = json.dumps(_serialize_package(pkg), ensure_ascii=False)
    raw = await client.complete_json(
        system=_read_prompt("prosecutor_system.md"),
        user=user_message,
        schema_name="BriefShape",
        max_tokens=_BRIEF_MAX_TOKENS,
    )
    return _safe_parse_brief(raw)


async def defense(pkg: EvidencePackage, client: GroqClient) -> BriefShape:
    """Build the defense brief for *pkg* using the Groq API."""
    import json

    user_message = json.dumps(_serialize_package(pkg), ensure_ascii=False)
    raw = await client.complete_json(
        system=_read_prompt("defense_system.md"),
        user=user_message,
        schema_name="BriefShape",
        max_tokens=_BRIEF_MAX_TOKENS,
    )
    return _safe_parse_brief(raw)
