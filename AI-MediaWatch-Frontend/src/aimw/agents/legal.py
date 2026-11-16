"""Legal — Tier 2 regulatory agent.

Maps the evidence to specific Kazakhstan statutes. Critically, the *citation*
comes deterministically from ``config/regulations_kz.yaml`` (keyed by the
``regulation_ref`` already attached to each evidence piece) — the LLM never
invents an article number. The LLM only drafts the human-readable rationale for
WHY each cited statute applies. This is advisory: it informs the case file, it
never sets the score.
"""
from __future__ import annotations

import json

from aimw.agents.base import Agent, AgentContext, AgentReport
from aimw.agents.state import CaseState
from aimw.reasoning import regulations as reg_catalog

_SYSTEM = """\
You are the Legal analyst in a fraud investigation cell operating under the law
of the Republic of Kazakhstan. You are given the statutes that the deterministic
engine has already matched to the evidence (you may NOT cite any other statute or
invent article numbers). For each, write one sentence explaining why the observed
conduct plausibly engages it. Be measured — say "plausibly engages", not "is
guilty".
Return JSON: {"analysis": [{"statute_id": "...", "why": "one sentence"}], "overall": "one sentence"}"""


class LegalAgent(Agent):
    name = "legal"
    role = "Legal"
    tier = 2
    uses_llm = True

    async def _run(self, state: CaseState, ctx: AgentContext) -> AgentReport:
        pkg = state.package
        brief = ctx.case_brief or {}
        regs = reg_catalog.load()

        # Collect the deterministically-attached regulation refs (no invention).
        fired_refs: list[str] = []
        if pkg:
            for p in pkg.evidence:
                if p.regulation_ref and p.regulation_ref in regs and p.regulation_ref not in fired_refs:
                    fired_refs.append(p.regulation_ref)

        statutes = [
            {
                "id": ref,
                "short": regs[ref].get("short", ref),
                "title": regs[ref].get("title", ""),
            }
            for ref in fired_refs
        ]

        if not statutes:
            return self.report(
                assessment="No statute matched by the deterministic engine.",
                findings=["No regulation_ref attached to any evidence piece."],
                confidence=0.4,
                signals={"statutes": [], "analysis": []},
            )

        analysis: list[dict] = []
        overall = ""
        used_llm = False
        payload = {
            "case_brief": brief,
            "matched_statutes": [
                {"statute_id": s["id"], "short": s["short"], "title": s["title"],
                 "article": (regs[s["id"]].get("article") or "").strip()[:400]}
                for s in statutes
            ],
            "transcript_excerpt": state.transcript[:2500],
        }
        data = await ctx.llm.ask(_SYSTEM, json.dumps(payload, ensure_ascii=False), "LegalAnalysis", 600)
        if data:
            analysis = [
                {"statute_id": str(a.get("statute_id", "")), "why": str(a.get("why", ""))[:240]}
                for a in (data.get("analysis") or [])
            ]
            overall = str(data.get("overall", ""))[:240]
            used_llm = True

        if not overall:
            overall = (
                f"Conduct plausibly engages {len(statutes)} Kazakhstan statute(s)."
                if statutes
                else "No statute matched by the deterministic engine."
            )
            analysis = [{"statute_id": s["id"], "why": "Matched by deterministic indicator evidence."} for s in statutes]

        return self.report(
            assessment=overall,
            findings=[f"{s['short']} — {s['title']}" for s in statutes],
            confidence=0.7 if used_llm else 0.55,
            signals={"statutes": statutes, "analysis": analysis, "case_focus": brief.get("focus")},
            suggested_next="Cite these statutes in the sealed case file.",
            used_llm=used_llm,
        )


__all__ = ["LegalAgent"]
