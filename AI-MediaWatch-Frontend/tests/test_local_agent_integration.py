import asyncio
import datetime as dt
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from aimw.workers.local_agent import analyze_file, validate_result


def response(score=10):
    return {"risk_score": score, "reasoning": "Test assessment", "flags": [],
            "transcript": "", "visual_report": "A landscape"}


@pytest.mark.parametrize("data", [
    {"error": "GPU unavailable"}, {}, response(True), response(-1),
    response(101), response(float("nan")),
    {**response(), "flags": ["parse_error"]},
])
def test_failed_or_invalid_assessment_is_not_clean(data):
    with pytest.raises(ValueError):
        validate_result(data)


def test_zero_score_is_valid():
    assert validate_result(response(0))["risk_score"] == 0


@pytest.mark.asyncio
async def test_multipart_contract(tmp_path, monkeypatch):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"test-video")
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=response(), request=request)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handle), **kw))
    await analyze_file(path, base_url="http://local-agent:8001/", caption="title", platform="manual-video")
    assert str(seen[0].url) == "http://local-agent:8001/analyze"
    assert b'name="file"' in seen[0].content
    assert b"test-video" in seen[0].content
    assert b"title" in seen[0].content


@pytest.mark.asyncio
async def test_silent_media_uses_backend_once_without_local_whisper(tmp_path, monkeypatch):
    from aimw.workers import pipeline, local_agent
    from aimw.db.models import Video
    settings = types.SimpleNamespace(gpu_pipeline_url="http://local-agent:8001", gpu_pipeline_timeout_s=900,
                                     resolved_ocr_cache_dir=tmp_path / "ocr")
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    remote = AsyncMock(return_value={**response(75), "ocr_results": [{"time": 0.0,
        "blocks": [{"text": "Ordinary image text", "bbox": [1, 2, 30, 20], "confidence": 0.95}]}]})
    monkeypatch.setattr(local_agent, "analyze_file", remote)
    local = AsyncMock(side_effect=AssertionError("Should not load duplicate ASR"))
    monkeypatch.setattr(pipeline, "_extract_real", local)
    path = tmp_path / "silent.mp4"
    path.write_bytes(b"test")
    video = Video(id="test", platform="manual-video", url="manual-video", raw_path=str(path), collected_at=dt.datetime.now(dt.UTC))
    payload = await pipeline._extract(video)
    assert payload.gpu_verdict.risk_score == 75
    assert payload.transcript.segments == []
    assert payload.vision_description == "A landscape"
    assert payload.ocr.frames[0].blocks[0].text == "Ordinary image text"
    remote.assert_awaited_once()
    local.assert_not_awaited()


@pytest.fixture
def backend(monkeypatch):
    """Import the real HTTP backend with inference/cache isolated from the machine."""
    for name, attrs in {
        "audio_engine": {"transcribe": lambda p: {"text": "test speech"}},
        "vision_engine": {"extract_frames": lambda *a: ([object()], [0.0]),
                          "ocr_frames_batch": lambda *a: {"ocr_results": []}},
        "agents": {"analyze": lambda *a: response()},
        "cache": {"compute_hash": lambda p: "same-bytes", "get_cached": lambda k: None, "set_cached": lambda *a: None},
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    source = Path(__file__).resolve().parents[2] / "main.py"
    spec = importlib.util.spec_from_file_location("integration_backend", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    module.executor.shutdown(wait=True)


def test_backend_failure_has_non_success_status(backend, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(backend, "analyze", lambda *a: {"risk_score": 50, "flags": ["parse_error"]})
    with TestClient(backend.app) as client:
        result = client.post("/analyze", files={"file": ("test.mp4", b"test", "video/mp4")})
    assert result.status_code == 502


def test_caption_changes_do_not_reuse_cached_result(backend, monkeypatch):
    cache = {}
    monkeypatch.setattr(backend, "get_cached", cache.get)
    monkeypatch.setattr(backend, "set_cached", lambda k, v: cache.update({k: v}))
    asyncio.run(backend.process_video("test.mp4", "first caption", "manual-video"))
    asyncio.run(backend.process_video("test.mp4", "second caption", "manual-video"))
    assert len(cache) == 2


def test_image_upload_skips_whisper(backend, monkeypatch):
    import io
    from PIL import Image
    from fastapi.testclient import TestClient
    def no_transcribe(*args):
        raise AssertionError("Images must not be transcribed")
    monkeypatch.setattr(backend, "transcribe", no_transcribe)
    image = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(image, format="PNG")
    with TestClient(backend.app) as client:
        result = client.post("/analyze", files={"file": ("test.png", image.getvalue(), "image/png")})
    assert result.status_code == 200
    assert result.json()["transcript"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_pipeline_retains_upload_and_records_outcome(tmp_path, monkeypatch, failed):
    from aimw.core.config import Settings
    from aimw.db.models import Base, Video, EvidencePackageRow
    from aimw.db.session import create_engine, create_sessionmaker
    from aimw.workers import pipeline, local_agent
    from sqlalchemy import select
    import aimw.db.session as db_session
    import aimw.alerts

    settings = Settings(_env_file=None, data_dir=tmp_path,
                        gpu_pipeline_url="http://test", auto_purge_clean=True)
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = create_sessionmaker(engine)
    monkeypatch.setattr(pipeline, "get_sessionmaker", lambda: sm)
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: sm)
    monkeypatch.setattr(pipeline, "_promote_if_campaign", AsyncMock())
    monkeypatch.setattr(aimw.alerts, "dispatch_alert", AsyncMock())
    path = tmp_path / "test.mp4"
    path.write_bytes(b"test")
    async with sm() as session, session.begin():
        session.add(Video(id="test", platform="manual-video", url="manual-video test",
                          raw_path=str(path), collected_at=dt.datetime.now(dt.UTC)))
    remote = (AsyncMock(side_effect=ValueError("GPU unavailable")) if failed
              else AsyncMock(return_value=response(10)))
    monkeypatch.setattr(local_agent, "analyze_file", remote)
    try:
        if failed:
            with pytest.raises(ValueError, match="GPU unavailable"):
                await pipeline.run_pipeline("test")
        else:
            await pipeline.run_pipeline("test")
        async with sm() as session:
            assert await session.get(Video, "test") is not None
            package = await session.scalar(select(EvidencePackageRow))
            assert package.risk_level == ("FAILED" if failed else "CLEAN")
        assert path.exists()
    finally:
        await engine.dispose()
