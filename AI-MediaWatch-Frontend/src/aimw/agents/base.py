"""Agent framework contracts — the shared spine of the investigation cell.

Every agent is a small, single-purpose unit that:
  1. reads the shared :class:`CaseState` (the blackboard),
  2. optionally calls an LLM (with a deterministic fallback),
  3. returns a structured :class:`AgentReport` — never free text into the verdict.

Agents NEVER write the final score, risk level, or custody chain. That is the
job of the deterministic firewall (``aimw.agents.firewall``). This separation is
what keeps every verdict reproducible and court-admissible while the agents do
the fuzzy investigative reasoning above it.
"""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from aimw.agents.llm import AgentLLM
    from aimw.agents.state import CaseState
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class AgentReport(BaseModel):
    """The structured output contract every agent must return.

    Free-form reasoning lives in ``assessment``/``findings`` for humans; the
    machine-actionable parts are ``confidence`` and the typed ``signals`` dict.
    """

    model_config = ConfigDict(extra="forbid")

    agent: str                                  # machine name, e.g. "correlator"
    role: str                                   # human label, e.g. "Network Analyst"
    tier: int                                   # 1..4 (acquisition→output)
    assessment: str                             # one-line summary for the journal
    findings: list[str] = Field(default_factory=list)
    confidence: float = 0.5                     # 0..1 — agent's own certainty
    signals: dict[str, Any] = Field(default_factory=dict)  # typed structured output
    suggested_next: str | None = None
    used_llm: bool = False
    elapsed_ms: float = 0.0
    error: str | None = None


@dataclass
class AgentContext:
    """Shared resources handed to every agent at run time.

    Carries the LLM wrapper and (optionally) DB access for agents that need to
    query the corpus (Scout, Correlator). A plain dataclass (not a Pydantic
    model) because it holds live runtime objects, not serialisable data.
    """

    llm: "AgentLLM"
    sessionmaker: "async_sessionmaker[AsyncSession] | None" = None
    case_brief: dict[str, Any] | None = None
    activation: dict[str, Any] | None = None


class Agent(abc.ABC):
    """Base class for every agent in the cell.

    Subclasses set the class attributes and implement :meth:`_run`. The public
    :meth:`run` wraps timing and error handling so one misbehaving agent can
    never crash the whole investigation — it returns an ``AgentReport`` with an
    ``error`` field instead.
    """

    name: str = "agent"
    role: str = "Agent"
    tier: int = 1
    uses_llm: bool = False

    async def run(self, state: "CaseState", ctx: AgentContext) -> AgentReport:
        """Execute the agent, capturing timing and isolating failures."""
        start = time.perf_counter()
        try:
            report = await self._run(state, ctx)
        except Exception as exc:  # never let one agent sink the cell
            report = AgentReport(
                agent=self.name,
                role=self.role,
                tier=self.tier,
                assessment=f"{self.role} failed: {type(exc).__name__}",
                confidence=0.0,
                error=f"{type(exc).__name__}: {exc}",
            )
        report.elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        return report

    @abc.abstractmethod
    async def _run(self, state: "CaseState", ctx: AgentContext) -> AgentReport:
        """Do the agent's actual work. Implemented by each subclass."""
        raise NotImplementedError

    # Convenience constructor for a report carrying this agent's identity.
    def report(self, **kwargs: Any) -> AgentReport:
        kwargs.setdefault("agent", self.name)
        kwargs.setdefault("role", self.role)
        kwargs.setdefault("tier", self.tier)
        return AgentReport(**kwargs)


__all__ = ["Agent", "AgentContext", "AgentReport"]
