"""Small built-in help screen for yt-vd."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


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
        ("yt-vd search \"query\"", "Search YouTube from the terminal"),
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
