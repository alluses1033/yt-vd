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
    SINGLE_VIDEO_TEMPLATE,
    SOCKET_TIMEOUT,
    VIDEO_ID_PATTERN,
    DownloadResult,
    DownloadStatus,
    ProgressInfo,
)
from core.fragment_safety import SafeDownloadManager, verify_file_integrity
from core.progress import ProgressCallback, ProgressTracker, make_progress_hook
from core.quality import (
    check_quality_available,
    get_best_matching_quality,
    normalize_quality,
    resolve_format_string,
)
from core.subtitles import cleanup_leftover_subtitles, normalize_subtitle_languages
from core.ydl_options import with_base_ydl_opts

logger = logging.getLogger(__name__)
_SUPPORTED_COOKIES_BROWSERS = {"chrome", "chromium", "firefox", "edge", "safari", "opera", "brave", "vivaldi"}
_SUPPORTED_PROXY_SCHEMES = ("http://", "https://", "socks4://", "socks4a://", "socks5://", "socks5h://")

# Precompiled regex for download_clip time parsing (HH:MM:SS / MM:SS / float)
_NUMERIC_TIME_PATTERN = re.compile(r"^\d+(\.\d+)?$")


def _has_aria2c() -> bool:
    """Check if aria2c binary is available on PATH."""
    import shutil
    return shutil.which("aria2c") is not None


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
    # New options
    use_aria2c: bool = False,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
    rate_limit: str | None = None,
    proxy: str | None = None,
    safety: SafeDownloadManager | None = None,
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
        # Reuse safety if provided, otherwise create it
        mgr = safety if safety is not None else SafeDownloadManager(output_dir, video_id=video_id)
        opts.update(mgr.get_ydl_paths())
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

    # External downloader: aria2c for faster multi-connection downloads
    # Only applies to direct HTTP downloads, not HLS/DASH (which use fragment_threads)
    if use_aria2c and _has_aria2c():
        opts["external_downloader"] = "aria2c"
        opts["external_downloader_args"] = {
            "aria2c": ["-x", "16", "-s", "16", "-k", "1M", "--min-split-size=1M"]
        }
        logger.debug("aria2c external downloader enabled")
    elif use_aria2c:
        logger.warning("aria2c requested but not found on PATH — using default downloader")

    # Cookie sources for age-restricted / private videos
    if cookies_from_browser:
        browser_name = str(cookies_from_browser).strip().lower()
        if browser_name in _SUPPORTED_COOKIES_BROWSERS:
            opts["cookiesfrombrowser"] = (browser_name,)
        else:
            logger.warning("Unsupported browser for cookies import: %r — ignoring", cookies_from_browser)
    elif cookies_file:
        cookie_path = Path(cookies_file).expanduser()
        if cookie_path.exists() and cookie_path.is_file():
            opts["cookiefile"] = str(cookie_path)
        else:
            logger.warning("Cookies file not found or invalid: %r — ignoring", cookies_file)

    # Rate limiting
    if rate_limit:
        # Accept strings like "5M", "500K", or plain bytes
        rate_str = str(rate_limit).upper().strip()
        multiplier = {"K": 1024, "M": 1024 * 1024, "G": 1024 * 1024 * 1024}
        try:
            if rate_str and rate_str[-1] in multiplier:
                opts["ratelimit"] = int(float(rate_str[:-1]) * multiplier[rate_str[-1]])
            else:
                opts["ratelimit"] = int(rate_str)
        except ValueError:
            logger.warning("Invalid rate limit value: %r — ignoring", rate_limit)

    # Proxy
    if proxy:
        proxy_value = str(proxy).strip()
        if proxy_value.lower().startswith(_SUPPORTED_PROXY_SCHEMES):
            opts["proxy"] = proxy_value
        else:
            logger.warning("Invalid proxy value %r — expected scheme://host:port", proxy)

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
    use_aria2c: bool = False,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
    rate_limit: str | None = None,
    proxy: str | None = None,
    skip_downloaded: bool = False,
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
    shutdown_event = kwargs.pop("shutdown_event", None)

    # Validate URL
    from core.utils import validate_url
    if not validate_url(url):
        logger.warning("URL does not appear to be a YouTube URL: %s", url)

    # Extract video ID from URL or fallback using shared helper
    from core.utils import extract_video_id
    video_id = extract_video_id(url)

    if subtitle_langs is None and sub_lang:
        if isinstance(sub_lang, str):
            subtitle_langs = [sub_lang]
        else:
            subtitle_langs = list(sub_lang)
    if embed_subs and not subtitle_langs:
        subtitle_langs = ["en"]

    # Validate quality string upfront
    from core.quality import resolve_format_string
    resolve_format_string(quality)

    result = DownloadResult(url=url)
    start_time = time.monotonic()

    # Skip if already in history
    if skip_downloaded:
        try:
            from core.history import history_exists
            if history_exists(url):
                logger.info("Skipping already-downloaded URL: %s", url)
                result.status = DownloadStatus.SKIPPED
                result.error_message = "Already downloaded (--skip-downloaded)"
                return result
        except Exception as e:
            logger.debug("History check failed: %s", e)

    # Ensure output directory exists and is absolute
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    # Setup progress tracker
    tracker = ProgressTracker()

    def wrapped_callback(info: ProgressInfo) -> None:
        if shutdown_event and shutdown_event.is_set():
            raise KeyboardInterrupt("Cancelled")
        if progress_callback:
            progress_callback(info)

    tracker.add_callback(wrapped_callback)

    # Quality fallback: check if requested quality is available
    effective_quality = quality
    try:
        if shutdown_event and shutdown_event.is_set():
            raise KeyboardInterrupt("Cancelled")
        info = extract_info(url)
        result.title = info.get("title", "")
        result.duration = float(info.get("duration") or 0.0)
        tracker.video_id = info.get("id", "")
        tracker.title = result.title

        quality_str = normalize_quality(quality)
        if quality_str not in ("best", "bestvideo+bestaudio/best") and not check_quality_available(info, quality_str):
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

    # Create safety manager once — reused for paths and cleanup
    safety = SafeDownloadManager(output_path, video_id=video_id)

    opts = build_ydl_opts(
        output_dir=output_path,
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
        use_aria2c=use_aria2c,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
        rate_limit=rate_limit,
        proxy=proxy,
        safety=safety,
    )

    # Download with retry
    def _do_download() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=True)
        if info is None:
            raise DownloadError("Download returned no info")
        return cast(dict[str, Any], info)

    try:
        from core.retry import retry_operation
        download_info = retry_operation(
            _do_download,
            max_retries=max_retries,
            shutdown_event=shutdown_event,
            tracker=tracker,
            safety=safety,
            label="Download",
            retriable_checker=_is_retriable,
        )

        # Find the downloaded file
        from core.utils import find_output_file
        search_dir = safety.temp_dir if use_temp_dir else output_path
        final_file_path = find_output_file(download_info, search_dir)
        title_value = download_info.get("title") or result.title
        result.title = title_value
        result.quality = effective_quality
        result.format = video_format

        if final_file_path and final_file_path.exists():
            # Verify integrity
            is_valid = verify_file_integrity(final_file_path)
            if not is_valid:
                logger.warning("File integrity check failed for %s", final_file_path)
            
            if use_temp_dir:
                # Atomically move from temp to final directory
                final_path = safety.move_to_final(final_file_path)
            else:
                final_path = final_file_path

            result.file_path = final_path
            result.file_size = final_path.stat().st_size
            result.status = DownloadStatus.COMPLETED
            tracker.set_status(DownloadStatus.COMPLETED)

            # Clean up subtitles if they were embedded
            if embed_subs:
                try:
                    cleanup_leftover_subtitles(final_path, result.title)
                except Exception as e:
                    logger.debug("Failed to clean up leftover subtitles: %s", e)
        else:
            result.status = DownloadStatus.COMPLETED
            tracker.set_status(DownloadStatus.COMPLETED)

        result.elapsed_seconds = time.monotonic() - start_time
        # Add to history database using shared safe helper
        from core.history import safe_add_to_history
        safe_add_to_history(result)

        # Clean up temp directory
        safety.cleanup_temp(force=True)
        return result

    except Exception as e:
        result.status = DownloadStatus.FAILED
        result.error_message = str(e)
        result.elapsed_seconds = time.monotonic() - start_time
        tracker.set_status(DownloadStatus.FAILED)
        logger.error("Download failed for %s: %s", url, result.error_message)

        # Clean up temp directory even on failure so empty folders are removed
        safety.cleanup_temp()
        return result


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────




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
        "service unavailable",
        "temporarily unavailable",
        "reset by peer",
        "broken pipe",
        "winerror 32",
        "being used by another process",
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
        if _NUMERIC_TIME_PATTERN.match(t_str):
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




