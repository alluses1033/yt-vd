"""Quality selection and fallback logic for yt-vd.

Resolves quality presets and resolution strings to yt-dlp format strings,
inspects available video qualities, and provides best-match fallback.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from constants import (
    QUALITY_FORMAT_MAP,
    RESOLUTION_FORMAT_MAP,
    QualityPreset,
)

logger = logging.getLogger(__name__)


def normalize_quality(quality: Any) -> str:
    """Normalize quality to a lowercase string value.

    Handles Enums, Enum members, and stringified representations of Enums.
    """
    if hasattr(quality, "value"):
        val = quality.value
    else:
        val = quality

    val_str = str(val).strip().lower()

    # If it is formatted like "<QualityPreset.BEST: 'best'>", extract the value
    if ":" in val_str and (val_str.startswith("<") or val_str.endswith(">")):
        match = re.search(r"'(.*?)'", val_str)
        if match:
            return match.group(1).strip().lower()
        parts = val_str.split(":")
        if len(parts) > 1:
            return parts[-1].replace(">", "").strip(" '\"").lower()

    return val_str


def resolve_format_string(quality: Any) -> str:
    """Convert a quality preset or resolution string to a yt-dlp format string.

    Supports:
    - Named presets: ``'best'``, ``'high'``, ``'medium'``, etc.
    - Resolution strings: ``'1080p'``, ``'720p'``, etc.
    - Raw yt-dlp format strings (passed through unchanged).

    All returned format strings include a fallback chain to ensure a download
    always succeeds even when the exact requested quality is unavailable.

    Args:
        quality: A quality preset name, resolution string, or raw format string.

    Returns:
        A yt-dlp format string with built-in fallback.

    Examples:
        >>> resolve_format_string('high')
        'bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best'
        >>> resolve_format_string('720p')
        'bestvideo[height<=720]+bestaudio/bestvideo+bestaudio/best'
    """
    normalized = normalize_quality(quality)

    # Check named presets first
    if normalized in QUALITY_FORMAT_MAP:
        return QUALITY_FORMAT_MAP[normalized]

    # Check resolution strings (e.g., "1080p", "720p")
    if normalized in RESOLUTION_FORMAT_MAP:
        return RESOLUTION_FORMAT_MAP[normalized]

    # Try bare numbers: "1080" → "1080p"
    if normalized.isdigit():
        with_p = f"{normalized}p"
        if with_p in RESOLUTION_FORMAT_MAP:
            return RESOLUTION_FORMAT_MAP[with_p]

    # If it looks like a raw yt-dlp format string, pass through with safety fallback
    if any(kw in normalized for kw in ("best", "worst", "+")):
        # Append /best as ultimate fallback if not already present
        if not normalized.endswith("/best"):
            return f"{normalized}/best"
        return normalized

    # Unknown quality — warn and fallback to best
    logger.warning(
        "Unknown quality %r — falling back to 'best'",
        quality,
    )
    return QUALITY_FORMAT_MAP[QualityPreset.BEST]


def check_quality_available(info_dict: dict[str, Any], quality: Any) -> bool:
    """Check whether the requested quality is available in a video's format list.

    Args:
        info_dict: The yt-dlp info dictionary (must contain ``'formats'``).
        quality: A resolution string like ``'1080p'`` or a preset name.

    Returns:
        True if a matching format exists, False otherwise.
    """
    target_height = _parse_height(quality)
    if target_height is None:
        return False

    formats: list[dict[str, Any]] = info_dict.get("formats") or []
    return any(
        fmt.get("height") == target_height and fmt.get("vcodec", "none") != "none"
        for fmt in formats
    )


def get_available_qualities(info_dict: dict[str, Any]) -> list[str]:
    """List all distinct video qualities available for a video.

    Args:
        info_dict: The yt-dlp info dictionary.

    Returns:
        Sorted list of resolution strings (e.g., ``['1080p', '720p', '480p']``),
        from highest to lowest.
    """
    formats: list[dict[str, Any]] = info_dict.get("formats") or []

    heights: set[int] = set()
    for fmt in formats:
        # Only count formats that actually have video
        if fmt.get("vcodec", "none") != "none" and (h := fmt.get("height")):
            heights.add(h)

    # Sort descending and format
    return [f"{h}p" for h in sorted(heights, reverse=True)]


def get_best_matching_quality(
    info_dict: dict[str, Any],
    requested: Any,
) -> str:
    """Find the closest available quality to the requested one.

    If the exact quality is available, returns it.  Otherwise, returns the
    next lower available quality.  If nothing lower exists, returns the
    lowest available quality.

    Args:
        info_dict: The yt-dlp info dictionary.
        requested: A resolution string or preset name.

    Returns:
        The resolution string of the best matching available quality,
        or ``'best'`` if no qualities can be determined.
    """
    target_height = _parse_height(requested)
    available = get_available_qualities(info_dict)

    if not available:
        return "best"

    if target_height is None:
        # Can't parse — return highest available
        return available[0]

    # available is sorted descending
    available_heights = [int(q.rstrip("p")) for q in available]

    # Find closest <= target
    for h in available_heights:
        if h <= target_height:
            return f"{h}p"

    # Nothing at or below target — return lowest available
    return available[-1]


def _parse_height(quality: Any) -> int | None:
    """Extract the numeric height from a quality string.

    Args:
        quality: E.g. ``'1080p'``, ``'1080'``, ``'high'``.

    Returns:
        The integer height, or None if unparseable.
    """
    normalized = normalize_quality(quality)

    # Preset name → height
    preset_to_height: dict[str, int] = {
        "best": 2160,
        "high": 1080,
        "medium": 720,
        "better": 480,
        "low": 360,
        "lowest": 240,
    }
    if normalized in preset_to_height:
        return preset_to_height[normalized]

    # Strip trailing 'p'
    numeric_str = normalized.rstrip("p")
    try:
        return int(numeric_str)
    except ValueError:
        return None

