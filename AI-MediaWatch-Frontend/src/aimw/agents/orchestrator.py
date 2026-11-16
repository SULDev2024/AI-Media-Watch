"""The Handler orchestrates the 9-agent investigation cell.

The cell still has the same public shape, but it now behaves more like a real
investigation team:

* Scout and Triage run in parallel.
* A shared case brief is built once and handed to every specialist.
* Forensics, Correlator, and Legal run together when the case needs depth.
* Adversary and Skeptic challenge the verdict in parallel.

The deterministic firewall remains the only place where the final verdict is
written. Agents investigate; the firewall adjudicates.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from aimw.agents import firewall
from aimw.agents.adversary import AdversaryAgent
from aimw.agents.base import Agent, AgentContext
from aimw.agents.briefer import BrieferAgent
from aimw.agents.correlator import CorrelatorAgent
from aimw.agents.forensics import ForensicsAgent
from aimw.agents.legal import LegalAgent
from aimw.agents.llm import AgentLLM
from aimw.agents.scout import ScoutAgent
from aimw.agents.skeptic import SkepticAgent
from aimw.agents.state import CaseState
from aimw.agents.triage import TriageAgent

SCOUT = ScoutAgent()
TRIAGE = TriageAgent()
FORENSICS = ForensicsAgent()
CORRELATOR = CorrelatorAgent()
LEGAL = LegalAgent()
ADVERSARY = AdversaryAgent()
SKEPTIC = SkepticAgent()
BRIEFER = BrieferAgent()

ROSTER = [
    {
        "name": "handler",
        "role": "Handler",
        "tier": 0,
        "objective": "Command the cell, choose the depth of review, seal the chain of custody.",
        "inputs": ["video id", "evidence package", "agent dissent"],
        "outputs": ["dispatch plan", "final case state", "human escalation flag"],
        "authority": "Orchestration only; final verdict is written by the deterministic firewall.",
    },
    {
        "name": "scout",
        "role": "Scout",
        "tier": 1,
        "objective": "Find expansion leads: channels, aliases, query terms, and campaign pivots.",
        "inputs": ["entities", "URL", "platform", "transcript excerpt"],
        "outputs": ["search leads", "related-source hints", "collection next steps"],
        "authority": "Recommends where to search next; never changes the verdict.",
    },
    {
        "name": "triage",
        "role": "Triage",
        "tier": 1,
        "objective": "Decide whether the case needs deep review or can close at the gate.",
        "inputs": ["risk hint", "evidence counts", "payment rail", "mitigating signals"],
        "outputs": ["proceed/stop gate", "urgency", "initial confidence"],
        "authority": "Can recommend early closure; cannot override evidence.",
    },
    {
        "name": "forensics",
        "role": "Forensics",
        "tier": 2,
        "objective": (
            "Extract fraud mechanics from transcript, OCR, payment claims, and calls to action."
        ),
        "inputs": ["transcript", "OCR text", "entities", "indicator map"],
        "outputs": ["modus operandi", "payment mechanics", "visual/textual markers"],
        "authority": "Builds the factual technical read of the media.",
    },
    {
        "name": "correlator",
        "role": "Network Analyst",
        "tier": 2,
        "objective": (
            "Connect this case to shared wallets, handles, domains, channels, and campaigns."
        ),
        "inputs": ["entities", "case graph", "historical reports"],
        "outputs": ["campaign links", "shared infrastructure", "recurrence signals"],
        "authority": "Raises campaign context; does not invent links without shared entities.",
    },
    {
        "name": "legal",
        "role": "Legal",
        "tier": 2,
        "objective": "Map evidence to regulatory concerns and analyst-ready legal rationale.",
        "inputs": ["evidence pieces", "indicator types", "risk level"],
        "outputs": ["regulatory hooks", "review rationale", "compliance notes"],
        "authority": "Cites only mapped regulation references already present in evidence.",
    },
    {
        "name": "adversary",
        "role": "Adversary",
        "tier": 3,
        "objective": "Stress-test the detection by simulating evasion and operator counter-moves.",
        "inputs": ["transcript", "baseline keyword classifier", "case signals"],
        "outputs": ["evasion risks", "baseline weaknesses", "operator playbook"],
        "authority": "Challenges robustness; cannot downgrade confirmed evidence.",
    },
    {
        "name": "skeptic",
        "role": "Skeptic",
        "tier": 3,
        "objective": (
            "Look for false positives, educational context, satire, news, or missing proof."
        ),
        "inputs": ["all agent reports", "mitigating evidence", "confidence signals"],
        "outputs": ["dissent flag", "false-positive arguments", "human-review trigger"],
        "authority": "Can force escalation when evidence is ambiguous.",
    },
    {
        "name": "briefer",
        "role": "Briefer",
        "tier": 4,
        "objective": "Compress the investigation into an analyst-ready action brief.",
        "inputs": ["firewall verdict", "agent reports", "journal", "case file"],
        "outputs": ["executive brief", "recommended action", "handoff summary"],
        "authority": "Narrates the result; does not alter score or custody chain.",
    },
]


def _entity_counts(state: CaseState) -> dict[str, int]:
    pkg = state.package
    ents = pkg.entities if pkg else None
    if ents is None:
        return {}
    return {
        "telegram_handles": len(ents.telegram_handles),
        "telegram_links": len(ents.telegram_links),
        "crypto_wallets": len(ents.crypto_wallets),
        "phone_numbers": len(ents.phone_numbers),
        "websites": len(ents.websites),
        "referral_codes": len(ents.referral_codes),
        "profit_claims": len(ents.profit_claims),
        "payment_phones": len(ents.payment_phones),
    }


def _case_brief(state: CaseState) -> dict[str, Any]:
    pkg = state.package
    evidence = list(pkg.evidence) if pkg else []
    incriminating = [p for p in evidence if p.polarity == "incriminating"]
    mitigating = [p for p in evidence if p.polarity == "mitigating"]
    indicator_counts = Counter(p.indicator_type for p in evidence)
    source_counts = Counter(p.source for p in evidence)
    counts = _entity_counts(state)
    payment_rail = bool(
        pkg
        and (
            pkg.entities.crypto_wallets
            or pkg.entities.payment_phones
            or pkg.entities.telegram_links
        )
    )
    transcript = state.transcript or ""

    score_hint: float | None = None
    risk_hint: str | None = None
    confidence_hint: float | None = None
    deterministic_score_hint: float | None = None
    deterministic_risk_hint: str | None = None
    if pkg is not None:
        try:
            deterministic_score_hint = float(pkg.score)
            deterministic_risk_hint = str(pkg.risk_level)
        except Exception:
            deterministic_score_hint = None
            deterministic_risk_hint = None

    projection = state.projection or {}
    if projection.get("risk_level") is not None:
        risk_hint = str(projection["risk_level"])
        raw_score = projection.get("score")
        if raw_score is not None:
            try:
                score_hint = float(raw_score)
            except (TypeError, ValueError):
                score_hint = None
        raw_confidence = projection.get("confidence")
        if raw_confidence is not None:
            try:
                confidence_hint = float(raw_confidence)
            except (TypeError, ValueError):
                confidence_hint = None
    else:
        score_hint = deterministic_score_hint
        risk_hint = deterministic_risk_hint

    if incriminating:
        confidence_hint = round(min(1.0, 0.25 + 0.15 * len(incriminating)), 3)
    elif confidence_hint is not None:
        confidence_hint = round(min(1.0, max(0.0, confidence_hint)), 3)

    high_projection = risk_hint in {"HIGH", "CRITICAL"} or (
        score_hint is not None and score_hint >= 0.45
    )
    medium_projection = risk_hint == "MEDIUM" or (
        score_hint is not None and score_hint >= 0.2
    )

    return {
        "video_id": state.video_id,
        "report_id": state.report_id,
        "platform": state.platform,
        "url": state.url,
        "transcript_excerpt": transcript[:2400],
        "transcript_len": len(transcript),
        "evidence_count": len(evidence),
        "incriminating_count": len(incriminating),
        "mitigating_count": len(mitigating),
        "payment_rail": payment_rail,
        "entity_counts": counts,
        "indicator_counts": dict(indicator_counts.most_common(12)),
        "source_counts": dict(source_counts.most_common()),
        "score_hint": score_hint,
        "risk_hint": risk_hint,
        "deterministic_score_hint": deterministic_score_hint,
        "deterministic_risk_hint": deterministic_risk_hint,
        "confidence_hint": confidence_hint,
        "top_incriminating": [p.indicator_type for p in incriminating[:8]],
        "top_mitigating": [p.indicator_type for p in mitigating[:8]],
        "focus": (
            "high" if payment_rail or len(incriminating) >= 3 or high_projection
            else "medium" if incriminating or mitigating or medium_projection
            else "low"
        ),
    }


def _risk_rank(level: str | None) -> int:
    return {
        "CLEAN": 0,
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "CRITICAL": 4,
    }.get(str(level or "").upper(), -1)


def _activation_profile(case_brief: dict[str, Any]) -> dict[str, bool]:
    entity_counts = case_brief.get("entity_counts", {})
    network_signal = any(
        entity_counts.get(key, 0) > 0
        for key in (
            "telegram_handles",
            "telegram_links",
            "crypto_wallets",
            "websites",
            "referral_codes",
        )
    )
    hot = (
        case_brief.get("focus") == "high"
        or case_brief.get("risk_hint") in {"HIGH", "CRITICAL"}
        or bool(case_brief.get("payment_rail"))
        or case_brief.get("incriminating_count", 0) >= 3
    )
    ambiguous = (
        bool(case_brief.get("mitigating_count"))
        or case_brief.get("confidence_hint") is not None
    )
    return {
        "fast_path": not hot and not ambiguous,
        "network": network_signal or hot,
        "legal": bool(case_brief.get("indicator_counts")) or hot,
        "red_team": hot or ambiguous,
        "skeptic": hot or ambiguous,
        "deep_review": hot or case_brief.get("evidence_count", 0) >= 3,
    }


async def _run_one(agent: Agent, state: CaseState, ctx: AgentContext) -> None:
    report = await agent.run(state, ctx)
    state.add_report(report)


async def investigate(state: CaseState, ctx: AgentContext) -> CaseState:
    """Run the full cell over *state* and return it enriched with the verdict."""
    import datetime as dt

    case_brief = _case_brief(state)
    activation = _activation_profile(case_brief)
    ctx.case_brief = case_brief
    ctx.activation = activation

    state.log("handler", "open", f"investigation opened for {state.video_id}")
    state.log(
        "handler",
        "context",
        f"focus={case_brief['focus']} evidence={case_brief['evidence_count']} "
        f"incrim={case_brief['incriminating_count']} network={activation['network']}",
    )

    state.log("handler", "dispatch", "Tier 1 - Scout | Triage (parallel)")
    await asyncio.gather(
        _run_one(SCOUT, state, ctx),
        _run_one(TRIAGE, state, ctx),
    )

    triage = state.get("triage")
    if triage and not triage.signals.get("proceed", True):
        state.log("handler", "gate", "Triage closed the case as benign - sealing minimal record")
        firewall.adjudicate(state)
        state.verdict = state.risk_level or "CLEAN"
        state.finished_at = dt.datetime.now(dt.UTC).isoformat()
        state.log("handler", "close", "closed at triage gate")
        return state

    state.log("handler", "dispatch", "Tier 2 - Forensics | Correlator | Legal (parallel)")
    await asyncio.gather(
        _run_one(FORENSICS, state, ctx),
        _run_one(CORRELATOR, state, ctx),
        _run_one(LEGAL, state, ctx),
    )

    state.log("handler", "firewall", "Tier 2.5 - deterministic adjudication")
    firewall.adjudicate(state)
    state.iterations += 1
    if _risk_rank(str(case_brief.get("risk_hint"))) > _risk_rank(state.risk_level):
        state.escalated_to_human = True
        state.log(
            "handler",
            "projection_gap",
            f"stored={case_brief.get('risk_hint')} deterministic={state.risk_level}",
        )

    state.log(
        "handler",
        "dispatch",
        f"Tier 3 - Adversary | Skeptic (challenge, focus={case_brief['focus']})",
    )
    await asyncio.gather(
        _run_one(ADVERSARY, state, ctx),
        _run_one(SKEPTIC, state, ctx),
    )

    skeptic = state.get("skeptic")
    if skeptic and skeptic.signals.get("dissent"):
        state.escalated_to_human = True
        state.log("handler", "escalate", "Skeptic dissented - routing to human review")

    state.log("handler", "dispatch", "Tier 4 - Briefer")
    await _run_one(BRIEFER, state, ctx)

    state.verdict = state.risk_level
    state.finished_at = dt.datetime.now(dt.UTC).isoformat()
    state.log(
        "handler",
        "close",
        f"verdict={state.verdict} escalated={state.escalated_to_human} "
        f"agents={len(state.reports)}",
    )
    return state


def build_context(
    llm_client,
    sessionmaker=None,
    *,
    case_brief: dict[str, Any] | None = None,
    activation: dict[str, bool] | None = None,
) -> AgentContext:  # type: ignore[no-untyped-def]
    """Construct an AgentContext. ``llm_client`` may be None -> deterministic cell."""
    return AgentContext(
        llm=AgentLLM(llm_client),
        sessionmaker=sessionmaker,
        case_brief=case_brief,
        activation=activation,
    )


__all__ = ["ROSTER", "build_context", "investigate"]
