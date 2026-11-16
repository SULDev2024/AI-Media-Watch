"""GET /api/v1/system/info — runtime + sovereignty posture.

Surfaces WHERE inference runs so a regulator can see the system can operate
fully on-premises / air-gapped. The same code path serves Groq cloud or a
self-hosted OpenAI-compatible server; this endpoint reports which is active.
"""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter

from aimw.api.deps import RequestIdDep, RequireAnalyst
from aimw.core.config import get_settings

router = APIRouter(prefix="/system", tags=["system"])

# Hosts that mean "inference leaves the operator's network".
_CLOUD_HOSTS = ("groq.com", "openai.com", "anthropic.com", "together.ai", "fireworks.ai")


@router.get("/info")
async def system_info(request_id: RequestIdDep, _user: RequireAnalyst) -> dict:
    """Report model, inference location, and sovereignty posture."""
    s = get_settings()
    base_url = s.resolved_llm_base_url or ""
    host = urlparse(base_url).hostname or ""
    is_cloud = any(host.endswith(h) for h in _CLOUD_HOSTS)
    return {
        "llm_model": s.resolved_llm_model,
        "llm_provider": getattr(s, "llm_provider", "unknown"),
        "inference_host": host,
        "on_prem": not is_cloud,
        "sovereign_capable": True,  # the client is provider-agnostic by design
        "mode": "cloud" if is_cloud else "on-prem / air-gapped",
        "note": (
            "Inference currently runs in the cloud. Switch to fully sovereign "
            "on-prem inference with a config change (AIMW_LLM_BASE_URL) — no code "
            "change. Citizen video never has to leave the operator's network."
            if is_cloud
            else "Inference runs on operator-controlled hardware. Data does not leave the network."
        ),
        "request_id": request_id,
    }


__all__ = ["router"]
