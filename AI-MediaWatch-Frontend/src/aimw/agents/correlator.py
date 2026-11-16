"""Correlator — Tier 2 network analyst.

Answers the question single-video analysis cannot: *are these accounts the same
operation?* It reads the corpus-wide campaign graph and the cross-platform
fingerprint links built in ``aimw.graph`` / ``aimw.fingerprint`` and reports the
campaign this video belongs to, its co-conspirator videos, and the shared
entities (wallets, handles, referral codes) that tie them together.

This agent is deterministic at its core — it reads the graph the firewall trusts
— and only uses the LLM to *name* and *narrate* the campaign, never to invent
membership.
"""
from __future__ import annotations

import json

from aimw.agents.base import Agent, AgentContext, AgentReport
from aimw.agents.state import CaseState

_SYSTEM = """\
You are the Network Analyst in a fraud investigation cell. Given a set of videos
that provably share entities (wallets, handles, referral codes) or near-identical
scripted content, write a SHORT operation name and a one-sentence description of
the coordinated campaign. Do not invent facts beyond the shared entities given.
Return JSON: {"operation_name": "...", "description": "one sentence"}"""


class CorrelatorAgent(Agent):
    name = "correlator"
    role = "Network Analyst"
    tier = 2
    uses_llm = True

    async def _run(self, state: CaseState, ctx: AgentContext) -> AgentReport:
        brief = ctx.case_brief or {}
        pkg = state.package

        if ctx.sessionmaker is None:
            shared_entities: list[str] = []
            if pkg is not None:
                ents = pkg.entities
                shared_entities.extend(f"handle:{h}" for h in ents.telegram_handles[:4])
                shared_entities.extend(f"wallet:{w}" for w in ents.crypto_wallets[:4])
                shared_entities.extend(f"link:{l}" for l in ents.telegram_links[:4])
                shared_entities.extend(f"site:{w}" for w in ents.websites[:4])
                shared_entities.extend(f"ref:{r}" for r in ents.referral_codes[:4])
            is_campaign = len(shared_entities) >= 2 or bool(brief.get("payment_rail"))
            op_name = f"Local cluster {state.report_id[:8].upper()}"
            assessment = (
                f"Local campaign cluster detected — {len(shared_entities)} shared entity hint(s)."
                if is_campaign
                else "No coordinated campaign detected — no corpus access and no local cluster hint."
            )
            return self.report(
                assessment=assessment,
                findings=[f"Shared entity hint: {e}" for e in shared_entities] or ["No links found."],
                confidence=0.62 if is_campaign else 0.25,
                signals={
                    "is_campaign": is_campaign,
                    "operation_name": op_name if is_campaign else None,
                    "description": "Local-only heuristic from the current package." if is_campaign else None,
                    "strength": "medium" if is_campaign else "none",
                    "linked_videos": [],
                    "shared_entities": shared_entities,
                    "fingerprint_links": [],
                    "case_focus": brief.get("focus"),
                },
                suggested_next="Escalate the whole campaign, not just this video." if is_campaign else None,
                used_llm=False,
            )

        # Build the campaign graph + fingerprint links (deterministic).
        from aimw.graph.builder import build_from_db
        from aimw.graph.campaigns import find as find_campaigns

        graph = await build_from_db(ctx.sessionmaker)
        campaigns = find_campaigns(graph, min_videos=2)

        my_rid = state.report_id
        # Find campaigns this video participates in.
        member_of = [c for c in campaigns if my_rid in c.videos]

        # Fingerprint neighbours: direct video↔video edges from this node.
        node = ("video", my_rid)
        fp_links: list[dict] = []
        if node in graph:
            for nbr in graph.neighbors(node):
                if isinstance(nbr, tuple) and nbr[0] == "video":
                    attrs = graph.edges[node, nbr]
                    if attrs.get("kind") == "fingerprint":
                        fp_links.append({
                            "video": nbr[1],
                            "link_type": attrs.get("link_type"),
                            "similarity": attrs.get("similarity"),
                        })

        linked_videos: set[str] = set()
        shared_entities: list[str] = []
        strength = "none"
        for c in member_of:
            linked_videos.update(v for v in c.videos if v != my_rid)
            shared_entities.extend(c.shared_entities)
            if c.strength == "strong" or strength == "strong":
                strength = "strong"
            elif strength != "strong":
                strength = c.strength
        for link in fp_links:
            linked_videos.add(link["video"])

        is_campaign = bool(member_of) or bool(fp_links) or bool(brief.get("payment_rail"))
        op_name = ""
        description = ""
        used_llm = False

        if is_campaign:
            payload = {
                "case_brief": brief,
                "linked_video_count": len(linked_videos),
                "shared_entities": shared_entities[:10],
                "fingerprint_links": fp_links[:10],
            }
            data = await ctx.llm.ask(_SYSTEM, json.dumps(payload, ensure_ascii=False), "CampaignName", 300)
            if data:
                op_name = str(data.get("operation_name", ""))[:80]
                description = str(data.get("description", ""))[:200]
                used_llm = True
            if not op_name:
                op_name = f"Operation {my_rid[:8].upper()}"
                description = (
                    f"{len(linked_videos)} videos linked via "
                    f"{len(shared_entities)} shared entities and {len(fp_links)} fingerprint matches."
                )

        if is_campaign:
            assessment = f"⚠ CAMPAIGN: {op_name} — {len(linked_videos)} linked video(s), strength={strength}."
            conf = 0.85 if strength == "strong" else 0.65
        else:
            assessment = "No coordinated campaign detected — appears to be a lone account."
            conf = 0.5

        return self.report(
            assessment=assessment,
            findings=(
                [f"Shared entity: {e}" for e in shared_entities[:5]]
                + [f"Fingerprint {l['link_type']} → {l['video'][:12]} ({l['similarity']})" for l in fp_links[:5]]
            ) or ["No links found."],
            confidence=conf,
            signals={
                "is_campaign": is_campaign,
                "operation_name": op_name or None,
                "description": description or None,
                "strength": strength,
                "linked_videos": sorted(linked_videos),
                "shared_entities": shared_entities[:20],
                "fingerprint_links": fp_links,
                "case_focus": brief.get("focus"),
            },
            suggested_next="Escalate the whole campaign, not just this video." if is_campaign else None,
            used_llm=used_llm,
        )


__all__ = ["CorrelatorAgent"]
