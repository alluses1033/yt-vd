"""Progress callback system for yt-vd.

Bridges yt-dlp's progress hooks to our ``ProgressInfo`` dataclass, with
thread-safe multi-callback support and rolling speed averaging.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

from constants import DownloadStatus, ProgressInfo

logger = logging.getLogger(__name__)

# Type alias for progress callback functions
ProgressCallback = Callable[[ProgressInfo], None]

# Rolling window size for speed averaging
_SPEED_WINDOW_SIZE = 10


class TerminalProgress:
    """Rich terminal progress renderer for a single download."""

    def __init__(self, console: Any, label: str = "Download") -> None:
        self.console = console
        self.label = label
        self.enabled = bool(getattr(console, "is_terminal", False))
        self._progress: Any | None = None
        self._task_id: Any | None = None

    def __enter__(self) -> ProgressCallback:
        if not self.enabled:
            return self.update

        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
        )

        self._progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("{task.fields[percent]}"),
            TextColumn("{task.fields[size]}"),
            TextColumn("{task.fields[speed]}"),
            TextColumn("ETA {task.fields[eta]}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=False,
            expand=True,
        )
        self._progress.start()
        self._task_id = self._progress.add_task(
            f"{self.label}: preparing...",
            total=None,
            percent="--",
            size="waiting for metadata",
            speed="-- B/s",
            eta="--:--",
        )
        return self.update

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._progress is not None:
            self._progress.stop()

    def update(self, info: ProgressInfo) -> None:
        if not self.enabled or self._progress is None or self._task_id is None:
            return

        title = _truncate(info.title or self.label, 54)
        description = f"{_status_label(info.status)}: {title}"

        total: float | None
        completed: float
        if info.status == DownloadStatus.COMPLETED:
            total = info.total_bytes or 100.0
            completed = total
            percent = "100.0%"
        elif info.total_bytes > 0:
            total = float(info.total_bytes)
            completed = float(info.downloaded_bytes)
            percent = f"{info.percent:5.1f}%"
        elif info.percent > 0:
            total = 100.0
            completed = min(info.percent, 100.0)
            percent = f"{info.percent:5.1f}%"
        else:
            total = None
            completed = 0.0
            percent = "--"

        if info.fragment_count:
            size = f"fragment {info.fragment_index}/{info.fragment_count}"
        else:
            size = info.size_str

        self._progress.update(
            self._task_id,
            description=description,
            completed=completed,
            total=total,
            percent=percent,
            size=size,
            speed=info.speed_str,
            eta=info.eta_str,
        )


class MultiTerminalProgress:
    """Rich terminal progress renderer for parallel downloads in a playlist."""

    def __init__(self, console: Any, titles: list[str]) -> None:
        self.console = console
        self.titles = titles
        self.enabled = bool(getattr(console, "is_terminal", False))
        self._progress: Any | None = None
        self._task_ids: list[Any] = []

    def __enter__(self) -> Callable[[int, ProgressInfo], None]:
        if not self.enabled:
            return self.update

        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
        )

        self._progress = Progress(
            SpinnerColumn(style="yellow"),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("{task.fields[percent]}"),
            TextColumn("{task.fields[size]}"),
            TextColumn("{task.fields[speed]}"),
            TextColumn("ETA {task.fields[eta]}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=False,
            expand=True,
        )
        self._progress.start()

        # Pre-populate tasks for each entry
        for i, title in enumerate(self.titles):
            truncated_title = _truncate(title or f"Video {i+1}", 30)
            task_id = self._progress.add_task(
                f"[yellow]Queued[/]: {truncated_title}",
                total=None,
                percent="--",
                size="queued",
                speed="-- B/s",
                eta="--:--",
            )
            self._task_ids.append(task_id)

        return self.update

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._progress is not None:
            self._progress.stop()

    def update(self, idx: int, info: ProgressInfo) -> None:
        if not self.enabled or self._progress is None or idx >= len(self._task_ids):
            return

        task_id = self._task_ids[idx]
        title = _truncate(info.title or self.titles[idx] or f"Video {idx+1}", 30)
        description = f"{_status_label(info.status)}: {title}"

        total: float | None
        completed: float
        if info.status == DownloadStatus.COMPLETED:
            total = info.total_bytes or 100.0
            completed = total
            percent = "100.0%"
        elif info.total_bytes > 0:
            total = float(info.total_bytes)
            completed = float(info.downloaded_bytes)
            percent = f"{info.percent:5.1f}%"
        elif info.percent > 0:
            total = 100.0
            completed = min(info.percent, 100.0)
            percent = f"{info.percent:5.1f}%"
        else:
            total = None
            completed = 0.0
            percent = "--"

        if info.fragment_count:
            size = f"frag {info.fragment_index}/{info.fragment_count}"
        else:
            size = info.size_str

        self._progress.update(
            task_id,
            description=description,
            completed=completed,
            total=total,
            percent=percent,
            size=size,
            speed=info.speed_str,
            eta=info.eta_str,
        )


class ProgressTracker:
    """Thread-safe progress tracker for a single download.

    Bridges yt-dlp progress hook dictionaries into ``ProgressInfo`` objects
    and dispatches them to registered callbacks (CLI, GUI, or both).

    Attributes:
        video_id: The YouTube video ID being tracked.
        title: The video title being tracked.
    """

    __slots__ = (
        "_callbacks",
        "_lock",
        "_progress",
        "_speed_samples",
        "_start_time",
        "title",
        "video_id",
    )

    def __init__(
        self,
        video_id: str = "",
        title: str = "",
    ) -> None:
        self._lock = threading.Lock()
        self._callbacks: list[ProgressCallback] = []
        self._speed_samples: deque[float] = deque(maxlen=_SPEED_WINDOW_SIZE)
        self._start_time: float = time.monotonic()
        self.video_id = video_id
        self.title = title
        self._progress = ProgressInfo(
            video_id=video_id,
            title=title,
            status=DownloadStatus.QUEUED,
        )

    # ── Callback Registration ────────────────

    def add_callback(self, callback: ProgressCallback) -> None:
        """Register a progress callback.

        Args:
            callback: A callable accepting a ``ProgressInfo`` instance.
        """
        with self._lock:
            self._callbacks.append(callback)

    def remove_callback(self, callback: ProgressCallback) -> None:
        """Remove a previously registered callback.

        Args:
            callback: The callback to remove.
        """
        with self._lock:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

    # ── Progress Updates ─────────────────────

    def update(self, data: dict[str, Any]) -> None:
        """Process a yt-dlp progress hook dictionary.

        This is the main entry point called from the yt-dlp hook.
        Extracts relevant fields, computes rolling speed average,
        and fires all registered callbacks.

        Args:
            data: The progress dictionary from yt-dlp's ``progress_hooks``.
        """
        with self._lock:
            status_str = data.get("status", "")
            hook_info = data.get("info_dict") or {}

            if not self.title:
                hook_title = hook_info.get("title") if isinstance(hook_info, dict) else None
                if hook_title:
                    self.title = str(hook_title)
                elif filename := data.get("filename") or data.get("tmpfilename"):
                    self.title = Path(str(filename)).name

            if not self.video_id and isinstance(hook_info, dict):
                self.video_id = str(hook_info.get("id") or "")

            match status_str:
                case "downloading":
                    self._progress.status = DownloadStatus.DOWNLOADING
                case "finished":
                    self._progress.status = DownloadStatus.PROCESSING
                case "error":
                    self._progress.status = DownloadStatus.FAILED
                case _:
                    pass  # keep current status

            # Downloaded / total bytes
            self._progress.downloaded_bytes = _safe_int(
                data.get("downloaded_bytes", self._progress.downloaded_bytes)
            )
            self._progress.total_bytes = _safe_int(
                data.get("total_bytes")
                or data.get("total_bytes_estimate")
                or self._progress.total_bytes
            )

            # Speed — add to rolling window and average
            raw_speed = data.get("speed")
            if raw_speed is not None and raw_speed > 0:
                self._speed_samples.append(float(raw_speed))
            if self._speed_samples:
                self._progress.speed = sum(self._speed_samples) / len(self._speed_samples)

            # ETA
            raw_eta = data.get("eta")
            if raw_eta is not None:
                self._progress.eta = float(raw_eta)

            # Fragment tracking
            if (fi := data.get("fragment_index")) is not None:
                self._progress.fragment_index = int(fi)
            if (fc := data.get("fragment_count")) is not None:
                self._progress.fragment_count = int(fc)

            # Percent — prefer yt-dlp's computed value, else derive
            if self._progress.total_bytes > 0:
                self._progress.percent = min(
                    100.0,
                    (self._progress.downloaded_bytes / self._progress.total_bytes) * 100.0,
                )
            elif self._progress.fragment_count > 0:
                self._progress.percent = min(
                    100.0,
                    (self._progress.fragment_index / self._progress.fragment_count) * 100.0,
                )

            # Elapsed time
            self._progress.elapsed = time.monotonic() - self._start_time

            # Ensure title / video_id stay in sync
            self._progress.video_id = self.video_id
            self._progress.title = self.title

            # Snapshot for callbacks (avoid holding the lock)
            snapshot = ProgressInfo(
                video_id=self._progress.video_id,
                title=self._progress.title,
                status=self._progress.status,
                downloaded_bytes=self._progress.downloaded_bytes,
                total_bytes=self._progress.total_bytes,
                speed=self._progress.speed,
                eta=self._progress.eta,
                percent=self._progress.percent,
                fragment_index=self._progress.fragment_index,
                fragment_count=self._progress.fragment_count,
                elapsed=self._progress.elapsed,
            )
            callbacks = list(self._callbacks)

        # Fire callbacks outside the lock
        for cb in callbacks:
            try:
                cb(snapshot)
            except Exception:
                logger.exception("Error in progress callback %r", cb)

    def set_status(self, status: DownloadStatus) -> None:
        """Manually set the download status and fire callbacks.

        Args:
            status: The new status to set.
        """
        with self._lock:
            self._progress.status = status
            self._progress.elapsed = time.monotonic() - self._start_time
            self._progress.video_id = self.video_id
            self._progress.title = self.title
            snapshot = ProgressInfo(
                video_id=self._progress.video_id,
                title=self._progress.title,
                status=status,
                downloaded_bytes=self._progress.downloaded_bytes,
                total_bytes=self._progress.total_bytes,
                speed=self._progress.speed,
                eta=self._progress.eta,
                percent=self._progress.percent,
                fragment_index=self._progress.fragment_index,
                fragment_count=self._progress.fragment_count,
                elapsed=self._progress.elapsed,
            )
            callbacks = list(self._callbacks)

        for cb in callbacks:
            try:
                cb(snapshot)
            except Exception:
                logger.exception("Error in progress callback %r", cb)

    @property
    def current(self) -> ProgressInfo:
        """Get a snapshot of the current progress state."""
        with self._lock:
            return ProgressInfo(
                video_id=self._progress.video_id,
                title=self._progress.title,
                status=self._progress.status,
                downloaded_bytes=self._progress.downloaded_bytes,
                total_bytes=self._progress.total_bytes,
                speed=self._progress.speed,
                eta=self._progress.eta,
                percent=self._progress.percent,
                fragment_index=self._progress.fragment_index,
                fragment_count=self._progress.fragment_count,
                elapsed=self._progress.elapsed,
            )

    def reset(self) -> None:
        """Reset the tracker to initial state for reuse."""
        with self._lock:
            self._speed_samples.clear()
            self._start_time = time.monotonic()
            self._progress = ProgressInfo(
                video_id=self.video_id,
                title=self.title,
                status=DownloadStatus.QUEUED,
            )


# ──────────────────────────────────────────────
# yt-dlp Hook Factory
# ──────────────────────────────────────────────

def make_progress_hook(tracker: ProgressTracker) -> Callable[[dict[str, Any]], None]:
    """Create a yt-dlp-compatible progress hook function.

    The returned function can be passed directly to
    ``YoutubeDL(params={'progress_hooks': [hook]})``.

    Args:
        tracker: The ``ProgressTracker`` instance to feed updates to.

    Returns:
        A callable suitable for yt-dlp's ``progress_hooks`` parameter.
    """

    def _hook(d: dict[str, Any]) -> None:
        tracker.update(d)

    return _hook


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _safe_int(value: Any) -> int:
    """Safely convert a value to int, returning 0 on failure."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _status_label(status: DownloadStatus) -> str:
    return {
        DownloadStatus.QUEUED: "Queued",
        DownloadStatus.DOWNLOADING: "Downloading",
        DownloadStatus.PROCESSING: "Processing",
        DownloadStatus.COMPLETED: "Complete",
        DownloadStatus.FAILED: "Failed",
        DownloadStatus.SKIPPED: "Skipped",
    }.get(status, "Working")


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
