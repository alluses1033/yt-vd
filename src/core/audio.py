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

    # Extract video ID from URL or fallback
    match = VIDEO_ID_PATTERN.search(url)
    video_id = match.group(1) if match else None
    if not video_id:
        import hashlib
        video_id = hashlib.md5(url.encode()).hexdigest()[:11]

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
        final_path = _find_audio_file(info, output_path, audio_format)
        if final_path and final_path.exists():
            if verify_file_integrity(final_path):
                result.file_path = final_path
                result.file_size = final_path.stat().st_size
            else:
                result.file_path = final_path
                result.file_size = final_path.stat().st_size

        result.status = DownloadStatus.COMPLETED
        result.elapsed_seconds = time.monotonic() - start_time
        tracker.set_status(DownloadStatus.COMPLETED)

        # Add to history database
        try:
            from core.history import add_to_history
            add_to_history(result)
        except Exception as e:
            logger.debug("Failed to write download history: %s", e)

        safety.cleanup_temp()
        return result

    except Exception as e:
        result.status = DownloadStatus.FAILED
        result.error_message = str(e)
        result.elapsed_seconds = time.monotonic() - start_time
        tracker.set_status(DownloadStatus.FAILED)
        logger.error("Audio extraction failed for %s: %s", url, result.error_message)
        safety.cleanup_temp()
        return result


def get_audio_info(url: str) -> dict[str, Any]:
    """Get audio-specific metadata for a YouTube video.

    Extracts information about available audio streams, codecs,
    bitrates, and sample rates.

    Args:
        url: YouTube video URL.

    Returns:
        A dict with keys: ``best_audio``, ``audio_streams``,
        ``title``, ``duration``, ``thumbnail``.
    """
    opts: dict[str, Any] = with_base_ydl_opts({
        "skip_download": True,
    })

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            return {}

    formats: list[dict[str, Any]] = info.get("formats") or []

    # Filter to audio-only streams
    audio_streams: list[dict[str, Any]] = []
    for fmt in formats:
        if fmt.get("acodec", "none") != "none" and fmt.get("vcodec", "none") == "none":
            audio_streams.append({
                "format_id": fmt.get("format_id", ""),
                "codec": fmt.get("acodec", "unknown"),
                "bitrate": fmt.get("abr", 0),
                "sample_rate": fmt.get("asr", 0),
                "file_size": fmt.get("filesize") or fmt.get("filesize_approx", 0),
                "ext": fmt.get("ext", ""),
            })

    # Sort by bitrate descending
    audio_streams.sort(key=lambda s: s.get("bitrate", 0), reverse=True)

    return {
        "title": info.get("title", ""),
        "duration": info.get("duration", 0),
        "thumbnail": info.get("thumbnail", ""),
        "best_audio": audio_streams[0] if audio_streams else {},
        "audio_streams": audio_streams,
    }


def _find_audio_file(
    info: dict[str, Any],
    output_dir: Path,
    audio_format: str,
) -> Path | None:
    """Locate the extracted audio file.

    Args:
        info: yt-dlp info dict after download.
        output_dir: Output directory.
        audio_format: The expected audio extension.

    Returns:
        Path to the audio file, or None.
    """
    # Check requested_downloads first
    for dl in info.get("requested_downloads", []):
        if filepath := dl.get("filepath"):
            p = Path(filepath)
            if p.exists():
                return p

    if filepath := info.get("filepath"):
        p = Path(filepath)
        if p.exists():
            return p

    # Fallback: title.ext
    title = info.get("title", "")
    if title:
        candidate = output_dir / f"{title}.{audio_format}"
        if candidate.exists():
            return candidate

    return None


