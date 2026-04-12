"""CLI module for sftp-parallel."""

from __future__ import annotations

import argparse
import sys

from rich.console import Console

from sftp_parallel import __version__

console = Console()


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
    upload_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable debug output",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Actual upload logic will be implemented in later tasks.
    # For now, just return the parsed args for validation / testing.
    console.print(f"[bold green]Command:[/bold green] {args.command}")
    console.print(f"[bold green]Local dir:[/bold green] {args.local_dir}")
    console.print(f"[bold green]Destination:[/bold green] {args.destination}")
    console.print(f"[bold green]Threads:[/bold green] {args.threads}")
    console.print(f"[bold green]Verify:[/bold green] {args.verify}")
    console.print(f"[bold green]Skip existing:[/bold green] {args.skip_existing}")
    console.print(f"[bold green]Verbose:[/bold green] {args.verbose}")


if __name__ == "__main__":
    main()
