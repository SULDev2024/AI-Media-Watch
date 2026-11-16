"""Live Groq briefs provider — Phase 15.6A.

Wraps :mod:`aimw.reasoning.briefs` + :class:`aimw.reasoning.client.GroqClient`
into the :class:`aimw.reasoning.referee.BriefProvider` protocol so the pipeline
can swap from ``ReasoningStub`` to live LLM calls without any further
structural changes.

Import contract: ``aimw.reasoning`` must not import ``aimw.db`` directly
(contract ``reasoning-no-direct-writes``).  Callers that need to construct a
``LiveBriefProvider`` with a database-backed usage tracker must wire this in
a module that is permitted to import ``aimw.db`` (e.g. ``aimw.workers.pipeline``).
"""
from __future__ import annotations

from aimw.confidence.models import BriefShape
from aimw.core.schema.evidence import EvidencePackage
from aimw.reasoning.client import GroqClient


class LiveBriefProvider:
    """Live Groq-backed brief provider satisfying ``BriefProvider`` protocol.

    Both :meth:`prosecutor` and :meth:`defense` call the Groq API through
    the budgeted :class:`GroqClient`.  ``TokenBudgetExhausted`` propagates
    up to the referee which handles it via the documented fallback path.

    Construction
    ------------
    The caller is responsible for budget checking before constructing this
    class.  See ``aimw.workers.pipeline._select_briefs_provider`` for the
    canonical wiring pattern.
    """

    def __init__(self, client: GroqClient) -> None:
        self._client = client

    async def prosecutor(self, pkg: EvidencePackage) -> BriefShape:
        from aimw.reasoning import briefs

        return await briefs.prosecutor(pkg, self._client)

    async def defense(self, pkg: EvidencePackage) -> BriefShape:
        from aimw.reasoning import briefs

        return await briefs.defense(pkg, self._client)


__all__ = ["LiveBriefProvider"]
