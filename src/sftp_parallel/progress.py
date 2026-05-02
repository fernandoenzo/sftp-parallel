"""Rich progress bar for parallel SFTP uploads."""

import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)
from rich.text import Text

_console = Console()


def _format_binary_size(size: float) -> str:
    if size >= 1024 ** 4:
        val = size / (1024 ** 4)
        return f"{val:.2f} TiB" if not val.is_integer() else f"{val:.0f} TiB"
    if size >= 1024 ** 3:
        val = size / (1024 ** 3)
        return f"{val:.2f} GiB" if not val.is_integer() else f"{val:.0f} GiB"
    if size >= 1024 ** 2:
        val = size / (1024 ** 2)
        return f"{val:.2f} MiB" if not val.is_integer() else f"{val:.0f} MiB"
    if size >= 1024:
        val = size / 1024
        return f"{val:.2f} KiB" if not val.is_integer() else f"{val:.0f} KiB"
    return f"{size:.0f} B"


class _BinaryDownloadColumn(ProgressColumn):

    def render(self, task: Task) -> Text:
        completed = task.completed
        total = task.total
        if total is not None:
            completed_text = _format_binary_size(completed)
            total_text = _format_binary_size(total)
            return Text(f"{completed_text}/{total_text}", style="progress.download")
        return Text(_format_binary_size(completed), style="progress.download")


class _StatusColumn(ProgressColumn):

    def __init__(self) -> None:
        super().__init__()
        self._spinner = SpinnerColumn()

    def render(self, task: Task) -> Text:
        if task.finished:
            desc = task.description or ""
            if desc.startswith("[green]") or desc.startswith("[bold green]"):
                return Text("✓", style="bold green")
            return Text("✗", style="bold red")
        return Text(str(self._spinner.render(task)))


@dataclass
class FileProgress:
    file_path: str
    file_size: int


@contextmanager
def create_upload_progress(
    total_files: int,
    host: str,
    remote_dir: str,
    num_workers: int = 2,
    disable: bool = False,
) -> Generator[Progress, None, None]:
    worker_suffix = f" ({num_workers} worker{'s' if num_workers != 1 else ''})" if num_workers > 1 else ""
    header = (
        f"Uploading {total_files} file"
        f"{'s' if total_files != 1 else ''} to {host}:{remote_dir}{worker_suffix}"
    )

    progress = Progress(
        _StatusColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        _BinaryDownloadColumn(),
        TransferSpeedColumn(),
        TimeElapsedColumn(),
        TextColumn("• {task.percentage:>3.0f}%"),
        disable=disable,
    )

    _console.print(header)
    with progress:
        yield progress


def add_file_task(
    progress: Progress,
    file_path: str,
    file_size: int,
) -> TaskID:
    basename = os.path.basename(file_path)
    task_id = progress.add_task(basename, total=file_size, visible=True)
    return task_id


def update_file_progress(
    progress: Progress,
    task_id: TaskID,
    bytes_transferred: int,
    file_progress: FileProgress,
) -> None:
    progress.update(task_id, completed=bytes_transferred)


def complete_file_task(
    progress: Progress,
    task_id: TaskID,
    file_progress: FileProgress,
    success: bool,
    elapsed: float,
) -> None:
    if success:
        progress.update(
            task_id,
            completed=file_progress.file_size,
            description=f"[green]{os.path.basename(file_progress.file_path)}[/green] ({elapsed:.1f}s)",
        )
        progress.stop_task(task_id)
    else:
        progress.update(
            task_id,
            description=f"[red]{os.path.basename(file_progress.file_path)}[/red]",
        )
        progress.stop_task(task_id)