"""The shared case file — the blackboard every agent reads and writes.

There is exactly one ``CaseState`` per investigation. Agents communicate ONLY
through it (never directly with each other), and every action is appended to an
immutable ``journal``. Replaying the journal reproduces the entire reasoning
path — the agent-layer equivalent of the deterministic firewall's audit trail.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aimw.agents.base import AgentReport
from aimw.core.schema.evidence import EvidencePackage


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


class JournalEntry(BaseModel):
    """One immutable line in the case journal."""

    model_config = ConfigDict(extra="forbid")

    seq: int
    agent: str
    action: str
    detail: str
    timestamp: str = Field(default_factory=_now)


class CaseState(BaseModel):
    """Shared, append-only investigation state for one video.

    The ``package`` is the deterministic EvidencePackage (read-only context).
    Agent outputs accumulate in ``reports``; the firewall writes the
    authoritative verdict fields. ``escalated_to_human`` is set when the
    adjudication tier dissents.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    video_id: str
    report_id: str
    platform: str = "unknown"
    url: str = ""
    transcript: str = ""
    package: EvidencePackage | None = None
    projection: dict[str, Any] | None = None

    # Accumulated agent outputs, keyed by agent name.
    reports: dict[str, AgentReport] = Field(default_factory=dict)
    journal: list[JournalEntry] = Field(default_factory=list)

    # Written by the deterministic firewall ONLY (agents must not set these).
    final_score: float | None = None
    risk_level: str | None = None
    confidence: float | None = None
    chain_root: str | None = None
    case_file: dict[str, Any] | None = None

    # Orchestration outcome.
    verdict: str | None = None
    escalated_to_human: bool = False
    iterations: int = 0
    started_at: str = Field(default_factory=_now)
    finished_at: str | None = None

    # ── mutation helpers ────────────────────────────────────────────────────
    def log(self, agent: str, action: str, detail: str = "") -> None:
        """Append one entry to the immutable journal."""
        self.journal.append(
            JournalEntry(seq=len(self.journal), agent=agent, action=action, detail=detail)
        )

    def add_report(self, report: AgentReport) -> None:
        """Record an agent's structured report and journal its assessment."""
        self.reports[report.agent] = report
        detail = report.assessment
        if report.error:
            detail = f"ERROR: {report.error}"
        self.log(report.agent, "reported", detail)

    def get(self, agent: str) -> AgentReport | None:
        return self.reports.get(agent)

    # ── serialisation for the API / dashboard ───────────────────────────────
    def to_public(self) -> dict[str, Any]:
        """JSON-serialisable view for the dashboard (no heavy package blob)."""
        return {
            "video_id": self.video_id,
            "report_id": self.report_id,
            "platform": self.platform,
            "url": self.url,
            "projection": self.projection,
            "verdict": self.verdict,
            "final_score": self.final_score,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "chain_root": self.chain_root,
            "escalated_to_human": self.escalated_to_human,
            "iterations": self.iterations,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "reports": {name: r.model_dump() for name, r in self.reports.items()},
            "journal": [
                {"ts": j.timestamp, "agent": j.agent, "event": j.action, "detail": j.detail}
                for j in self.journal
            ],
            "case_file": self.case_file,
        }


__all__ = ["CaseState", "JournalEntry"]
