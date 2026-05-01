"""CLI module for sftp-parallel — flat interface with named flags."""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from rich.console import Console
from rich.progress import TaskID

from sftp_parallel import __version__
from sftp_parallel.batch import (
    validate_filename,
    validate_host,
    validate_port,
    validate_remote_dir,
)
from sftp_parallel.progress import (
    FileProgress,
    add_worker_task,
    complete_worker_task,
    create_upload_progress_v2,
    update_worker_progress,
)
from sftp_parallel.uploader import (
    get_remote_file_sizes,
    upload_files,
)
from sftp_parallel.verify import compute_local_checksum, compute_remote_checksums

console = Console()


def resolve_file_patterns(
    patterns: list[str],
    cwd: Path | None = None,
) -> list[Path]:
    """Resolve file patterns (globs and literals) into sorted ``Path`` objects.

    For each pattern:

    1. If the literal path exists, use it directly.
    2. If it contains glob characters (``*``, ``?``, ``[``) and the literal
       doesn't exist, expand as a glob.
    3. If it has no glob characters and doesn't exist, print a warning.

    When no patterns are provided (i.e. the user passed ``-f *.mp4`` and
    the shell expanded it), all regular files in *cwd* are returned.

    Note
    ----
    Glob patterns (those with ``**``) are recursive.  Single-star patterns
    (``*.txt``) match only the immediate directory.
    """
    base = Path(cwd or Path.cwd())
    result: list[Path] = []

    if not patterns:
        for entry in base.iterdir():
            if entry.is_symlink():
                target = os.path.realpath(entry)
                if not os.path.isfile(target):
                    console.print(
                        f"[yellow]Skipping symlink to non-regular file:[/yellow] {entry.name}"
                    )
                    continue
                name = entry.name
                if validate_filename(name):
                    result.append(entry.resolve())
                else:
                    console.print(f"[yellow]Skipping unsafe filename:[/yellow] {name}")
            elif entry.is_file():
                name = entry.name
                if validate_filename(name):
                    result.append(entry.resolve())
                else:
                    console.print(f"[yellow]Skipping unsafe filename:[/yellow] {name}")
    else:
        for pattern in patterns:
            resolved = (base / pattern).resolve()
            original = base / pattern
            if original.is_symlink():
                target = os.path.realpath(original)
                if os.path.isfile(target):
                    name = Path(pattern).name
                    if validate_filename(name):
                        result.append(resolved)
                    else:
                        console.print(
                            f"[yellow]Skipping unsafe filename:[/yellow] {name}"
                        )
                else:
                    console.print(
                        f"[yellow]Skipping symlink to non-regular file:[/yellow] {Path(pattern).name}"
                    )
            elif resolved.is_file():
                name = Path(pattern).name
                if validate_filename(name):
                    result.append(resolved)
                else:
                    console.print(
                        f"[yellow]Skipping unsafe filename:[/yellow] {name}"
                    )
            elif any(ch in pattern for ch in ("*", "?", "[")):
                for entry in base.glob(pattern):
                    if entry.is_symlink():
                        target = os.path.realpath(entry)
                        if not os.path.isfile(target):
                            console.print(
                                f"[yellow]Skipping symlink to non-regular file:[/yellow] {entry.name}"
                            )
                            continue
                        name = entry.name
                        if validate_filename(name):
                            result.append(entry.resolve())
                        else:
                            console.print(
                                f"[yellow]Skipping unsafe filename:[/yellow] {name}"
                            )
                    elif entry.is_file():
                        name = entry.name
                        if validate_filename(name):
                            result.append(entry.resolve())
                        else:
                            console.print(
                                f"[yellow]Skipping unsafe filename:[/yellow] {name}"
                            )
            else:
                console.print(
                    f"[yellow]Warning: file not found:[/yellow] {pattern}"
                )

    return sorted(result, key=lambda p: str(p))


def validate_basename_uniqueness(file_paths: list[Path]) -> None:
    """Raise ``ValueError`` if any two paths share the same basename.

    SFTP uploads place files by basename in a single remote directory,
    so two files with the same basename would silently overwrite each other.
    """
    seen: dict[str, Path] = {}
    for p in file_paths:
        name = p.name
        if name in seen:
            raise ValueError(
                f"Duplicate basename {name!r}:\n"
                f"  {seen[name]}\n"
                f"  {p}"
            )
        seen[name] = p


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sftp-parallel",
        description="Parallel SFTP uploader with verification",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-s",
        "--server",
        required=True,
        metavar="HOST",
        help="remote host (e.g. user@host)",
    )
    parser.add_argument(
        "-f",
        "--files",
        required=True,
        nargs="+",
        metavar="PATTERN",
        help="files or glob patterns to upload",
    )
    parser.add_argument(
        "-d",
        "--dest",
        default=".",
        metavar="DIR",
        help="remote directory (default: current remote directory)",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=22,
        help="SSH port (default: 22)",
    )
    parser.add_argument(
        "-t",
        "--threads",
        type=int,
        default=2,
        choices=range(1, 17),
        metavar="N",
        help="parallel sessions (default: 2, max: 16)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify uploads with checksums",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        dest="skip_existing",
        help="skip files that exist on remote with same size",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        dest="no_progress",
        help="disable per-file progress bars (show only file count)",
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=120,
        metavar="SECONDS",
        help="seconds without progress before killing a transfer (default: 120)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.dest == "":
        parser.error("--dest cannot be empty")

    _handle_upload(args)


def _handle_upload(args: argparse.Namespace) -> None:
    # 1. Validate host
    try:
        validate_host(args.server)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(2)

    # 2. Validate port
    try:
        validate_port(args.port)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(2)

    # 2.5. Validate remote_dir
    try:
        validate_remote_dir(args.dest)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(2)

    # 3. Resolve and deduplicate file patterns
    file_paths = list(dict.fromkeys(resolve_file_patterns(args.files)))

    # 4. Check for duplicate basenames
    try:
        validate_basename_uniqueness(file_paths)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(2)

    if not file_paths:
        console.print("[yellow]No files found matching the specified patterns.[/yellow]")
        sys.exit(0)

    # 5. Convert to strings
    file_paths_str = [str(p) for p in file_paths]

    # 6. Get remote_dir
    remote_dir = args.dest

    # 7. Skip-existing logic
    if args.skip_existing:
        remote_sizes = get_remote_file_sizes(
            args.server, remote_dir, port=args.port
        )
        if remote_sizes is None:
            remote_sizes = {}
        need_upload: list[str] = []
        skipped: list[str] = []
        oserror_count = 0
        for fp in file_paths_str:
            basename = os.path.basename(fp)
            try:
                local_size = os.path.getsize(fp)
            except OSError as exc:
                console.print(f"[yellow]Warning: cannot stat {fp}: {exc}[/yellow]")
                need_upload.append(fp)
                oserror_count += 1
                continue
            remote_size = remote_sizes.get(basename)
            if remote_size is not None and remote_size == local_size:
                skipped.append(basename)
            else:
                need_upload.append(fp)
        if skipped:
            console.print(
                f"Skipping {len(skipped)} existing file"
                f"{'s' if len(skipped) != 1 else ''}"
            )
        if oserror_count > 0:
            console.print(
                f"[yellow]Warning: {oserror_count} file"
                f"{'s' if oserror_count != 1 else ''}"
                " could not be checked -- will attempt upload[/yellow]"
            )
        if not need_upload:
            console.print(
                "[bold green]All files already exist on remote.[/bold green]"
            )
            if not args.verify:
                sys.exit(0)
        # TOCTOU guard: re-check files still exist before upload
        if need_upload:
            validated: list[str] = []
            for fp in need_upload:
                try:
                    _ = os.path.getsize(fp)
                    validated.append(fp)
                except OSError:
                    console.print(
                        f"[yellow]Warning: {fp} changed or disappeared, skipping[/yellow]"
                    )
            file_paths_str = validated
        else:
            file_paths_str = need_upload

    # 8. Upload with progress
    total_files = len(file_paths_str)
    results: list[tuple[str, bool, float]] = []
    with create_upload_progress_v2(
        total_files, args.server, remote_dir,
        num_workers=min(args.threads, total_files),
        disable=args.no_progress,
    ) as progress:
        # Map of file paths to (Rich TaskID, FileProgress)
        task_map: dict[str, tuple[TaskID, FileProgress]] = {}
        task_map_lock = threading.Lock()
        files_completed = 0
        files_failed = 0

        # Track when each file's upload began for elapsed-time display
        file_start_times: dict[str, float] = {}

        def progress_callback(file_path: str, bytes_transferred: int, total_bytes: int) -> None:
            with task_map_lock:
                if file_path not in task_map:
                    task_id = add_worker_task(progress, file_path, max(total_bytes, 1))
                    fp = FileProgress(file_path=file_path, file_size=max(total_bytes, 1))
                    task_map[file_path] = (task_id, fp)
                    file_start_times[file_path] = time.monotonic()
                task_id, fp = task_map[file_path]
            update_worker_progress(progress, task_id, bytes_transferred, fp)

        def completion_callback(file_path: str, success: bool) -> None:
            nonlocal files_completed, files_failed
            elapsed = time.monotonic() - file_start_times.get(file_path, time.monotonic())
            with task_map_lock:
                if file_path in task_map:
                    task_id, fp = task_map[file_path]
                    complete_worker_task(progress, task_id, fp, success, elapsed)
                    del task_map[file_path]
            results.append((os.path.basename(file_path), success, elapsed))
            if success:
                files_completed += 1
            else:
                files_failed += 1

        all_success, failed_count = upload_files(
            args.server,
            file_paths_str,
            remote_dir,
            num_workers=args.threads,
            port=args.port,
            progress_callback=progress_callback,
            completion_callback=completion_callback,
            idle_timeout=args.idle_timeout,
        )

    if total_files > 1:
        if files_failed == 0:
            console.print(f"[bold green]Success[/bold green] — {files_completed}/{total_files} files uploaded")
        else:
            console.print(f"[bold red]Failed[/bold red] — {files_failed}/{total_files} files failed, {files_completed} succeeded")

    # 10. Report result + optional verification
    if args.verify:
        verify_paths = file_paths_str
        basenames = [os.path.basename(fp) for fp in verify_paths]
        console.print("Upload complete")
        console.print("Verifying checksums...")
        remote_checksums = compute_remote_checksums(
            args.server,
            remote_dir,
            basenames,
            port=args.port,
        )
        if remote_checksums is None:
            remote_checksums = {}
        if not remote_checksums and basenames:
            console.print(
                "[yellow]Warning: Could not retrieve remote checksums"
                " (validation error or SSH failure?)."
                " Verification may be unreliable.[/yellow]"
            )
        matched: list[str] = []
        mismatched: list[str] = []
        for fp in verify_paths:
            basename = os.path.basename(fp)
            try:
                local_hash = compute_local_checksum(fp)
            except OSError:
                mismatched.append(basename)
                continue
            remote_hash = remote_checksums.get(basename)
            if remote_hash is not None and remote_hash == local_hash:
                matched.append(basename)
            else:
                mismatched.append(basename)
        for f in matched:
            console.print(f"[bold green]✓[/bold green] {f}")
        for f in mismatched:
            console.print(f"[bold red]✗[/bold red] {f}")
        if matched:
            console.print(
                f"[green]{len(matched)} file"
                f"{'s' if len(matched) != 1 else ''} verified[/green]"
            )
        if mismatched:
            console.print(
                f"[bold red]{len(mismatched)} file"
                f"{'s' if len(mismatched) != 1 else ''}"
                " FAILED verification[/bold red]"
            )
            sys.exit(1)

    if all_success:
        if total_files <= 1:
            console.print("[bold green]Success[/bold green]")
        sys.exit(0)
    else:
        console.print(
            f"[bold red]Failed:[/bold red] {failed_count} file"
            f"{'s' if failed_count != 1 else ''} failed"
        )
        sys.exit(74)


if __name__ == "__main__":
    main()
