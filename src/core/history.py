"""SQLite download history for yt-vd.

Thread-safe history storage using SQLite, with context-managed connections
and query utilities for tracking past downloads.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import platformdirs

from constants import (
    APP_AUTHOR,
    APP_NAME,
    HISTORY_DB_NAME,
    DownloadResult,
    DownloadStatus,
)

logger = logging.getLogger(__name__)

# Precompile video ID extraction pattern globally for performance
_VIDEO_ID_PATTERN = re.compile(r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})")

# ──────────────────────────────────────────────
# Database Schema
# ──────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS download_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT    NOT NULL,
    video_id        TEXT    NOT NULL DEFAULT '',
    title           TEXT    NOT NULL DEFAULT '',
    quality         TEXT    NOT NULL DEFAULT '',
    format          TEXT    NOT NULL DEFAULT '',
    file_path       TEXT    NOT NULL DEFAULT '',
    file_size       INTEGER NOT NULL DEFAULT 0,
    duration        REAL    NOT NULL DEFAULT 0.0,
    downloaded_at   TEXT    NOT NULL DEFAULT ''
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_history_url ON download_history (url);
CREATE INDEX IF NOT EXISTS idx_history_video_id ON download_history (video_id);
CREATE INDEX IF NOT EXISTS idx_history_downloaded_at ON download_history (downloaded_at);
"""


class DownloadHistory:
    """Thread-safe SQLite-backed download history.

    The database is stored in the platform-appropriate user data directory
    (``platformdirs.user_data_dir('yt-vd')/download_history.db``).

    Usage::

        history = DownloadHistory()
        history.add(result)
        recent = history.get_all(limit=10)
        if history.exists("https://youtu.be/abc123"):
            print("Already downloaded!")
    """

    __slots__ = ("_db_path", "_lock")

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialize the history manager.

        Args:
            db_path: Override path for the database file.  If ``None``,
                     uses the default platform data directory.
        """
        if db_path is not None:
            self._db_path = Path(db_path)
        else:
            data_dir = Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
            self._db_path = data_dir / HISTORY_DB_NAME

        self._lock = threading.Lock()
        self._initialize_db()

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database file."""
        return self._db_path

    # ── Context-Managed Connections ──────────

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a thread-safe SQLite connection with WAL mode.

        Uses context manager pattern for automatic commit/rollback.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(
            str(self._db_path),
            timeout=10,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize_db(self) -> None:
        """Create the database tables and indexes if they don't exist."""
        with self._lock, self._connect() as conn:
            conn.executescript(_CREATE_TABLE_SQL + _CREATE_INDEX_SQL)
            logger.debug("History database initialized at %s", self._db_path)

    # ── Public API ───────────────────────────

    def add(self, result: DownloadResult) -> int:
        """Log a completed download to history.

        Only adds entries with COMPLETED status.

        Args:
            result: The download result to record.

        Returns:
            The row ID of the inserted record, or -1 if skipped.
        """
        if result.status != DownloadStatus.COMPLETED:
            logger.debug("Skipping non-completed download: %s", result.url)
            return -1

        # Extract video_id from URL (best effort)
        video_id = _extract_video_id(result.url)

        now = datetime.now(UTC).isoformat()

        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO download_history
                    (url, video_id, title, quality, format, file_path, file_size, duration, downloaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.url,
                    video_id,
                    result.title,
                    result.quality,
                    result.format,
                    str(result.file_path) if result.file_path else "",
                    result.file_size,
                    result.duration,
                    now,
                ),
            )
            row_id = cursor.lastrowid or -1
            logger.info("Added to history: %s (id=%d)", result.title, row_id)
            return row_id

    def get_all(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Retrieve recent download history entries.

        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip (for pagination).

        Returns:
            List of dicts representing history rows, newest first.
        """
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT id, url, video_id, title, quality, format,
                       file_path, file_size, duration, downloaded_at
                FROM download_history
                ORDER BY downloaded_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            return [dict(row) for row in cursor.fetchall()]
    def exists(self, url: str) -> bool:
        """Check if a URL has been previously downloaded.

        Args:
            url: The YouTube URL to check.

        Returns:
            True if the URL exists in history.
        """
        video_id = _extract_video_id(url)

        with self._lock, self._connect() as conn:
            if video_id:
                cursor = conn.execute(
                    """
                    SELECT 1 FROM download_history
                    WHERE url = ? OR video_id = ?
                    LIMIT 1
                    """,
                    (url, video_id),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT 1 FROM download_history
                    WHERE url = ?
                    LIMIT 1
                    """,
                    (url,),
                )
            return cursor.fetchone() is not None

    def clear(self) -> int:
        """Delete all history records.

        Returns:
            The number of deleted records.
        """
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM download_history")
            count = cursor.rowcount
            logger.info("Cleared %d history records", count)
            return count

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate download statistics.

        Returns:
            A dict containing:
            - ``total_downloads``: Total number of completed downloads.
            - ``total_size``: Total bytes downloaded.
            - ``total_duration``: Total video duration in seconds.
            - ``first_download``: ISO timestamp of the first download.
            - ``last_download``: ISO timestamp of the most recent download.
        """
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*)            AS total_downloads,
                    COALESCE(SUM(file_size), 0)  AS total_size,
                    COALESCE(SUM(duration), 0.0) AS total_duration,
                    MIN(downloaded_at)  AS first_download,
                    MAX(downloaded_at)  AS last_download
                FROM download_history
                """
            )
            row = cursor.fetchone()
            if row is None:
                return {
                    "total_downloads": 0,
                    "total_count": 0,
                    "total_size": 0,
                    "total_duration": 0.0,
                    "first_download": None,
                    "last_download": None,
                }
            res = dict(row)
            res["total_count"] = res["total_downloads"]
            return res

    def delete(self, record_id: int) -> bool:
        """Delete a single history record by ID.

        Args:
            record_id: The row ID to delete.

        Returns:
            True if a record was deleted.
        """
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM download_history WHERE id = ?",
                (record_id,),
            )
            return cursor.rowcount > 0

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search history by title or URL.

        Args:
            query: Search string (matched with SQL LIKE).
            limit: Maximum results.

        Returns:
            Matching history records.
        """
        like_query = f"%{query}%"
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT id, url, video_id, title, quality, format,
                       file_path, file_size, duration, downloaded_at
                FROM download_history
                WHERE title LIKE ? OR url LIKE ?
                ORDER BY downloaded_at DESC
                LIMIT ?
                """,
                (like_query, like_query, limit),
            )
            return [dict(row) for row in cursor.fetchall()]


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _extract_video_id(url: str) -> str:
    """Extract the YouTube video ID from a URL.

    Handles standard, short, and embed URL formats.

    Args:
        url: A YouTube URL.

    Returns:
        The video ID string, or an empty string if extraction fails.
    """
    if match := _VIDEO_ID_PATTERN.search(url):
        return match.group(1)
    return ""


# ──────────────────────────────────────────────
# Global Shared History Helper Functions
# ──────────────────────────────────────────────

_default_history: DownloadHistory | None = None


def _get_history_manager() -> DownloadHistory:
    global _default_history
    if _default_history is None:
        _default_history = DownloadHistory()
    return _default_history


def get_history(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Retrieve recent download history entries using the default manager.

    Args:
        limit: Maximum number of records to return.
        offset: Number of records to skip.

    Returns:
        List of dicts representing history rows, newest first.
    """
    return _get_history_manager().get_all(limit=limit, offset=offset)


def clear_history() -> int:
    """Delete all history records from the default manager.

    Returns:
        The number of deleted records.
    """
    return _get_history_manager().clear()


def add_to_history(result: DownloadResult) -> int:
    """Log a completed download to the default history manager.

    Args:
        result: The download result to record.

    Returns:
        The row ID of the inserted record, or -1 if skipped.
    """
    return _get_history_manager().add(result)
