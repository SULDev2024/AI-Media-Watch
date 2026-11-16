"""Forensics — Tier 2 evidence interpreter.

Reads the deterministic extraction output (transcript, OCR, entities) and
interprets it: what is actually being claimed, who is being addressed, and what
the viewer is asked to do. It surfaces the *solicitation cues* that distinguish
promotion from education — the judgement the keyword engine cannot make.

LLM path: structured intent/solicitation read of the transcript. Fallback:
deterministic summary of fired indicators and extracted payment rails.
"""
from __future__ import annotations

import json

from aimw.agents.base import Agent, AgentContext, AgentReport
from aimw.agents.state import CaseState

_SYSTEM = """\
You are the Forensics analyst in a fraud investigation cell. Read the transcript
and the list of extracted entities. Identify concrete SOLICITATION cues — moments
where the viewer is told to join, invest, deposit, pay, click a link/bot, or
recruit others. Distinguish these from neutral mentions.
Return JSON:
{"solicitation_cues": ["short quote", ...],
 "addressed_to_viewer": true|false,
 "call_to_action": "what the viewer is asked to do, or 'none'",
 "summary": "1-2 sentences"}"""


class ForensicsAgent(Agent):
    name = "forensics"
    role = "Forensics"
    tier = 2
    uses_llm = True

    async def _run(self, state: CaseState, ctx: AgentContext) -> AgentReport:
        pkg = state.package
        brief = ctx.case_brief or {}
        ents = pkg.entities if pkg else None
        entity_view = {}
        fired: list[str] = []
        if pkg:
            fired = sorted({p.indicator_type for p in pkg.evidence if p.polarity == "incriminating"})
        if ents:
            entity_view = {
                "telegram_handles": list(ents.telegram_handles),
                "telegram_links": list(ents.telegram_links),
                "crypto_wallets": list(ents.crypto_wallets),
                "referral_codes": list(ents.referral_codes),
                "profit_claims": list(ents.profit_claims),
            }

        cues: list[str] = []
        cta = "none"
        addressed = False
        summary = ""
        used_llm = False

        payload = {
            "case_brief": brief,
            "entities": entity_view,
            "fired_indicators": fired,
            "transcript": state.transcript[:6000],
        }
        data = await ctx.llm.ask(_SYSTEM, json.dumps(payload, ensure_ascii=False), "ForensicsRead", 700)
        if data:
            cues = [str(c)[:160] for c in (data.get("solicitation_cues") or [])][:8]
            cta = str(data.get("call_to_action", "none"))[:160]
            addressed = bool(data.get("addressed_to_viewer", False))
            summary = str(data.get("summary", ""))[:300]
            used_llm = True

        if not summary:
            n_pay = len((ents.crypto_wallets if ents else [])) + len((ents.telegram_links if ents else []))
            evidence_count = int(brief.get("evidence_count", len(fired)))
            summary = f"{len(fired)} incriminating indicator types; {n_pay} payment/contact rails extracted; {evidence_count} total evidence pieces."
            cues = [f"indicator: {f}" for f in fired[:6]]
            if brief.get("top_incriminating"):
                cues.extend(f"brief: {x}" for x in brief["top_incriminating"][:2])
            addressed = n_pay > 0
            cta = "contact/payment rail present" if n_pay > 0 else "none"

        conf = 0.7 if used_llm else 0.45
        return self.report(
            assessment=summary,
            findings=cues or ["No explicit solicitation cues found."],
            confidence=conf,
            signals={
                "solicitation_cues": cues,
                "call_to_action": cta,
                "addressed_to_viewer": addressed,
                "case_focus": brief.get("focus"),
            },
            suggested_next="Pass enriched read to Correlator and Legal.",
            used_llm=used_llm,
        )


__all__ = ["ForensicsAgent"]
