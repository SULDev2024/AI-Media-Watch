"""Offline, deterministic scoring of text artefacts (revision evaluation harness).

Runs exactly the production path *after* extraction:

    speech segments + OCR blocks
        → aimw.entities.extractor.extract   (entities + promoter linkage)
        → aimw.scoring.signals.tag          (EvidencePieces)
        → aimw.scoring.engine.score         (gated, signed score → level)

No LLM, database or network is touched, so results are reproducible
byte-for-byte. Used by ``scripts/revision/`` (benchmark, baselines, ablations,
sensitivity) and by the unit tests.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from aimw.core.schema.evidence import EvidencePackage
from aimw.entities.extractor import extract
from aimw.extraction.ocr.models import OcrBlock, OcrFrameResult, OcrResult
from aimw.extraction.whisper.models import Segment, Transcript
from aimw.scoring.engine import ScoreBreakdown, score
from aimw.scoring.signals import tag

_EPOCH = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

Span = tuple[float, str]  # (timestamp_seconds, text)


def build_transcript(segments: Sequence[Span], video_id: str = "offline") -> Transcript | None:
    if not segments:
        return None
    segs = [Segment(start=t, end=t + 4.0, text=txt) for t, txt in segments]
    return Transcript(
        engine_version="offline",
        model="offline",
        device="cpu",
        compute_type="none",
        source_file_sha256="0" * 64,
        video_id=video_id,
        language_detected="en",
        segments=segs,
        generated_at=_EPOCH,
    )


def build_ocr(blocks: Sequence[Span], video_id: str = "offline") -> OcrResult | None:
    if not blocks:
        return None
    frames = [
        OcrFrameResult(
            frame_index=i,
            timestamp_s=t,
            image_path=f"offline-{i}.png",
            blocks=[OcrBlock(text=txt, bbox=(0, 0, 1, 1), confidence=1.0)],
        )
        for i, (t, txt) in enumerate(blocks)
    ]
    fields: dict[str, Any] = {
        "engine": "offline",
        "engine_version": "offline",
        "source_file_sha256": "0" * 64,
        "video_id": video_id,
        "frames": frames,
        "generated_at": _EPOCH,
    }
    allowed = set(OcrResult.model_fields)
    return OcrResult(**{k: v for k, v in fields.items() if k in allowed})


def build_package(
    speech: Sequence[Span],
    ocr: Sequence[Span] = (),
    *,
    video_id: str = "offline",
) -> EvidencePackage:
    transcript = build_transcript(speech, video_id)
    ocr_res = build_ocr(ocr, video_id)
    if transcript is None and ocr_res is None:
        return EvidencePackage(
            report_id=f"r-{video_id}", video_id=video_id, platform="offline",
            url="offline://", collected_at=_EPOCH, processed_at=_EPOCH,
        )
    entities, spans = extract(transcript, ocr_res)
    pieces = tag(spans, entities, ocr=ocr_res, transcript=transcript)
    return EvidencePackage(
        report_id=f"r-{video_id}",
        video_id=video_id,
        platform="offline",
        url="offline://",
        collected_at=_EPOCH,
        processed_at=_EPOCH,
        evidence=pieces,
        entities=entities,
    )


def score_text(
    speech: Sequence[Span],
    ocr: Sequence[Span] = (),
    *,
    video_id: str = "offline",
    **score_kwargs: Any,
) -> ScoreBreakdown:
    return score(build_package(speech, ocr, video_id=video_id), **score_kwargs)
