"""Subtitle handling for yt-vd.

Downloads subtitles (manual or auto-generated), lists available
languages, and builds yt-dlp subtitle options.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, cast

import yt_dlp

from constants import SubtitleFormat
from core.ydl_options import with_base_ydl_opts

logger = logging.getLogger(__name__)

# Precompile filename normalization pattern for performance
_NORMALIZE_NAME_PATTERN = re.compile(r'[^a-z0-9]')


def get_available_subtitles(url: str) -> dict[str, dict[str, Any]]:
    """List all available subtitle languages for a video.

    Returns both manual and auto-generated subtitles.

    Args:
        url: YouTube video URL.

    Returns:
        A dict mapping language codes to subtitle info. Structure::

            {
                "en": {
                    "name": "English",
                    "auto_generated": False,
                    "formats": ["srt", "vtt"]
                },
                ...
            }
    """
    opts: dict[str, Any] = with_base_ydl_opts({
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "listsubtitles": False,  # we'll parse the info dict ourselves
    })

    with yt_dlp.YoutubeDL(cast(Any, opts)) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            return {}

    result: dict[str, dict[str, Any]] = {}

    # Manual subtitles
    manual_subs: dict[str, Any] = info.get("subtitles") or {}
    for lang, sub_list in manual_subs.items():
        formats = [s.get("ext", "vtt") for s in sub_list] if isinstance(sub_list, list) else []
        result[lang] = {
            "name": _language_name(lang),
            "auto_generated": False,
            "formats": list(set(formats)),
        }

    # Auto-generated subtitles
    auto_subs: dict[str, Any] = info.get("automatic_captions") or {}
    for lang, sub_list in auto_subs.items():
        if lang not in result:  # manual subs take priority
            formats = (
                [s.get("ext", "vtt") for s in sub_list]
                if isinstance(sub_list, list)
                else []
            )
            result[lang] = {
                "name": _language_name(lang),
                "auto_generated": True,
                "formats": list(set(formats)),
            }

    return result


def download_subtitles(
    url: str,
    *,
    output_dir: str | Path = ".",
    languages: list[str] | None = None,
    subtitle_format: str = SubtitleFormat.SRT,
    auto_generated: bool = True,
) -> list[Path]:
    """Download subtitles for a YouTube video.

    Args:
        url: YouTube video URL.
        output_dir: Directory to save subtitle files.
        languages: Language codes to download (e.g., ``['en', 'es']``).
                   If ``None``, downloads all available.
        subtitle_format: Output format (srt, vtt, ass).
        auto_generated: Include auto-generated subtitles if manual not available.

    Returns:
        List of paths to downloaded subtitle files.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    opts = build_subtitle_opts(
        languages=languages,
        subtitle_format=subtitle_format,
        embed=False,
        auto_generated=auto_generated,
    )
    opts.update(with_base_ydl_opts({
        "outtmpl": {"default": "%(title)s.%(ext)s"},
        "paths": {"home": str(output_path)},
        "skip_download": True,
    }))

    downloaded: list[Path] = []

    with yt_dlp.YoutubeDL(cast(Any, opts)) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            return downloaded

    # Scan output dir for subtitle files created by yt-dlp
    title = info.get("title", "")
    if title:
        import glob
        escaped_title = glob.escape(title)
        for sub_file in output_path.glob(f"*{escaped_title}*"):
            if sub_file.suffix.lstrip(".") in ("srt", "vtt", "ass", "json3", "srv1", "srv2", "srv3"):
                downloaded.append(sub_file)

    # Also check requested_downloads
    for dl in info.get("requested_subtitles", {}).values():
        if filepath := dl.get("filepath"):
            p = Path(filepath)
            if p.exists() and p not in downloaded:
                downloaded.append(p)

    logger.info("Downloaded %d subtitle file(s) for %s", len(downloaded), url)
    return downloaded


def build_subtitle_opts(
    *,
    languages: list[str] | None = None,
    subtitle_format: str = SubtitleFormat.SRT,
    embed: bool = False,
    auto_generated: bool = True,
) -> dict[str, Any]:
    """Build yt-dlp options for subtitle handling.

    Args:
        languages: Language codes to download. ``None`` = all available.
        subtitle_format: Desired subtitle format.
        embed: If True, embed subtitles into the video container.
        auto_generated: Also download auto-generated subs.

    Returns:
        A dict of yt-dlp options for subtitle configuration.
    """
    opts: dict[str, Any] = {
        "writesubtitles": True,
        "subtitlesformat": subtitle_format,
    }

    if auto_generated:
        opts["writeautomaticsub"] = True

    if languages:
        opts["subtitleslangs"] = normalize_subtitle_languages(languages)
    else:
        opts["subtitleslangs"] = ["all"]

    if embed:
        # Subtitle embedding is handled via postprocessor
        if "postprocessors" not in opts:
            opts["postprocessors"] = []
        opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})

    # Convert subtitle format via postprocessor
    opts.setdefault("postprocessors", [])
    opts["postprocessors"].append({
        "key": "FFmpegSubtitlesConvertor",
        "format": subtitle_format,
    })

    return opts


def normalize_subtitle_languages(languages: list[str] | tuple[str, ...]) -> list[str]:
    """Expand simple language codes to include regional/auto-caption variants."""
    expanded: list[str] = []
    for lang in languages:
        clean = str(lang).strip()
        if not clean:
            continue
        expanded.append(clean)
    return list(dict.fromkeys(expanded))


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

# Common language code → name mappings (extensible)
_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)",
    "ar": "Arabic",
    "hi": "Hindi",
    "nl": "Dutch",
    "sv": "Swedish",
    "pl": "Polish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
    "uk": "Ukrainian",
    "cs": "Czech",
    "ro": "Romanian",
    "hu": "Hungarian",
    "el": "Greek",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
    "he": "Hebrew",
}


def _language_name(code: str) -> str:
    """Get a human-readable name for a language code.

    Args:
        code: ISO 639-1 language code.

    Returns:
        The language name, or the code itself if not recognised.
    """
    # Handle codes like "en-US" → try "en"
    base = code.split("-")[0] if "-" in code and code not in _LANGUAGE_NAMES else code
    return _LANGUAGE_NAMES.get(base, code)


def cleanup_leftover_subtitles(video_path: Path, title: str) -> None:
    """Find and delete external subtitle files matching the video.

    Checks the directory of `video_path` for files with subtitle extensions
    that match the video's filename stem (ignoring trailing spaces, etc.).
    """
    if not video_path:
        return

    parent_dir = video_path.parent
    if not parent_dir.exists():
        return

    # Get normalized base name of the video file (lowercase, stripped)
    video_stem = video_path.stem.strip().lower()

    # We also check the title normalized
    from core.utils import sanitize_filename
    sanitized_title = sanitize_filename(title).strip().lower()

    sub_exts = {".srt", ".vtt", ".ass", ".sbv", ".lrc"}

    logger.debug("Cleaning up subtitles for %s in %s", video_path.name, parent_dir)

    for item in parent_dir.iterdir():
        if item.is_file() and item.suffix.lower() in sub_exts:
            item_name = item.name.lower()

            # Check if this subtitle belongs to our video.
            # It should start with the video stem or sanitized title (ignoring spaces/punctuation differences)
            match = False

            # Direct startswith checks
            if item_name.startswith(video_stem):
                match = True
            elif item_name.startswith(sanitized_title):
                match = True

            # If there's a space or dot, e.g. "video_title .en.srt" or "video_title.en.srt"
            # let's do a normalized comparison by stripping spaces and punctuation
            if not match:
                norm_item = _NORMALIZE_NAME_PATTERN.sub('', item_name)
                norm_video = _NORMALIZE_NAME_PATTERN.sub('', video_stem)
                norm_title = _NORMALIZE_NAME_PATTERN.sub('', sanitized_title)

                # Subtitle files contain the language code, so they will be longer than the video stem.
                # We check if the normalized item starts with the normalized video stem/title.
                if norm_video and norm_item.startswith(norm_video):
                    match = True
                elif norm_title and norm_item.startswith(norm_title):
                    match = True

            if match:
                try:
                    item.unlink()
                    logger.info("Cleaned up residue subtitle file: %s", item.name)
                except OSError as e:
                    logger.warning("Failed to delete residue subtitle %s: %s", item.name, e)
