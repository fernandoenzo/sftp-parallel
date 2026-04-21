"""Rich progress bar for parallel SFTP uploads."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
)

if TYPE_CHECKING:
    from collections.abc import Generator

_console = Console()


@contextmanager
def create_upload_progress(
    total_files: int,
    host: str,
    remote_dir: str,
    disable: bool = False,
) -> Generator[tuple[Progress, TaskID], None, None]:
    """Create a Rich progress bar for tracking SFTP upload progress.

    Context manager that yields a ``(progress, task_id)`` tuple. The progress
    bar tracks files completed (not bytes) since sftp batch mode does not
    emit per-byte progress.

    Use :func:`advance_progress` to update the progress as buckets complete.

    Parameters
    ----------
    total_files:
        Total number of files to upload across all buckets.
    host:
        Remote host specification (e.g. ``user@host``). Used in description.
    remote_dir:
        Remote directory path. Used in description.
    disable:
        If ``True``, progress bar is disabled (useful for programmatic use
        or when output is redirected).

    Yields
    ------
    tuple[Progress, int]
        A ``(progress, task_id)`` pair. ``progress`` is the Rich Progress
        instance, and ``task_id`` is the ID of the created task.

    Example
    -------
    >>> with create_upload_progress(10, "user@host", "/remote") as (progress, task):
    ...     # Upload files in parallel
    ...     advance_progress(progress, task, 3)  # 3 files completed
    ...     advance_progress(progress, task, 5)  # 5 more files completed
    """
    description = (
        f"Uploading {total_files} file"
        f"{'s' if total_files != 1 else ''} to {host}:{remote_dir}"
    )

    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        SpinnerColumn(),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("{task.completed}/{task.total}"),
        disable=disable,
    )

    with progress:
        task_id = progress.add_task(description, total=total_files)
        yield progress, task_id


def advance_progress(
    progress: Progress,
    task_id: TaskID,
    filename: str,
) -> None:
    """Advance the upload progress bar by one file and print a checkmark.

    Call this function each time a single file upload completes to update
    the progress bar and display ``✓ filename``.

    Parameters
    ----------
    progress:
        The Rich Progress instance from :func:`create_upload_progress`.
    task_id:
        The task ID from :func:`create_upload_progress`.
    filename:
        Name of the file that just finished uploading.
    """
    _console.print(f"[bold green]✓[/bold green] {filename}")
    progress.update(task_id, advance=1)
