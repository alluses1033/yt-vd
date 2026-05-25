"""yt-vd — Main Typer CLI application.

Every command supports ``--help`` with usage examples.  Running ``yt-vd``
with no arguments launches the interactive questionary-based menu.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from __init__ import __version__
from constants import (
    DEFAULT_PARALLEL_WORKERS,
    DownloadResult,
    DownloadStatus,
)

# ── Typer app ────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="yt-vd",
    help=(
        "[bold magenta]yt-vd[/] — A powerful YouTube video & playlist downloader.\n\n"
        "Download videos, playlists, channels, and audio with smart quality "
        "fallback, parallel downloads, and beautiful progress output.\n\n"
        "Run [bold cyan]yt-vd[/] with no arguments for interactive mode."
    ),
    no_args_is_help=False,
    rich_markup_mode="rich",
    add_completion=False,
    pretty_exceptions_enable=True,
    pretty_exceptions_show_locals=False,
)

console = Console()

# ── Helpers ──────────────────────────────────────────────────────────────────


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold magenta]yt-vd[/] version [cyan]{__version__}[/]")
        raise typer.Exit()


def _format_size(b: int) -> str:
    """Return a human-readable file size."""
    if b <= 0:
        return "N/A"
    if b >= 1e9:
        return f"{b / 1e9:.1f} GB"
    if b >= 1e6:
        return f"{b / 1e6:.1f} MB"
    if b >= 1e3:
        return f"{b / 1e3:.1f} KB"
    return f"{b} B"


def _format_duration(seconds: float) -> str:
    """Return MM:SS or HH:MM:SS string."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _show_result_panel(result: DownloadResult) -> None:
    """Display a Rich panel for a single download result."""
    if result.status == DownloadStatus.COMPLETED:
        style = "green"
    elif result.status == DownloadStatus.FAILED:
        style = "red"
    else:
        style = "yellow"

    size = _format_size(result.file_size)
    elapsed = f"{result.elapsed_seconds:.1f}s" if result.elapsed_seconds else "N/A"

    body = (
        f"[bold]{result.title or result.url}[/]\n\n"
        f"  [bold]Status:[/]  [{style}]{result.status.value}[/{style}]\n"
        f"  [bold]Quality:[/] {result.quality or 'N/A'}\n"
        f"  [bold]Size:[/]    {size}\n"
        f"  [bold]Time:[/]    {elapsed}\n"
        f"  [bold]File:[/]    {result.file_path or 'N/A'}"
    )
    if result.error_message:
        body += f"\n  [bold red]Error:[/]  {result.error_message}"

    console.print(Panel(body, title=f"[bold {style}]Download Result[/]", border_style=style))


def _show_summary_table(results: list[DownloadResult]) -> None:
    """Display a Rich table summarising multiple downloads."""
    table = Table(
        title="Download Summary",
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
        expand=True,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Filename", style="bold white", ratio=3)
    table.add_column("Quality", justify="center", width=10)
    table.add_column("Size", justify="right", width=10)
    table.add_column("Status", justify="center", width=12)
    table.add_column("Time", justify="right", width=8)

    for i, r in enumerate(results, 1):
        s_style = {
            DownloadStatus.COMPLETED: "green",
            DownloadStatus.FAILED: "red",
            DownloadStatus.SKIPPED: "yellow",
        }.get(r.status, "white")

        filename = Path(r.file_path).name if r.file_path else (r.title or r.url[:40])
        table.add_row(
            str(i),
            filename,
            r.quality or "N/A",
            _format_size(r.file_size),
            f"[{s_style}]{r.status.value}[/{s_style}]",
            f"{r.elapsed_seconds:.1f}s" if r.elapsed_seconds else "N/A",
        )

    console.print()
    console.print(table)

    ok = sum(1 for r in results if r.status == DownloadStatus.COMPLETED)
    fail = sum(1 for r in results if r.status == DownloadStatus.FAILED)
    skip = sum(1 for r in results if r.status == DownloadStatus.SKIPPED)
    total_bytes = sum(r.file_size for r in results if r.file_size)

    console.print(
        f"\n  [green]{ok} completed[/]  "
        f"[red]{fail} failed[/]  "
        f"[yellow]{skip} skipped[/]  "
        f"[cyan]{_format_size(total_bytes)} total[/]\n"
    )


# ── Default callback → interactive mode ──────────────────────────────────────


@app.callback(invoke_without_command=True)
def _main_callback(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option("--version", "-V", help="Show version and exit.", callback=_version_callback,
                     is_eager=True),
    ] = None,
) -> None:
    """Launch interactive mode when no command is given."""
    if ctx.invoked_subcommand is None:
        from interactive import run_interactive

        run_interactive()


# ══════════════════════════════════════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════════════════════════════════════


# ── download ─────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Download a single YouTube video.\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd download \"https://youtube.com/watch?v=ID\"\n\n"
        "  yt-vd download \"URL\" -q high -f mkv\n\n"
        "  yt-vd download \"URL\" -q medium -o ./videos --subtitles\n\n"
        "  yt-vd download \"URL\" --sponsorblock --thumbnail\n"
    ),
)
def download(
    url: Annotated[str, typer.Argument(help="YouTube video URL.")],
    quality: Annotated[
        str, typer.Option("--quality", "-q", help="Quality preset or resolution (e.g. best, high, 1080p).")
    ] = "best",
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Video container format (mp4, mkv, webm).")
    ] = "mp4",
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output directory.")
    ] = ".",
    subtitles: Annotated[
        bool, typer.Option("--subtitles", "-s", help="Download subtitles.")
    ] = False,
    sub_lang: Annotated[
        str, typer.Option("--sub-lang", help="Subtitle language code (ISO 639-1).")
    ] = "en",
    thumbnail: Annotated[
        bool, typer.Option("--thumbnail", help="Embed thumbnail.")
    ] = False,
    sponsorblock: Annotated[
        bool, typer.Option("--sponsorblock", help="Remove sponsor segments via SponsorBlock.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose/debug output.")
    ] = False,
) -> None:
    """Download a single YouTube video."""
    console.print(
        Panel(
            f"[bold]URL:[/] {url}\n"
            f"[bold]Quality:[/] {quality}  [bold]Format:[/] {fmt}\n"
            f"[bold]Output:[/] {output}",
            title="[bold cyan]Downloading[/]",
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
            subtitles=subtitles,
            sub_lang=sub_lang,
            embed_thumbnail=thumbnail,
            sponsorblock=sponsorblock,
            progress_callback=progress_callback,
            verbose=verbose,
        )

    _show_result_panel(result)

    if result.status == DownloadStatus.FAILED:
        raise typer.Exit(code=1)


# ── playlist ─────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Download a YouTube playlist.\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd playlist \"PLAYLIST_URL\"\n\n"
        "  yt-vd playlist \"URL\" -q high -p 6\n\n"
        "  yt-vd playlist \"URL\" --start 5 --end 20 -q medium\n"
    ),
)
def playlist(
    url: Annotated[str, typer.Argument(help="YouTube playlist URL.")],
    quality: Annotated[
        str, typer.Option("--quality", "-q", help="Quality preset or resolution.")
    ] = "best",
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Video container format.")
    ] = "mp4",
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output directory.")
    ] = ".",
    start: Annotated[
        int, typer.Option("--start", help="Start index (1-based).")
    ] = 1,
    end: Annotated[
        int | None, typer.Option("--end", help="End index (inclusive). Omit for all.")
    ] = None,
    parallel: Annotated[
        int, typer.Option("--parallel", "-p", help="Number of parallel download workers.")
    ] = DEFAULT_PARALLEL_WORKERS,
    subtitles: Annotated[
        bool, typer.Option("--subtitles", "-s", help="Download subtitles for each video.")
    ] = False,
    sub_lang: Annotated[
        str, typer.Option("--sub-lang", help="Subtitle language code.")
    ] = "en",
    thumbnail: Annotated[
        bool, typer.Option("--thumbnail", help="Embed thumbnails.")
    ] = False,
    sponsorblock: Annotated[
        bool, typer.Option("--sponsorblock", help="Remove sponsor segments.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose output.")
    ] = False,
) -> None:
    """Download a YouTube playlist."""
    console.print(
        Panel(
            f"[bold]Playlist:[/] {url}\n"
            f"[bold]Quality:[/] {quality}  [bold]Format:[/] {fmt}\n"
            f"[bold]Range:[/] {start}–{end or 'end'}  [bold]Workers:[/] {parallel}",
            title="[bold yellow]Playlist Download[/]",
            border_style="yellow",
        )
    )

    # Fetch and display playlist info
    from core.playlist import download_playlist, get_playlist_info

    try:
        info = get_playlist_info(url)
        if info:
            info_table = Table(
                show_header=False, border_style="yellow", expand=True, pad_edge=True
            )
            info_table.add_column("Field", style="bold yellow", min_width=14)
            info_table.add_column("Value", style="white")
            info_table.add_row("Title", info.title)
            info_table.add_row("Uploader", info.uploader)
            info_table.add_row("Videos", str(info.video_count))
            if info.total_duration:
                info_table.add_row("Total Duration", _format_duration(info.total_duration))
            console.print(info_table)
            console.print()
    except Exception:
        pass  # Non-fatal; proceed with download

    from core.progress import MultiTerminalProgress

    titles = []
    if info and info.entries:
        start_idx = max(0, start - 1)
        end_idx = end if end is not None else len(info.entries)
        sliced_entries = info.entries[start_idx:end_idx]
        titles = [entry.get("title") or f"Video {idx}" for idx, entry in enumerate(sliced_entries, start_idx + 1)]

    with MultiTerminalProgress(console, titles) as progress_callback:
        results = download_playlist(
            url=url,
            quality=quality,
            fmt=fmt,
            output_dir=output,
            start=start,
            end=end,
            parallel=parallel,
            subtitles=subtitles,
            sub_lang=sub_lang,
            embed_thumbnail=thumbnail,
            sponsorblock=sponsorblock,
            verbose=verbose,
            on_progress=progress_callback,
        )

    _show_summary_table(results)

    if any(r.status == DownloadStatus.FAILED for r in results):
        raise typer.Exit(code=1)


# ── audio ────────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Extract audio from a YouTube video.\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd audio \"URL\" -f mp3 -b 320k\n\n"
        "  yt-vd audio \"URL\" -f flac\n\n"
        "  yt-vd audio \"URL\" -f mp3 --thumbnail\n"
    ),
)
def audio(
    url: Annotated[str, typer.Argument(help="YouTube video or playlist URL.")],
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Audio format (mp3, m4a, flac, wav, opus).")
    ] = "mp3",
    bitrate: Annotated[
        str, typer.Option("--bitrate", "-b", help="Audio bitrate (128k, 192k, 256k, 320k).")
    ] = "320k",
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output directory.")
    ] = ".",
    thumbnail: Annotated[
        bool, typer.Option("--thumbnail", help="Embed thumbnail as album art.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose output.")
    ] = False,
) -> None:
    """Extract audio from a YouTube video."""
    console.print(
        Panel(
            f"[bold]URL:[/] {url}\n"
            f"[bold]Format:[/] {fmt}  [bold]Bitrate:[/] {bitrate}\n"
            f"[bold]Thumbnail:[/] {'yes' if thumbnail else 'no'}",
            title="[bold green]Audio Extraction[/]",
            border_style="green",
        )
    )

    from core.audio import extract_audio
    from core.progress import TerminalProgress

    with TerminalProgress(console, "Audio") as progress_callback:
        result = extract_audio(
            url=url,
            audio_format=fmt,
            bitrate=bitrate,
            output_dir=output,
            embed_thumbnail=thumbnail,
            progress_callback=progress_callback,
            verbose=verbose,
        )

    _show_result_panel(result)

    if result.status == DownloadStatus.FAILED:
        raise typer.Exit(code=1)


# ── channel ──────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Download videos from a YouTube channel.\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd channel \"https://youtube.com/@ChannelName\" -n 10\n\n"
        "  yt-vd channel \"URL\" -n 5 -q medium -p 4\n"
    ),
)
def channel(
    url: Annotated[str, typer.Argument(help="YouTube channel URL.")],
    last: Annotated[
        int, typer.Option("--last", "-n", help="Number of recent videos to download.")
    ] = 10,
    quality: Annotated[
        str, typer.Option("--quality", "-q", help="Quality preset or resolution.")
    ] = "best",
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Video container format.")
    ] = "mp4",
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output directory.")
    ] = ".",
    parallel: Annotated[
        int, typer.Option("--parallel", "-p", help="Number of parallel download workers.")
    ] = DEFAULT_PARALLEL_WORKERS,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose output.")
    ] = False,
) -> None:
    """Download videos from a YouTube channel."""
    console.print(
        Panel(
            f"[bold]Channel:[/] {url}\n"
            f"[bold]Last:[/] {last} videos  [bold]Quality:[/] {quality}\n"
            f"[bold]Workers:[/] {parallel}",
            title="[bold magenta]Channel Download[/]",
            border_style="magenta",
        )
    )

    from core.playlist import download_channel, get_playlist_info
    from core.progress import MultiTerminalProgress

    titles = []
    try:
        info = get_playlist_info(url)
        if info and info.entries:
            selected_entries = info.entries[:last]
            titles = [entry.get("title") or f"Video {idx}" for idx, entry in enumerate(selected_entries, 1)]
    except Exception:
        pass

    with MultiTerminalProgress(console, titles) as progress_callback:
        results = download_channel(
            url=url,
            last_n=last,
            quality=quality,
            fmt=fmt,
            output_dir=output,
            parallel=parallel,
            verbose=verbose,
            on_progress=progress_callback,
        )

    _show_summary_table(results)

    if any(r.status == DownloadStatus.FAILED for r in results):
        raise typer.Exit(code=1)


# ── batch ────────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Batch download from a file of URLs (one per line).\n\n"
        "Lines starting with [bold]#[/] are treated as comments. "
        "Empty lines are skipped.\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd batch urls.txt\n\n"
        "  yt-vd batch urls.txt -q high -p 4\n"
    ),
)
def batch(
    file_path: Annotated[Path, typer.Argument(help="Path to a text file with URLs (one per line).")],
    quality: Annotated[
        str, typer.Option("--quality", "-q", help="Quality preset or resolution.")
    ] = "best",
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Video container format.")
    ] = "mp4",
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output directory.")
    ] = ".",
    parallel: Annotated[
        int, typer.Option("--parallel", "-p", help="Number of parallel download workers.")
    ] = DEFAULT_PARALLEL_WORKERS,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose output.")
    ] = False,
) -> None:
    """Batch download from a file of URLs."""
    if not file_path.exists():
        console.print(f"[bold red]Error:[/] File not found: {file_path}")
        raise typer.Exit(code=1)

    # Read and filter URLs
    raw_lines = file_path.read_text(encoding="utf-8").splitlines()
    urls = [
        line.strip()
        for line in raw_lines
        if line.strip() and not line.strip().startswith("#")
    ]

    if not urls:
        console.print("[bold yellow]No URLs found in file.[/]")
        raise typer.Exit()

    console.print(
        Panel(
            f"[bold]File:[/] {file_path}\n"
            f"[bold]URLs:[/] {len(urls)} found  [bold]Quality:[/] {quality}\n"
            f"[bold]Workers:[/] {parallel}",
            title="[bold cyan]Batch Download[/]",
            border_style="cyan",
        )
    )

    from core.parallel import download_batch

    results = download_batch(
        urls=urls,
        quality=quality,
        fmt=fmt,
        output_dir=output,
        parallel=parallel,
        verbose=verbose,
    )

    _show_summary_table(results)

    if any(r.status == DownloadStatus.FAILED for r in results):
        raise typer.Exit(code=1)


# ── search ───────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Search YouTube and display results.\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd search \"python tutorial\"\n\n"
        "  yt-vd search \"lofi hip hop\" -n 20\n"
    ),
)
def search(
    query: Annotated[str, typer.Argument(help="Search query string.")],
    results_count: Annotated[
        int, typer.Option("--results", "-n", help="Number of results to show.")
    ] = 10,
) -> None:
    import questionary

    from core.search import search_youtube

    current_page = 1
    while True:
        console.clear()
        console.print(f"\n[cyan]Searching for:[/] [bold]{query}[/] (Page {current_page}) ...\n")
        results = search_youtube(query=query, max_results=results_count, page=current_page)

        if not results:
            console.print("[yellow]No results found.[/]")
            if current_page > 1:
                choice = questionary.select(
                    "What would you like to do?",
                    choices=["Go back to previous page", "New search query", "Exit"],
                ).ask()
                if choice == "Go back to previous page":
                    current_page -= 1
                    continue
                elif choice == "New search query":
                    new_query = questionary.text("Enter search query:").ask()
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
            dur_str = _format_duration(dur) if dur else "N/A"
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

        if not sys.stdin.isatty():
            break

        choices = ["Download a result", "Next page of results"]
        if current_page > 1:
            choices.append("Previous page of results")
        choices.extend(["New search query", "Exit"])

        action = questionary.select(
            "What would you like to do next?",
            choices=choices,
        ).ask()

        if action == "Download a result":
            idx_raw = questionary.text(
                f"Enter result number (1-{len(results)}):"
            ).ask()
            try:
                idx = int(idx_raw) - 1
                if 0 <= idx < len(results):
                    selected = results[idx]
                    sel_url = selected.url
                    console.print(f"\n[cyan]Selected:[/] [bold]{selected.title}[/]\n")

                    if selected.thumbnail_url and is_term:
                        from core.thumbnail_renderer import get_ansi_thumbnail
                        with console.status("[cyan]Loading preview...[/]"):
                            large_ansi = get_ansi_thumbnail(selected.thumbnail_url, 42, 14)
                        if large_ansi:
                            console.print(Panel(Text.from_ansi(large_ansi), title="[cyan]Video Preview[/]", border_style="cyan", expand=False))

                    is_playlist = "[Playlist]" in selected.title or "playlist" in sel_url

                    if is_playlist:
                        quality = questionary.select(
                            "Quality:",
                            choices=[
                                questionary.Choice("Best (no limit)", value="best"),
                                questionary.Choice("High (1080p)", value="high"),
                                questionary.Choice("Medium (720p)", value="medium"),
                                questionary.Choice("Better (480p)", value="better"),
                                questionary.Choice("Low (360p)", value="low"),
                                questionary.Choice("Lowest (240p)", value="lowest"),
                            ],
                            default="best",
                        ).ask() or "best"

                        fmt = questionary.select(
                            "Format:",
                            choices=[
                                questionary.Choice("MP4  (recommended)", value="mp4"),
                                questionary.Choice("MKV  (more codec support)", value="mkv"),
                                questionary.Choice("WEBM (web optimised)", value="webm"),
                            ],
                            default="mp4",
                        ).ask() or "mp4"

                        output = questionary.path(
                            "Output directory:",
                            default="Downloads\\",
                            only_directories=True,
                        ).ask()
                        if output:
                            output = output.strip().strip('"').strip("'")
                        output = output or "Downloads\\"

                        parallel = questionary.text(
                            "Parallel workers (default 8):",
                            default="8",
                        ).ask()
                        try:
                            parallel_num = max(1, int(parallel or 8))
                        except ValueError:
                            parallel_num = 8

                        start_raw = questionary.text(
                            "Start index (default 1):", default="1"
                        ).ask()
                        end_raw = questionary.text(
                            "End index (leave blank for all):", default=""
                        ).ask()

                        start = max(1, int(start_raw or 1))
                        end = int(end_raw) if end_raw and end_raw.strip().isdigit() else None

                        want_subs = questionary.confirm("Download subtitles?", default=False).ask()
                        sub_lang = "en"
                        if want_subs:
                            sub_lang = questionary.text("Subtitle language code (e.g. en, ja, es):", default="en").ask() or "en"

                        thumbnail = questionary.confirm("Embed thumbnail?", default=False).ask()

                        # Fetch playlist info first
                        from core.playlist import download_playlist, get_playlist_info
                        info = None
                        with console.status("[cyan]Fetching playlist info...[/]"):
                            try:
                                info = get_playlist_info(sel_url)
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
                                    url=sel_url,
                                    quality=quality,
                                    fmt=fmt,
                                    output_dir=output,
                                    start=start,
                                    end=end,
                                    parallel=parallel_num,
                                    subtitles=want_subs,
                                    sub_lang=sub_lang,
                                    embed_thumbnail=thumbnail,
                                    on_progress=progress_callback,
                                )
                        else:
                            results_dl = download_playlist(
                                url=sel_url,
                                quality=quality,
                                fmt=fmt,
                                output_dir=output,
                                start=start,
                                end=end,
                                parallel=parallel_num,
                                subtitles=want_subs,
                                sub_lang=sub_lang,
                                embed_thumbnail=thumbnail,
                            )
                        _show_summary_table(results_dl)
                    else:
                        quality = questionary.select(
                            "Quality:",
                            choices=[
                                questionary.Choice("Best (no limit)", value="best"),
                                questionary.Choice("High (1080p)", value="high"),
                                questionary.Choice("Medium (720p)", value="medium"),
                                questionary.Choice("Better (480p)", value="better"),
                                questionary.Choice("Low (360p)", value="low"),
                                questionary.Choice("Lowest (240p)", value="lowest"),
                            ],
                            default="best",
                        ).ask() or "best"

                        fmt = questionary.select(
                            "Format:",
                            choices=[
                                questionary.Choice("MP4  (recommended)", value="mp4"),
                                questionary.Choice("MKV  (more codec support)", value="mkv"),
                                questionary.Choice("WEBM (web optimised)", value="webm"),
                            ],
                            default="mp4",
                        ).ask() or "mp4"

                        output = questionary.path(
                            "Output directory:",
                            default="Downloads\\",
                            only_directories=True,
                        ).ask()
                        if output:
                            output = output.strip().strip('"').strip("'")
                        output = output or "Downloads\\"

                        want_subs = questionary.confirm("Download subtitles?", default=False).ask()
                        sub_lang = "en"
                        if want_subs:
                            sub_lang = questionary.text("Subtitle language code (e.g. en, ja, es):", default="en").ask() or "en"

                        thumbnail = questionary.confirm("Embed thumbnail?", default=False).ask()

                        from core.downloader import download_video
                        from core.progress import TerminalProgress

                        with TerminalProgress(console, "Download") as progress_callback:
                            result = download_video(
                                url=sel_url,
                                quality=quality,
                                fmt=fmt,
                                output_dir=output,
                                subtitles=want_subs,
                                sub_lang=sub_lang,
                                embed_thumbnail=thumbnail,
                                progress_callback=progress_callback,
                            )
                        _show_result_panel(result)
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
            new_query = questionary.text("Enter search query:").ask()
            if new_query and new_query.strip():
                query = new_query.strip()
                current_page = 1
            continue
        else:
            break


# ── info ─────────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Show detailed information about a video (no download).\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd info \"URL\"\n"
    ),
)
def info(
    url: Annotated[str, typer.Argument(help="YouTube video URL.")],
) -> None:
    """Show video information without downloading."""
    console.print(f"\n[cyan]Fetching info for:[/] {url}\n")

    from core.metadata import get_video_info

    video = get_video_info(url)

    if not video:
        console.print("[bold red]Could not retrieve video information.[/]")
        raise typer.Exit(code=1)

    dur_str = _format_duration(video.duration) if video.duration else "N/A"
    views_str = f"{video.view_count:,}" if video.view_count else "N/A"
    size_str = _format_size(video.file_size_approx) if video.file_size_approx else "N/A"

    details = Table(show_header=False, border_style="cyan", expand=True, pad_edge=True)
    details.add_column("Field", style="bold cyan", min_width=20)
    details.add_column("Value", style="white")

    details.add_row("Title", video.title)
    details.add_row("Channel", video.uploader)
    details.add_row("Duration", dur_str)
    details.add_row("Views", views_str)
    details.add_row("Upload Date", video.upload_date or "N/A")
    details.add_row("Video ID", video.video_id)
    details.add_row("Approx. Size", size_str)

    if video.available_qualities:
        details.add_row("Available Qualities", ", ".join(video.available_qualities))

    if video.subtitles:
        langs = ", ".join(sorted(video.subtitles.keys()))
        details.add_row("Subtitles", langs)

    if video.chapters:
        ch_lines = []
        for ch in video.chapters[:15]:
            ch_start = _format_duration(ch.get("start_time", 0))
            ch_lines.append(f"  {ch_start}  {ch.get('title', 'Chapter')}")
        if len(video.chapters) > 15:
            ch_lines.append(f"  ... and {len(video.chapters) - 15} more")
        details.add_row("Chapters", "\n".join(ch_lines))

    if video.description:
        desc = video.description[:300]
        if len(video.description) > 300:
            desc += "..."
        details.add_row("Description", desc)

    console.print(
        Panel(details, title="[bold cyan]Video Info[/]", border_style="cyan")
    )


# ── chapters ─────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Download a video split by its chapter markers.\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd chapters \"URL\"\n\n"
        "  yt-vd chapters \"URL\" -q high -f mkv\n"
    ),
)
def chapters(
    url: Annotated[str, typer.Argument(help="YouTube video URL.")],
    quality: Annotated[
        str, typer.Option("--quality", "-q", help="Quality preset or resolution.")
    ] = "best",
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Video container format.")
    ] = "mp4",
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output directory.")
    ] = ".",
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose output.")
    ] = False,
) -> None:
    """Download a video split by chapter markers."""
    console.print(
        Panel(
            f"[bold]URL:[/] {url}\n"
            f"[bold]Quality:[/] {quality}  [bold]Format:[/] {fmt}",
            title="[bold yellow]Chapter Download[/]",
            border_style="yellow",
        )
    )

    from core.metadata import download_by_chapters
    from core.progress import TerminalProgress

    with TerminalProgress(console, "Chapters") as progress_callback:
        results = download_by_chapters(
            url=url,
            quality=quality,
            fmt=fmt,
            output_dir=output,
            progress_callback=progress_callback,
            verbose=verbose,
        )

    _show_summary_table(results)

    if any(r.status == DownloadStatus.FAILED for r in results):
        raise typer.Exit(code=1)


# ── clip ─────────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Download a specific time range (clip) from a video.\n\n"
        "Time format: [bold]MM:SS[/] or [bold]HH:MM:SS[/]\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd clip \"URL\" --start 01:30 --end 03:45\n\n"
        "  yt-vd clip \"URL\" --end 05:00\n\n"
        "  yt-vd clip \"URL\" --start 10:00\n"
    ),
)
def clip(
    url: Annotated[str, typer.Argument(help="YouTube video URL.")],
    start: Annotated[
        str | None, typer.Option("--start", help="Start time (MM:SS or HH:MM:SS). Omit for beginning.")
    ] = None,
    end: Annotated[
        str | None, typer.Option("--end", help="End time (MM:SS or HH:MM:SS). Omit for end of video.")
    ] = None,
    quality: Annotated[
        str, typer.Option("--quality", "-q", help="Quality preset or resolution.")
    ] = "best",
    fmt: Annotated[
        str, typer.Option("--format", "-f", help="Video container format.")
    ] = "mp4",
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output directory.")
    ] = ".",
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose output.")
    ] = False,
) -> None:
    """Download a specific time range from a video."""
    if not start and not end:
        console.print("[bold red]Error:[/] Specify at least --start or --end.")
        raise typer.Exit(code=1)

    range_str = f"{start or 'start'} → {end or 'end'}"
    console.print(
        Panel(
            f"[bold]URL:[/] {url}\n"
            f"[bold]Range:[/] {range_str}\n"
            f"[bold]Quality:[/] {quality}  [bold]Format:[/] {fmt}",
            title="[bold magenta]Clip Download[/]",
            border_style="magenta",
        )
    )

    from core.downloader import download_clip
    from core.progress import TerminalProgress

    with TerminalProgress(console, "Clip") as progress_callback:
        result = download_clip(
            url=url,
            start_time=start,
            end_time=end,
            quality=quality,
            fmt=fmt,
            output_dir=output,
            progress_callback=progress_callback,
            verbose=verbose,
        )

    _show_result_panel(result)

    if result.status == DownloadStatus.FAILED:
        raise typer.Exit(code=1)


# ── history ──────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Show or manage download history.\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd history\n\n"
        "  yt-vd history --limit 50\n\n"
        "  yt-vd history --clear\n"
    ),
)
def history(
    clear: Annotated[
        bool, typer.Option("--clear", help="Clear all download history.")
    ] = False,
    limit: Annotated[
        int, typer.Option("--limit", help="Number of recent entries to show.")
    ] = 20,
) -> None:
    """Show or manage download history."""
    from core.history import clear_history, get_history

    if clear:
        clear_history()
        console.print("[green]Download history cleared.[/]")
        return

    entries = get_history(limit=limit)

    if not entries:
        console.print("[yellow]No download history found.[/]")
        return

    table = Table(
        title=f"Download History (last {limit})",
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
    )
    table.add_column("#", style="dim", justify="right")
    table.add_column("Title", style="bold white", min_width=30)
    table.add_column("Quality", justify="center")
    table.add_column("Format", justify="center")
    table.add_column("Size", justify="right")
    table.add_column("Date", style="dim")
    table.add_column("Status", justify="center")

    for i, entry in enumerate(entries, 1):
        date_val = entry.get("downloaded_at", "N/A")
        if isinstance(date_val, str) and len(date_val) > 16:
            date_val = date_val[:16].replace("T", " ")
        table.add_row(
            str(i),
            entry.get("title", "Unknown"),
            entry.get("quality", "N/A"),
            entry.get("format", "N/A"),
            _format_size(entry.get("file_size", 0)),
            date_val,
            "[green]completed[/]",
        )

    console.print()
    console.print(table)
    console.print()


# ── manual ───────────────────────────────────────────────────────────────────


@app.command(
    help="Show the built-in yt-vd help manual with examples and tips.",
)
def manual() -> None:
    """Display the comprehensive yt-vd user manual."""
    from manual import show_manual

    show_manual()



