"""Shared non-UI workflow helpers for CLI and interactive modes."""

from __future__ import annotations

from typing import Any

from constants import PlaylistInfo
from core.presentation import build_entry_titles


def slice_entries(
    entries: list[dict[str, Any]],
    *,
    start: int = 1,
    end: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return a 1-based slice and the computed start index."""
    start_idx = max(0, start - 1)
    end_idx = end if end is not None else len(entries)
    return entries[start_idx:end_idx], start_idx


def playlist_titles_from_info(
    info: PlaylistInfo | None,
    *,
    start: int = 1,
    end: int | None = None,
) -> list[str]:
    """Build display titles for a playlist range."""
    if not info or not info.entries:
        return []
    sliced_entries, start_idx = slice_entries(info.entries, start=start, end=end)
    return build_entry_titles(sliced_entries, start_index=start_idx + 1)


def channel_titles_from_info(
    info: PlaylistInfo | None,
    *,
    last_n: int,
) -> list[str]:
    """Build display titles for most-recent channel entries."""
    if not info or not info.entries:
        return []
    selected = info.entries[: max(0, last_n)]
    return build_entry_titles(selected, start_index=1)
