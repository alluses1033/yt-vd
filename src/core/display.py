"""Display helpers and shared console instance for yt-vd."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from constants import DownloadResult, DownloadStatus
from core.utils import format_file_size

# Shared Console instance across the application
console = Console()


def show_result_panel(result: DownloadResult) -> None:
    """Display a Rich panel for a single download result."""
    if result.status == DownloadStatus.COMPLETED:
        style = "green"
    elif result.status == DownloadStatus.FAILED:
        style = "red"
    else:
        style = "yellow"

    size = format_file_size(result.file_size)
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

    console.print()
    console.print(Panel(body, title=f"[bold {style}]Download Result[/]", border_style=style))


def show_summary_table(results: list[DownloadResult]) -> None:
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
            format_file_size(r.file_size),
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
        f"[cyan]{format_file_size(total_bytes)} total[/]\n"
    )
