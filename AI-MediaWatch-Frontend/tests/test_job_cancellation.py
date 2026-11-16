"""Offline cancellation tests: no media requests, model loads, or servers."""
import asyncio
import datetime as dt
import json
import unittest
from unittest.mock import AsyncMock
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from aimw.db.models import Base, EvidencePackageRow, IngestQueueRow, Video
from aimw.workers import cancellation as jobs
from aimw.db.repositories.packages import PackagesRepository


class JobCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        self.sm = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        now = dt.datetime.now(dt.UTC)
        async with self.sm() as session, session.begin():
            for name in ['selected', 'unrelated', 'completed']:
                jobs.reset_job(name)
                session.add(Video(id=name, platform='youtube', url='https://example.com/' + name, collected_at=now))
            await session.flush()
            for name in ['selected', 'unrelated']:
                session.add(IngestQueueRow(kind='video_url', payload={'video_id': name}, created_at=now, status='pending'))
            session.add(EvidencePackageRow(report_id='completed-report', video_id='completed', processed_at=now, schema_version='1', package_json='{}', risk_level='LOW'))

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_cancels_only_selected_and_persists_across_duplicate_requests(self):
        await jobs.cancel_video(self.sm, 'selected')
        await jobs.cancel_video(self.sm, 'selected')
        async with self.sm() as session:
            packages = (await session.scalars(select(EvidencePackageRow).where(EvidencePackageRow.video_id == 'selected'))).all()
            queue = (await session.scalars(select(IngestQueueRow))).all()
        self.assertEqual(len(packages), 1)
        self.assertEqual(json.loads(packages[0].package_json)['error']['message'], jobs.CANCEL_MESSAGE)
        self.assertEqual({row.payload['video_id']: row.status for row in queue}, {'selected': 'cancelled', 'unrelated': 'pending'})
        self.assertTrue(jobs.event_for('selected').is_set())
        self.assertFalse(jobs.event_for('unrelated').is_set())

    async def test_completed_and_unknown_items_are_protected(self):
        with self.assertRaises(ValueError):
            await jobs.cancel_video(self.sm, 'completed')
        with self.assertRaises(LookupError):
            await jobs.cancel_video(self.sm, 'unknown')
        self.assertFalse(jobs.event_for('completed').is_set())

    async def test_active_task_is_cancelled_and_registry_is_cleaned(self):
        task = asyncio.create_task(asyncio.Event().wait())
        jobs.track_task('selected', task)
        await asyncio.sleep(0)
        await jobs.cancel_video(self.sm, 'selected')
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        self.assertNotIn('selected', jobs._tasks)

    async def test_retry_keeps_old_download_signal_cancelled(self):
        old = jobs.event_for('selected')
        jobs.request_cancel('selected')
        jobs.reset_job('selected')
        self.assertTrue(old.is_set())
        self.assertFalse(jobs.event_for('selected').is_set())

    async def test_timeout_with_empty_message_remains_a_failure(self):
        async with self.sm() as session, session.begin():
            session.add(EvidencePackageRow(
                report_id='timeout', video_id='selected', processed_at=dt.datetime.now(dt.UTC),
                schema_version='failed', risk_level='FAILED', action='failed',
                package_json=json.dumps({'error': {'type': 'ReadTimeout', 'message': ''}}),
            ))
        self.assertEqual(await PackagesRepository(self.sm).latest_failure('selected'), 'ReadTimeout')
        from aimw.api.v1.routes_videos import get_video, list_videos
        from aimw.db.repositories.videos import VideosRepository
        packages = PackagesRepository(self.sm)
        videos = VideosRepository(self.sm)
        detail = await get_video('selected', 'test-request', None, videos, packages)
        self.assertEqual(detail.status, 'failed')
        self.assertEqual(detail.error, 'ReadTimeout')
        async with self.sm() as session:
            row = await session.get(Video, 'selected')
        queue = await list_videos('test-request', None,
            SimpleNamespace(list_recent=AsyncMock(return_value=[row])), packages,
            limit=50, since=None, level=None)
        self.assertEqual(queue.items[0].level, 'FAILED')
        with self.assertRaisesRegex(ValueError, 'already failed'):
            await jobs.cancel_video(self.sm, 'selected')

    async def test_failure_without_message_or_type_has_fallback(self):
        async with self.sm() as session, session.begin():
            session.add(EvidencePackageRow(
                report_id='empty-error', video_id='selected', processed_at=dt.datetime.now(dt.UTC),
                schema_version='failed', risk_level='FAILED', action='failed',
                package_json=json.dumps({'error': {'message': None}}),
            ))
        self.assertEqual(await PackagesRepository(self.sm).latest_failure('selected'), 'Analysis failed')


if __name__ == '__main__':
    unittest.main()
