"""Playlist and channel download handling for yt-vd."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from constants import (
    DEFAULT_PARALLEL_WORKERS,
    DownloadResult,
    PlaylistInfo,
)
from core.downloader import extract_info
from core.parallel import download_parallel

logger = logging.getLogger(__name__)


def get_playlist_info(url: str) -> PlaylistInfo | None:
    """Fetch playlist info (flat extraction for speed)."""
    try:
        info = extract_info(url, flat=True)

        # Parse entries
        entries_raw = info.get("entries") or []
        entries = []
        total_duration = 0.0

        for entry in entries_raw:
            if entry:
                entries.append(entry)
                total_duration += float(entry.get("duration") or 0.0)

        return PlaylistInfo(
            title=info.get("title", "Unknown Playlist"),
            uploader=info.get("uploader") or info.get("uploader_id") or "Unknown Uploader",
            url=info.get("webpage_url") or url,
            video_count=len(entries),
            entries=entries,
            description=info.get("description", ""),
            total_duration=total_duration,
        )
    except Exception as e:
        logger.error("Failed to fetch playlist info for %s: %s", url, e)
        raise e



def download_playlist(
    url: str,
    *,
    quality: str = "best",
    fmt: str = "mp4",
    output_dir: str | Path = ".",
    start: int = 1,
    end: int | None = None,
    parallel: int = DEFAULT_PARALLEL_WORKERS,
    **kwargs: Any,
) -> list[DownloadResult]:
    """Download a playlist's videos in parallel.

    Supports sequential numbering (done in parallel.py via prefixing index).
    """
    logger.info("Fetching playlist metadata for downloading: %s", url)
    info = get_playlist_info(url)
    if not info or not info.entries:
        logger.warning("No entries found in playlist: %s", url)
        return []

    # Slice entries based on 1-based start and end indices
    start_idx = max(0, start - 1)
    end_idx = end if end is not None else len(info.entries)
    sliced_entries = info.entries[start_idx:end_idx]

    logger.info(
        "Downloading playlist range %d to %d (total %d selected entries)",
        start_idx + 1,
        end_idx,
        len(sliced_entries),
    )

    # Call parallel downloader
    from core.utils import sanitize_filename
    playlist_folder = sanitize_filename(info.title)
    final_output_dir = Path(output_dir) / playlist_folder

    results = download_parallel(
        sliced_entries,
        quality=quality,
        fmt=fmt,
        workers=parallel,
        output_dir=final_output_dir,
        playlist_title=info.title,
        **kwargs,
    )
    return results


def download_channel(
    url: str,
    *,
    last_n: int = 10,
    quality: str = "best",
    fmt: str = "mp4",
    output_dir: str | Path = ".",
    parallel: int = DEFAULT_PARALLEL_WORKERS,
    **kwargs: Any,
) -> list[DownloadResult]:
    """Download the most recent N videos from a YouTube channel."""
    logger.info("Fetching channel uploads metadata: %s", url)

    # In yt-dlp, channels are handled like playlists. Extract flat entries.
    info = get_playlist_info(url)
    if not info or not info.entries:
        logger.warning("No uploads found for channel: %s", url)
        return []

    # Get the last N uploaded videos
    selected_entries = info.entries[:last_n]
    logger.info(
        "Downloading last %d videos from channel %s in parallel",
        len(selected_entries),
        info.title,
    )

    from core.utils import sanitize_filename
    channel_folder = sanitize_filename(info.title)
    final_output_dir = Path(output_dir) / channel_folder

    results = download_parallel(
        selected_entries,
        quality=quality,
        fmt=fmt,
        workers=parallel,
        output_dir=final_output_dir,
        playlist_title=info.title,
        **kwargs,
    )
    return results
