import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_local_collector_state_and_lock_without_redis(tmp_path, monkeypatch):
    from aimw.collection import control
    monkeypatch.setattr(control, "get_settings", lambda: SimpleNamespace(eager=True, resolved_data_dir=tmp_path))
    monkeypatch.setattr(control, "_client", lambda: pytest.fail("Local mode must not contact Redis"))
    assert control.get_state()["status"] == "stopped"
    control.start(["test search"], per_query=1)
    assert control.get_state()["status"] == "running"
    token = control.acquire_tick_lock()
    assert token
    assert control.acquire_tick_lock() is None
    control.release_tick_lock(token)
    control.record_run(2)
    assert control.get_state()["enqueued_total"] == 2
    control.stop()
    assert control.get_state()["status"] == "stopped"


@pytest.mark.asyncio
async def test_failed_upload_is_not_returned_as_pending():
    from aimw.api.v1.routes_videos import list_videos
    video = SimpleNamespace(id="failed-test", platform="manual-video", url="test.mp4",
                            collected_at=dt.datetime.now(dt.UTC), raw_path="test.mp4", title=None)
    videos = SimpleNamespace(list_recent=AsyncMock(return_value=[video]))
    packages = SimpleNamespace(list_by_video=AsyncMock(return_value=[]), latest_failure=AsyncMock(return_value="Unreadable media"))
    result = await list_videos("test", None, videos, packages, limit=50, since=None, level=None)
    assert result.items[0].level == "FAILED"
    assert result.items[0].action == "failed"
    assert result.items[0].score is None


@pytest.mark.asyncio
async def test_local_collector_start_stop_schedules_async_work(tmp_path, monkeypatch):
    import asyncio
    from aimw.collection import control
    from aimw.api.v1 import routes_collector as routes
    from aimw.api.v1.schemas import CollectorStartRequest
    from aimw.workers import tasks
    settings = SimpleNamespace(eager=True, resolved_data_dir=tmp_path)
    monkeypatch.setattr(control, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(control, "supported_platforms", lambda: ("youtube",))
    tick = AsyncMock(return_value=0)
    monkeypatch.setattr(tasks, "collect_once", tick)
    try:
        state = await routes.collector_start(CollectorStartRequest(queries=["test"]), None)
        assert state.status == "running"
        await asyncio.sleep(0)
        tick.assert_awaited_once()
    finally:
        await routes.shutdown_local_collector()
    assert control.get_state()["status"] == "stopped"
