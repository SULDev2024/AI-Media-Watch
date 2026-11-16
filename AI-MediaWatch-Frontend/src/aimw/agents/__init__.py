"""Multi-agent investigation cell — 9 agents over a deterministic core.

The cell elevates the deterministic pipeline into an orchestrated team of
specialised agents that investigate, correlate, challenge, and brief — while the
authoritative verdict stays with the deterministic firewall (scoring + custody).

Principle: **agents investigate · the engine adjudicates · the chain of custody
is never written by an LLM.**

Public surface
--------------
``orchestrator.investigate(state, ctx)``  -> CaseState (run the whole cell)
``orchestrator.build_context(client, sm)`` -> AgentContext
``orchestrator.ROSTER``                    -> stable agent roster for the UI
``state.CaseState``                        -> the shared blackboard
``firewall.adjudicate(state)``             -> deterministic verdict gate
"""
from __future__ import annotations

__all__ = ["firewall", "orchestrator", "state"]
