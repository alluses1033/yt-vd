"""Interactive mode for yt-vd.

Presents a questionary-powered menu when ``yt-vd`` is invoked with no
arguments.  Each menu item collects the necessary inputs and delegates to
the core engine, re-using the same Rich output helpers as the CLI commands.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import questionary
from questionary import Style as QStyle
from rich.panel import Panel
from rich.text import Text

from constants import (
    AudioBitrate,
    AudioFormat,
    QualityPreset,
    VideoFormat,
)
from core.display import console
from core.display import show_result_panel as _show_result
from core.display import show_summary_table as _show_results_table
from core.presentation import render_result_thumbnails
from core.usecases import playlist_titles_from_info
from core.utils import ask_with_resize_monitor, format_duration

logger = logging.getLogger(__name__)

# ── Questionary theming ──────────────────────────────────────────────────────

CUSTOM_STYLE = QStyle(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "fg:white bold"),
        ("answer", "fg:green bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
        ("separator", "fg:magenta"),
        ("instruction", "fg:#808080"),
        ("text", ""),
    ]
)

# ── Shared prompt helpers ────────────────────────────────────────────────────


def _ask_url(label: str = "YouTube URL") -> str | None:
    """Prompt for a YouTube URL and return it (or None on cancel)."""
    url = questionary.text(f"{label}:", style=CUSTOM_STYLE).ask()
    if not url:
        console.print("[yellow]No URL provided — returning to menu.[/]")
        return None
    val = str(url).strip()
    if not val:
        console.print("[yellow]No URL provided — returning to menu.[/]")
        return None
    return val


def _ask_quality() -> str:
    """Prompt the user to select a quality preset."""
    choices = [
        questionary.Choice("Best (no limit)", value=QualityPreset.BEST),
        questionary.Choice("High (1080p)", value=QualityPreset.HIGH),
        questionary.Choice("Medium (720p)", value=QualityPreset.MEDIUM),
        questionary.Choice("Better (480p)", value=QualityPreset.BETTER),
        questionary.Choice("Low (360p)", value=QualityPreset.LOW),
        questionary.Choice("Lowest (240p)", value=QualityPreset.LOWEST),
    ]
    return questionary.select(
        "Quality:", choices=choices, default=QualityPreset.BEST, style=CUSTOM_STYLE
    ).ask() or QualityPreset.BEST


def _ask_video_format() -> str:
    """Prompt the user to select a video container format."""
    choices = [
        questionary.Choice("MP4  (recommended)", value=VideoFormat.MP4),
        questionary.Choice("MKV  (more codec support)", value=VideoFormat.MKV),
        questionary.Choice("WEBM (web optimised)", value=VideoFormat.WEBM),
    ]
    return questionary.select(
        "Format:", choices=choices, default=VideoFormat.MP4, style=CUSTOM_STYLE
    ).ask() or VideoFormat.MP4


def _ask_audio_format() -> str:
    """Prompt the user to select an audio format."""
    choices = [
        questionary.Choice("MP3   (universal)", value=AudioFormat.MP3),
        questionary.Choice("M4A   (Apple / AAC)", value=AudioFormat.M4A),
        questionary.Choice("OPUS  (best ratio)", value=AudioFormat.OPUS),
        questionary.Choice("FLAC  (lossless)", value=AudioFormat.FLAC),
        questionary.Choice("WAV   (uncompressed)", value=AudioFormat.WAV),
    ]
    return questionary.select(
        "Audio format:", choices=choices, default=AudioFormat.MP3, style=CUSTOM_STYLE
    ).ask() or AudioFormat.MP3


def _ask_bitrate() -> str:
    """Prompt the user to select an audio bitrate."""
    choices = [
        questionary.Choice("320k  (best)", value=AudioBitrate.BEST),
        questionary.Choice("256k  (very good)", value=AudioBitrate.HIGH),
        questionary.Choice("192k  (good)", value=AudioBitrate.MEDIUM),
        questionary.Choice("128k  (acceptable)", value=AudioBitrate.LOW),
    ]
    return questionary.select(
        "Bitrate:", choices=choices, default=AudioBitrate.BEST, style=CUSTOM_STYLE
    ).ask() or AudioBitrate.BEST


def _ask_output_dir() -> str:
    """Prompt for an output directory path."""
    default_path = str(Path.home() / "Downloads")
    path = questionary.path(
        "Output directory:",
        default=default_path,
        only_directories=True,
        style=CUSTOM_STYLE,
    ).ask()
    if path:
        path = path.strip().strip('"').strip("'")
        candidate = Path(path)
        if not candidate.is_absolute() and candidate.parts and candidate.parts[0] not in (".", ".."):
            path = str(Path.home() / candidate)
    return path or default_path


def _ask_parallel() -> int:
    """Prompt for number of parallel workers."""
    from constants import DEFAULT_PARALLEL_WORKERS

    raw = questionary.text(
        f"Parallel workers (default {DEFAULT_PARALLEL_WORKERS}):",
        default=str(DEFAULT_PARALLEL_WORKERS),
        style=CUSTOM_STYLE,
    ).ask()
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_PARALLEL_WORKERS


def _ask_subtitles() -> tuple[bool, str]:
    """Ask if the user wants subtitles and which language."""
    want = questionary.confirm(
        "Download subtitles?", default=False, style=CUSTOM_STYLE
    ).ask()
    lang = "en"
    if want:
        lang = questionary.text(
            "Subtitle language code (e.g. en, ja, es):",
            default="en",
            style=CUSTOM_STYLE,
        ).ask() or "en"
    return bool(want), lang


def _ask_thumbnail() -> bool:
    return bool(
        questionary.confirm(
            "Embed thumbnail?", default=False, style=CUSTOM_STYLE
        ).ask()
    )


# ── Menu actions ─────────────────────────────────────────────────────────────


def _action_download_video() -> None:
    """Collect inputs and download a single video."""
    url = _ask_url()
    if not url:
        return

    quality = _ask_quality()
    fmt = _ask_video_format()
    output = _ask_output_dir()
    subs, sub_lang = _ask_subtitles()
    thumbnail = _ask_thumbnail()

    console.print()
    console.print(
        Panel(
            f"[bold]Downloading:[/] {url}\n"
            f"[bold]Quality:[/] {quality}  [bold]Format:[/] {fmt}\n"
            f"[bold]Output:[/] {output}  [bold]Subs:[/] {sub_lang if subs else 'no'}",
            title="[bold cyan]Download Settings[/]",
            border_style="cyan",
        )
    )

    from core.downloader import download_video
    from core.progress import TerminalProgress

    with TerminalProgress(console, "Download") as progress_callback:
        result = download_video(
            url=url,
            quality=quality,
            fmt=fmt,
            output_dir=output,
            subtitles=subs,
            sub_lang=sub_lang,
            embed_thumbnail=thumbnail,
            progress_callback=progress_callback,
        )

    _show_result(result)


def _download_playlist_interactive(url: str) -> None:
    """Interactively configure and download a playlist."""
    quality = _ask_quality()
    fmt = _ask_video_format()
    output = _ask_output_dir()
    parallel = _ask_parallel()

    start_raw = questionary.text(
        "Start index (default 1):", default="1", style=CUSTOM_STYLE
    ).ask()
    end_raw = questionary.text(
        "End index (leave blank for all):", default="", style=CUSTOM_STYLE
    ).ask()

    try:
        start = max(1, int(start_raw or 1))
    except (TypeError, ValueError):
        start = 1
    end = int(end_raw) if end_raw and end_raw.strip().isdigit() else None

    subs, sub_lang = _ask_subtitles()
    thumbnail = _ask_thumbnail()

    console.print()
    console.print(
        Panel(
            f"[bold]Playlist:[/] {url}\n"
            f"[bold]Quality:[/] {quality}  [bold]Format:[/] {fmt}\n"
            f"[bold]Range:[/] {start}–{end or 'end'}  [bold]Workers:[/] {parallel}\n"
            f"[bold]Subtitles:[/] {sub_lang if subs else 'No'}  [bold]Thumbnail:[/] {'Yes' if thumbnail else 'No'}",
            title="[bold yellow]Playlist Settings[/]",
            border_style="yellow",
        )
    )

    from core.playlist import download_playlist, get_playlist_info

    info = None
    with console.status("[cyan]Fetching playlist info...[/]"):
        try:
            info = get_playlist_info(url)
        except Exception as e:
            console.print(f"[red]Error fetching playlist info: {e}[/]")
            logger.debug("Interactive playlist info preview unavailable for %s: %s", url, e)

    titles = playlist_titles_from_info(info, start=start, end=end)

    from core.progress import MultiTerminalProgress

    if titles:
        with MultiTerminalProgress(console, titles) as progress_callback:
            results = download_playlist(
                url=url,
                quality=quality,
                fmt=fmt,
                output_dir=output,
                start=start,
                end=end,
                parallel=parallel,
                subtitles=subs,
                sub_lang=sub_lang,
                embed_thumbnail=thumbnail,
                on_progress=progress_callback,
            )
    else:
        results = download_playlist(
            url=url,
            quality=quality,
            fmt=fmt,
            output_dir=output,
            start=start,
            end=end,
            parallel=parallel,
            subtitles=subs,
            sub_lang=sub_lang,
            embed_thumbnail=thumbnail,
        )

    _show_results_table(results)


def _action_download_playlist() -> None:
    """Collect inputs and download a playlist."""
    url = _ask_url("Playlist URL")
    if not url:
        return
    _download_playlist_interactive(url)


def _action_extract_audio() -> None:
    """Collect inputs and extract audio."""
    url = _ask_url()
    if not url:
        return

    audio_fmt = _ask_audio_format()
    bitrate = _ask_bitrate()
    output = _ask_output_dir()
    thumbnail = _ask_thumbnail()

    console.print()
    console.print(
        Panel(
            f"[bold]URL:[/] {url}\n"
            f"[bold]Format:[/] {audio_fmt}  [bold]Bitrate:[/] {bitrate}\n"
            f"[bold]Thumbnail:[/] {'yes' if thumbnail else 'no'}",
            title="[bold green]Audio Settings[/]",
            border_style="green",
        )
    )

    from core.audio import extract_audio
    from core.progress import TerminalProgress

    with TerminalProgress(console, "Audio") as progress_callback:
        result = extract_audio(
            url=url,
            audio_format=audio_fmt,
            bitrate=bitrate,
            output_dir=output,
            embed_thumbnail=thumbnail,
            progress_callback=progress_callback,
        )

    _show_result(result)


def _action_search() -> None:
    """Search YouTube and optionally download a result."""
    query = questionary.text("Search query:", style=CUSTOM_STYLE).ask()
    if not query or not query.strip():
        console.print("[yellow]No query provided — returning to menu.[/]")
        return

    count_raw = questionary.text(
        "Number of results per page (default 10):", default="10", style=CUSTOM_STYLE
    ).ask()
    try:
        count = max(1, int(count_raw or 10))
    except ValueError:
        count = 10

    from core.search import search_youtube

    current_page = 1
    while True:
        console.clear()
        console.print(f"\n[cyan]Searching for:[/] [bold]{query.strip()}[/] (Page {current_page}) ...\n")
        results = search_youtube(query=query.strip(), max_results=count, page=current_page)

        if not results:
            console.print("[red]No results found.[/]")
            if current_page > 1:
                choice = questionary.select(
                    "What would you like to do?",
                    choices=["Go back to previous page", "New search query", "Exit"],
                    style=CUSTOM_STYLE,
                ).ask()
                if choice == "Go back to previous page":
                    current_page -= 1
                    continue
                elif choice == "New search query":
                    new_query = questionary.text("Enter search query:", style=CUSTOM_STYLE).ask()
                    if new_query and new_query.strip():
                        query = new_query.strip()
                        current_page = 1
                    continue
                else:
                    break
            else:
                break

        # Check if console is a terminal
        is_term = bool(getattr(console, "is_terminal", False))

        ansi_thumbnails = {}
        if is_term and results:
            with console.status("[cyan]Rendering thumbnails...[/]"):
                ansi_thumbnails = render_result_thumbnails(results, width=32, height=12)

        from rich.table import Table
        from rich.text import Text

        def draw_search_results_table():
            console.clear()
            table = Table(
                title=f"Search Results (Page {current_page})",
                show_header=True,
                header_style="bold cyan",
                border_style="cyan",
                expand=True,
            )
            table.add_column("#", style="dim", width=4, justify="right")
            table.add_column("Thumbnail", width=32, justify="center", no_wrap=True)
            table.add_column("Title", style="bold white", ratio=3)
            table.add_column("Channel", style="green", no_wrap=True)
            table.add_column("Duration", justify="center", width=10)
            table.add_column("Views", justify="right", width=12)
            table.add_column("Link", style="dim cyan", ratio=2)

            for i, entry in enumerate(results, 1):
                dur = entry.duration
                dur_str = format_duration(dur) if dur else "N/A"
                views = entry.view_count
                views_str = f"{views:,}" if views else "N/A"
                entry_url = entry.url or "N/A"

                thumb_ansi = ansi_thumbnails.get(entry_url)
                thumb_render = thumb_ansi if thumb_ansi else Text("No Image", style="dim")

                table.add_row(
                    str(i),
                    thumb_render,
                    entry.title or "Unknown",
                    entry.uploader or "Unknown",
                    dur_str,
                    views_str,
                    entry_url,
                )

            console.print(table)
            console.print()

        draw_search_results_table()

        choices = ["Download a result", "Next page of results"]
        if current_page > 1:
            choices.append("Previous page of results")
        choices.extend(["New search query", "Exit"])

        while True:
            action = ask_with_resize_monitor(
                lambda: questionary.select(
                    "What would you like to do next?",
                    choices=choices,
                    style=CUSTOM_STYLE,
                ).ask(),
                on_resize=draw_search_results_table
            )
            if action != "RESIZE":
                break

        if action == "Download a result":
            while True:
                idx_raw = ask_with_resize_monitor(
                    lambda: questionary.text(
                        f"Enter result number (1-{len(results)}):", style=CUSTOM_STYLE
                    ).ask(),
                    on_resize=draw_search_results_table
                )
                if idx_raw != "RESIZE":
                    break
            if idx_raw == "RESIZE":
                continue
            try:
                idx = int(idx_raw) - 1
                if 0 <= idx < len(results):
                    selected = results[idx]
                    selected_url = selected.url
                    console.print(f"\n[cyan]Selected:[/] [bold]{selected.title}[/]")

                    if selected.thumbnail_url and is_term:
                        from core.thumbnail_renderer import get_ansi_thumbnail
                        with console.status("[cyan]Loading preview...[/]"):
                            large_ansi = get_ansi_thumbnail(selected.thumbnail_url, 72, 22)
                        if large_ansi:
                            console.print(Panel(large_ansi, title="[cyan]Video Preview[/]", border_style="cyan", expand=False))

                    is_playlist = "[Playlist]" in selected.title or "playlist" in selected_url

                    if is_playlist:
                        _download_playlist_interactive(selected_url)
                    else:
                        quality = _ask_quality()
                        fmt = _ask_video_format()
                        output = _ask_output_dir()
                        subs, sub_lang = _ask_subtitles()
                        thumbnail = _ask_thumbnail()

                        from core.downloader import download_video
                        from core.progress import TerminalProgress

                        with TerminalProgress(console, "Download") as progress_callback:
                            result = download_video(
                                url=selected_url,
                                quality=quality,
                                fmt=fmt,
                                output_dir=output,
                                subtitles=subs,
                                sub_lang=sub_lang,
                                embed_thumbnail=thumbnail,
                                progress_callback=progress_callback,
                            )
                        _show_result(result)
                else:
                    console.print("[red]Invalid selection.[/]")
            except (ValueError, TypeError) as e:
                console.print(f"[red]Invalid input: {e}[/]")
            continue
        elif action == "Next page of results":
            current_page += 1
            continue
        elif action == "Previous page of results":
            current_page = max(1, current_page - 1)
            continue
        elif action == "New search query":
            new_query = questionary.text("Enter search query:", style=CUSTOM_STYLE).ask()
            if new_query and new_query.strip():
                query = new_query.strip()
                current_page = 1
            continue
        else:
            break


def _action_video_info() -> None:
    """Show detailed video information."""
    url = _ask_url()
    if not url:
        return

    console.print("\n[cyan]Fetching info...[/]\n")

    from core.metadata import get_video_info

    info = get_video_info(url)

    if not info:
        console.print("[red]Could not retrieve video information.[/]")
        return

    dur_str = format_duration(info.duration) if info.duration else "N/A"
    views_str = f"{info.view_count:,}" if info.view_count else "N/A"

    from rich.table import Table

    details = Table(show_header=False, border_style="cyan", expand=True, pad_edge=True)
    details.add_column("Field", style="bold cyan", min_width=18)
    details.add_column("Value", style="white")

    details.add_row("Title", info.title)
    details.add_row("Channel", info.uploader)
    details.add_row("Duration", dur_str)
    details.add_row("Views", views_str)
    details.add_row("Upload Date", info.upload_date or "N/A")
    details.add_row("Video ID", info.video_id)

    if info.available_qualities:
        details.add_row("Qualities", ", ".join(info.available_qualities))

    if info.subtitles:
        details.add_row("Subtitles", ", ".join(sorted(info.subtitles.keys())))

    if info.chapters:
        chapters_str = "\n".join(
            f"  {ch.get('title', 'Chapter')} ({ch.get('start_time', 0):.0f}s)"
            for ch in info.chapters[:10]
        )
        if len(info.chapters) > 10:
            chapters_str += f"\n  ... and {len(info.chapters) - 10} more"
        details.add_row("Chapters", chapters_str)

    console.print(
        Panel(details, title="[bold cyan]Video Info[/]", border_style="cyan")
    )


def _action_help() -> None:
    """Show the built-in manual."""
    from manual import show_manual

    show_manual()

def _action_download_channel() -> None:
    """Download videos from a YouTube channel."""
    url = _ask_url("YouTube Channel URL")
    if not url:
        return
    last_n_str = questionary.text(
        "Number of recent videos to download (default 10):",
        default="10",
        style=CUSTOM_STYLE,
    ).ask()
    if last_n_str is None:
        return
    try:
        last_n = int(last_n_str)
    except ValueError:
        last_n = 10

    quality = _ask_quality()
    fmt = _ask_video_format()
    output_dir = _ask_output_dir()
    parallel = _ask_parallel()

    from core.playlist import download_channel
    console.print(f"\n[cyan]Fetching channel metadata for {url}...[/]")
    results = download_channel(
        url,
        last_n=last_n,
        quality=quality,
        fmt=fmt,
        output_dir=output_dir,
        parallel=parallel,
    )
    _show_results_table(results)


def _action_download_batch() -> None:
    """Download videos from a batch text file."""
    file_path = questionary.text(
        "Path to text file containing URLs:",
        style=CUSTOM_STYLE,
    ).ask()
    if not file_path:
        return
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        console.print("[bold red]Error:[/] File not found or is not a file.")
        return

    # Read URLs
    urls = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    except Exception as e:
        console.print(f"[bold red]Error reading file:[/] {e}")
        return

    if not urls:
        console.print("[yellow]No URLs found in file.[/]")
        return

    quality = _ask_quality()
    fmt = _ask_video_format()
    output_dir = _ask_output_dir()
    parallel = _ask_parallel()

    from core.parallel import download_parallel
    entries = [{"url": url} for url in urls]

    console.print(f"\n[cyan]Starting batch download of {len(urls)} URLs...[/]")
    results = download_parallel(
        entries,
        quality=quality,
        fmt=fmt,
        output_dir=output_dir,
        workers=parallel,
    )
    _show_results_table(results)


def _action_download_clip() -> None:
    """Download a specific time range from a video."""
    url = _ask_url("YouTube Video URL")
    if not url:
        return
    start = questionary.text(
        "Start time (e.g. 01:30 or 10:00, leave blank for beginning):",
        style=CUSTOM_STYLE,
    ).ask()
    if start is None:
        return
    end = questionary.text(
        "End time (e.g. 03:45 or 12:30, leave blank for end of video):",
        style=CUSTOM_STYLE,
    ).ask()
    if end is None:
        return

    if not start.strip() and not end.strip():
        console.print("[bold red]Error:[/] Specify at least start or end time.")
        return

    quality = _ask_quality()
    fmt = _ask_video_format()
    output_dir = _ask_output_dir()

    from core.downloader import download_clip
    from core.progress import TerminalProgress

    with TerminalProgress(console, "Clip") as progress_callback:
        result = download_clip(
            url=url,
            start_time=start.strip() or None,
            end_time=end.strip() or None,
            quality=quality,
            fmt=fmt,
            output_dir=output_dir,
            progress_callback=progress_callback,
        )
    _show_result(result)


def _action_download_chapters() -> None:
    """Download a video split by chapter markers."""
    url = _ask_url("YouTube Video URL")
    if not url:
        return
    quality = _ask_quality()
    fmt = _ask_video_format()
    output_dir = _ask_output_dir()

    from core.metadata import download_by_chapters
    from core.progress import TerminalProgress

    with TerminalProgress(console, "Chapters") as progress_callback:
        results = download_by_chapters(
            url=url,
            quality=quality,
            fmt=fmt,
            output_dir=output_dir,
            progress_callback=progress_callback,
        )
    _show_results_table(results)


def _action_history() -> None:
    """Show or manage download history."""
    from core.history import clear_history, get_history
    choice = questionary.select(
        "History Management:",
        choices=[
            questionary.Choice("Show recent entries", value="show"),
            questionary.Choice("Clear all history", value="clear"),
            questionary.Choice("Back to main menu", value="back"),
        ],
        style=CUSTOM_STYLE,
    ).ask()

    if choice == "clear":
        confirm = questionary.confirm(
            "Are you sure you want to clear all history?",
            default=False,
            style=CUSTOM_STYLE,
        ).ask()
        if confirm:
            clear_history()
            console.print("[green]Download history cleared.[/]")
    elif choice == "show":
        limit_str = questionary.text(
            "Number of entries to show (default 20):",
            default="20",
            style=CUSTOM_STYLE,
        ).ask()
        try:
            limit = int(limit_str)
        except (ValueError, TypeError):
            limit = 20

        entries = get_history(limit=limit)
        if not entries:
            console.print("[yellow]No download history found.[/]")
            return

        from rich.table import Table

        from core.utils import format_file_size
        def draw_history_table():
            console.clear()
            table = Table(
                title=f"Download History (last {limit})",
                show_header=True,
                header_style="bold cyan",
                border_style="cyan",
            )
            table.add_column("#", style="dim", justify="right")
            table.add_column("Downloaded At", style="cyan")
            table.add_column("Title", style="bold white")
            table.add_column("Quality", justify="center")
            table.add_column("Size", justify="right")

            for idx, entry in enumerate(entries, 1):
                size = format_file_size(entry["file_size"]) if entry.get("file_size") else "N/A"
                dt_str = entry.get("downloaded_at", "Unknown")
                if "T" in dt_str:
                    dt_str = dt_str.split(".")[0].replace("T", " ")
                table.add_row(
                    str(idx),
                    dt_str,
                    entry.get("title") or "Unknown",
                    entry.get("quality") or "N/A",
                    size,
                )
            console.print()
            console.print(table)
            console.print()

        draw_history_table()
        while True:
            res = ask_with_resize_monitor(
                lambda: questionary.press_any_key_to_continue(
                    "Press any key to return to history menu...",
                    style=CUSTOM_STYLE
                ).ask(),
                on_resize=draw_history_table
            )
            if res != "RESIZE":
                break


# ── Main menu loop ───────────────────────────────────────────────────────────

MENU_CHOICES = [
    questionary.Choice("Download Video", value="download"),
    questionary.Choice("Download Playlist", value="playlist"),
    questionary.Choice("Download Channel", value="channel"),
    questionary.Choice("Download Batch File", value="batch"),
    questionary.Choice("Download Clip Range", value="clip"),
    questionary.Choice("Download Split by Chapters", value="chapters"),
    questionary.Choice("Extract Audio", value="audio"),
    questionary.Choice("Search YouTube", value="search"),
    questionary.Choice("View Video Info", value="info"),
    questionary.Choice("View Download History", value="history"),
    questionary.Choice("Help Manual", value="manual"),
    questionary.Separator(),
    questionary.Choice("Exit", value="exit"),
]

ACTIONS: dict[str, Callable[[], None]] = {
    "download": _action_download_video,
    "playlist": _action_download_playlist,
    "channel": _action_download_channel,
    "batch": _action_download_batch,
    "clip": _action_download_clip,
    "chapters": _action_download_chapters,
    "audio": _action_extract_audio,
    "search": _action_search,
    "info": _action_video_info,
    "history": _action_history,
    "manual": _action_help,
}



def run_interactive() -> None:
    """Launch the interactive yt-vd menu loop."""
    console.print()
    console.print(
        Panel(
            Text.assemble(
                Text("yt-vd", style="bold magenta"),
                Text("  •  Interactive Mode", style="dim"),
                "\n",
                Text("Select an option below to get started.", style="italic"),
            ),
            border_style="bright_magenta",
            padding=(1, 4),
        )
    )

    while True:
        console.print()
        choice = questionary.select(
            "What would you like to do?",
            choices=MENU_CHOICES,
            style=CUSTOM_STYLE,
        ).ask()

        if choice is None or choice == "exit":
            console.print("\n[bold magenta]Goodbye![/]\n")
            raise SystemExit(0)

        action = ACTIONS.get(choice)
        if action:
            try:
                action()
            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted — returning to menu.[/]")
            except Exception as exc:
                console.print(f"\n[bold red]Error:[/] {exc}")
        else:
            console.print(f"[red]Unknown action: {choice}[/]")
