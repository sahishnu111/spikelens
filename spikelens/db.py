"""Tiny SQLite persistence layer (stdlib sqlite3, WAL mode)."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    detector TEXT NOT NULL DEFAULT 'robust_z',
    threshold REAL NOT NULL DEFAULT 4.0,
    win INTEGER NOT NULL DEFAULT 60,
    webhook_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id INTEGER NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    value REAL NOT NULL,
    score REAL NOT NULL,
    is_anomaly INTEGER NOT NULL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_points_stream ON points(stream_id, id);
"""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class Database:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.environ.get("SPIKELENS_DB", "spikelens.db")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._conn:
            yield self._conn

    def create_stream(self, name: str, detector: str, threshold: float, window: int,
                      webhook_url: str | None) -> tuple[int, str]:
        key = "sk_" + secrets.token_urlsafe(24)
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO streams(name, key_hash, detector, threshold, win, webhook_url) VALUES (?,?,?,?,?,?)",
                (name, hash_key(key), detector, threshold, window, webhook_url),
            )
        return int(cur.lastrowid), key

    def stream_by_key(self, key: str) -> sqlite3.Row | None:
        with self.tx() as c:
            return c.execute("SELECT * FROM streams WHERE key_hash=?", (hash_key(key),)).fetchone()

    def stream(self, stream_id: int) -> sqlite3.Row | None:
        with self.tx() as c:
            return c.execute("SELECT * FROM streams WHERE id=?", (stream_id,)).fetchone()

    def add_points(self, stream_id: int, rows: list[tuple[str, float, float, bool, str | None]]) -> None:
        with self.tx() as c:
            c.executemany(
                "INSERT INTO points(stream_id, ts, value, score, is_anomaly, reason) VALUES (?,?,?,?,?,?)",
                [(stream_id, ts, v, s, int(a), r) for ts, v, s, a, r in rows],
            )

    def points(self, stream_id: int, limit: int = 5000) -> list[sqlite3.Row]:
        with self.tx() as c:
            rows = c.execute(
                "SELECT ts, value, score, is_anomaly, reason FROM points WHERE stream_id=? ORDER BY id DESC LIMIT ?",
                (stream_id, limit),
            ).fetchall()
        return rows[::-1]
