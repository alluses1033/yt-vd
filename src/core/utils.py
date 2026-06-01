"""Shared utilities for yt-vd.

Provides filename sanitization, URL validation, human-readable formatting,
dependency checking, and filesystem helpers.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from constants import YOUTUBE_URL_PATTERNS

logger = logging.getLogger(__name__)

# Precompile URL patterns once for performance
_COMPILED_URL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(pattern) for pattern in YOUTUBE_URL_PATTERNS
]

# Characters illegal in Windows filenames (superset covers Linux too)
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Collapse multiple spaces / dots
_MULTI_SPACE = re.compile(r"\s+")
_TRAILING_DOTS_SPACES = re.compile(r"[. ]+$")

# URL type detection patterns (order matters — more specific first)
_URL_TYPE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/playlist\?(?:[^&]+&)*list=[\w-]+"), "playlist"),
    (re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+"), "shorts"),
    (re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/@[\w.-]+"), "channel"),
    (re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/channel/[\w-]+"), "channel"),
    (re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/c/[\w-]+"), "channel"),
    (re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/user/[\w-]+"), "channel"),
    (re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/watch\?(?:[^&]+&)*v=[\w-]+"), "video"),
    (re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/embed/[\w-]+"), "video"),
    (re.compile(r"(?:https?://)?youtu\.be/[\w-]+"), "video"),
]

UrlType = Literal["video", "playlist", "channel", "shorts", "unknown"]


# ──────────────────────────────────────────────
# Filename Sanitization
# ──────────────────────────────────────────────

def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Remove or replace characters that are invalid in file names.

    Works correctly on both Windows and Linux.  Collapses whitespace,
    strips trailing dots/spaces, and truncates to *max_length* characters
    (preserving any file extension).

    Args:
        name: The raw filename string to sanitize.
        max_length: Maximum allowed length for the filename.

    Returns:
        A sanitized, filesystem-safe filename string.
    """
    if not name:
        return "untitled"

    # Replace invalid chars with underscore
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name)

    # Collapse whitespace
    cleaned = _MULTI_SPACE.sub(" ", cleaned).strip()

    # Remove trailing dots/spaces (Windows restriction)
    cleaned = _TRAILING_DOTS_SPACES.sub("", cleaned)

    if not cleaned:
        return "untitled"

    # Truncate while preserving extension
    if len(cleaned) > max_length:
        stem = Path(cleaned).stem
        suffix = Path(cleaned).suffix
        max_stem = max_length - len(suffix)
        cleaned = stem[:max_stem] + suffix

    return cleaned


# ──────────────────────────────────────────────
# URL Validation & Detection
# ──────────────────────────────────────────────

def validate_url(url: str) -> bool:
    """Check if *url* is a valid YouTube URL.

    Args:
        url: The URL string to validate.

    Returns:
        True if the URL matches any known YouTube pattern.
    """
    clean_url = url.strip()
    return any(pattern.match(clean_url) is not None for pattern in _COMPILED_URL_PATTERNS)


def detect_url_type(url: str) -> UrlType:
    """Classify a YouTube URL by content type.

    Args:
        url: A YouTube URL string.

    Returns:
        One of ``'video'``, ``'playlist'``, ``'channel'``,
        ``'shorts'``, or ``'unknown'``.
    """
    for pattern, url_type in _URL_TYPE_PATTERNS:
        if pattern.search(url):
            return url_type  # type: ignore[return-value]
    return "unknown"


# ──────────────────────────────────────────────
# Human-Readable Formatting
# ──────────────────────────────────────────────

def format_duration(seconds: float | int) -> str:
    """Convert a duration in seconds to a human-readable string.

    Examples:
        >>> format_duration(65)
        '01:05'
        >>> format_duration(3723)
        '1:02:03'
    """
    if seconds <= 0:
        return "00:00"

    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_file_size(size_bytes: int | float) -> str:
    """Convert a byte count to a human-readable string.

    Uses binary units (KiB, MiB, GiB) for precision.

    Examples:
        >>> format_file_size(1536)
        '1.50 KiB'
        >>> format_file_size(1_073_741_824)
        '1.00 GiB'
    """
    if size_bytes <= 0:
        return "0 B"

    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(size_bytes)

    for unit in units:
        if value < 1024.0:
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0

    return f"{value:.2f} PiB"


def normalize_youtube_thumbnail_url(url: str) -> str:
    """Normalize YouTube thumbnail URL to a stable high-quality variant."""
    if not url:
        return ""

    if "i.ytimg.com" in url or "img.youtube.com" in url:
        for name in ("default", "mqdefault", "sddefault", "maxresdefault"):
            if f"/{name}.jpg" in url:
                return url.replace(f"/{name}.jpg", "/hqdefault.jpg")
            if f"/{name}.webp" in url:
                return url.replace(f"/{name}.webp", "/hqdefault.jpg")
    return url


# ──────────────────────────────────────────────
# Dependency Checking
# ──────────────────────────────────────────────

def check_ffmpeg() -> str | None:
    """Verify that ffmpeg is available on the system PATH.

    Returns:
        The ffmpeg version string if found, or ``None`` if unavailable.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        return None

    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        # First line is typically "ffmpeg version X.Y.Z ..."
        first_line = result.stdout.split("\n", maxsplit=1)[0]
        version = first_line.split("version", maxsplit=1)[-1].strip().split(" ", maxsplit=1)[0]
        return version
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        logger.debug("ffmpeg found at %s but failed to get version", ffmpeg_path)
        return None


# ──────────────────────────────────────────────
# Filesystem Helpers
# ──────────────────────────────────────────────

def find_output_file(
    info: dict[str, Any],
    output_dir: Path | str,
    ext: str | None = None,
) -> Path | None:
    """Locate the downloaded or extracted file from yt-dlp's info dict.

    Args:
        info: The yt-dlp info dictionary.
        output_dir: The destination directory.
        ext: Optional expected file extension. Falls back to info['ext'] or 'mp4'.
    """
    out_dir_path = Path(output_dir)

    # 1. Check requested_downloads first
    for dl in info.get("requested_downloads", []):
        if filepath := dl.get("filepath"):
            p = Path(filepath)
            if p.exists():
                return p

    # 2. Check info.get("filepath")
    if filepath := info.get("filepath"):
        p = Path(filepath)
        if p.exists():
            return p

    # 3. Fallback: title and ext
    title = info.get("title", "")
    expected_ext = ext or info.get("ext") or "mp4"
    if title:
        candidate = out_dir_path / f"{title}.{expected_ext}"
        if candidate.exists():
            return candidate

    return None


def extract_video_id(url: str) -> str:
    """Extract the 11-character video ID from a YouTube URL.

    Falls back to a stable MD5 hash if no ID can be extracted.
    """
    import hashlib

    from constants import VIDEO_ID_PATTERN

    match = VIDEO_ID_PATTERN.search(url)
    if match:
        return match.group(1)
    return hashlib.md5(url.encode()).hexdigest()[:11]


def get_best_thumbnail_url(info_dict: dict[str, Any]) -> str:
    """Get the highest resolution thumbnail URL from info dictionary."""
    thumbs = info_dict.get("thumbnails")
    thumb = None
    if isinstance(thumbs, list) and len(thumbs) > 0:
        def get_res(t: dict[str, Any]) -> int:
            w = t.get("width") or 0
            h = t.get("height") or 0
            return w * h
        sorted_thumbs = sorted(thumbs, key=get_res, reverse=True)
        if sorted_thumbs:
            thumb = sorted_thumbs[0].get("url")
    if not thumb:
        thumb = info_dict.get("thumbnail", "")
    return normalize_youtube_thumbnail_url(thumb or "")



