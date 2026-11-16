"""Cancel selected unfinished YouTube entries while the AIMW backend is stopped.

Keeps videos and prior evidence; marks queued work cancelled and records why
processing stopped. Does not launch services, delete files, or contact YouTube.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import socket
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def cancel_pending(db_path: Path, youtube_ids: list[str]) -> list[str]:
    if not db_path.is_file():
        raise RuntimeError('Project database was not found.')
    changed = []
    wanted = set(youtube_ids)
    with closing(sqlite3.connect(str(db_path))) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        for video_id, url in db.execute('SELECT id, url FROM videos').fetchall():
            parts = urlsplit(url)
            source_id = parts.path.lstrip('/') if parts.hostname == 'youtu.be' else parse_qs(parts.query).get('v', [''])[0]
            if parts.hostname not in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be') or source_id not in wanted:
                continue
            # Completed results and existing failures are preserved unchanged.
            if db.execute('SELECT 1 FROM evidence_packages WHERE video_id=? AND (schema_version != ? OR action=?) LIMIT 1', (video_id, 'failed', 'failed')).fetchone():
                continue
            now = dt.datetime.now(dt.UTC).isoformat()
            blob = json.dumps({'status': 'failed', 'video_id': video_id, 'error': {'type': 'CancelledByUser', 'message': 'Cancelled by user.'}, 'failed_at': now})
            db.execute('INSERT INTO evidence_packages (report_id,video_id,processed_at,schema_version,package_json,risk_level,action) VALUES (?,?,?,?,?,?,?)',
                       ('cancelled-' + uuid.uuid4().hex, video_id, now, 'failed', blob, 'CANCELLED', 'failed'))
            for queue_id, payload in db.execute('SELECT id,payload FROM ingest_queue WHERE status IN (?,?)', ('pending', 'processing')).fetchall():
                if json.loads(payload).get('video_id') == video_id:
                    db.execute('UPDATE ingest_queue SET status=? WHERE id=?', ('cancelled', queue_id))
            changed.append(source_id)
    return changed


def main() -> None:
    from dotenv import load_dotenv
    project = Path(__file__).resolve().parents[1]
    load_dotenv(project / '.env')
    import os
    os.chdir(project)
    from aimw.core.config import get_settings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--youtube-id', nargs='+', required=True, help='Only these YouTube video IDs will be considered.')
    args = parser.parse_args()
    settings = get_settings()
    try:
        connection = socket.create_connection(('127.0.0.1', settings.api_port), timeout=1)
    except OSError:
        pass
    else:
        connection.close()
        raise SystemExit('Stop the AIMW launcher with Ctrl+C before cancelling jobs, so downloads cannot continue in the background.')
    changed = cancel_pending(settings.resolved_sqlite_path, args.youtube_id)
    for source_id in changed:
        print(f'Cancelled unfinished entry: {source_id}')
    if not changed:
        print('No matching unfinished entries. Existing results and failures were left unchanged.')
    print('You can now restart the project and refresh the detection queue.')


if __name__ == '__main__':
    main()
