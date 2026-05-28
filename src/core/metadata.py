"""Metadata, thumbnails, chapters, and SponsorBlock for yt-vd.

Provides video info extraction, thumbnail downloading, chapter-based
splitting, and formatted display preparation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yt_dlp

from constants import (
    DownloadResult,
    DownloadStatus,
    VideoInfo,
)
from core.downloader import build_ydl_opts, extract_info
from core.progress import ProgressCallback, ProgressTracker, make_progress_hook
from core.utils import normalize_youtube_thumbnail_url

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Video Info Extraction
# ──────────────────────────────────────────────

def get_video_info(url: str) -> VideoInfo:
    """Extract detailed metadata for a YouTube video.

    Performs a fast extraction without downloading the video.

    Args:
        url: YouTube video URL.

    Returns:
        A populated ``VideoInfo`` dataclass.

    Raises:
        yt_dlp.utils.DownloadError: If extraction fails.
    """
    info = extract_info(url)

    # Build available qualities list
    formats: list[dict[str, Any]] = info.get("formats") or []
    heights: set[int] = set()
    for fmt in formats:
        if fmt.get("vcodec", "none") != "none" and (h := fmt.get("height")):
            heights.add(h)

    available_qualities = [f"{h}p" for h in sorted(heights, reverse=True)]

    # Extract chapters
    chapters: list[dict[str, Any]] = info.get("chapters") or []

    # Approximate file size (sum of best video + best audio)
    file_size_approx = _estimate_file_size(formats)

    # Parse thumbnail url: sort by resolution descending to get highest quality
    thumb = None
    if info.get("thumbnails"):
        thumbs = info.get("thumbnails")
        if isinstance(thumbs, list) and len(thumbs) > 0:
            def get_res(t: dict[str, Any]) -> int:
                w = t.get("width") or 0
                h = t.get("height") or 0
                return w * h
            sorted_thumbs = sorted(thumbs, key=get_res, reverse=True)
            if sorted_thumbs:
                thumb = sorted_thumbs[0].get("url")
    if not thumb:
        thumb = info.get("thumbnail", "")

    thumb = normalize_youtube_thumbnail_url(thumb or "")

    return VideoInfo(
        title=info.get("title", "Unknown"),
        url=info.get("webpage_url", url),
        video_id=info.get("id", ""),
        uploader=info.get("uploader", "Unknown"),
        duration=float(info.get("duration") or 0.0),
        view_count=int(info.get("view_count") or 0),
        upload_date=info.get("upload_date", ""),
        description=info.get("description", ""),
        thumbnail_url=thumb,
        formats=formats,
        available_qualities=available_qualities,
        chapters=chapters,
        subtitles=info.get("subtitles") or {},
        file_size_approx=file_size_approx,
    )


# ──────────────────────────────────────────────
# Chapters
# ──────────────────────────────────────────────

def get_chapters(url: str) -> list[dict[str, Any]]:
    """Extract the chapter list from a YouTube video.

    Args:
        url: YouTube video URL.

    Returns:
        List of chapter dicts, each containing ``title``, ``start_time``,
        and ``end_time`` (in seconds).  Empty list if no chapters.
    """
    info = extract_info(url)
    raw_chapters: list[dict[str, Any]] = info.get("chapters") or []

    chapters: list[dict[str, Any]] = []
    for ch in raw_chapters:
        chapters.append({
            "title": ch.get("title", "Untitled Chapter"),
            "start_time": float(ch.get("start_time", 0)),
            "end_time": float(ch.get("end_time", 0)),
            "duration": float(ch.get("end_time", 0)) - float(ch.get("start_time", 0)),
        })

    return chapters


def download_by_chapters(
    url: str,
    *,
    output_dir: str | Path = ".",
    quality: str = "best",
    video_format: str = "mp4",
    progress_callback: ProgressCallback | None = None,
    verbose: bool = False,
    **kwargs: Any,
) -> list[DownloadResult]:
    """Download a video split by its chapters.

    Each chapter is saved as a separate file named
    ``{index:02d} - {chapter_title}.{ext}``.

    Args:
        url: YouTube video URL.
        output_dir: Destination directory.
        quality: Quality preset or resolution.
        video_format: Output container format.
        progress_callback: Optional progress callback.
        verbose: Enable verbose logging.
        kwargs: Additional arguments.

    Returns:
        List of ``DownloadResult`` objects, one per chapter.
    """
    video_format = kwargs.pop("fmt", video_format)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    chapters = get_chapters(url)
    if not chapters:
        logger.warning("No chapters found for %s — downloading full video", url)
        from core.downloader import download_video

        result = download_video(
            url,
            output_dir=output_dir,
            quality=quality,
            video_format=video_format,
            progress_callback=progress_callback,
        )
        return [result]

    results: list[DownloadResult] = []

    for i, chapter in enumerate(chapters, start=1):
        chapter_title = chapter["title"]
        start = chapter["start_time"]
        end = chapter["end_time"]

        logger.info("Downloading chapter %d/%d: %s", i, len(chapters), chapter_title)

        tracker = ProgressTracker(title=chapter_title)
        if progress_callback:
            tracker.add_callback(progress_callback)

        hook = make_progress_hook(tracker)

        # Use yt-dlp's download_ranges for chapter extraction
        opts = build_ydl_opts(
            output_dir=output_dir,
            quality=quality,
            video_format=video_format,
            output_template=f"{i:02d} - {chapter_title}.%(ext)s",
            progress_hooks=[hook],
            extra_opts={
                "download_ranges": _make_chapter_range(start, end),
                "force_keyframes_at_cuts": True,
            },
        )

        result = DownloadResult(url=url, title=chapter_title)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

            if info:
                result.status = DownloadStatus.COMPLETED
                result.duration = end - start
                # Find the downloaded chapter file
                for dl in info.get("requested_downloads", []):
                    if filepath := dl.get("filepath"):
                        p = Path(filepath)
                        if p.exists():
                            result.file_path = p
                            result.file_size = p.stat().st_size
                            break
            else:
                result.status = DownloadStatus.FAILED
                result.error_message = "No info returned"
        except Exception as e:
            result.status = DownloadStatus.FAILED
            result.error_message = str(e)
            logger.error("Failed to download chapter %d: %s", i, e)

        results.append(result)

    return results


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _estimate_file_size(formats: list[dict[str, Any]]) -> int:
    """Estimate total file size from best video + best audio streams.

    Args:
        formats: The list of format dicts from yt-dlp.

    Returns:
        Approximate file size in bytes, or 0 if unknown.
    """
    best_video_size = 0
    best_audio_size = 0

    for fmt in formats:
        size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        if fmt.get("vcodec", "none") != "none":
            best_video_size = max(best_video_size, size)
        if fmt.get("acodec", "none") != "none" and fmt.get("vcodec", "none") == "none":
            best_audio_size = max(best_audio_size, size)

    return best_video_size + best_audio_size


def _make_chapter_range(
    start: float, end: float
) -> Any:
    """Create a download_ranges callback for yt-dlp.

    Args:
        start: Chapter start time in seconds.
        end: Chapter end time in seconds.

    Returns:
        A callable that yt-dlp uses for download_ranges.
    """
    def _ranges(info_dict: dict[str, Any], ydl: Any) -> list[dict[str, Any]]:
        return [{
            "start_time": start,
            "end_time": end,
            "title": info_dict.get("title", "Chapter"),
            "index": 0,
        }]

    return _ranges
