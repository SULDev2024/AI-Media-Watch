import hashlib
import json
import os
import sqlite3
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "analysis_cache.db")

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            video_hash TEXT PRIMARY KEY,
            result TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON cache(video_hash)")
    return conn

def compute_hash(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def get_cached(hash_str: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute("SELECT result FROM cache WHERE video_hash = ?", (hash_str,)).fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

def set_cached(hash_str: str, result: dict):
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO cache (video_hash, result) VALUES (?, ?)",
        (hash_str, json.dumps(result))
    )
    conn.commit()
    conn.close()

def clear_old(days: int = 7):
    conn = _get_conn()
    conn.execute("DELETE FROM cache WHERE timestamp < datetime('now', ?)", (f'-{days} days',))
    conn.commit()
    conn.close()
