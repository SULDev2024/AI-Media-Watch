"""Biometric analysis API — face re-identification, voice linking, logo detection.

Provides endpoints for the three biometric capabilities:
  GET  /api/v1/biometrics/capabilities — list available capabilities + status
  GET  /api/v1/biometrics/logos/references — list loaded reference logos
  POST /api/v1/biometrics/logos/reload — reload reference logo library
  POST /api/v1/biometrics/faces/match — match faces across provided embeddings
  POST /api/v1/biometrics/voices/match — match voices across provided embeddings
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from fastapi import APIRouter

from aimw.api.deps import RequestIdDep, RequireAnalyst

router = APIRouter(prefix="/biometrics", tags=["biometrics"])


@router.get("/capabilities")
async def capabilities(request_id: RequestIdDep, _user: RequireAnalyst) -> dict:
    """Report which biometric modules are operational."""
    from aimw.biometrics import face, speaker, logo

    face_ok = face._HAS_DEPS
    speaker_ok = speaker._HAS_DEPS
    logo_ok = logo._HAS_DEPS
    refs = logo.list_reference_logos() if logo_ok else []

    return {
        "face_recognition": {
            "available": face_ok,
            "embedding_dim": face.EMBED_DIM if face_ok else None,
            "match_threshold": face.MATCH_THRESHOLD,
            "description": "Detect and re-identify faces across videos/images",
        },
        "speaker_diarization": {
            "available": speaker_ok,
            "embedding_dim": speaker.EMBED_DIM if speaker_ok else None,
            "match_threshold": speaker.VOICE_MATCH_THRESHOLD,
            "description": "Identify speakers and link same voice across videos",
        },
        "logo_detection": {
            "available": logo_ok,
            "n_reference_logos": len(refs),
            "reference_logos": [r["brand"] for r in refs],
            "min_good_matches": logo.MIN_GOOD_MATCHES,
            "description": "Detect fraudulent use of government/bank logos",
        },
        "request_id": request_id,
    }


@router.get("/logos/references")
async def logo_references(request_id: RequestIdDep, _user: RequireAnalyst) -> dict:
    """List loaded reference logos."""
    from aimw.biometrics.logo import list_reference_logos

    refs = list_reference_logos()
    return {"references": refs, "total": len(refs), "request_id": request_id}


@router.post("/logos/reload")
async def reload_logos(request_id: RequestIdDep, _user: RequireAnalyst) -> dict:
    """Hot-reload reference logo library from config/logos/."""
    from aimw.biometrics.logo import reload_references

    count = reload_references()
    return {"reloaded": count, "request_id": request_id}


class FaceMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embeddings: dict[str, list[list[float]]] = Field(
        ..., description="Mapping video_id → list of face embedding vectors"
    )
    threshold: float = Field(default=0.82, ge=0.5, le=1.0)


@router.post("/faces/match")
async def face_match(
    body: FaceMatchRequest,
    request_id: RequestIdDep,
    _user: RequireAnalyst,
) -> dict:
    """Match faces across videos using pre-computed embeddings."""
    from aimw.biometrics.face import cluster_faces, find_reidentifications

    all_faces: dict[str, list[dict]] = {}
    for vid, emb_list in body.embeddings.items():
        faces = []
        for i, emb in enumerate(emb_list):
            faces.append({
                "embedding": emb,
                "face_id": f"face_{i:04d}",
                "frame_idx": 0,
                "bbox": (0, 0, 0, 0),
            })
        all_faces[vid] = faces

    clusters = cluster_faces(all_faces, threshold=body.threshold)
    reids = find_reidentifications(all_faces, threshold=body.threshold)

    return {
        "clusters": clusters,
        "cross_video_matches": [
            {
                "video_a": r[0], "face_a": r[1],
                "video_b": r[2], "face_b": r[3],
                "similarity": r[4],
            }
            for r in reids
        ],
        "n_identities": len(clusters),
        "n_cross_matches": len(reids),
        "request_id": request_id,
    }


class VoiceMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embeddings: dict[str, list[float]] = Field(
        ..., description="Mapping video_id → speaker embedding vector"
    )
    threshold: float = Field(default=0.88, ge=0.5, le=1.0)


@router.post("/voices/match")
async def voice_match(
    body: VoiceMatchRequest,
    request_id: RequestIdDep,
    _user: RequireAnalyst,
) -> dict:
    """Match speaker voices across videos using pre-computed embeddings."""
    from aimw.biometrics.speaker import find_voice_matches

    matches = find_voice_matches(body.embeddings, threshold=body.threshold)
    return {
        "matches": [
            {"video_a": m[0], "video_b": m[1], "similarity": m[2]}
            for m in matches
        ],
        "n_matches": len(matches),
        "request_id": request_id,
    }


__all__ = ["router"]
