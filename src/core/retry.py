"""Shared retry utility for downloading and extraction in yt-vd."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from constants import RETRY_BACKOFF_FACTOR, DownloadStatus

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_operation[T](
    func: Callable[[], T],
    max_retries: int,
    shutdown_event: Any,
    tracker: Any,
    safety: Any,
    label: str = "Download",
    retriable_checker: Callable[[Exception], bool] | None = None,
) -> T:
    """Execute an operation with exponential backoff retry.

    Args:
        func: Callback function to execute.
        max_retries: Maximum number of attempts.
        shutdown_event: Optional Event to check for user cancellation.
        tracker: ProgressTracker to update status.
        safety: SafeDownloadManager for temp file cleanup.
        label: Name of the operation for logging.
        retriable_checker: Optional callback to filter which exceptions trigger a retry.

    Returns:
        The result of the callback function.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        if shutdown_event and shutdown_event.is_set():
            raise KeyboardInterrupt("Cancelled")
        try:
            tracker.set_status(DownloadStatus.DOWNLOADING)
            return func()
        except KeyboardInterrupt:
            logger.warning("%s interrupted by user.", label)
            safety.cleanup_temp()
            tracker.set_status(DownloadStatus.FAILED)
            raise
        except Exception as e:
            last_error = e
            is_retriable = True
            if retriable_checker:
                is_retriable = retriable_checker(e)

            if attempt < max_retries and is_retriable:
                wait = RETRY_BACKOFF_FACTOR ** attempt
                logger.warning(
                    "%s attempt %d/%d failed: %s — retrying in %.0fs",
                    label,
                    attempt,
                    max_retries,
                    e,
                    wait,
                )
                if shutdown_event:
                    shutdown_event.wait(timeout=wait)
                else:
                    time.sleep(wait)
            else:
                break

    raise last_error if last_error else RuntimeError(f"{label} failed")
