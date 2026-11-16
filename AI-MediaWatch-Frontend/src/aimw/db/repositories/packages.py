"""Evidence-package repository.

The canonical blob (``package_json``) is authoritative. ``save`` writes the exact
:func:`to_json` output plus *projections* (flattened pieces/entities/network) for
SQL queries; ``get`` reconstructs only via :func:`from_json`. The derived columns
``score``/``risk_level``/``confidence``/``action`` are left NULL — the scoring
engine (Phase 8) does not exist yet and the repository never fabricates them.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aimw.core.schema import SCHEMA_VERSION, EvidencePackage, from_json, to_json
from aimw.db.models import (
    EntityRow,
    EvidencePackageRow,
    EvidencePieceRow,
    NetworkConnectionRow,
    Video,
)
from aimw.db.session import writer_lock

# The canonical entity list fields projected into the ``entities`` table.
# ``payment_phones`` is computed and ``phone_purposes`` is metadata; neither is
# flattened (both are re-derivable from the canonical blob).
_ENTITY_LIST_FIELDS = (
    "telegram_handles",
    "telegram_links",
    "crypto_wallets",
    "phone_numbers",
    "websites",
    "referral_codes",
    "profit_claims",
)


class PackagesRepository:
    """Persistence for evidence packages."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def save(self, package: EvidencePackage) -> None:
        """Persist a package: canonical blob + projections, idempotently.

        Re-saving the same ``report_id`` updates the blob and rebuilds the
        projection rows without deleting the package row, so any ``reports`` or
        ``analyst_feedback`` referencing it survive.
        """
        canonical = to_json(package)
        report_id = package.report_id

        async with writer_lock(), self._sm() as session, session.begin():
            # 1) Ensure the parent video exists (project canonical fields only;
            #    never clobber collection-owned fields like language_hint).
            await session.execute(
                sqlite_insert(Video)
                .values(
                    id=package.video_id,
                    platform=package.platform,
                    url=package.url,
                    collected_at=package.collected_at,
                )
                .on_conflict_do_nothing(index_elements=[Video.id])
            )

            # 2) Upsert the package row. Derived columns are omitted (NULL on
            #    insert) and untouched on update — never fabricated here.
            pkg_stmt = sqlite_insert(EvidencePackageRow).values(
                report_id=report_id,
                video_id=package.video_id,
                processed_at=package.processed_at,
                schema_version=SCHEMA_VERSION,
                package_json=canonical,
            )
            pkg_stmt = pkg_stmt.on_conflict_do_update(
                index_elements=[EvidencePackageRow.report_id],
                set_={
                    "video_id": pkg_stmt.excluded.video_id,
                    "processed_at": pkg_stmt.excluded.processed_at,
                    "schema_version": pkg_stmt.excluded.schema_version,
                    "package_json": pkg_stmt.excluded.package_json,
                },
            )
            await session.execute(pkg_stmt)

            # 3) Rebuild projections (pieces / entities / network).
            for model in (EvidencePieceRow, EntityRow, NetworkConnectionRow):
                await session.execute(delete(model).where(model.report_id == report_id))

            session.add_all(
                [
                    EvidencePieceRow(
                        report_id=report_id,
                        source=piece.source,
                        polarity=piece.polarity,
                        strength=piece.strength,
                        indicator_type=piece.indicator_type,
                        raw_value=piece.raw_value,
                        recovery_method=piece.recovery_method,
                        regulation_ref=piece.regulation_ref,
                        timestamp=piece.timestamp,
                    )
                    for piece in package.evidence
                ]
            )
            session.add_all(
                [
                    EntityRow(report_id=report_id, kind=kind, value=value, certainty=None)
                    for kind in _ENTITY_LIST_FIELDS
                    for value in getattr(package.entities, kind)
                ]
            )
            # Network connections are typed (NetworkConnection) as of Phase 11.
            # We persist the model_dump as the JSON payload and stamp the
            # row-level detected_at column so time-window queries don't have
            # to join back through evidence_packages.processed_at.
            session.add_all(
                [
                    NetworkConnectionRow(
                        report_id=report_id,
                        payload=conn.model_dump(mode="json"),
                        detected_at=conn.detected_at,
                    )
                    for conn in package.network_connections
                ]
            )

    async def get(self, report_id: str) -> EvidencePackage | None:
        """Reconstruct a package from its canonical blob, or return None."""
        async with self._sm() as session:
            row = await session.get(EvidencePackageRow, report_id)
            if row is None:
                return None
            return from_json(row.package_json)

    async def get_projection(self, report_id: str) -> dict | None:
        """Return the stored verdict projection (score/level/confidence/action).

        These columns carry the LLM judge's verdict when the pipeline ran it,
        or the rule-based result otherwise. Returns None if the row is absent.
        """
        async with self._sm() as session:
            row = await session.get(EvidencePackageRow, report_id)
            if row is None:
                return None
            return {
                "score": row.score,
                "risk_level": row.risk_level,
                "confidence": row.confidence,
                "action": row.action,
            }

    async def get_stored_markdown(self, report_id: str) -> str | None:
        """Return the persisted report markdown (verdict-led), or None."""
        from aimw.db.models import ReportRow

        async with self._sm() as session:
            row = await session.get(ReportRow, report_id)
            return row.markdown if row is not None else None

    async def list_by_level(
        self, level: str, since: dt.datetime | None = None
    ) -> list[EvidencePackage]:
        """Packages at a given risk level (empty until Phase 8 populates levels)."""
        async with self._sm() as session:
            stmt = select(EvidencePackageRow.package_json).where(
                EvidencePackageRow.risk_level == level,
                EvidencePackageRow.schema_version != "failed",
            )
            if since is not None:
                stmt = stmt.where(EvidencePackageRow.processed_at >= since)
            result = await session.execute(stmt)
            return [from_json(blob) for (blob,) in result.all()]

    async def list_all(
        self, *, limit: int = 20, offset: int = 0
    ) -> tuple[int, list[EvidencePackage]]:
        """Paginated listing of all packages, newest first.

        Returns ``(total_count, page_packages)`` where ``total_count`` is the
        number of rows in the table (not the page size).
        """
        async with self._sm() as session:
            total_result = await session.execute(
                select(func.count(EvidencePackageRow.report_id)).where(
                    EvidencePackageRow.schema_version != "failed"
                )
            )
            total: int = total_result.scalar_one() or 0
            result = await session.execute(
                select(EvidencePackageRow.package_json)
                .where(EvidencePackageRow.schema_version != "failed")
                .order_by(EvidencePackageRow.processed_at.desc())
                .limit(limit)
                .offset(offset)
            )
            packages = [from_json(blob) for (blob,) in result.all()]
        return total, packages

    async def latest_failure(self, video_id: str) -> str | None:
        """Return the recorded processing error for the detail/polling API."""
        import json
        async with self._sm() as session:
            blob = await session.scalar(
                select(EvidencePackageRow.package_json).where(
                    EvidencePackageRow.video_id == video_id,
                    EvidencePackageRow.schema_version == "failed",
                    EvidencePackageRow.action == "failed",
                ).order_by(EvidencePackageRow.processed_at.desc()).limit(1)
            )
        if not blob:
            return None
        error = json.loads(blob).get('error') or {}
        message = error.get('message')
        if isinstance(message, str) and message.strip():
            return message.strip()
        # Timeout and cancellation exceptions may have an empty str(exc).
        # A saved failure must remain truthy so polling cannot show it pending.
        error_type = error.get('type')
        return error_type if isinstance(error_type, str) and error_type.strip() else 'Analysis failed'

    async def list_by_video(self, video_id: str) -> list[EvidencePackage]:
        """All packages derived from a given video."""
        async with self._sm() as session:
            result = await session.execute(
                select(EvidencePackageRow.package_json)
                .where(
                    EvidencePackageRow.video_id == video_id,
                    EvidencePackageRow.schema_version != "failed",
                )
                .order_by(EvidencePackageRow.processed_at)
            )
            return [from_json(blob) for (blob,) in result.all()]
