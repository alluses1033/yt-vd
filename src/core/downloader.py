"""Core download logic for yt-vd.

This is the main download module.  It builds yt-dlp option dictionaries,
orchestrates quality fallback, fragment-safe downloads, and progress
tracking.  Includes retry logic with exponential backoff.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, cast

import yt_dlp
from yt_dlp.utils import DownloadError

from constants import (
    DEFAULT_FRAGMENT_THREADS,
    DOWNLOAD_CHUNK_SIZE,
    MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
    SINGLE_VIDEO_TEMPLATE,
    SOCKET_TIMEOUT,
    DownloadResult,
    DownloadStatus,
)
from core.fragment_safety import SafeDownloadManager, verify_file_integrity
from core.progress import ProgressCallback, ProgressTracker, make_progress_hook
from core.quality import (
    check_quality_available,
    get_best_matching_quality,
    resolve_format_string,
)
from core.subtitles import normalize_subtitle_languages
from core.ydl_options import with_base_ydl_opts

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# yt-dlp Options Builder
# ──────────────────────────────────────────────

def build_ydl_opts(
    *,
    output_dir: str | Path,
    quality: str = "best",
    video_format: str = "mp4",
    output_template: str = SINGLE_VIDEO_TEMPLATE,
    embed_thumbnail: bool = True,
    embed_metadata: bool = True,
    embed_subs: bool = False,
    subtitle_langs: list[str] | None = None,
    sponsorblock: bool = False,
    progress_hooks: list[Any] | None = None,
    fragment_threads: int = DEFAULT_FRAGMENT_THREADS,
    use_temp_dir: bool = True,
    extra_opts: dict[str, Any] | None = None,
    video_id: str | None = None,
) -> dict[str, Any]:
    """Build a complete yt-dlp options dictionary.

    All format strings include automatic fallback chains so downloads
    never fail due to unavailable quality alone.

    Args:
        output_dir: Directory for finished downloads.
        quality: Quality preset, resolution string, or raw format string.
        video_format: Container format for merged output (mp4, mkv, webm).
        output_template: yt-dlp output template string.
        embed_thumbnail: Embed thumbnail in output file.
        embed_metadata: Embed video metadata.
        embed_subs: Embed subtitles into the container.
        subtitle_langs: Subtitle languages to download.
        sponsorblock: Enable SponsorBlock chapter marking/removal.
        progress_hooks: List of yt-dlp progress hook callables.
        fragment_threads: Number of threads for fragment downloads.
        use_temp_dir: Use SafeDownloadManager for temp-then-move.
        extra_opts: Additional yt-dlp options to merge.

    Returns:
        A dict ready to pass to ``yt_dlp.YoutubeDL(opts)``.
    """
    format_string = resolve_format_string(quality)

    opts: dict[str, Any] = with_base_ydl_opts({
        "format": format_string,
        "outtmpl": {"default": output_template},
        "merge_output_format": video_format,
        "socket_timeout": SOCKET_TIMEOUT,
        "retries": MAX_RETRIES,
        "fragment_retries": MAX_RETRIES,
        "concurrent_fragment_downloads": fragment_threads,
        "buffersize": DOWNLOAD_CHUNK_SIZE,
        "noprogress": True,  # we handle progress ourselves
        "ignoreerrors": False,
        "overwrites": False,
        "continuedl": True,  # resume partial downloads
        "noplaylist": True,  # single video by default
    })

    # Paths
    if use_temp_dir:
        safety = SafeDownloadManager(output_dir, video_id=video_id)
        opts.update(safety.get_ydl_paths())
    else:
        opts["paths"] = {"home": str(output_dir)}

    # Post-processors
    postprocessors: list[dict[str, Any]] = []

    if embed_metadata:
        postprocessors.append({"key": "FFmpegMetadata"})

    if embed_thumbnail:
        postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg"})
        postprocessors.append({"key": "EmbedThumbnail"})
        opts["writethumbnail"] = True

    if embed_subs and subtitle_langs:
        subtitle_langs = normalize_subtitle_languages(subtitle_langs)
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = subtitle_langs
        opts["subtitlesformat"] = "srt/best"
        postprocessors.append({
            "key": "FFmpegEmbedSubtitle",
            "already_have_subtitle": False,
        })

    if sponsorblock:
        postprocessors.append({
            "key": "SponsorBlock",
            "categories": ["sponsor", "selfpromo", "interaction", "intro", "outro"],
        })
        postprocessors.append({"key": "ModifyChapters", "remove_sponsor_segments": ["sponsor"]})

    if postprocessors:
        opts["postprocessors"] = postprocessors

    # Merge extra options (user overrides), preserving progress callbacks.
    extra_progress_hooks: list[Any] = []
    if extra_opts:
        extra_opts = extra_opts.copy()
        raw_hooks = extra_opts.pop("progress_hooks", [])
        if raw_hooks is None:
            extra_progress_hooks = []
        elif callable(raw_hooks):
            extra_progress_hooks = [raw_hooks]
        else:
            extra_progress_hooks = list(raw_hooks)
        opts.update(extra_opts)

    merged_progress_hooks = [*(progress_hooks or []), *extra_progress_hooks]
    if merged_progress_hooks:
        opts["progress_hooks"] = merged_progress_hooks

    return opts


# ──────────────────────────────────────────────
# Info Extraction
# ──────────────────────────────────────────────

def extract_info(
    url: str,
    *,
    download: bool = False,
    flat: bool = False,
) -> dict[str, Any]:
    """Extract video/playlist info without downloading.

    Args:
        url: YouTube URL to extract info from.
        download: If True, also download (rarely used directly).
        flat: If True, only extract basic info for playlist entries.

    Returns:
        The yt-dlp info dictionary.

    Raises:
        DownloadError: If extraction fails.
    """
    opts: dict[str, Any] = with_base_ydl_opts({
        "extract_flat": flat,
        "skip_download": not download,
        "ignoreerrors": True,
    })

    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(url, download=download)
        if info is None:
            raise DownloadError(f"Failed to extract info from {url}")
        return cast(dict[str, Any], info)


# ──────────────────────────────────────────────
# Core Download Function
# ──────────────────────────────────────────────

def download_video(
    url: str,
    *,
    output_dir: str | Path = ".",
    quality: str = "best",
    video_format: str = "mp4",
    output_template: str = SINGLE_VIDEO_TEMPLATE,
    embed_thumbnail: bool = True,
    embed_metadata: bool = True,
    embed_subs: bool = False,
    subtitle_langs: list[str] | None = None,
    sponsorblock: bool = False,
    progress_callback: ProgressCallback | None = None,
    max_retries: int = MAX_RETRIES,
    extra_opts: dict[str, Any] | None = None,
    **kwargs: Any,
) -> DownloadResult:
    """Download a single YouTube video.

    Handles quality fallback (warns if requested quality unavailable),
    fragment-safe downloading, and exponential backoff retries.

    Args:
        url: YouTube video URL.
        output_dir: Destination directory.
        quality: Desired quality (preset, resolution, or raw format string).
        video_format: Container format (mp4, mkv, webm).
        output_template: yt-dlp output template.
        embed_thumbnail: Embed thumbnail in output.
        embed_metadata: Embed metadata tags.
        embed_subs: Embed subtitles.
        subtitle_langs: Languages to embed.
        sponsorblock: Enable SponsorBlock.
        progress_callback: Optional callback for progress updates.
        max_retries: Maximum retry attempts on network errors.
        extra_opts: Additional yt-dlp options.
        kwargs: Additional arguments for GUI parameter aliases.

    Returns:
        A ``DownloadResult`` describing the outcome.
    """
    # Extract aliases
    video_format = kwargs.pop("fmt", video_format)
    embed_thumbnail = kwargs.pop("thumbnail", embed_thumbnail)
    embed_subs = kwargs.pop("subtitles", embed_subs)
    sub_lang = kwargs.pop("sub_lang", None)
    progress_hook = kwargs.pop("progress_hook", None)
    use_temp_dir = kwargs.pop("use_temp_dir", True)

    # Extract video ID from URL or fallback
    match = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})", url)
    video_id = match.group(1) if match else None
    if not video_id:
        import hashlib
        video_id = hashlib.md5(url.encode()).hexdigest()[:11]

    if subtitle_langs is None and sub_lang:
        if isinstance(sub_lang, str):
            subtitle_langs = [sub_lang]
        else:
            subtitle_langs = list(sub_lang)
    if embed_subs and not subtitle_langs:
        subtitle_langs = ["en"]

    result = DownloadResult(url=url)
    start_time = time.monotonic()

    # Ensure output directory exists
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Setup progress tracker
    tracker = ProgressTracker()
    if progress_callback:
        tracker.add_callback(progress_callback)

    # Quality fallback: check if requested quality is available
    effective_quality = quality
    try:
        info = extract_info(url)
        result.title = info.get("title", "")
        result.duration = float(info.get("duration") or 0.0)
        tracker.video_id = info.get("id", "")
        tracker.title = result.title

        quality_str = str(quality).strip().lower()
        if quality_str not in ("best", "qualitypreset.best") and not check_quality_available(info, quality_str):
            best_match = get_best_matching_quality(info, quality_str)
            if best_match.lower() != quality_str:
                logger.warning(
                    "Requested quality %r not available — using %r instead",
                    quality_str,
                    best_match,
                )
            effective_quality = best_match
    except Exception as e:
        # If info extraction fails, proceed anyway and let yt-dlp handle it
        logger.debug("Pre-download info extraction failed: %s", e)

    # Build yt-dlp options
    hook = make_progress_hook(tracker)
    progress_hooks = [hook]
    if progress_hook:
        progress_hooks.append(progress_hook)

    opts = build_ydl_opts(
        output_dir=output_dir,
        quality=effective_quality,
        video_format=video_format,
        output_template=output_template,
        embed_thumbnail=embed_thumbnail,
        embed_metadata=embed_metadata,
        embed_subs=embed_subs,
        subtitle_langs=subtitle_langs,
        sponsorblock=sponsorblock,
        progress_hooks=progress_hooks,
        use_temp_dir=use_temp_dir,
        extra_opts=extra_opts,
        video_id=video_id,
    )

    # Download with retry
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            tracker.set_status(DownloadStatus.DOWNLOADING)

            with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
                download_info = ydl.extract_info(url, download=True)

            if download_info is None:
                raise DownloadError("Download returned no info")

            # Find the downloaded file
            final_path = _find_downloaded_file(cast(dict[str, Any], download_info), output_path)
            title_value = cast(dict[str, Any], download_info).get("title") or result.title
            result.title = title_value
            result.quality = effective_quality
            result.format = video_format

            if final_path and final_path.exists():
                # Verify integrity
                if verify_file_integrity(final_path):
                    result.file_path = final_path
                    result.file_size = final_path.stat().st_size
                    result.status = DownloadStatus.COMPLETED
                    tracker.set_status(DownloadStatus.COMPLETED)
                else:
                    logger.warning("File integrity check failed for %s", final_path)
                    result.file_path = final_path
                    result.file_size = final_path.stat().st_size
                    result.status = DownloadStatus.COMPLETED  # still usable
                    tracker.set_status(DownloadStatus.COMPLETED)
            else:
                result.status = DownloadStatus.COMPLETED
                tracker.set_status(DownloadStatus.COMPLETED)

            result.elapsed_seconds = time.monotonic() - start_time
            # Add to history database
            try:
                from core.history import add_to_history
                add_to_history(result)
            except Exception as e:
                logger.debug("Failed to write download history: %s", e)

            # Clean up temp directory
            safety = SafeDownloadManager(output_dir, video_id=video_id)
            safety.cleanup_temp()
            return result

        except DownloadError as e:
            last_error = e
            if attempt < max_retries and _is_retriable(e):
                wait = RETRY_BACKOFF_FACTOR ** attempt
                logger.warning(
                    "Download attempt %d/%d failed: %s — retrying in %.0fs",
                    attempt,
                    max_retries,
                    e,
                    wait,
                )
                time.sleep(wait)
            else:
                break
        except KeyboardInterrupt:
            logger.warning("Download interrupted by user.")
            safety = SafeDownloadManager(output_dir, video_id=video_id)
            safety.cleanup_temp()
            tracker.set_status(DownloadStatus.FAILED)
            raise
        except Exception as e:
            last_error = e
            break

    # All retries exhausted or non-retriable error
    result.status = DownloadStatus.FAILED
    result.error_message = str(last_error) if last_error else "Unknown error"
    result.elapsed_seconds = time.monotonic() - start_time
    tracker.set_status(DownloadStatus.FAILED)
    logger.error("Download failed for %s: %s", url, result.error_message)
    return result


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _find_downloaded_file(
    info: dict[str, Any],
    output_dir: Path,
) -> Path | None:
    """Locate the downloaded file from yt-dlp's info dict.

    Checks multiple yt-dlp info fields in order of reliability.

    Args:
        info: The yt-dlp info dictionary after download.
        output_dir: The expected output directory.

    Returns:
        Path to the downloaded file, or None if not found.
    """
    # yt-dlp may provide the filepath directly
    if filepath := info.get("filepath"):
        p = Path(filepath)
        if p.exists():
            return p

    # Try requested_downloads
    for dl in info.get("requested_downloads", []):
        if filepath := dl.get("filepath"):
            p = Path(filepath)
            if p.exists():
                return p

    # Fallback: construct from title and ext
    title = info.get("title", "")
    ext = info.get("ext", "mp4")
    if title:
        candidate = output_dir / f"{title}.{ext}"
        if candidate.exists():
            return candidate

    return None


def _is_retriable(error: Exception) -> bool:
    """Determine if a download error is worth retrying.

    Args:
        error: The exception that occurred.

    Returns:
        True if the error is likely transient (network issue).
    """
    msg = str(error).lower()
    retriable_keywords = (
        "connection",
        "timeout",
        "network",
        "http error 5",
        "http error 429",
        "too many requests",
        "temporary",
        "unavailable",
        "reset by peer",
        "broken pipe",
    )
    return any(kw in msg for kw in retriable_keywords)


def download_clip(
    url: str,
    *,
    start_time: str | None = None,
    end_time: str | None = None,
    output_dir: str | Path = ".",
    quality: str = "best",
    video_format: str = "mp4",
    **kwargs: Any,
) -> DownloadResult:
    """Download a specific time range (clip) from a YouTube video.

    Args:
        url: YouTube video URL.
        start_time: Start time as string (MM:SS, HH:MM:SS) or float seconds.
        end_time: End time as string (MM:SS, HH:MM:SS) or float seconds.
        output_dir: Output folder.
        quality: Video quality option.
        video_format: Video format option.
        **kwargs: Additional args passed to download_video.
    """
    def to_secs(t: str | float | None) -> float | None:
        if t is None:
            return None
        if isinstance(t, (int, float)):
            return float(t)
        t_str = str(t).strip()
        if not t_str:
            return None
        if re.match(r"^\d+(\.\d+)?$", t_str):
            return float(t_str)
        parts = t_str.split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        return float(t_str)

    start_sec = to_secs(start_time) or 0.0
    end_sec = to_secs(end_time)

    # yt-dlp download_ranges requires start_time and end_time (or float('inf') if end is None)
    range_info = {
        "start_time": start_sec,
        "end_time": end_sec if end_sec is not None else float("inf"),
        "title": "clip",
        "index": 1,
    }

    extra_opts = kwargs.get("extra_opts") or {}
    extra_opts["download_ranges"] = lambda info, ctx: [range_info]
    extra_opts["force_keyframes_at_cuts"] = True
    kwargs["extra_opts"] = extra_opts

    return download_video(
        url,
        output_dir=output_dir,
        quality=quality,
        video_format=video_format,
        **kwargs,
    )




