"""Adversary — Tier 3 adjudication (red team).

Thinks like the scammer. It (1) runs the naive keyword baseline against the
content AND against evaded variants to prove the case would slip past a
keyword filter, and (2) reasons about how this operator would evolve to evade
detection. Its purpose is to *stress-test robustness*: if a trivially-evaded
keyword filter would have missed this, that is evidence the intent-based verdict
is doing real work — and a warning about what to watch next.
"""
from __future__ import annotations

import json

from aimw.adversarial import baseline, evasion
from aimw.agents.base import Agent, AgentContext, AgentReport
from aimw.agents.state import CaseState

_SYSTEM = """\
You are the Adversary (red team) in a fraud investigation cell. Given a suspect
transcript, predict how THIS operator would most likely evolve to evade
automated detection next (new code words, platform hops, payment-rail changes).
Be specific and concrete.
Return JSON: {"evasion_moves": ["...", ...], "next_watch": "one sentence"}"""


class AdversaryAgent(Agent):
    name = "adversary"
    role = "Adversary"
    tier = 3
    uses_llm = True

    async def _run(self, state: CaseState, ctx: AgentContext) -> AgentReport:
        brief = ctx.case_brief or {}
        text = state.transcript or ""

        # ── Deterministic robustness proof: keyword filter vs evasion ────────
        original = baseline.classify(text)
        evaded = {tech: baseline.classify(mut) for tech, mut in evasion.mutate(text).items()}
        # How many evasion techniques defeat the keyword baseline?
        defeated = [t for t, r in evaded.items() if not r["flagged"] and original["flagged"]]
        robustness_note = (
            f"Keyword baseline flagged the original ({original['n_hits']} hits) but was "
            f"DEFEATED by {len(defeated)}/{len(evaded)} trivial evasions: {', '.join(defeated)}."
            if original["flagged"]
            else "Keyword baseline did not even flag the original — pure keyword filtering is blind here."
        )

        # ── LLM: predict the operator's next evasion moves ───────────────────
        moves: list[str] = []
        next_watch = ""
        used_llm = False
        data = await ctx.llm.ask(
            _SYSTEM,
            json.dumps({"case_brief": brief, "transcript": text[:5000]}, ensure_ascii=False),
            "AdversaryForecast",
            500,
        )
        if data:
            moves = [str(m)[:160] for m in (data.get("evasion_moves") or [])][:6]
            next_watch = str(data.get("next_watch", ""))[:240]
            used_llm = True
        if not moves:
            focus = str(brief.get("focus", "low"))
            moves = [
                "Swap Latin letters for Cyrillic homoglyphs in on-screen text.",
                "Move the call-to-action into the pinned comment / bio link.",
                "Rotate to a fresh Telegram handle and referral code.",
            ]
            if focus == "high":
                moves.append("Split the campaign across mirrored channels and fresh payment rails.")
            next_watch = "Watch for the same wallet/handle surfacing under new account names."

        return self.report(
            assessment=robustness_note,
            findings=[f"original: {original['n_hits']} kw hits, flagged={original['flagged']}"]
            + [f"evaded[{t}]: flagged={evaded[t]['flagged']}" for t in evaded]
            + [f"forecast: {m}" for m in moves],
            confidence=0.75,
            signals={
                "baseline_original": original,
                "baseline_evaded": evaded,
                "evasions_defeating_baseline": defeated,
                "forecast_moves": moves,
                "next_watch": next_watch,
                "case_focus": brief.get("focus"),
            },
            suggested_next="Keyword-only filtering is insufficient — intent layer is load-bearing.",
            used_llm=used_llm,
        )


__all__ = ["AdversaryAgent"]
