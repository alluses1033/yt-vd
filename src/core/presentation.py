"""Shared presentation helpers for CLI and interactive flows."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core.thumbnail_renderer import TerminalImage, get_ansi_thumbnail

SEARCH_THUMBNAIL_SIZE = (43, 12)
MIN_SEARCH_THUMBNAIL_WIDTH = 115


def build_entry_titles(entries: list[dict[str, Any]], *, start_index: int = 1) -> list[str]:
    """Build stable display titles for a list of playlist-like entries."""
    return [
        entry.get("title") or f"Video {idx}"
        for idx, entry in enumerate(entries, start_index)
    ]


def get_search_thumbnail_size(
    terminal_width: int,
    *,
    is_terminal: bool,
    has_results: bool,
) -> tuple[int, int] | None:
    """Return the search thumbnail size in terminal cells, or None when hidden."""
    if not is_terminal or not has_results or terminal_width < MIN_SEARCH_THUMBNAIL_WIDTH:
        return None
    return SEARCH_THUMBNAIL_SIZE


def render_result_thumbnails(
    results: list[Any],
    *,
    width: int = 32,
    height: int = 12,
    max_workers: int = 6,
    force_ansi: bool = True,
) -> dict[str, TerminalImage | None]:
    """Render ANSI thumbnails concurrently for search-style result objects.

    Args:
        results: Search result objects with ``thumbnail_url`` and ``url`` attributes.
        width: Thumbnail width in terminal columns.
        height: Thumbnail height in terminal rows.
        max_workers: Maximum number of concurrent download threads.
        force_ansi: If True (default), always use ANSI half-block rendering.
            This prevents Sixel/Kitty inline protocols from corrupting
            Rich table layout.
    """
    if not results:
        return {}

    workers = min(max_workers, len(results))
    output: dict[str, TerminalImage | None] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                get_ansi_thumbnail, entry.thumbnail_url, width, height,
                force_ansi=force_ansi,
            ): entry
            for entry in results
            if getattr(entry, "thumbnail_url", None)
        }
        for future, entry in futures.items():
            entry_url = getattr(entry, "url", "") or ""
            try:
                output[entry_url] = future.result()
            except Exception:
                output[entry_url] = None
    return output
