"""Skeptic — Tier 3 adjudication (devil's advocate).

Runs AFTER the deterministic firewall has produced a score. Its sole job is to
*argue against* the verdict: surface exculpatory evidence, benign explanations
(education / journalism / satire), and weak links — to kill false positives
before a human's time is spent. If it finds a credible benign reading, it raises
a dissent that can escalate the case to a human rather than auto-acting.

This extends the spirit of the existing deterministic ``reasoning.referee``.
"""
from __future__ import annotations

import json

from aimw.agents.base import Agent, AgentContext, AgentReport
from aimw.agents.state import CaseState

_SYSTEM = """\
You are the Skeptic in a fraud investigation cell — the devil's advocate. The
system has produced a risk verdict. Your job is to argue the OTHER side: could
this be education, journalism, satire, debunking, or a false positive? Cite the
transcript. Be rigorous, not contrarian.
Return JSON:
{"benign_explanation": "the strongest innocent reading, or 'none credible'",
 "exculpatory": ["short quote/fact", ...],
 "dissent": true|false,
 "confidence_in_dissent": 0.0-1.0,
 "note": "one sentence"}"""


class SkepticAgent(Agent):
    name = "skeptic"
    role = "Skeptic"
    tier = 3
    uses_llm = True

    async def _run(self, state: CaseState, ctx: AgentContext) -> AgentReport:
        brief = ctx.case_brief or {}
        pkg = state.package
        mitig: list[str] = []
        if pkg:
            mitig = sorted({p.indicator_type for p in pkg.evidence if p.polarity == "mitigating"})

        benign = ""
        exculpatory: list[str] = []
        dissent = False
        dissent_conf = 0.0
        note = ""
        used_llm = False

        payload = {
            "case_brief": brief,
            "current_verdict": {"risk_level": state.risk_level, "score": state.final_score},
            "mitigating_indicators": mitig,
            "forensics_summary": (state.get("forensics").assessment if state.get("forensics") else ""),
            "transcript": state.transcript[:6000],
        }
        data = await ctx.llm.ask(_SYSTEM, json.dumps(payload, ensure_ascii=False), "SkepticReview", 600)
        if data:
            benign = str(data.get("benign_explanation", ""))[:300]
            exculpatory = [str(x)[:160] for x in (data.get("exculpatory") or [])][:6]
            dissent = bool(data.get("dissent", False))
            try:
                dissent_conf = max(0.0, min(1.0, float(data.get("confidence_in_dissent", 0.0))))
            except (TypeError, ValueError):
                dissent_conf = 0.0
            note = str(data.get("note", ""))[:240]
            used_llm = True

        if not note:
            # Deterministic fallback: dissent if mitigating evidence present and
            # the score is not extreme.
            has_mitig = bool(mitig)
            score = state.final_score or 0.0
            dissent = has_mitig and score < 0.80
            if not has_mitig and brief.get("mitigating_count"):
                dissent = bool(brief.get("score_hint", 0.0) or 0.0) < 0.80 and brief.get("mitigating_count", 0) > 0
            dissent_conf = 0.5 if dissent else 0.2
            benign = "Mitigating indicators present (e.g. educational/journalism framing)." if has_mitig else "none credible"
            exculpatory = [f"mitigating: {m}" for m in mitig[:4]]
            if brief.get("top_mitigating"):
                exculpatory.extend(f"brief: {m}" for m in brief["top_mitigating"][:2])
            note = "Dissent raised on mitigating evidence." if dissent else "No credible benign reading; verdict stands."

        return self.report(
            assessment=("DISSENT — " if dissent else "Concurs — ") + note,
            findings=exculpatory or ["No exculpatory evidence found."],
            confidence=dissent_conf if dissent else (1.0 - dissent_conf),
            signals={"dissent": dissent, "benign_explanation": benign,
                     "exculpatory": exculpatory, "confidence_in_dissent": dissent_conf,
                     "case_focus": brief.get("focus")},
            suggested_next="Escalate to human — verdict contested." if dissent else "Verdict may proceed.",
            used_llm=used_llm,
        )


__all__ = ["SkepticAgent"]
