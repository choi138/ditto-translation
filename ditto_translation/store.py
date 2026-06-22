from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path

from ditto_translation.models import EventStart


class TranslationStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def begin_event(self, event_key: str, *, stale_after_seconds: int) -> EventStart:
        now = time.time()
        stale_before = now - stale_after_seconds
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO processed_events
                    (event_key, status, attempts, created_at, updated_at)
                VALUES (?, 'in_progress', 1, ?, ?)
                """,
                (event_key, now, now),
            )
            if cursor.rowcount == 1:
                self._connection.commit()
                return EventStart.STARTED

            cursor = self._connection.execute(
                """
                UPDATE processed_events
                SET status = 'in_progress',
                    attempts = attempts + 1,
                    last_error = NULL,
                    updated_at = ?
                WHERE event_key = ?
                  AND (
                    status = 'failed'
                    OR (status = 'in_progress' AND updated_at < ?)
                  )
                """,
                (now, event_key, stale_before),
            )
            if cursor.rowcount == 1:
                self._connection.commit()
                return EventStart.RETRY_STARTED

            row = self._connection.execute(
                "SELECT status FROM processed_events WHERE event_key = ?",
                (event_key,),
            ).fetchone()
            self._connection.commit()

            if row is not None and str(row["status"]) == "in_progress":
                return EventStart.IN_PROGRESS

            return EventStart.DUPLICATE

    def finish_event(self, event_key: str, *, status: str = "succeeded") -> None:
        now = time.time()
        with self._lock:
            self._connection.execute(
                """
                UPDATE processed_events
                SET status = ?, updated_at = ?, last_error = NULL
                WHERE event_key = ?
                """,
                (status, now, event_key),
            )
            self._connection.commit()

    def fail_event(self, event_key: str, error: str) -> None:
        now = time.time()
        with self._lock:
            self._connection.execute(
                """
                UPDATE processed_events
                SET status = 'failed', last_error = ?, updated_at = ?
                WHERE event_key = ?
                """,
                (error[:1000], now, event_key),
            )
            self._connection.commit()

    def remember_outbound_update(
        self,
        *,
        project_id: str,
        developer_id: str,
        locale: str,
        text: str,
        ttl_seconds: int,
    ) -> None:
        now = time.time()
        expires_at = now + ttl_seconds
        text_hash = _text_hash(text)
        with self._lock:
            self._delete_expired_outbound_updates(now)
            self._connection.execute(
                """
                INSERT INTO outbound_updates
                    (project_id, developer_id, locale, text_hash, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, developer_id, locale, text_hash)
                DO UPDATE SET expires_at = excluded.expires_at
                """,
                (project_id, developer_id, locale, text_hash, expires_at, now),
            )
            self._connection.commit()

    def consume_outbound_update(
        self,
        *,
        project_id: str,
        developer_id: str,
        locale: str,
        text: str,
    ) -> bool:
        now = time.time()
        text_hash = _text_hash(text)
        with self._lock:
            self._delete_expired_outbound_updates(now)
            row = self._connection.execute(
                """
                SELECT id
                FROM outbound_updates
                WHERE project_id = ?
                  AND developer_id = ?
                  AND locale = ?
                  AND text_hash = ?
                  AND expires_at > ?
                LIMIT 1
                """,
                (project_id, developer_id, locale, text_hash, now),
            ).fetchone()
            if row is None:
                self._connection.commit()
                return False

            self._connection.commit()
            return True

    def forget_outbound_update(
        self,
        *,
        project_id: str,
        developer_id: str,
        locale: str,
        text: str,
    ) -> None:
        text_hash = _text_hash(text)
        with self._lock:
            self._connection.execute(
                """
                DELETE FROM outbound_updates
                WHERE project_id = ?
                  AND developer_id = ?
                  AND locale = ?
                  AND text_hash = ?
                """,
                (project_id, developer_id, locale, text_hash),
            )
            self._connection.commit()

    def _initialize(self) -> None:
        with self._lock:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_events (
                    event_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS outbound_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    developer_id TEXT NOT NULL,
                    locale TEXT NOT NULL,
                    text_hash TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(project_id, developer_id, locale, text_hash)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_outbound_updates_lookup
                ON outbound_updates(project_id, developer_id, locale, text_hash, expires_at)
                """
            )
            self._connection.commit()

    def _delete_expired_outbound_updates(self, now: float) -> None:
        self._connection.execute("DELETE FROM outbound_updates WHERE expires_at <= ?", (now,))


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
