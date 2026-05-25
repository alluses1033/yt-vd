"""Interactive mode for yt-vd.

Presents a questionary-powered menu when ``yt-vd`` is invoked with no
arguments.  Each menu item collects the necessary inputs and delegates to
the core engine, re-using the same Rich output helpers as the CLI commands.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import questionary
from questionary import Style as QStyle
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from constants import (
    AudioBitrate,
    AudioFormat,
    QualityPreset,
    VideoFormat,
)

console = Console()

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


def _action_download_playlist() -> None:
    """Collect inputs and download a playlist."""
    url = _ask_url("Playlist URL")
    if not url:
        return

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

    start = max(1, int(start_raw or 1))
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

    titles = []
    if info and info.entries:
        start_idx = max(0, start - 1)
        end_idx = end if end is not None else len(info.entries)
        sliced_entries = info.entries[start_idx:end_idx]
        titles = [entry.get("title") or f"Video {idx}" for idx, entry in enumerate(sliced_entries, start_idx + 1)]

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
            from concurrent.futures import ThreadPoolExecutor

            from core.thumbnail_renderer import get_ansi_thumbnail

            with console.status("[cyan]Rendering thumbnails...[/]"):
                with ThreadPoolExecutor(max_workers=min(10, len(results))) as executor:
                    futures = {
                        executor.submit(get_ansi_thumbnail, entry.thumbnail_url, 24, 8): entry
                        for entry in results
                        if entry.thumbnail_url
                    }
                    for future in futures:
                        entry = futures[future]
                        try:
                            ansi_thumbnails[entry.url] = future.result()
                        except Exception:
                            ansi_thumbnails[entry.url] = ""

        from rich.table import Table
        from rich.text import Text

        table = Table(
            title=f"Search Results (Page {current_page})",
            show_header=True,
            header_style="bold cyan",
            border_style="cyan",
            expand=True,
        )
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Thumbnail", width=24, justify="center")
        table.add_column("Title", style="bold white", ratio=3)
        table.add_column("Channel", style="green", ratio=1)
        table.add_column("Duration", justify="center", width=10)
        table.add_column("Views", justify="right", width=12)
        table.add_column("Link", style="dim cyan", ratio=2)

        for i, entry in enumerate(results, 1):
            dur = entry.duration
            m, s = divmod(int(dur), 60)
            h, m = divmod(m, 60)
            dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}" if dur else "N/A"
            views = entry.view_count
            views_str = f"{views:,}" if views else "N/A"
            entry_url = entry.url or "N/A"

            thumb_ansi = ansi_thumbnails.get(entry_url, "")
            thumb_render = Text.from_ansi(thumb_ansi) if thumb_ansi else Text("No Image", style="dim")

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

        choices = ["Download a result", "Next page of results"]
        if current_page > 1:
            choices.append("Previous page of results")
        choices.extend(["New search query", "Exit"])

        action = questionary.select(
            "What would you like to do next?",
            choices=choices,
            style=CUSTOM_STYLE,
        ).ask()

        if action == "Download a result":
            idx_raw = questionary.text(
                f"Enter result number (1-{len(results)}):", style=CUSTOM_STYLE
            ).ask()
            try:
                idx = int(idx_raw) - 1
                if 0 <= idx < len(results):
                    selected = results[idx]
                    selected_url = selected.url
                    console.print(f"\n[cyan]Selected:[/] [bold]{selected.title}[/]")

                    if selected.thumbnail_url and is_term:
                        from core.thumbnail_renderer import get_ansi_thumbnail
                        with console.status("[cyan]Loading preview...[/]"):
                            large_ansi = get_ansi_thumbnail(selected.thumbnail_url, 42, 14)
                        if large_ansi:
                            console.print(Panel(Text.from_ansi(large_ansi), title="[cyan]Video Preview[/]", border_style="cyan", expand=False))

                    is_playlist = "[Playlist]" in selected.title or "playlist" in selected_url

                    if is_playlist:
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

                        start = max(1, int(start_raw or 1))
                        end = int(end_raw) if end_raw and end_raw.strip().isdigit() else None

                        subs, sub_lang = _ask_subtitles()
                        thumbnail = _ask_thumbnail()

                        # Fetch playlist info first
                        from core.playlist import download_playlist, get_playlist_info
                        info = None
                        with console.status("[cyan]Fetching playlist info...[/]"):
                            try:
                                info = get_playlist_info(selected_url)
                            except Exception as e:
                                console.print(f"[red]Error fetching playlist info: {e}[/]")

                        titles = []
                        if info and info.entries:
                            start_idx = max(0, start - 1)
                            end_idx = end if end is not None else len(info.entries)
                            sliced_entries = info.entries[start_idx:end_idx]
                            titles = [entry.get("title") or f"Video {idx}" for idx, entry in enumerate(sliced_entries, start_idx + 1)]

                        from core.progress import MultiTerminalProgress

                        if titles:
                            with MultiTerminalProgress(console, titles) as progress_callback:
                                results_dl = download_playlist(
                                    url=selected_url,
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
                            results_dl = download_playlist(
                                url=selected_url,
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
                        _show_results_table(results_dl)
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

    dur = info.duration
    m, s = divmod(int(dur), 60)
    h, m = divmod(m, 60)
    dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
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


# ── Result display helpers ───────────────────────────────────────────────────


def _show_result(result) -> None:  # noqa: ANN001  — accepts DownloadResult
    """Display a single download result."""
    from constants import DownloadStatus

    if result.status == DownloadStatus.COMPLETED:
        style = "green"
    elif result.status == DownloadStatus.FAILED:
        style = "red"
    else:
        style = "yellow"

    size_mb = f"{result.file_size / 1_048_576:.1f} MB" if result.file_size else "N/A"
    elapsed = f"{result.elapsed_seconds:.1f}s" if result.elapsed_seconds else "N/A"

    console.print()
    console.print(
        Panel(
            f"[bold]{result.title or result.url}[/]\n\n"
            f"  [bold]Status:[/]  [{style}]{result.status.value}[/{style}]\n"
            f"  [bold]Quality:[/] {result.quality or 'N/A'}\n"
            f"  [bold]Size:[/]    {size_mb}\n"
            f"  [bold]Time:[/]    {elapsed}\n"
            f"  [bold]File:[/]    {result.file_path or 'N/A'}"
            + (f"\n  [bold red]Error:[/]  {result.error_message}" if result.error_message else ""),
            title=f"[bold {style}]Download Result[/]",
            border_style=style,
        )
    )


def _show_results_table(results: list) -> None:
    """Display a summary table for multiple download results."""
    from rich.table import Table

    from constants import DownloadStatus

    table = Table(
        title="Download Summary",
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
        expand=True,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Title", style="bold white", ratio=3)
    table.add_column("Quality", justify="center", width=10)
    table.add_column("Size", justify="right", width=10)
    table.add_column("Time", justify="right", width=8)
    table.add_column("Status", justify="center", width=12)

    for i, r in enumerate(results, 1):
        status_style = {
            DownloadStatus.COMPLETED: "green",
            DownloadStatus.FAILED: "red",
            DownloadStatus.SKIPPED: "yellow",
        }.get(r.status, "white")

        size_mb = f"{r.file_size / 1_048_576:.1f} MB" if r.file_size else "N/A"
        elapsed = f"{r.elapsed_seconds:.1f}s" if r.elapsed_seconds else "N/A"

        table.add_row(
            str(i),
            r.title or r.url[:40],
            r.quality or "N/A",
            size_mb,
            elapsed,
            f"[{status_style}]{r.status.value}[/{status_style}]",
        )

    console.print()
    console.print(table)

    # Summary counts
    from constants import DownloadStatus

    ok = sum(1 for r in results if r.status == DownloadStatus.COMPLETED)
    fail = sum(1 for r in results if r.status == DownloadStatus.FAILED)
    skip = sum(1 for r in results if r.status == DownloadStatus.SKIPPED)
    total_size = sum(r.file_size for r in results if r.file_size)
    total_mb = f"{total_size / 1_048_576:.1f} MB" if total_size else "0 MB"

    console.print(
        f"\n  [green]{ok} completed[/]  "
        f"[red]{fail} failed[/]  "
        f"[yellow]{skip} skipped[/]  "
        f"[cyan]{total_mb} total[/]\n"
    )


# ── Main menu loop ───────────────────────────────────────────────────────────

MENU_CHOICES = [
    questionary.Choice("Download Video", value="download"),
    questionary.Choice("Download Playlist", value="playlist"),
    questionary.Choice("Extract Audio", value="audio"),
    questionary.Choice("Search YouTube", value="search"),
    questionary.Choice("Video Info", value="info"),
    questionary.Choice("Help Manual", value="manual"),
    questionary.Separator(),
    questionary.Choice("Exit", value="exit"),
]

ACTIONS: dict[str, Callable[[], None]] = {
    "download": _action_download_video,
    "playlist": _action_download_playlist,
    "audio": _action_extract_audio,
    "search": _action_search,
    "info": _action_video_info,
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
            sys.exit(0)

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
