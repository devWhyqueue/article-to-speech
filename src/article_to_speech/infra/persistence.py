from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from article_to_speech.core.models import IncomingUrlJob, JobStatus


def _to_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._lock = Lock()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path)
        try:
            connection.row_factory = sqlite3.Row
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the SQLite schema used for queued and completed jobs."""
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER,
                    input_url TEXT NOT NULL,
                    canonical_url TEXT,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    audio_path TEXT,
                    article_title TEXT,
                    article_source TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source
                ON jobs(chat_id, message_id, input_url);
                """
            )

    def enqueue(self, chat_id: int, message_id: int | None, input_url: str) -> IncomingUrlJob:
        """Insert or retrieve a job for the given Telegram message and URL."""
        now = _utc_now_text()
        with self._lock, self._connect() as connection:
            row = self._insert_or_fetch_job(connection, chat_id, message_id, input_url, now)
            return self._row_to_job(row)

    def mark_processing(self, job_id: int, canonical_url: str | None) -> IncomingUrlJob:
        """Mark a job as in-flight and increment its attempt counter."""
        now = _utc_now_text()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET updated_at = ?,
                    status = ?,
                    attempts = attempts + 1,
                    canonical_url = COALESCE(?, canonical_url)
                WHERE id = ?
                """,
                (now, JobStatus.PROCESSING.value, canonical_url, job_id),
            )
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert row is not None
        return self._row_to_job(row)

    def mark_failed(self, job_id: int, error_message: str) -> None:
        """Persist a terminal failure for a job."""
        now = _utc_now_text()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET updated_at = ?, status = ?, last_error = ?
                WHERE id = ?
                """,
                (now, JobStatus.FAILED.value, error_message, job_id),
            )

    def mark_succeeded(
        self,
        job_id: int,
        canonical_url: str,
        article_title: str,
        article_source: str | None,
        audio_path: str,
    ) -> None:
        """Persist the successful output metadata for a completed job."""
        now = _utc_now_text()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET updated_at = ?,
                    status = ?,
                    canonical_url = ?,
                    article_title = ?,
                    article_source = ?,
                    audio_path = ?
                WHERE id = ?
                """,
                (
                    now,
                    JobStatus.SUCCEEDED.value,
                    canonical_url,
                    article_title,
                    article_source,
                    audio_path,
                    job_id,
                ),
            )

    def _insert_or_fetch_job(
        self,
        connection: sqlite3.Connection,
        chat_id: int,
        message_id: int | None,
        input_url: str,
        now: str,
    ) -> sqlite3.Row:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO jobs (
                created_at,
                updated_at,
                chat_id,
                message_id,
                input_url,
                status,
                attempts
            ) VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (now, now, chat_id, message_id, input_url, JobStatus.QUEUED.value),
        )
        if cursor.lastrowid == 0:
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE chat_id = ? AND message_id IS ? AND input_url = ?
                """,
                (chat_id, message_id, input_url),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        assert row is not None
        return row

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> IncomingUrlJob:
        return IncomingUrlJob(
            job_id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            message_id=int(row["message_id"]) if row["message_id"] is not None else None,
            input_url=str(row["input_url"]),
            created_at=_to_datetime(str(row["created_at"])),
            status=JobStatus(str(row["status"])),
            attempts=int(row["attempts"]),
            canonical_url=str(row["canonical_url"]) if row["canonical_url"] else None,
            last_error=str(row["last_error"]) if row["last_error"] else None,
        )
