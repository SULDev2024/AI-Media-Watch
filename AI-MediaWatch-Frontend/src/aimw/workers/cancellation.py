"""Cancellation signals and durable state for local, API-owned jobs."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import threading
import uuid

from sqlalchemy import select

from aimw.db.models import EvidencePackageRow, IngestQueueRow, Video
from aimw.db.session import writer_lock

CANCEL_MESSAGE = 'Cancelled by user.'
_events: dict[str, threading.Event] = {}
_tasks: dict[str, set[asyncio.Task]] = {}


class JobCancelled(Exception):
    pass


def event_for(video_id: str) -> threading.Event:
    return _events.setdefault(video_id, threading.Event())


def reset_job(video_id: str) -> None:
    # Replace the event; an older download thread must retain its cancelled one.
    _events[video_id] = threading.Event()


def track_task(video_id: str, task: asyncio.Task) -> None:
    group = _tasks.setdefault(video_id, set())
    group.add(task)
    def finished(done: asyncio.Task) -> None:
        group.discard(done)
        if not group and _tasks.get(video_id) is group:
            _tasks.pop(video_id, None)
    task.add_done_callback(finished)


def request_cancel(video_id: str) -> None:
    event_for(video_id).set()
    for task in tuple(_tasks.get(video_id, ())):
        task.cancel()


def check_cancelled(video_id: str) -> None:
    if event_for(video_id).is_set():
        raise JobCancelled(CANCEL_MESSAGE)


async def cancel_video(sm, video_id: str) -> None:
    """Cancel only unfinished items; preserve completed results and audit history."""
    async with writer_lock():
        async with sm() as session, session.begin():
            if await session.get(Video, video_id) is None:
                raise LookupError('Content not found')
            complete = await session.scalar(select(EvidencePackageRow.report_id).where(
                EvidencePackageRow.video_id == video_id,
                EvidencePackageRow.schema_version != 'failed',
            ).limit(1))
            if complete:
                raise ValueError('Analysis has already completed; refresh the queue.')
            latest = await session.scalar(select(EvidencePackageRow.package_json).where(
                EvidencePackageRow.video_id == video_id,
                EvidencePackageRow.schema_version == 'failed',
                EvidencePackageRow.action == 'failed',
            ).order_by(EvidencePackageRow.processed_at.desc()).limit(1))
            if latest and json.loads(latest).get('error', {}).get('message') != CANCEL_MESSAGE:
                raise ValueError('Analysis has already failed; refresh the queue.')
            if not latest:
                now = dt.datetime.now(dt.UTC)
                session.add(EvidencePackageRow(
                    report_id='cancelled-' + uuid.uuid4().hex,
                    video_id=video_id, processed_at=now, schema_version='failed',
                    risk_level='CANCELLED', action='failed',
                    package_json=json.dumps({'status': 'failed', 'video_id': video_id,
                        'error': {'type': 'CancelledByUser', 'message': CANCEL_MESSAGE},
                        'failed_at': now.isoformat()}),
                ))
            queue = (await session.scalars(select(IngestQueueRow).where(
                IngestQueueRow.status.in_(['pending', 'processing']),
                IngestQueueRow.payload['video_id'].as_string() == video_id,
            ))).all()
            for item in queue:
                item.status = 'cancelled'
        # Commit before stopping the task, while still excluding result writers.
        request_cancel(video_id)
