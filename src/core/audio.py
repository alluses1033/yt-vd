"""Audio extraction module for yt-vd.

Configures yt-dlp to extract and convert audio from YouTube videos,
with support for format selection, bitrate control, and metadata embedding.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, cast

import yt_dlp

from constants import (
    AUDIO_BITRATE_MAP,
    MAX_RETRIES,
    SINGLE_VIDEO_TEMPLATE,
    SOCKET_TIMEOUT,
    VIDEO_ID_PATTERN,
    AudioBitrate,
    AudioFormat,
    DownloadResult,
    DownloadStatus,
    ProgressInfo,
)
from core.fragment_safety import SafeDownloadManager, verify_file_integrity
from core.progress import ProgressCallback, ProgressTracker, make_progress_hook
from core.ydl_options import with_base_ydl_opts

logger = logging.getLogger(__name__)


def extract_audio(
    url: str,
    *,
    output_dir: str | Path = ".",
    audio_format: str = AudioFormat.MP3,
    bitrate: str = AudioBitrate.BEST,
    embed_thumbnail: bool = True,
    embed_metadata: bool = True,
    progress_callback: ProgressCallback | None = None,
    output_template: str = SINGLE_VIDEO_TEMPLATE,
    max_retries: int = MAX_RETRIES,
    **kwargs: Any,
) -> DownloadResult:
    """Extract audio from a YouTube video.

    Downloads the best audio stream and converts it to the requested
    format/bitrate using ffmpeg post-processing.

    Args:
        url: YouTube video URL.
        output_dir: Destination directory for the audio file.
        audio_format: Target audio format (mp3, m4a, flac, wav, opus).
        bitrate: Target bitrate (128k, 192k, 256k, 320k).
        embed_thumbnail: Embed album art / thumbnail.
        embed_metadata: Embed ID3 / metadata tags.
        progress_callback: Optional progress callback.
        output_template: yt-dlp output filename template.
        max_retries: Maximum retry attempts.
        kwargs: Additional arguments (e.g. progress_hook).

    Returns:
        A ``DownloadResult`` describing the outcome.
    """
    result = DownloadResult(url=url)
    start_time = time.monotonic()
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    progress_hook = kwargs.pop("progress_hook", None)
    shutdown_event = kwargs.pop("shutdown_event", None)

    # Validate URL
    from core.utils import validate_url
    if not validate_url(url):
        logger.warning("URL does not appear to be a YouTube URL: %s", url)

    # Setup progress
    tracker = ProgressTracker()

    def wrapped_callback(info: ProgressInfo) -> None:
        if shutdown_event and shutdown_event.is_set():
            raise KeyboardInterrupt("Cancelled")
        if progress_callback:
            progress_callback(info)

    tracker.add_callback(wrapped_callback)

    # Extract video ID from URL or fallback using shared helper
    from core.utils import extract_video_id
    video_id = extract_video_id(url)

    hook = make_progress_hook(tracker)
    safety = SafeDownloadManager(output_path, video_id=video_id)

    # Resolve bitrate to numeric quality (for yt-dlp)
    quality_num = AUDIO_BITRATE_MAP.get(bitrate, 320)

    # Build post-processors
    postprocessors: list[dict[str, Any]] = [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_format,
            "preferredquality": str(quality_num),
        }
    ]

    if embed_metadata:
        postprocessors.append({"key": "FFmpegMetadata"})

    if embed_thumbnail:
        postprocessors.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg"})
        postprocessors.append({"key": "EmbedThumbnail"})

    progress_hooks = [hook]
    if progress_hook:
        progress_hooks.append(progress_hook)

    opts: dict[str, Any] = with_base_ydl_opts({
        "format": "bestaudio/best",
        "outtmpl": {"default": output_template},
        "postprocessors": postprocessors,
        "writethumbnail": embed_thumbnail,
        "socket_timeout": SOCKET_TIMEOUT,
        "retries": MAX_RETRIES,
        "noprogress": True,
        "ignoreerrors": False,
        "continuedl": True,
        "noplaylist": True,
        "progress_hooks": progress_hooks,
    })
    opts.update(safety.get_ydl_paths())

    # Download with retry
    def _do_download() -> dict[str, Any]:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if info is None:
            raise yt_dlp.utils.DownloadError("Audio extraction returned no info")
        return cast(dict[str, Any], info)

    try:
        from core.retry import retry_operation
        info = retry_operation(
            _do_download,
            max_retries=max_retries,
            shutdown_event=shutdown_event,
            tracker=tracker,
            safety=safety,
            label="Audio extraction",
        )

        result.title = info.get("title", "")
        result.duration = float(info.get("duration") or 0.0)
        result.quality = bitrate
        result.format = audio_format
        tracker.title = result.title
        tracker.video_id = str(info.get("id") or "")

        # Find downloaded file
        from core.utils import find_output_file
        temp_file_path = find_output_file(info, safety.temp_dir, audio_format)
        if temp_file_path and temp_file_path.exists():
            is_valid = verify_file_integrity(temp_file_path)
            if not is_valid:
                logger.warning("File integrity check failed for %s", temp_file_path)
            
            # Atomically move from temp to final directory
            final_path = safety.move_to_final(temp_file_path)
            result.file_path = final_path
            result.file_size = final_path.stat().st_size

        result.status = DownloadStatus.COMPLETED
        result.elapsed_seconds = time.monotonic() - start_time
        tracker.set_status(DownloadStatus.COMPLETED)

        # Add to history database using shared safe helper
        from core.history import safe_add_to_history
        safe_add_to_history(result)

        safety.cleanup_temp(force=True)
        return result

    except Exception as e:
        result.status = DownloadStatus.FAILED
        result.error_message = str(e)
        result.elapsed_seconds = time.monotonic() - start_time
        tracker.set_status(DownloadStatus.FAILED)
        logger.error("Audio extraction failed for %s: %s", url, result.error_message)
        safety.cleanup_temp()
        return result





