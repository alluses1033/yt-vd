"""YouTube search via yt-dlp for yt-vd.

Provides a simple search interface using yt-dlp's ``ytsearch`` extractor,
returning results as ``VideoInfo`` dataclass instances.
"""

from __future__ import annotations

import logging
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import yt_dlp

from constants import VideoInfo
from core.ydl_options import with_base_ydl_opts

logger = logging.getLogger(__name__)

_VIDEO_SEARCH_CACHE: dict[str, list[dict[str, Any]]] = {}
_PLAYLIST_SEARCH_CACHE: dict[str, list[dict[str, Any]]] = {}


def search_youtube(
    query: str,
    max_results: int = 10,
    page: int = 1,
) -> list[VideoInfo]:
    """Search YouTube for videos and playlists matching a query.

    Uses flat extraction for speed and a thread pool to query videos and playlists in parallel.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return.
        page: Page number for pagination.

    Returns:
        A list of ``VideoInfo`` instances for search results.
    """
    needed_limit = page * max_results

    # Run video search and playlist search in parallel
    def get_videos() -> list[dict[str, Any]]:
        cached = _VIDEO_SEARCH_CACHE.get(query, [])
        if len(cached) >= needed_limit:
            return cached[:needed_limit]

        opts = with_base_ydl_opts({
            "skip_download": True,
            "extract_flat": True,
            "ignoreerrors": True,
            "check_formats": False,
            "extractor_args": {
                "youtube": {
                    "skip": ["dash", "hls"],
                    "player_client": ["default"]
                }
            }
        })
        search_url = f"ytsearch{needed_limit}:{query}"
        results = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_url, download=False)
                if info and "entries" in info:
                    for entry in info["entries"]:
                        if entry:
                            results.append(entry)
        except Exception as e:
            logger.debug("Video search failed: %s", e)
            return cached[:needed_limit]
        _VIDEO_SEARCH_CACHE[query] = results
        if len(_VIDEO_SEARCH_CACHE) > 20:
            first_key = next(iter(_VIDEO_SEARCH_CACHE))
            _VIDEO_SEARCH_CACHE.pop(first_key, None)
        return results

    def get_playlists() -> list[dict[str, Any]]:
        cached = _PLAYLIST_SEARCH_CACHE.get(query, [])
        if len(cached) >= needed_limit:
            return cached[:needed_limit]

        opts = with_base_ydl_opts({
            "skip_download": True,
            "extract_flat": True,
            "ignoreerrors": True,
            "check_formats": False,
            "extractor_args": {
                "youtube": {
                    "skip": ["dash", "hls"],
                    "player_client": ["default"]
                }
            }
        })
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://www.youtube.com/results?search_query={encoded_query}&sp=EgIQAw%253D%253D"
        results = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_url, download=False)
                if info and "entries" in info:
                    for entry in info["entries"]:
                        if entry:
                            entry["_is_playlist"] = True
                            results.append(entry)
        except Exception as e:
            logger.debug("Playlist search failed: %s", e)
            return cached[:needed_limit]
        _PLAYLIST_SEARCH_CACHE[query] = results
        if len(_PLAYLIST_SEARCH_CACHE) > 20:
            first_key = next(iter(_PLAYLIST_SEARCH_CACHE))
            _PLAYLIST_SEARCH_CACHE.pop(first_key, None)
        return results

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_videos = executor.submit(get_videos)
        f_playlists = executor.submit(get_playlists)

        video_entries = f_videos.result()
        playlist_entries = f_playlists.result()

    # Interleave results to show a mix of videos and playlists
    combined_entries = []
    max_len = max(len(video_entries), len(playlist_entries))
    for i in range(max_len):
        if i < len(video_entries):
            combined_entries.append(video_entries[i])
        if i < len(playlist_entries):
            combined_entries.append(playlist_entries[i])
    combined_entries = _dedupe_entries(combined_entries)

    # Paginate by slicing the combined results
    start_idx = (page - 1) * max_results
    end_idx = page * max_results
    sliced_entries = combined_entries[start_idx:end_idx]

    video_infos: list[VideoInfo] = []
    for entry in sliced_entries:
        is_playlist = (
            entry.get("_is_playlist", False)
            or entry.get("_type") == "playlist"
            or "playlist" in entry.get("url", "")
            or "PL" in entry.get("id", "")
        )

        title = entry.get("title", "Unknown")
        if is_playlist and not title.startswith("[Playlist]"):
            title = f"[Playlist] {title}"

        # Parse thumbnail url using shared helper
        from core.utils import get_best_thumbnail_url
        thumb = get_best_thumbnail_url(entry)

        # Parse duration
        dur_val = entry.get("duration")
        duration = float(dur_val) if dur_val is not None else 0.0

        # Parse views
        views_val = entry.get("view_count")
        view_count = int(views_val) if views_val is not None else 0

        video_info = VideoInfo(
            title=title,
            url=_entry_url(entry),
            video_id=entry.get("id", ""),
            uploader=entry.get("uploader") or entry.get("channel") or "Unknown",
            duration=duration,
            view_count=view_count,
            upload_date=entry.get("upload_date", ""),
            description=entry.get("description", ""),
            thumbnail_url=thumb or "",
            formats=[],
            available_qualities=[],
            chapters=entry.get("chapters") or [],
            subtitles=entry.get("subtitles") or {},
        )
        video_infos.append(video_info)

    logger.info("Search for %r page %d returned %d results", query, page, len(video_infos))
    return video_infos


def _entry_url(entry: dict[str, Any]) -> str:
    webpage_url = entry.get("webpage_url")
    if webpage_url:
        return str(webpage_url)

    url = str(entry.get("url") or "")
    if url.startswith(("http://", "https://")):
        return url

    video_id = str(entry.get("id") or url)
    if video_id:
        if entry.get("_is_playlist") or "PL" in video_id:
            return f"https://www.youtube.com/playlist?list={video_id}"
        return f"https://www.youtube.com/watch?v={video_id}"
    return ""


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for entry in entries:
        key = _entry_url(entry) or str(entry.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped
