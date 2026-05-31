"""Small built-in help screen for yt-vd."""

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table

from core.display import console


def show_manual() -> None:
    """Show a short, practical help screen."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("What it does", style="white")

    rows = [
        ("yt-vd", "Open the interactive menu"),
        ("yt-vd download URL", "Download one video"),
        ("yt-vd download URL -s --sub-lang en", "Download video with subtitles"),
        ("yt-vd playlist URL -p 4", "Download a playlist with 4 workers"),
        ("yt-vd audio URL -f mp3 -b 320k", "Save audio only"),
        ("yt-vd clip URL --start 01:00 --end 02:30", "Download a specific time range"),
        ("yt-vd chapters URL", "Download a video split by its chapters"),
        ("yt-vd info URL", "View video metadata and available qualities"),
        ("yt-vd search \"query\"", "Search YouTube from the terminal"),
        ("yt-vd batch FILE", "Download multiple URLs from a text file"),
        ("yt-vd config [--set KEY=VALUE] [--reset]", "View or modify configuration"),
        ("yt-vd history [--clear] [--export csv|json]", "View or manage download history"),
        ("yt-vd COMMAND --help", "Show options for one command"),
    ]

    for command, description in rows:
        table.add_row(command, description)

    console.print(
        Panel(
            table,
            title="[bold magenta]yt-vd User Manual[/]",
            subtitle="Use quoted URLs when they contain &",
            border_style="magenta",
            padding=(1, 2),
        )
    )
