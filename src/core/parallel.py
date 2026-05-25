"""CPU-aware parallel download manager for yt-vd."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from constants import (
    DEFAULT_PARALLEL_WORKERS,
    DownloadResult,
    DownloadStatus,
    ProgressInfo,
)
from core.downloader import download_video

logger = logging.getLogger(__name__)


def download_batch(
    urls: list[str],
    *,
    quality: str = "best",
    fmt: str = "mp4",
    output_dir: str | Path = ".",
    parallel: int = DEFAULT_PARALLEL_WORKERS,
    verbose: bool = False,
    **kwargs: Any,
) -> list[DownloadResult]:
    """Download a list of URLs in parallel.

    Each download runs in its own worker thread with its own progress tracking.

    Args:
        urls: List of YouTube video URLs.
        quality: Quality preset or resolution.
        fmt: Container format.
        output_dir: Destination directory.
        parallel: Number of parallel workers.
        verbose: Verbose output.
        kwargs: Additional options.

    Returns:
        List of DownloadResult objects.
    """
    results: list[DownloadResult] = []
    if not urls:
        return results

    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    workers = min(max(1, parallel), len(urls))
    logger.info("Starting batch download of %d videos with %d workers", len(urls), workers)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                download_video,
                url,
                output_dir=output_dir,
                quality=quality,
                video_format=fmt,
                verbose=verbose,
                **kwargs,
            ): url
            for url in urls
        }

        try:
            for future in as_completed(futures):
                url = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error("Error downloading %s: %s", url, e)
                    results.append(
                        DownloadResult(
                            url=url,
                            status=DownloadStatus.FAILED,
                            error_message=str(e),
                        )
                    )
        except KeyboardInterrupt:
            logger.warning("Batch download interrupted by user. Cancelling pending tasks...")
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            from core.fragment_safety import SafeDownloadManager
            SafeDownloadManager(output_dir).cleanup_temp()
            raise

    return results


def download_parallel(
    entries: list[dict[str, Any]],
    *,
    quality: str = "best",
    fmt: str = "mp4",
    workers: int = DEFAULT_PARALLEL_WORKERS,
    output_dir: str | Path = ".",
    playlist_title: str = "",
    on_video_done: Callable[[int, DownloadResult], None] | None = None,
    on_progress: Callable[[int, ProgressInfo], None] | None = None,
    **kwargs: Any,
) -> list[DownloadResult]:
    """Download playlist entries in parallel.

    Each entry contains metadata like 'url' or 'id'.
    Progress for each worker is reported via on_progress.

    Args:
        entries: List of playlist entry dicts.
        quality: Quality preset.
        fmt: Container format.
        workers: Thread count.
        output_dir: Output directory.
        playlist_title: Title of the playlist.
        on_video_done: Callback for individual video completions.
        on_progress: Progress update callback.
        kwargs: Additional options.

    Returns:
        List of DownloadResult objects.
    """
    results: list[DownloadResult] = [DownloadResult(url="") for _ in entries]
    if not entries:
        return []

    # Ensure output directory exists
    dest_dir = Path(output_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    worker_count = min(max(1, workers), len(entries))
    logger.info("Downloading %d playlist entries with %d workers", len(entries), worker_count)

    def download_worker(idx: int, entry: dict[str, Any]) -> DownloadResult:
        video_url = entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={entry.get('id')}"

        # Build index prefix
        index_prefix = f"{idx + 1:03d} - "
        output_template = f"{index_prefix}%(title)s.%(ext)s"

        def progress_callback(info: ProgressInfo) -> None:
            if on_progress:
                on_progress(idx, info)

        # Single video download
        worker_kwargs = kwargs.copy()
        worker_kwargs.pop("progress_callback", None)

        result = download_video(
            video_url,
            output_dir=dest_dir,
            quality=quality,
            video_format=fmt,
            output_template=output_template,
            progress_callback=progress_callback,
            **worker_kwargs,
        )

        if on_video_done:
            on_video_done(idx, result)

        return result

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(download_worker, idx, entry): idx
            for idx, entry in enumerate(entries)
        }

        try:
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    logger.error("Worker error downloading index %d: %s", idx, e)
                    results[idx] = DownloadResult(
                        url="",
                        status=DownloadStatus.FAILED,
                        error_message=str(e),
                    )
                    if on_video_done:
                        on_video_done(idx, results[idx])
        except KeyboardInterrupt:
            logger.warning("Parallel download interrupted by user. Cancelling pending tasks...")
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            from core.fragment_safety import SafeDownloadManager
            SafeDownloadManager(dest_dir).cleanup_temp()
            raise

    return results
