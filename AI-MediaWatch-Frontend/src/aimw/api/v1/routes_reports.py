"""GET /api/v1/reports/{report_id} (.md, .html).

Composes ``PackagesRepository`` + the Phase 10 report generator. The
JSON view bundles the canonical ``EvidencePackage`` with the rendered
Markdown body so the dashboard can render either view from one call.

Route ordering note: FastAPI evaluates path patterns in registration
order.  The ``.md`` and ``.html`` routes are registered BEFORE the
plain ``{report_id}`` route so a path like ``rpt-001.md`` matches the
markdown handler instead of being captured by ``report_id`` as
``"rpt-001.md"``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response

from aimw.api.deps import PackagesRepoDep, RequestIdDep, RequireAnalyst
from aimw.api.v1.schemas import ReportResponse
from aimw.reasoning.referee import run as referee_run
from aimw.reasoning.stub import ReasoningStub
from aimw.report.generator import render_html, render_markdown
from aimw.scoring.registry import register

router = APIRouter(prefix="/reports", tags=["reports"])


async def _load_pkg_and_referee(repo, report_id: str):  # type: ignore[no-untyped-def]
    """Shared loader: package + deterministic referee result."""
    register()
    pkg = await repo.get(report_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail=f"report {report_id!r} not found")
    # Deterministic referee (no Groq) so reports are reproducible.
    result = await referee_run(pkg, briefs_provider=ReasoningStub())
    return pkg, result


# IMPORTANT: register the extension-bearing routes first.


@router.get(
    "/{report_id}.md",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/markdown": {}}}},
)
async def get_report_markdown(
    report_id: str,
    _request_id: RequestIdDep,
    _user: RequireAnalyst,
    packages: PackagesRepoDep,
) -> Response:
    """Markdown report body — Content-Type text/markdown."""
    pkg, result = await _load_pkg_and_referee(packages, report_id)
    body = render_markdown(pkg, result)
    return Response(content=body, media_type="text/markdown")


@router.get(
    "/{report_id}.html",
    responses={200: {"content": {"text/html": {}}}},
)
async def get_report_html(
    report_id: str,
    _request_id: RequestIdDep,
    _user: RequireAnalyst,
    packages: PackagesRepoDep,
) -> Response:
    """HTML report body — Content-Type text/html."""
    pkg, result = await _load_pkg_and_referee(packages, report_id)
    body = render_html(pkg, result)
    return Response(content=body, media_type="text/html")


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: str,
    request_id: RequestIdDep,
    _user: RequireAnalyst,
    packages: PackagesRepoDep,
) -> ReportResponse:
    """Full EvidencePackage JSON + Markdown body.

    Prefers the stored verdict projection (the LLM judge's result when the
    pipeline ran it) and the persisted verdict-led markdown; falls back to the
    deterministic computed score and a freshly-rendered body when those are
    absent (older packages, or runs with no LLM key).
    """
    pkg, result = await _load_pkg_and_referee(packages, report_id)
    proj = await packages.get_projection(report_id)
    stored_md = await packages.get_stored_markdown(report_id)

    md = stored_md or render_markdown(pkg, result)
    if stored_md and stored_md.startswith("## AI judge verdict"):
        md = md.replace("## Verdict", "## Rule-only assessment (supporting evidence)", 1)

    rl_computed = pkg.risk_level
    rl_computed_str = (
        rl_computed.value if hasattr(rl_computed, "value")
        else str(rl_computed) if rl_computed is not None else None
    )

    has_proj = proj is not None and proj.get("risk_level") is not None
    # Infer judge mode from the action: the LLM judge sets "report" or "clear",
    # while the rule/referee path sets "auto_escalate" / "analyst_review" /
    # "monitor" / "suppress". This is the cheap projection — no extra column.
    proj_action = proj.get("action") if proj else None
    if proj_action in ("report", "clear"):
        judge: str | None = "llm"
    elif proj_action is not None:
        judge = "rules"
    else:
        judge = None
    return ReportResponse(
        package=pkg,
        markdown=md,
        request_id=request_id,
        score=proj["score"] if has_proj else pkg.score,
        risk_level=proj["risk_level"] if has_proj else rl_computed_str,
        confidence=proj["confidence"] if proj else None,
        action=proj["action"] if proj else None,
        judge=judge,
    )


__all__ = ["router"]
