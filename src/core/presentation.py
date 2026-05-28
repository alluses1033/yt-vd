"""Shared presentation helpers for CLI and interactive flows."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core.thumbnail_renderer import get_ansi_thumbnail


def build_entry_titles(entries: list[dict[str, Any]], *, start_index: int = 1) -> list[str]:
    """Build stable display titles for a list of playlist-like entries."""
    return [
        entry.get("title") or f"Video {idx}"
        for idx, entry in enumerate(entries, start_index)
    ]


def render_result_thumbnails(
    results: list[Any],
    *,
    width: int = 32,
    height: int = 12,
    max_workers: int = 6,
) -> dict[str, str | None]:
    """Render ANSI thumbnails concurrently for search-style result objects."""
    if not results:
        return {}

    workers = min(max_workers, len(results))
    output: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(get_ansi_thumbnail, entry.thumbnail_url, width, height): entry
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
