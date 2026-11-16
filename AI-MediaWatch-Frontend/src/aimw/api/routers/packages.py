"""Packages router — GET /packages, GET /packages/{report_id}."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aimw.api.dependencies import AuthDep, PageDep, SessionmakerDep
from aimw.api.models import (
    EntitiesResponse,
    EvidencePieceResponse,
    NetworkConnectionResponse,
    PackageDetail,
    PackageSummary,
    Paginated,
)
from aimw.core.schema import EvidencePackage
from aimw.db.repositories.packages import PackagesRepository
from aimw.reasoning.referee import run as referee_run
from aimw.reasoning.stub import ReasoningStub
from aimw.scoring.registry import register

router = APIRouter(prefix="/packages", tags=["packages"])


def _ensure_scoring() -> None:
    register()


def _to_summary(pkg: EvidencePackage) -> PackageSummary:
    _ensure_scoring()
    return PackageSummary(
        report_id=pkg.report_id,
        video_id=pkg.video_id,
        platform=pkg.platform,
        url=pkg.url,
        processed_at=pkg.processed_at,
        risk_level=pkg.risk_level,
        score=round(pkg.score, 4),
        n_evidence=len(pkg.evidence),
        n_network_connections=len(pkg.network_connections),
    )


def _to_detail(
    pkg: EvidencePackage,
    *,
    confidence: float | None,
    action: str | None,
) -> PackageDetail:
    _ensure_scoring()
    return PackageDetail(
        report_id=pkg.report_id,
        video_id=pkg.video_id,
        platform=pkg.platform,
        url=pkg.url,
        processed_at=pkg.processed_at,
        risk_level=pkg.risk_level,
        score=round(pkg.score, 4),
        n_evidence=len(pkg.evidence),
        n_network_connections=len(pkg.network_connections),
        confidence=confidence,
        action=action,
        evidence=[
            EvidencePieceResponse(
                source=p.source,
                polarity=p.polarity,
                strength=p.strength,
                indicator_type=p.indicator_type,
                raw_value=p.raw_value,
                timestamp=p.timestamp,
                corroborated_by=list(p.corroborated_by),
                recovery_method=p.recovery_method,
                regulation_ref=p.regulation_ref,
            )
            for p in pkg.evidence
        ],
        entities=EntitiesResponse(
            telegram_handles=list(pkg.entities.telegram_handles),
            telegram_links=list(pkg.entities.telegram_links),
            crypto_wallets=list(pkg.entities.crypto_wallets),
            phone_numbers=list(pkg.entities.phone_numbers),
            websites=list(pkg.entities.websites),
            referral_codes=list(pkg.entities.referral_codes),
            profit_claims=list(pkg.entities.profit_claims),
            payment_phones=list(pkg.entities.payment_phones),
        ),
        network_connections=[
            NetworkConnectionResponse(
                kind=nc.kind,
                shared_entity_kind=nc.shared_entity_kind,
                shared_entity_value=nc.shared_entity_value,
                co_occurring_report_ids=list(nc.co_occurring_report_ids),
                campaign_strength=nc.campaign_strength,
                detected_at=nc.detected_at,
            )
            for nc in pkg.network_connections
        ],
    )


@router.get("", response_model=Paginated[PackageSummary])
async def list_packages(
    page: PageDep,
    sm: SessionmakerDep,
    _auth: AuthDep,
) -> Paginated[PackageSummary]:
    """List all evidence packages, newest first.

    Scoring is computed in-memory for each package; the DB projection columns
    (score, risk_level) are ignored because they are not populated until Phase 13.
    """
    _ensure_scoring()
    repo = PackagesRepository(sm)
    total, packages = await repo.list_all(limit=page.limit, offset=page.offset)
    return Paginated(
        total=total,
        limit=page.limit,
        offset=page.offset,
        items=[_to_summary(p) for p in packages],
    )


@router.get("/{report_id}", response_model=PackageDetail)
async def get_package(
    report_id: str,
    sm: SessionmakerDep,
    _auth: AuthDep,
) -> PackageDetail:
    """Retrieve a single package with full evidence, computed score, and confidence.

    Runs the deterministic referee (ReasoningStub) to produce confidence and
    action without making any Groq API calls.
    """
    _ensure_scoring()
    repo = PackagesRepository(sm)
    pkg = await repo.get(report_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail=f"Package {report_id!r} not found")

    result = await referee_run(pkg, briefs_provider=ReasoningStub())
    confidence = result.confidence.confidence if result.confidence is not None else None
    return _to_detail(pkg, confidence=confidence, action=result.action)
