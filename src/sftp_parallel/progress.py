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
    """Format a byte count in binary units (KiB, MiB, GiB, TiB)."""
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
    """Download column that formats sizes in binary units (KiB, MiB, GiB, TiB)."""

    def render(self, task: Task) -> Text:
        completed = task.completed
        total = task.total
        if total is not None:
            completed_text = _format_binary_size(completed)
            total_text = _format_binary_size(total)
            return Text(f"{completed_text}/{total_text}", style="progress.download")
        return Text(_format_binary_size(completed), style="progress.download")


class _StatusColumn(ProgressColumn):
    """Spinner while running, ✓/✗ when finished."""

    def __init__(self) -> None:
        super().__init__()
        self._spinner = SpinnerColumn()

    def render(self, task: Task) -> Text:
        if task.finished:
            desc = task.description or ""
            if desc.startswith("[green]") or desc.startswith("[bold green]"):
                return Text("✓", style="bold green")
            return Text("✗", style="bold red")
        return self._spinner.render(task)  # type: ignore[return-value]


@dataclass
class FileProgress:
    """Tracks byte-level progress for a single file upload."""

    file_path: str
    file_size: int


@contextmanager
def create_upload_progress_v2(
    total_files: int,
    host: str,
    remote_dir: str,
    num_workers: int = 2,
    disable: bool = False,
) -> Generator[Progress, None, None]:
    """Create a Rich progress bar with per-file byte-level progress tracking.

    Context manager that yields a ``Progress`` instance.  Per-file sub-tasks
    (added via :func:`add_worker_task`) show byte-level transfer progress for
    each individual file with human-readable size, speed, and percentage
    columns.  The overall file count is tracked by the caller — this function
    no longer manages an overall task.

    Parameters
    ----------
    total_files:
        Total number of files to upload (informational, not used for a task).
    host:
        Remote host specification (e.g. ``user@host``).
    remote_dir:
        Remote directory path.
    num_workers:
        Number of parallel workers (shown in description).
    disable:
        If ``True``, progress bar is disabled.

    Yields
    ------
    Progress
        The Rich Progress instance.
    """
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


def add_worker_task(
    progress: Progress,
    file_path: str,
    file_size: int,
) -> TaskID:
    """Add a per-file progress bar task, initially invisible.

    Creates a new task on the progress bar for an individual file transfer.
    The task starts with ``total=file_size`` but is made invisible until
    :func:`update_worker_progress` reports the first byte-level update.

    Parameters
    ----------
    progress:
        The Rich Progress instance from :func:`create_upload_progress_v2`.
    file_path:
        Local path of the file being uploaded.
    file_size:
        Size of the file in bytes.

    Returns
    -------
    TaskID
        The ID of the newly created task.
    """
    basename = os.path.basename(file_path)
    task_id = progress.add_task(basename, total=file_size, visible=True)
    return task_id


def update_worker_progress(
    progress: Progress,
    task_id: TaskID,
    bytes_transferred: int,
    file_progress: FileProgress,
) -> None:
    """Update byte-level progress on a per-file task.

    Updates the task's completed bytes on the progress bar and syncs
    the :class:`FileProgress` dataclass.

    Parameters
    ----------
    progress:
        The Rich Progress instance from :func:`create_upload_progress_v2`.
    task_id:
        The task ID from :func:`add_worker_task`.
    bytes_transferred:
        Number of bytes transferred so far.
    file_progress:
        The :class:`FileProgress` instance tracking this file's state.
    """
    progress.update(task_id, completed=bytes_transferred)


def complete_worker_task(
    progress: Progress,
    task_id: TaskID,
    file_progress: FileProgress,
    success: bool,
    elapsed: float,
) -> None:
    """Mark a per-file task as complete.

    On success, updates to 100%%, shows a green description with elapsed
    time, and stops the task via :meth:`~rich.progress.Progress.stop_task`.
    On failure, shows a red description and stops the task.
    The calling code is responsible for printing per-file summaries after
    the Live display closes.

    Parameters
    ----------
    progress:
        The Rich Progress instance from :func:`create_upload_progress_v2`.
    task_id:
        The per-file task ID from :func:`add_worker_task`.
    file_progress:
        The :class:`FileProgress` instance tracking this file's state.
    success:
        ``True`` if the upload succeeded, ``False`` otherwise.
    elapsed:
        Elapsed time in seconds for this file upload.
    """
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
