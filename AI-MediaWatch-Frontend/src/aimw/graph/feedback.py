"""Graph-feedback writer -- Phase 11 (§0.2 issue #5).

When a campaign of >=3 videos sharing an entity is found, this module writes
a ``source="network"`` ``EvidencePiece`` back into each participating package.
The new piece raises the distinct-incrim-source count from 1 to 2, escaping
the §6.2 Rule D single-source ceiling -- which is exactly the mechanism by
which Case E (coordinated campaign) escalates from per-clip MEDIUM to HIGH.

Hard invariants:

* **No LLM call.** ``promote`` does NOT re-run the referee, does NOT call Groq,
  does NOT recompute confidence (the original briefs + confidence stored in
  the report stay authoritative). It only re-scores and re-renders.
* **Idempotent.** Re-running with the same campaigns adds nothing -- duplicates
  are detected on the triple ``(source, indicator_type, raw_value)`` and the
  matching ``NetworkConnection`` is also deduped on
  ``(shared_entity_kind, shared_entity_value)``.
* **Strength capped at MEDIUM.** Network pieces never originate STRONG; this
  prevents an attacker from manufacturing fake co-occurrences to auto-escalate.
* **Determinism.** All inner iterations sort their inputs.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aimw.core.schema import (
    EvidencePackage,
    EvidencePiece,
    NetworkConnection,
)
from aimw.db.repositories.packages import PackagesRepository
from aimw.graph.models import Campaign

INDICATOR_TYPE: str = "coordinated_campaign"
REGULATION_REF: str = "art_217_part2_kz"

# Map back from the per-campaign shared-entity kind to the ExtractedEntities
# field name where its presence would have been recorded. Used to determine
# the SharedEntityKind for the NetworkConnection payload.
_GRAPH_KIND_TO_ENTITY_FIELD: dict[str, str] = {
    "telegram_handle": "telegram_handles",
    "telegram_link": "telegram_links",
    "crypto_wallet": "crypto_wallets",
    "phone": "phone_numbers",
    "website": "websites",
    "referral_code": "referral_codes",
}

# Reverse map: from the field name back to the SharedEntityKind.
_ENTITY_FIELD_TO_GRAPH_KIND = {v: k for k, v in _GRAPH_KIND_TO_ENTITY_FIELD.items()}


def _shared_entity_kind_for_value(
    package: EvidencePackage, value: str
) -> str | None:
    """Return the SharedEntityKind under which *value* appears in package.entities, if any.

    Iterates the entity fields in a fixed order so the result is deterministic
    for cases where a value appears under multiple kinds (unlikely but possible).
    """
    for field, graph_kind in sorted(_ENTITY_FIELD_TO_GRAPH_KIND.items()):
        values: list[str] = getattr(package.entities, field, []) or []
        if value in values:
            return graph_kind
    return None


def _has_existing_network_piece(
    package: EvidencePackage, shared_entity_value: str
) -> bool:
    """Idempotency check for the EvidencePiece dedup key."""
    return any(
        p.source == "network"
        and p.indicator_type == INDICATOR_TYPE
        and p.raw_value == shared_entity_value
        for p in package.evidence
    )


def _has_existing_network_connection(
    package: EvidencePackage,
    shared_entity_kind: str,
    shared_entity_value: str,
) -> bool:
    """Idempotency check for the NetworkConnection dedup key."""
    return any(
        c.kind == "shared_entity"
        and c.shared_entity_kind == shared_entity_kind
        and c.shared_entity_value == shared_entity_value
        for c in package.network_connections
    )


def _build_network_piece(
    *,
    campaign: Campaign,
    shared_entity_value: str,
    this_video_id: str,
) -> EvidencePiece:
    """Construct the EvidencePiece to be added to one video's package."""
    other_videos = sorted(v for v in campaign.videos if v != this_video_id)
    # corroborated_by carries `Source` values, not video ids -- one entry per
    # other participating video (each is a separate "network" source contribution).
    # We list "network" repeated to reflect N independent corroborations.
    corroborated_by_count = min(len(other_videos), 5)
    corroborated_by = ["network"] * corroborated_by_count
    return EvidencePiece(
        source="network",
        polarity="incriminating",
        timestamp=None,
        content=(
            f"{len(campaign.videos)} videos share {shared_entity_value} "
            f"(co-occurring: {', '.join(other_videos)})"
        ),
        raw_value=shared_entity_value,
        indicator_type=INDICATOR_TYPE,
        strength="medium",
        recovery_method=None,
        corroborated_by=corroborated_by,
        regulation_ref=REGULATION_REF,
    )


async def promote(
    sessionmaker: async_sessionmaker[AsyncSession],
    campaigns: list[Campaign],
    *,
    now: dt.datetime | None = None,
    render_report: bool = True,
) -> int:
    """Write back a ``network`` piece + ``NetworkConnection`` for each campaign video.

    Parameters
    ----------
    sessionmaker:
        Async sessionmaker for the SQLite database.
    campaigns:
        Sorted list of campaigns from ``campaigns.find``.
    now:
        Override for ``detected_at`` -- defaults to ``datetime.now(UTC)``.
        Tests pass a fixed value for byte-stable assertions.
    render_report:
        When True (production default), re-render the Markdown report after
        re-scoring and persist it via ``ReportRow``. Tests can set this to
        False if they want to verify scoring alone.

    Returns
    -------
    int
        Number of packages actually modified (a package already containing the
        promoted piece for the campaign's entity contributes zero).
    """
    if now is None:
        now = dt.datetime.now(dt.UTC)

    repo = PackagesRepository(sessionmaker)
    updated_packages = 0

    # Collect (video, shared_entity, campaign) plan deterministically.
    plan: list[tuple[str, str, Campaign]] = []
    for campaign in campaigns:
        for shared_entity in sorted(campaign.shared_entities):
            for video_id in sorted(campaign.videos):
                plan.append((video_id, shared_entity, campaign))

    for video_id, shared_entity, campaign in plan:
        # Load the package by report_id (== video_id is NOT guaranteed; the
        # graph uses report_id as the video-key value, see builder.py).
        package = await repo.get(video_id)
        if package is None:
            continue

        # Determine the SharedEntityKind under which this value appears.
        shared_entity_kind = _shared_entity_kind_for_value(package, shared_entity)
        if shared_entity_kind is None:
            # Defensive: the graph said this video has the entity, but the
            # canonical entities don't agree. Skip rather than fabricate.
            continue

        added_piece = False
        added_connection = False
        new_evidence: list[EvidencePiece] = list(package.evidence)
        new_connections: list[NetworkConnection] = list(package.network_connections)

        if not _has_existing_network_piece(package, shared_entity):
            new_evidence.append(
                _build_network_piece(
                    campaign=campaign,
                    shared_entity_value=shared_entity,
                    this_video_id=video_id,
                )
            )
            added_piece = True

        if not _has_existing_network_connection(
            package, shared_entity_kind, shared_entity
        ):
            new_connections.append(
                NetworkConnection(
                    kind="shared_entity",
                    shared_entity_kind=shared_entity_kind,
                    shared_entity_value=shared_entity,
                    co_occurring_report_ids=sorted(campaign.videos),
                    campaign_strength=campaign.strength,
                    detected_at=now,
                )
            )
            added_connection = True

        if not (added_piece or added_connection):
            continue

        # Reconstruct the package with the new fields (frozen model).
        updated = package.model_copy(
            update={
                "evidence": new_evidence,
                "network_connections": new_connections,
            }
        )
        await repo.save(updated)
        updated_packages += 1

        if render_report:
            await _persist_report(sessionmaker, updated, now)

    return updated_packages


async def _persist_report(
    sessionmaker: async_sessionmaker[AsyncSession],
    package: EvidencePackage,
    generated_at: dt.datetime,
) -> None:
    """Re-render the Markdown report and persist it.

    Uses a minimal ``RefereeResult``-shaped wrapper around the re-scored
    package: the report carries the new ScoreBreakdown but no fresh briefs
    (Phase 11 invariant: graph events do NOT call the LLM).
    """
    # Lazy imports to keep graph/__init__ import-time small and so the
    # extraction subsystem cannot pull these transitively.
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from aimw.confidence.models import BriefShape
    from aimw.db.models import ReportRow
    from aimw.db.session import writer_lock
    from aimw.reasoning.referee import RefereeResult
    from aimw.report.generator import render_markdown
    from aimw.scoring.engine import score

    score_breakdown = score(package)
    review_levels = ("HIGH", "CRITICAL", "MEDIUM")
    action = "analyst_review" if score_breakdown.level in review_levels else "monitor"
    result = RefereeResult(
        base=score_breakdown,
        adjusted=score_breakdown,
        confidence=None,
        prosecutor=None,
        defense=None,
        valid_discounts=[],
        level=score_breakdown.level,
        confidence_softened=False,
        action=action,
        status_note="graph_recomputed",
    )
    # Silence the unused-import noise for the legacy BriefShape import.
    _ = BriefShape

    markdown = render_markdown(package, result)

    async with writer_lock(), sessionmaker() as session, session.begin():
        stmt = sqlite_insert(ReportRow).values(
            report_id=package.report_id,
            markdown=markdown,
            generated_at=generated_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ReportRow.report_id],
            set_={
                "markdown": stmt.excluded.markdown,
                "generated_at": stmt.excluded.generated_at,
            },
        )
        await session.execute(stmt)


__all__ = ["INDICATOR_TYPE", "REGULATION_REF", "promote"]
