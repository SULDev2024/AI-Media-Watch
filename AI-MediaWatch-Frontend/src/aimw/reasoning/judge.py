"""LLM Fraud-Intent Judge — Phase 20 architecture inversion.

Why this exists
---------------
Phase 19B proved that the deterministic keyword/regex engine cannot distinguish
*promoting* a fraudulent scheme from *discussing/teaching/reporting* one: it fired
65 indicators on an anti-MLM exposé and flagged TED-Ed, a law firm, and two
educators as scams, while missing 73 % of real scams whose phrasing it had not
been tuned on.

The fix is to put the layers in the right order:

* The **LLM judges intent** from the full transcript — the one thing the
  deterministic engine fundamentally cannot do.
* The **deterministic engine supplies auditable evidence** (signals + entities +
  regulation refs) as *features the judge reads*, not as the decision — the one
  thing an LLM cannot give a compliance buyer.

This module is the judge. It is read-only over the EvidencePackage (contract
``reasoning-no-direct-writes``); it never mutates evidence or touches the DB.

The deterministic ``EvidencePackage`` is preserved unchanged so every verdict
keeps a regulation-mapped, inspectable audit trail underneath the LLM call.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from aimw.core.schema.evidence import EvidencePackage, FrozenModel
from aimw.core.schema.types import RiskLevel
from aimw.reasoning.client import GroqClient

Intent = Literal["promotion", "education", "news", "gray", "clean"]

_MAX_TRANSCRIPT_CHARS = 16000

_JUDGE_SYSTEM = """\
You are a financial-fraud content classifier inside a regulated compliance system.

YOUR TASK
Decide whether a video is PROMOTING or RECRUITING the viewer INTO a fraudulent or
high-risk financial scheme, versus DISCUSSING, EXPLAINING, TEACHING, REPORTING,
CRITICIZING, or WARNING ABOUT such schemes.

THE CRITICAL PRINCIPLE — READ CAREFULLY
The presence of fraud-related vocabulary is NOT evidence of fraud. Words like
"pyramid scheme", "MLM", "recruit", "downline", "guaranteed returns", "passive
income", "crypto bot", "referral", "Ponzi" appear constantly in EDUCATIONAL
videos, JOURNALISM, DOCUMENTARIES, LAW-FIRM EXPLAINERS, and CONSUMER-PROTECTION
content. A video that uses these words 50 times to WARN people is the OPPOSITE of
fraud. You must classify on the SPEAKER'S INTENT and STANCE toward the scheme,
read from the transcript — never on keyword presence.

DECISION RULES
- PROMOTION: the video actively solicits the viewer to join, invest in, deposit
  into, pay for, sign up for, click a link/bot/channel for, or recruit others
  into a scheme — OR presents the scheme favorably as an opportunity FOR THE
  VIEWER. This is the only class that is fraud.
- EDUCATION: explains, teaches, analyzes, debunks, satirizes, or warns about
  schemes. NOT fraud, even with heavy fraud vocabulary or a provocative title
  like "How To Start A Pyramid Scheme".
- NEWS: journalistic reporting or documentary coverage. NOT fraud.
- GRAY: hype-driven, speculative, affiliate-marketing, or aggressive financial
  marketing where fraudulent intent cannot be confidently established.
- CLEAN: not about financial schemes at all.

EVIDENCE YOU ARE GIVEN
1. The TRANSCRIPT — your primary signal. Read it for who is being addressed and
   what they are being asked to do.
2. DETERMINISTIC EVIDENCE extracted by a separate deterministic system: the
   indicator signals that fired and the entities found (wallets, Telegram
   handles, referral codes, profit claims, phone numbers). Treat these as
   SUPPORTING FEATURES, not as the verdict. Note especially: a Telegram handle,
   crypto wallet, or referral funnel that the speaker tells the viewer to USE is
   strong evidence of PROMOTION; the same entities merely cited in an
   investigation are not.

OUTPUT — return ONLY this JSON object:
{
  "intent": "promotion" | "education" | "news" | "gray" | "clean",
  "is_fraud_promotion": true | false,
  "risk_score": 0-100,
  "risk_level": "HIGH" | "MEDIUM" | "LOW" | "CLEAN",
  "confidence": 0.0-1.0,
  "rationale": "1-3 sentences citing the transcript for WHY this intent",
  "key_evidence": ["short quote or entity fact", "..."]
}

RISK SCORE — a 0-100 number for HOW dangerous this specific content is to a
viewer. Judge it on its own merits; do NOT snap to round numbers. Vary it:
two different scams should rarely get the same score. Guidance:
- 85-100: aggressive direct solicitation, money/wallet/contact handed over.
- 60-84: clear promotion, fewer or softer solicitation cues.
- 30-59: gray-area hype, affiliate marketing, ambiguous intent.
- 10-29: mostly benign with a minor risk cue.
- 0-9: education, news, debunking, satire, or unrelated content.

RISK LEVEL must agree with the score band: HIGH=score>=60, MEDIUM=40-59,
LOW=15-39, CLEAN=score<15.
is_fraud_promotion must be true only for intent="promotion".
"""


class FraudVerdict(FrozenModel):
    """The judge's auditable intent decision for one video.

    Sits ON TOP of the deterministic EvidencePackage: the package remains the
    regulation-mapped audit trail; this is the intent layer a moderator acts on.
    """

    intent: Intent
    is_fraud_promotion: bool
    risk_score: int = 0  # 0-100 severity for this specific content
    risk_level: RiskLevel
    confidence: float
    rationale: str
    key_evidence: list[str]

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "FraudVerdict":
        if isinstance(obj, dict) and "risk_score" in obj:
            obj = dict(obj)
            obj["risk_score"] = int(round(float(obj["risk_score"])))
        return super().model_validate(obj, **kwargs)


def _evidence_features(package: EvidencePackage) -> dict[str, object]:
    """Compact, deterministic feature view of the package for the judge.

    Counts of fired indicators (not the 80-char log snippets) plus entity
    tallies. The judge reads these as features; the full transcript carries the
    intent signal.
    """
    sig_counts: dict[str, int] = {}
    for piece in package.evidence:
        sig_counts[piece.indicator_type] = sig_counts.get(piece.indicator_type, 0) + 1
    e = package.entities
    return {
        "signals_fired": sig_counts,
        "entities": {
            "telegram_handles": list(e.telegram_handles),
            "telegram_links": list(e.telegram_links),
            "crypto_wallets": list(e.crypto_wallets),
            "phone_numbers": list(e.phone_numbers),
            "referral_codes": list(e.referral_codes),
            "profit_claims": list(e.profit_claims),
        },
    }


async def classify(
    package: EvidencePackage,
    transcript_text: str,
    client: GroqClient,
    *,
    title: str = "",
    channel: str = "",
    max_transcript_chars: int = _MAX_TRANSCRIPT_CHARS,
) -> FraudVerdict:
    """Classify fraud intent from the full transcript + deterministic evidence.

    Parameters
    ----------
    package:
        The deterministic EvidencePackage (read-only — supplies features only).
    transcript_text:
        The full speech transcript. Truncated to ``max_transcript_chars`` for
        token control; production chunking is future work.
    client:
        Budgeted Groq client.
    title, channel:
        Optional provenance shown to the judge.
    """
    transcript = transcript_text.strip()
    truncated = len(transcript) > max_transcript_chars
    if truncated:
        # keep the opening (where solicitation/CTAs usually are) plus the tail
        head = transcript[: int(max_transcript_chars * 0.7)]
        tail = transcript[-int(max_transcript_chars * 0.3) :]
        transcript = f"{head}\n...[transcript truncated]...\n{tail}"

    clean_channel = channel if channel and channel != "manual" else ""
    user_payload = {
        "title": title or "",
        "channel": clean_channel,
        "deterministic_evidence": _evidence_features(package),
        "transcript": transcript,
        "transcript_truncated": truncated,
    }
    raw = await client.complete_json(
        system=_JUDGE_SYSTEM,
        user=json.dumps(user_payload, ensure_ascii=False),
        schema_name="FraudVerdict",
        max_tokens=1024,
    )
    return FraudVerdict.model_validate(raw)


__all__ = ["FraudVerdict", "Intent", "classify"]
