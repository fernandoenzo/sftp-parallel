"""CLI module for sftp-parallel."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from rich.console import Console

from sftp_parallel import __version__
from sftp_parallel.progress import advance_progress, create_upload_progress
from sftp_parallel.signals import cleanup_signal_handlers
from sftp_parallel.uploader import (
    distribute_files,
    filter_existing_files,
    get_remote_file_sizes,
    run_parallel_uploads,
)
from sftp_parallel.verify import verify_uploads

console = Console()


def parse_destination(destination: str) -> tuple[str, str]:
    """Parse HOST:REMOTE_DIR destination string.

    Splits on the *last* colon so that ``user@host:/remote/dir`` and
    IPv6 literals like ``[::1]:/remote`` are handled correctly.

    Parameters
    ----------
    destination:
        Destination string in ``HOST:REMOTE_DIR`` format.

    Returns
    -------
    tuple[str, str]
        ``(host, remote_dir)`` pair.

    Raises
    ------
    ValueError
        If the destination does not contain a colon.
    """
    colon_idx = destination.rfind(":")
    if colon_idx == -1:
        raise ValueError(
            f"Invalid destination '{destination}': expected HOST:REMOTE_DIR format"
        )
    host = destination[:colon_idx]
    remote_dir = destination[colon_idx + 1 :]
    if not host:
        raise ValueError(f"Invalid destination '{destination}': host part is empty")
    if not remote_dir:
        raise ValueError(
            f"Invalid destination '{destination}': remote directory is empty"
        )
    return host, remote_dir


def list_local_files(local_dir: str) -> list[str]:
    """Return sorted top-level regular files in *local_dir* (non-recursive)."""
    try:
        entries = os.listdir(local_dir)
    except OSError as exc:
        console.print(f"[bold red]Error listing directory:[/bold red] {exc}")
        return []
    files = [name for name in entries if os.path.isfile(os.path.join(local_dir, name))]
    return sorted(files)


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

    subparsers = parser.add_subparsers(dest="command")

    upload_parser = subparsers.add_parser(
        "upload",
        help="upload a local directory to a remote host",
    )
    upload_parser.add_argument(
        "local_dir",
        metavar="LOCAL_DIR",
        help="local directory to upload from",
    )
    upload_parser.add_argument(
        "destination",
        metavar="HOST:REMOTE_DIR",
        help="remote destination in HOST:REMOTE_DIR format",
    )
    upload_parser.add_argument(
        "-t",
        "--threads",
        type=int,
        default=2,
        choices=range(1, 17),
        metavar="N",
        help="number of parallel sessions (default: 2, max: 16)",
    )
    upload_parser.add_argument(
        "--verify",
        action="store_true",
        help="verify uploads with checksum",
    )
    upload_parser.add_argument(
        "--skip-existing",
        action="store_true",
        dest="skip_existing",
        help="skip files that exist on remote with same size",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "upload":
        _handle_upload(args)


def _handle_upload(args: argparse.Namespace) -> None:
    try:
        host, remote_dir = parse_destination(args.destination)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(2)

    local_dir = os.path.abspath(args.local_dir)

    if not os.path.isdir(local_dir):
        console.print(
            f"[bold red]Error:[/bold red] local directory '{local_dir}' does not exist"
        )
        sys.exit(2)

    files = list_local_files(local_dir)
    if not files:
        console.print("[yellow]No files found in local directory.[/yellow]")
        sys.exit(0)

    if args.skip_existing:
        remote_sizes: dict[str, int] = get_remote_file_sizes(host, remote_dir)
        skip_count = len(files) - len(
            [
                f
                for f in files
                if f in remote_sizes
                and remote_sizes[f] == os.path.getsize(os.path.join(local_dir, f))
            ]
        )
        files = filter_existing_files(local_dir, files, remote_sizes)
        if skip_count > 0:
            console.print(
                f"Skipping {skip_count} existing file{'s' if skip_count != 1 else ''}"
            )
        if not files:
            console.print("[bold green]All files already exist on remote.[/bold green]")
            sys.exit(0)

    num_files = len(files)
    console.print(
        f"Uploading {num_files} file{'s' if num_files != 1 else ''} "
        f"to {args.destination}"
    )

    buckets = distribute_files(files, args.threads)

    def progress_callback(completed: int) -> None:
        advance_progress(progress, task, completed)

    with create_upload_progress(num_files, host, remote_dir) as (progress, task):
        all_success, failed_count = run_parallel_uploads(
            host,
            buckets,
            remote_dir,
            local_dir,
            timeout=10,
            progress_callback=progress_callback,
        )

    cleanup_signal_handlers()

    if all_success:
        console.print("[bold green]Success[/bold green]")

        if args.verify:
            console.print("Verifying checksums...")
            matched, mismatched = verify_uploads(host, remote_dir, local_dir, files)

            for f in matched:
                console.print(f"[bold green]✓[/bold green] {f}")
            for f in mismatched:
                console.print(f"[bold red]✗[/bold red] {f}")

            if matched:
                console.print(
                    f"[green]{len(matched)} file{'s' if len(matched) != 1 else ''}"
                    f" verified[/green]"
                )
            if mismatched:
                console.print(
                    f"[bold red]{len(mismatched)} file"
                    f"{'s' if len(mismatched) != 1 else ''}"
                    f" FAILED verification[/bold red]"
                )
                sys.exit(1)

        sys.exit(0)
    else:
        console.print(
            f"[bold red]Failed:[/bold red] {failed_count} bucket"
            f"{'s' if failed_count != 1 else ''} failed"
        )
        sys.exit(74)


if __name__ == "__main__":
    main()
