"""Triage — Tier 1 gatekeeper.

The cheap first pass. Decides whether a case is worth the expensive deep
analysis, so the cell doesn't burn compute on benign content. Outputs a
suspicion level (drop / review / hot) and a routing recommendation.

LLM path: a fast single-shot intent skim. Fallback: counts incriminating
indicators and live payment rails from the deterministic package.
"""
from __future__ import annotations

import json

from aimw.agents.base import Agent, AgentContext, AgentReport
from aimw.agents.state import CaseState

_SYSTEM = """\
You are the Triage officer in a fraud investigation cell. From a short transcript
excerpt and a count of fired risk indicators, decide how suspicious this video is.
Be cheap and fast. Return JSON:
{"suspicion": "drop"|"review"|"hot", "confidence": 0.0-1.0, "reason": "one sentence"}
- drop: clearly benign / unrelated to financial schemes.
- review: ambiguous, deserves the full pipeline.
- hot: strong signs of active solicitation/recruitment."""


class TriageAgent(Agent):
    name = "triage"
    role = "Triage"
    tier = 1
    uses_llm = True

    async def _run(self, state: CaseState, ctx: AgentContext) -> AgentReport:
        pkg = state.package
        brief = ctx.case_brief or {}
        incrim = 0
        has_payment = False
        if pkg:
            incrim = sum(1 for p in pkg.evidence if p.polarity == "incriminating")
            e = pkg.entities
            has_payment = bool(e.crypto_wallets or e.payment_phones or e.telegram_links)
        if not incrim:
            incrim = int(brief.get("incriminating_count", 0))
            has_payment = has_payment or bool(brief.get("payment_rail"))

        suspicion = ""
        reason = ""
        conf = 0.5
        used_llm = False

        payload = {
            "case_brief": brief,
            "incriminating_indicators": incrim,
            "has_payment_rail": has_payment,
            "transcript_excerpt": state.transcript[:1200],
        }
        data = await ctx.llm.ask(
            _SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            "TriageDecision",
            300,
        )
        if data and data.get("suspicion") in ("drop", "review", "hot"):
            suspicion = data["suspicion"]
            reason = str(data.get("reason", ""))[:200]
            try:
                conf = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
            except (TypeError, ValueError):
                conf = 0.5
            used_llm = True

        if not suspicion:
            # Deterministic fallback from indicator counts + payment rails.
            risk_hint = str(brief.get("risk_hint") or "").upper()
            score_hint = brief.get("score_hint")
            try:
                score_value = float(score_hint) if score_hint is not None else None
            except (TypeError, ValueError):
                score_value = None
            if risk_hint in {"HIGH", "CRITICAL"} or (
                score_value is not None and score_value >= 0.45
            ):
                suspicion = "hot"
                reason = f"stored projection is {risk_hint or score_value}."
                conf = 0.7
            elif risk_hint == "MEDIUM" or (score_value is not None and score_value >= 0.2):
                suspicion, reason, conf = "review", "stored projection needs review.", 0.6
            elif incrim == 0:
                suspicion, reason, conf = "drop", "No incriminating indicators fired.", 0.55
            elif has_payment or incrim >= 3:
                reason = (
                    f"{incrim} indicators + payment rail."
                    if has_payment
                    else f"{incrim} indicators fired."
                )
                suspicion, conf = "hot", 0.6
            else:
                suspicion, reason, conf = "review", f"{incrim} indicator(s) — ambiguous.", 0.5
        elif suspicion == "hot" and has_payment:
            reason = reason or "payment rail plus suspicious recruitment signals."

        proceed = suspicion != "drop"
        return self.report(
            assessment=f"Suspicion: {suspicion.upper()} — {reason}",
            findings=[f"{incrim} incriminating indicators", f"payment rail: {has_payment}"],
            confidence=conf,
            signals={"suspicion": suspicion, "proceed": proceed, "reason": reason},
            suggested_next="Open full investigation." if proceed else "Close — benign.",
            used_llm=used_llm,
        )


__all__ = ["TriageAgent"]
