"""Scout — Tier 1 acquisition agent.

Decides WHAT to hunt for: expands the seed terms of a flagged case into related
search queries a human collector would run next (sibling channels, code words,
платформа variants). It does not collect; it tasks collection.

LLM path: proposes high-signal query expansions from the case's entities and
transcript. Fallback: derives queries deterministically from extracted entities
and a built-in fraud-lexicon.
"""
from __future__ import annotations

import json

from aimw.agents.base import Agent, AgentContext, AgentReport
from aimw.agents.state import CaseState

_SYSTEM = """\
You are the Scout in a financial-fraud investigation cell. Given one suspect
video's entities and a transcript excerpt, propose up to 6 NEW search queries an
investigator should run to find related videos from the SAME operation across
TikTok, Instagram, YouTube, and Telegram. Favour: reused handles, code words,
brand names, and recruiter phrasing. Avoid generic terms.
Return JSON: {"queries": ["...", ...], "rationale": "one sentence"}"""

# Deterministic fallback lexicon (RU/KZ/EN fraud-recruitment vocabulary).
_SEED_TERMS = [
    "пассивный доход", "инвестиции крипто", "гарантированный доход",
    "схема заработка", "реферальная программа", "crypto signals vip",
    "заработок телеграм",
]


class ScoutAgent(Agent):
    name = "scout"
    role = "Scout"
    tier = 1
    uses_llm = True

    async def _run(self, state: CaseState, ctx: AgentContext) -> AgentReport:
        pkg = state.package
        entities = pkg.entities if pkg else None
        brief = ctx.case_brief or {}
        handles = list(entities.telegram_handles) if entities else []
        websites = list(entities.websites) if entities else []
        refs = list(entities.referral_codes) if entities else []
        incrim = list(brief.get("top_incriminating", []))
        focus = str(brief.get("focus", "low"))

        queries: list[str] = []
        rationale = ""
        used_llm = False

        payload = {
            "case_brief": brief,
            "entities": {
                "telegram_handles": handles,
                "websites": websites,
                "referral_codes": refs,
            },
            "transcript_excerpt": state.transcript[:1500],
        }
        data = await ctx.llm.ask(_SYSTEM, json.dumps(payload, ensure_ascii=False), "ScoutQueries", 500)
        if data and isinstance(data.get("queries"), list):
            queries = [str(q).strip() for q in data["queries"] if str(q).strip()][:6]
            rationale = str(data.get("rationale", ""))[:200]
            used_llm = True

        if not queries:
            # Deterministic fallback: handles + referral codes + seed lexicon.
            queries = [f"telegram {h}" for h in handles[:2]]
            queries += [f"referral {r}" for r in refs[:1]]
            queries += [f"indicator {i}" for i in incrim[:2]]
            if focus == "high":
                queries += ["join telegram", "guaranteed returns"]
            queries += _SEED_TERMS[: max(0, 6 - len(queries))]
            rationale = "Derived from the shared case brief, extracted entities, and the fraud lexicon."

        return self.report(
            assessment=f"Proposed {len(queries)} follow-up search queries.",
            findings=[f"Hunt: {q}" for q in queries],
            confidence=0.65 if used_llm else (0.5 if queries else 0.4),
            signals={"queries": queries, "rationale": rationale},
            suggested_next="Hand queries to the collector for the next crawl tick.",
            used_llm=used_llm,
        )


__all__ = ["ScoutAgent"]
