"""yt-vd — Main Typer CLI application.

Every command supports ``--help`` with usage examples.  Running ``yt-vd``
with no arguments launches the interactive questionary-based menu.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.panel import Panel
from rich.table import Table

from __init__ import __version__
from constants import (
    DEFAULT_PARALLEL_WORKERS,
    DownloadStatus,
)
from core.display import console, show_result_panel, show_summary_table
from core.presentation import get_search_thumbnail_size, render_result_thumbnails
from core.usecases import channel_titles_from_info, playlist_titles_from_info
from core.utils import ask_with_resize_monitor, format_duration, format_file_size

logger = logging.getLogger(__name__)

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

# ── Helpers ──────────────────────────────────────────────────────────────────


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold magenta]yt-vd[/] version [cyan]{__version__}[/]")
        raise typer.Exit()


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
        "  yt-vd download \"URL\" --sponsorblock --thumbnail\n\n"
        "  yt-vd download \"URL\" --aria2c --rate-limit 5M\n\n"
        "  yt-vd download \"URL\" --cookies-from-browser chrome\n"
    ),
)
def download(
    ctx: typer.Context,
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
    aria2c: Annotated[
        bool, typer.Option("--aria2c", help="Use aria2c for faster multi-connection downloads (requires aria2c on PATH).")
    ] = False,
    cookies_from_browser: Annotated[
        str | None, typer.Option("--cookies-from-browser", help="Import cookies from browser (chrome, firefox, edge, safari).")
    ] = None,
    cookies_file: Annotated[
        str | None, typer.Option("--cookies-file", help="Path to Netscape-format cookies file.")
    ] = None,
    rate_limit: Annotated[
        str | None, typer.Option("--rate-limit", "-r", help="Max download speed (e.g. 5M, 500K).")
    ] = None,
    proxy: Annotated[
        str | None, typer.Option("--proxy", help="Proxy URL (e.g. socks5://127.0.0.1:1080).")
    ] = None,
    skip_downloaded: Annotated[
        bool, typer.Option("--skip-downloaded", help="Skip URLs already in download history.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose/debug output.")
    ] = False,
) -> None:
    """Download a single YouTube video."""
    import click

    from core.config import ConfigManager

    config = ConfigManager().load()

    if ctx.get_parameter_source("quality") == click.core.ParameterSource.DEFAULT:
        quality = config.quality
    if ctx.get_parameter_source("fmt") == click.core.ParameterSource.DEFAULT:
        fmt = config.format
    if ctx.get_parameter_source("output") == click.core.ParameterSource.DEFAULT:
        output = config.output_dir
    if ctx.get_parameter_source("sub_lang") == click.core.ParameterSource.DEFAULT:
        sub_lang = config.subtitle_lang
    if ctx.get_parameter_source("thumbnail") == click.core.ParameterSource.DEFAULT:
        thumbnail = config.embed_thumbnail
    if ctx.get_parameter_source("sponsorblock") == click.core.ParameterSource.DEFAULT:
        sponsorblock = config.sponsorblock

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

    try:
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
                use_aria2c=aria2c,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                rate_limit=rate_limit,
                proxy=proxy,
                skip_downloaded=skip_downloaded,
            )
    except ValueError as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

    show_result_panel(result)

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

    info = None
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
                info_table.add_row("Total Duration", format_duration(info.total_duration))
            console.print(info_table)
            console.print()
    except Exception as exc:
        logger.debug("Playlist info preview unavailable for %s: %s", url, exc)

    from core.progress import MultiTerminalProgress

    titles = playlist_titles_from_info(info, start=start, end=end)

    try:
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
    except ValueError as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

    show_summary_table(results)

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
    ctx: typer.Context,
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
    from core.utils import check_ffmpeg
    if not check_ffmpeg():
        console.print("[bold red]Error: ffmpeg is required for extracting and converting audio. Please install ffmpeg and make sure it is in your PATH.[/]")
        raise typer.Exit(code=1)

    import click

    from core.config import ConfigManager

    config = ConfigManager().load()

    if ctx.get_parameter_source("fmt") == click.core.ParameterSource.DEFAULT:
        fmt = config.audio_format
    if ctx.get_parameter_source("bitrate") == click.core.ParameterSource.DEFAULT:
        bitrate = config.audio_bitrate
    if ctx.get_parameter_source("output") == click.core.ParameterSource.DEFAULT:
        output = config.output_dir
    if ctx.get_parameter_source("thumbnail") == click.core.ParameterSource.DEFAULT:
        thumbnail = config.embed_thumbnail

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

    show_result_panel(result)

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

    info = None
    titles = []
    try:
        info = get_playlist_info(url)
        titles = channel_titles_from_info(info, last_n=last)
    except Exception as exc:
        logger.debug("Channel info preview unavailable for %s: %s", url, exc)

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

    show_summary_table(results)

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

    show_summary_table(results)

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

        ansi_thumbnails: dict[str, Any] = {}
        from rich.text import Text

        def draw_search_results_table():
            nonlocal ansi_thumbnails
            import shutil
            term_w, _ = shutil.get_terminal_size()

            thumb_size = get_search_thumbnail_size(
                term_w,
                is_terminal=is_term,
                has_results=bool(results),
            )
            show_thumbnails = thumb_size is not None
            if show_thumbnails:
                thumb_w, thumb_h = thumb_size

                if not ansi_thumbnails:
                    with console.status("[cyan]Rendering thumbnails...[/]"):
                        ansi_thumbnails = render_result_thumbnails(results, width=thumb_w, height=thumb_h)
                else:
                    ansi_thumbnails = render_result_thumbnails(results, width=thumb_w, height=thumb_h)

            console.print("\033[H\033[2J\033[3J", end="")
            table = Table(
                title=f"Search Results (Page {current_page})",
                show_header=True,
                header_style="bold cyan",
                border_style="cyan",
                expand=True,
            )
            table.add_column("#", style="dim", width=4, justify="right")
            if show_thumbnails:
                table.add_column("Thumbnail", width=thumb_w, justify="center", no_wrap=True)
            table.add_column("Title", style="bold white", ratio=3, overflow="ellipsis", no_wrap=True)
            table.add_column("Channel", style="green", max_width=15, overflow="ellipsis", no_wrap=True)
            table.add_column("Duration", justify="center", width=10)
            table.add_column("Views", justify="right", width=12)

            for i, entry in enumerate(results, 1):
                dur = entry.duration
                dur_str = format_duration(dur) if dur else "N/A"
                views = entry.view_count
                views_str = f"{views:,}" if views else "N/A"

                title_text = entry.title or "Unknown"
                channel_text = entry.uploader or "Unknown"

                if show_thumbnails:
                    thumb_ansi = ansi_thumbnails.get(entry.url or "N/A")
                    thumb_render = thumb_ansi if thumb_ansi else Text("No Image", style="dim")
                    table.add_row(
                        str(i),
                        thumb_render,
                        title_text,
                        channel_text,
                        dur_str,
                        views_str,
                    )
                else:
                    table.add_row(
                        str(i),
                        title_text,
                        channel_text,
                        dur_str,
                        views_str,
                    )

            console.print(table)
            console.print()

        draw_search_results_table()

        if not sys.stdin.isatty():
            break

        choices = ["Download a result", "Next page of results"]
        if current_page > 1:
            choices.append("Previous page of results")
        choices.extend(["New search query", "Exit"])

        while True:
            action = ask_with_resize_monitor(
                lambda: questionary.select(
                    "What would you like to do next?",
                    choices=choices,
                ).ask(),
                on_resize=draw_search_results_table
            )
            if action != "RESIZE":
                break

        if action == "Download a result":
            while True:
                idx_raw = ask_with_resize_monitor(
                    lambda: questionary.text(
                        f"Enter result number (1-{len(results)}):"
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
                    sel_url = selected.url
                    console.print(f"\n[cyan]Selected:[/] [bold]{selected.title}[/]\n")

                    if selected.thumbnail_url and is_term:
                        from core.thumbnail_renderer import get_ansi_thumbnail
                        with console.status("[cyan]Loading preview...[/]"):
                            large_ansi = get_ansi_thumbnail(selected.thumbnail_url, 72, 22)
                        if large_ansi:
                            console.print(Panel(large_ansi, title="[cyan]Video Preview[/]", border_style="cyan", expand=False))
                            console.print("[dim]Terminal thumbnails are low-resolution. Use title, channel, duration, and views to confirm your selection.[/]")

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
                            default=str(Path.home() / "Downloads"),
                            only_directories=True,
                        ).ask()
                        if output:
                            output = output.strip().strip('"').strip("'")
                        output = output or str(Path.home() / "Downloads")

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

                        titles = playlist_titles_from_info(info, start=start, end=end)

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
                        show_summary_table(results_dl)
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
                            default=str(Path.home() / "Downloads"),
                            only_directories=True,
                        ).ask()
                        if output:
                            output = output.strip().strip('"').strip("'")
                        output = output or str(Path.home() / "Downloads")

                        want_subs = questionary.confirm("Download subtitles?", default=False).ask()
                        sub_lang = "en"
                        if want_subs:
                            sub_lang = questionary.text("Subtitle language code (e.g. en, ja, es):", default="en").ask() or "en"

                        thumbnail = questionary.confirm("Embed thumbnail?", default=False).ask()

                        from core.downloader import download_video
                        from core.progress import TerminalProgress

                        with TerminalProgress(console, "Download") as download_cb:
                            result = download_video(
                                url=sel_url,
                                quality=quality,
                                fmt=fmt,
                                output_dir=output,
                                subtitles=want_subs,
                                sub_lang=sub_lang,
                                embed_thumbnail=thumbnail,
                                progress_callback=download_cb,
                            )
                        show_result_panel(result)
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

    try:
        video = get_video_info(url)
    except Exception as e:
        console.print(f"[bold red]Could not retrieve video information:[/] {e}")
        raise typer.Exit(code=1)

    if not video:
        console.print("[bold red]Could not retrieve video information.[/]")
        raise typer.Exit(code=1)

    dur_str = format_duration(video.duration) if video.duration else "N/A"
    views_str = f"{video.view_count:,}" if video.view_count else "N/A"
    size_str = format_file_size(video.file_size_approx) if video.file_size_approx else "N/A"

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
            ch_start = format_duration(ch.get("start_time", 0))
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
    from core.utils import check_ffmpeg
    if not check_ffmpeg():
        console.print("[bold red]Error: ffmpeg is required for chapter downloads. Please install ffmpeg and make sure it is in your PATH.[/]")
        raise typer.Exit(code=1)

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

    try:
        with TerminalProgress(console, "Chapters") as progress_callback:
            results = download_by_chapters(
                url=url,
                quality=quality,
                fmt=fmt,
                output_dir=output,
                progress_callback=progress_callback,
                verbose=verbose,
            )
    except ValueError as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

    show_summary_table(results)

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
    from core.utils import check_ffmpeg
    if not check_ffmpeg():
        console.print("[bold red]Error: ffmpeg is required for downloading clips. Please install ffmpeg and make sure it is in your PATH.[/]")
        raise typer.Exit(code=1)

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

    try:
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
    except ValueError as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(code=1)

    show_result_panel(result)

    if result.status == DownloadStatus.FAILED:
        raise typer.Exit(code=1)


# ── history ──────────────────────────────────────────────────────────────────


@app.command(
    help=(
        "Show or manage download history.\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd history\n\n"
        "  yt-vd history --limit 50\n\n"
        "  yt-vd history --clear\n\n"
        "  yt-vd history --export csv > downloads.csv\n\n"
        "  yt-vd history --export json > downloads.json\n"
    ),
)
def history(
    clear: Annotated[
        bool, typer.Option("--clear", help="Clear all download history.")
    ] = False,
    limit: Annotated[
        int, typer.Option("--limit", help="Number of recent entries to show.")
    ] = 20,
    export: Annotated[
        str | None, typer.Option("--export", help="Export history as 'csv' or 'json' (writes to stdout).")
    ] = None,
) -> None:
    """Show or manage download history."""
    from core.history import clear_history, get_history

    if clear:
        clear_history()
        console.print("[green]Download history cleared.[/]")
        return

    if export:
        fmt_lower = export.strip().lower()
        if fmt_lower not in ("json", "csv"):
            console.print(f"[red]Unknown export format: {export!r}. Use 'csv' or 'json'.[/]")
            raise typer.Exit(code=1)

    entries = get_history(limit=limit if not export else 999999)

    if not entries:
        console.print("[yellow]No download history found.[/]")
        return

    # Export mode: machine-readable output to stdout
    if export:
        fmt_lower = export.strip().lower()
        if fmt_lower == "json":
            import json
            print(json.dumps(entries, indent=2, default=str))
            return
        elif fmt_lower == "csv":
            import csv
            import io
            keys = ["title", "url", "quality", "format", "file_size", "file_path", "downloaded_at", "video_id"]
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            for entry in entries:
                writer.writerow(entry)
            print(buf.getvalue(), end="")
            return
        else:
            console.print(f"[red]Unknown export format: {export!r}. Use 'csv' or 'json'.[/]")
            raise typer.Exit(code=1)

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
            format_file_size(entry.get("file_size", 0)),
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


# ── config ───────────────────────────────────────────────────────────────────


@app.command(
    name="config",
    help=(
        "View or modify application configuration settings.\n\n"
        "[bold cyan]Examples:[/]\n\n"
        "  yt-vd config\n\n"
        "  yt-vd config --set quality=1080p\n\n"
        "  yt-vd config --reset\n"
    ),
)
def config_cmd(
    set_value: Annotated[
        list[str] | None,
        typer.Option("--set", "-s", help="Set a configuration value. Format: key=value (e.g. quality=1080p)."),
    ] = None,
    reset: Annotated[
        bool, typer.Option("--reset", help="Reset all configuration values to defaults.")
    ] = False,
) -> None:
    """View or modify configuration settings."""
    from core.config import ConfigManager

    manager = ConfigManager.get_instance()

    if reset:
        manager.reset()
        console.print("[green]Configuration reset to defaults.[/]")
        return

    if set_value:
        updates = {}
        for pair in set_value:
            if "=" not in pair:
                console.print(f"[bold red]Error:[/] Invalid format for --set: {pair!r}. Use key=value.")
                raise typer.Exit(code=1)
            key, val = pair.split("=", 1)
            key = key.strip()
            val = val.strip()

            current_config = manager.current
            if not hasattr(current_config, key):
                console.print(f"[bold red]Error:[/] Unknown configuration key: {key!r}.")
                raise typer.Exit(code=1)

            orig_val = getattr(current_config, key)
            converted_val: Any
            if isinstance(orig_val, bool):
                converted_val = val.lower() in ("true", "yes", "1", "on")
            elif isinstance(orig_val, int):
                try:
                    converted_val = int(val)
                except ValueError:
                    console.print(f"[bold red]Error:[/] Value for {key!r} must be an integer.")
                    raise typer.Exit(code=1)
            else:
                converted_val = val

            updates[key] = converted_val

        try:
            manager.update(**updates)
            console.print("[green]Configuration updated successfully.[/]")
        except Exception as e:
            console.print(f"[bold red]Error updating configuration:[/] {e}")
            raise typer.Exit(code=1)
        return

    current = manager.current
    table = Table(
        title="yt-vd Configuration Settings",
        show_header=True,
        header_style="bold cyan",
        border_style="cyan",
    )
    table.add_column("Setting Key", style="bold white")
    table.add_column("Current Value", style="green")

    config_dict = current.to_dict()
    for key, val in sorted(config_dict.items()):
        table.add_row(key, str(val))

    console.print()
    console.print(table)
    console.print(f"Config file path: [dim]{manager.config_path}[/]\n")


# ── uninstall ─────────────────────────────────────────────────────────────────



@app.command(
    help="Uninstall yt-vd and clean up all associated files.",
)
def uninstall(
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")
    ] = False,
) -> None:
    """Uninstall yt-vd and clean up all associated files."""
    if not yes:
        confirm = typer.confirm("Are you sure you want to uninstall yt-vd and delete all config/history data?")
        if not confirm:
            console.print("Uninstallation cancelled.")
            raise typer.Abort()

    import os
    import shutil
    import subprocess

    import platformdirs

    # Identify user appdata dir
    user_data = Path(platformdirs.user_data_dir("yt-vd", "yt-vd"))

    # Determine if running from a compiled binary or source
    is_frozen = getattr(sys, "frozen", False)
    exe_path = Path(sys.executable)

    console.print("Uninstalling yt-vd...")

    default_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "yt-vd"
    default_bin = Path.home() / ".local" / "bin" / "yt-vd"

    # Check if this running binary is the standard installation
    is_standard_install = False
    if sys.platform == "win32":
        try:
            is_standard_install = is_frozen and exe_path.parent.resolve() == default_dir.resolve()
        except Exception:
            is_standard_install = is_frozen and exe_path.parent == default_dir
    else:
        try:
            is_standard_install = is_frozen and exe_path.resolve() == default_bin.resolve()
        except Exception:
            is_standard_install = is_frozen and exe_path == default_bin

    if is_frozen and not is_standard_install:
        console.print(
            f"[yellow]Note: You are running a non-standard or development binary at:[/] {exe_path}\n"
            f"[yellow]The global installation will be removed, but this binary will be kept.[/]"
        )

    if sys.platform == "win32":
        # Windows-specific uninstall
        # We write a detached PowerShell script to clean up after we exit.
        # This is necessary because on Windows we cannot delete the running .exe file.
        def _ps_single_quote(value: str) -> str:
            return value.replace("'", "''")

        user_data_str = _ps_single_quote(str(user_data))
        default_dir_str = _ps_single_quote(str(default_dir))
        exe_parent_str = _ps_single_quote(str(exe_path.parent))

        script_content = f"""Start-Transcript -Path "$env:TEMP\\yt-vd-uninstall.log" -Force
Start-Sleep -Seconds 2
Get-Process -Name 'yt-vd', 'yt-vd-gui' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# Loop to delete user data
for ($i=0; $i -lt 10; $i++) {{
    if (Test-Path '{user_data_str}') {{
        Remove-Item '{user_data_str}' -Recurse -Force -ErrorAction SilentlyContinue
    }}
    if (!(Test-Path '{user_data_str}')) {{
        break
    }}
    Start-Sleep -Milliseconds 500
}}

# Loop to delete default install directory
for ($i=0; $i -lt 10; $i++) {{
    Get-Process -Name 'yt-vd', 'yt-vd-gui' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    if (Test-Path '{default_dir_str}') {{
        Remove-Item '{default_dir_str}' -Recurse -Force -ErrorAction SilentlyContinue
    }}
    if (!(Test-Path '{default_dir_str}')) {{
        break
    }}
    Start-Sleep -Milliseconds 500
}}

# Remove default install folder from PATH
$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($UserPath) {{
    $CleanPaths = ($UserPath -split ';') | Where-Object {{ $_ -ne '{default_dir_str}' -and $_ -ne '{default_dir_str}\\' -and [string]::IsNullOrWhiteSpace($_) -eq $false }}
    [Environment]::SetEnvironmentVariable('Path', ($CleanPaths -join ';'), 'User')
}}
"""

        if not is_standard_install:
            script_content += f"""
# Remove development path from user PATH if applicable
$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($UserPath) {{
    $CleanPaths = ($UserPath -split ';') | Where-Object {{ $_ -ne '{exe_parent_str}' -and $_ -ne '{exe_parent_str}\\' -and [string]::IsNullOrWhiteSpace($_) -eq $false }}
    [Environment]::SetEnvironmentVariable('Path', ($CleanPaths -join ';'), 'User')
}}
"""

        script_content += """
Stop-Transcript
# Self delete this script
Remove-Item $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"""

        import tempfile
        temp_dir = Path(tempfile.gettempdir())
        script_path = temp_dir / "yt_vd_uninstall_temp.ps1"
        try:
            script_path.write_text(script_content, encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to write temporary uninstallation script: %s", exc)

        # Launch detached PowerShell via WMI to break away from any Job objects/sandbox limits
        ps_cmd = (
            "Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
            f"-Arguments @{{ CommandLine = 'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File \"{script_path}\"' }}"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        import time
        time.sleep(1.0)
        console.print("Cleanup process started in the background. Goodbye!")
        raise typer.Exit()
    else:
        # Unix/macOS uninstall
        # Delete user config/history
        if user_data.exists():
            try:
                shutil.rmtree(user_data)
                console.print("Deleted config/history directory.")
            except Exception as e:
                console.print(f"Warning: Failed to delete config directory: {e}")

        # Always delete global binary at default_bin path if it exists
        if default_bin.exists():
            try:
                default_bin.unlink()
                console.print("Deleted binary from ~/.local/bin.")
            except Exception as e:
                console.print(f"Warning: Failed to delete binary at ~/.local/bin: {e}")

        # If running standard install (and it differs from default_bin), delete the running binary
        if is_frozen and is_standard_install and exe_path != default_bin:
            try:
                exe_path.unlink()
                console.print("Deleted running binary file.")
            except Exception as e:
                console.print(f"Warning: Failed to delete binary file: {e}")

        console.print("yt-vd has been successfully uninstalled.")
        raise typer.Exit()

# Forceful exit wrapper to prevent hanging on non-daemon yt-dlp threads
original_call = app.__call__

def _wrapped_app_call(*args: Any, **kwargs: Any) -> Any:
    try:
        return original_call(*args, **kwargs)
    except KeyboardInterrupt:
        import os
        import sys
        print("\n⚠ Interrupted by user — cleaning up temporary files and forcing exit...", file=sys.stderr)
        try:
            output_dir = None
            for i, arg in enumerate(sys.argv):
                if arg in ("-o", "--output"):
                    if i + 1 < len(sys.argv):
                        output_dir = sys.argv[i + 1]
                        break
            if not output_dir:
                from core.config import ConfigManager
                output_dir = ConfigManager.get_instance().current.output_dir
            if output_dir:
                from core.fragment_safety import SafeDownloadManager
                SafeDownloadManager(output_dir).cleanup_temp()
        except Exception:
            pass
        os._exit(130)
    except SystemExit as e:
        # Preserve normal exit semantics so cleanup/finally handlers can run.
        raise e

app.__call__ = _wrapped_app_call  # type: ignore[method-assign]
