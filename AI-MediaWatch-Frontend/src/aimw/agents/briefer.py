"""Briefer — Tier 4 output agent.

The last agent. It assembles everything the cell produced into a human-readable
investigation brief and records the prioritisation rationale. It does NOT seal
the case file (the firewall already did that, deterministically) — it writes the
narrative a human analyst reads on top of the sealed evidence.

LLM path: a tight investigator's brief. Fallback: a templated summary stitched
from each agent's assessment.
"""
from __future__ import annotations

import json

from aimw.agents.base import Agent, AgentContext, AgentReport
from aimw.agents.state import CaseState

_SYSTEM = """\
You are the Briefer in a fraud investigation cell. Write a concise investigator's
brief (4-6 sentences) for a human analyst, synthesising the agents' findings.
State the verdict, the campaign context if any, the statutes engaged, and any
dissent. Plain, factual, no hype.
Return JSON: {"brief": "the brief text", "headline": "one short line"}"""


class BrieferAgent(Agent):
    name = "briefer"
    role = "Briefer"
    tier = 4
    uses_llm = True

    async def _run(self, state: CaseState, ctx: AgentContext) -> AgentReport:
        brief_ctx = ctx.case_brief or {}
        # Gather every agent's assessment for synthesis.
        digest = {
            name: {"assessment": r.assessment, "confidence": r.confidence, "signals": r.signals}
            for name, r in state.reports.items()
        }
        verdict = {
            "risk_level": state.risk_level,
            "final_score": state.final_score,
            "confidence": state.confidence,
            "escalated_to_human": state.escalated_to_human,
            "chain_root": state.chain_root,
        }

        brief = ""
        headline = ""
        used_llm = False
        payload = {"verdict": verdict, "agent_findings": digest, "case_brief": brief_ctx}
        data = await ctx.llm.ask(_SYSTEM, json.dumps(payload, ensure_ascii=False, default=str), "InvestigatorBrief", 700)
        if data:
            brief = str(data.get("brief", ""))[:1200]
            headline = str(data.get("headline", ""))[:160]
            used_llm = True

        if not brief:
            corr = state.get("correlator")
            legal = state.get("legal")
            skeptic = state.get("skeptic")
            parts = [
                f"Verdict: {state.risk_level} (score {state.final_score}).",
            ]
            if corr and corr.signals.get("is_campaign"):
                parts.append(f"Part of {corr.signals.get('operation_name')}: {len(corr.signals.get('linked_videos', []))} linked videos.")
            if legal and legal.signals.get("statutes"):
                parts.append(f"Engages {len(legal.signals['statutes'])} statute(s).")
            if skeptic and skeptic.signals.get("dissent"):
                parts.append("Skeptic dissents — escalated to human review.")
            if brief_ctx.get("focus") == "high":
                parts.append("High-focus case — deep review path activated.")
            if state.chain_root:
                parts.append(f"Sealed under chain {state.chain_root[:16]}…")
            brief = " ".join(parts)
            headline = f"{state.risk_level} — { 'campaign' if (corr and corr.signals.get('is_campaign')) else 'single video' }"

        return self.report(
            assessment=headline or "Brief assembled.",
            findings=[brief],
            confidence=0.8,
            signals={"brief": brief, "headline": headline, "case_focus": brief_ctx.get("focus")},
            suggested_next="Deliver to human analyst queue.",
            used_llm=used_llm,
        )


__all__ = ["BrieferAgent"]
