"""Shared presentation helpers for CLI and interactive flows."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core.thumbnail_renderer import TerminalImage, get_ansi_thumbnail

# (width in terminal columns, height in terminal rows)
# Correct 16:9 ratio for standard 8×16 px cells:
#   display_aspect = (width × 8) / (height × 16) = width / (height × 2)
#   For 16:9: width / (height × 2) = 16/9  →  width/height ≈ 3.56
#   (48, 14): 48 / (14×2) = 48/28 = 1.71  ≈ 16:9 ✓
SEARCH_THUMBNAIL_SIZE = (48, 14)
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
    width: int = 48,
    height: int = 14,
    max_workers: int = 6,
    force_ansi: bool = False,
) -> dict[str, TerminalImage | None]:
    """Render thumbnails concurrently for search-style result objects.

    Args:
        results: Search result objects with ``thumbnail_url`` and ``url`` attributes.
        width: Thumbnail width in terminal columns.
        height: Thumbnail height in terminal rows.
        max_workers: Maximum number of concurrent download threads.
        force_ansi: If True, force ANSI half-block fallback regardless of terminal
            protocol. Default is False — Sixel/Kitty are used when available because
            thumbnails are rendered via :func:`draw_result_tiles` which uses a
            cursor-overlay tile layout (not Rich table cells).
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


def draw_result_tiles(
    results: list[Any],
    thumbnails: dict[str, TerminalImage | None],
    *,
    thumb_w: int,
    thumb_h: int,
    terminal_width: int,
    page: int,
    console: Any,
) -> None:
    """Draw search results as side-by-side image+text tiles.

    For Sixel / Kitty / iTerm2 thumbnails (``is_inline=True``): the image is
    printed first (the terminal renders it inline), then cursor-up + cursor-right
    moves the text cursor alongside the image so the result metadata is overlaid
    to the right of the thumbnail.  No Rich table cell tricks are needed.

    For ANSI half-block thumbnails (``is_inline=False``): the half-block lines are
    printed one by one with metadata text appended to the first few lines.

    Args:
        results: Ordered list of search result objects.
        thumbnails: Mapping of result URL → rendered TerminalImage (or None).
        thumb_w: Thumbnail column width in characters.
        thumb_h: Thumbnail height in terminal rows.
        terminal_width: Full terminal width in characters.
        page: Current page number (for header).
        console: Rich Console instance for styled text output.
    """
    from core.utils import format_duration

    sep = "─" * terminal_width
    text_width = max(20, terminal_width - thumb_w - 4)

    console.print(
        f"\n[bold cyan]  Search Results — Page {page}[/]  "
        f"[dim](select by number below)[/]\n"
    )
    sys.stdout.flush()

    for i, entry in enumerate(results, 1):
        url = getattr(entry, "url", "") or ""
        thumb = thumbnails.get(url)
        raw_title = getattr(entry, "title", None) or "Unknown"
        channel = (getattr(entry, "uploader", None) or "Unknown")[:22]
        duration = getattr(entry, "duration", None)
        view_count = getattr(entry, "view_count", None)
        dur = format_duration(duration) if duration else "N/A"
        views = f"{view_count:,}" if view_count else "N/A"
        num_label = f"{i:2d}."

        if thumb is None:
            # No thumbnail available
            console.print(f"[bold cyan]{num_label}[/] [bold white]{raw_title[:text_width]}[/]")
            console.print(f"     [green]{channel}[/]  [cyan]{dur}[/]  {views}")
            console.print(f"[dim]{sep}[/]")
            continue

        raw_seq = thumb.raw_sequence

        if thumb.is_inline:
            # ── Sixel / Kitty / iTerm2 ─────────────────────────────────────────
            # 1. Print the image — terminal renders it at the current cursor row.
            #    After the DCS/OSC sequence the cursor is below the image (col 0).
            # 2. Move cursor back to the TOP of the image (up thumb_h rows).
            # 3. Move cursor RIGHT past the image + 2-char gap.
            # 4. Write text metadata lines alongside the image.
            # 5. Move cursor DOWN to just below the image for the separator.
            sys.stdout.write(raw_seq)
            sys.stdout.flush()
            # Back to top-left of image area, then right past it
            sys.stdout.write(f"\033[{thumb_h}A\033[{thumb_w + 2}C")
            title_text = raw_title[:max(1, text_width - len(num_label) - 1)]
            sys.stdout.write(
                f"\033[1;36m{num_label}\033[0m \033[1;37m{title_text}\033[0m\r\n"
            )
            sys.stdout.write(
                f"\033[{thumb_w + 3}C"
                f"\033[32m{channel}\033[0m  \033[36m{dur}\033[0m  {views}\r\n"
            )
            # Advance past the remaining image rows using newlines to force terminal scrolling/allocation
            remaining = thumb_h - 2
            if remaining > 0:
                sys.stdout.write("\n" * remaining)
            sys.stdout.flush()

        else:
            # ── ANSI half-block fallback ────────────────────────────────────────
            # Each element of lines is one terminal row of the image.
            # We print text metadata alongside the first few rows.
            lines = raw_seq.split("\n")
            for li, img_line in enumerate(lines):
                if li == 0:
                    aside = (
                        f"  \033[1;36m{num_label}\033[0m"
                        f" \033[1;37m{raw_title[:text_width]}\033[0m"
                    )
                elif li == 1:
                    aside = f"  \033[32m{channel}\033[0m"
                elif li == 2:
                    aside = f"  \033[36m{dur}\033[0m  {views}"
                else:
                    aside = ""
                sys.stdout.write(f"{img_line}{aside}\n")
            sys.stdout.flush()

        console.print(f"[dim]{sep}[/]")
