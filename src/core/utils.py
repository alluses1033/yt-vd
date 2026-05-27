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
from typing import Literal

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


def check_dependencies() -> dict[str, str | None]:
    """Check availability of external dependencies.

    Returns:
        A dict mapping dependency names to version strings (or None if missing).
        Currently checks: ``ffmpeg``.
    """
    deps: dict[str, str | None] = {
        "ffmpeg": check_ffmpeg(),
    }

    # Check for a JavaScript runtime (optional — used by some yt-dlp extractors)
    for js_runtime in ("node", "deno", "bun"):
        if (js_path := shutil.which(js_runtime)):
            try:
                result = subprocess.run(
                    [js_path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                deps["js_runtime"] = f"{js_runtime} {result.stdout.strip()}"
                break
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                continue
    else:
        deps["js_runtime"] = None

    return deps


# ──────────────────────────────────────────────
# Filesystem Helpers
# ──────────────────────────────────────────────

def ensure_dir(path: str | Path) -> Path:
    """Create a directory (and parents) if it doesn't exist.

    Args:
        path: The directory path to ensure exists.

    Returns:
        The resolved Path object.
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p



