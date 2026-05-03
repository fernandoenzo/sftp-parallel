"""CLI module for sftp-parallel."""

import argparse
import os
import sys
from pathlib import Path

from rich.console import Console

from sftp_parallel import __version__
from sftp_parallel.lib import (
    compute_local_checksum,
    compute_remote_checksums,
    get_remote_file_sizes,
    validate_filename,
    validate_host,
    validate_port,
    validate_remote_dir,
)
from sftp_parallel.progress import create_upload_progress
from sftp_parallel.upload import parallel_upload

console = Console()


def _resolve_one(path: Path) -> Path | None:
    if path.is_file():
        if not validate_filename(path.name):
            console.print(f"[yellow]Skipping unsafe filename:[/yellow] {path.name}")
            return None
        return path.resolve()
    if path.is_symlink():
        if path.is_dir():
            return None
        console.print(f"[yellow]Skipping symlink to non-regular file:[/yellow] {path.name}")
        return None
    return None


def resolve_file_patterns(
    patterns: list[str],
    cwd: Path | None = None,
) -> list[Path]:
    base = Path(cwd or Path.cwd())
    result: list[Path] = []

    if not patterns:
        for entry in base.iterdir():
            path = _resolve_one(entry)
            if path is not None:
                result.append(path)
    else:
        for pattern in patterns:
            path = _resolve_one(base / pattern)
            if path is not None:
                result.append(path)
            elif any(ch in pattern for ch in ("*", "?", "[")):
                for entry in base.glob(pattern):
                    resolved = _resolve_one(entry)
                    if resolved is not None:
                        result.append(resolved)
            elif not (base / pattern).exists() and not (base / pattern).is_symlink():
                console.print(
                    f"[yellow]Warning: file not found:[/yellow] {pattern}"
                )

    return sorted(result, key=lambda p: str(p))


def validate_basename_uniqueness(file_paths: list[Path]) -> None:
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

    try:
        validate_host(args.server)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(2)

    try:
        validate_port(args.port)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(2)

    try:
        validate_remote_dir(args.dest)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(2)

    file_paths = list(dict.fromkeys(resolve_file_patterns(args.files)))

    try:
        validate_basename_uniqueness(file_paths)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(2)

    if not file_paths:
        console.print("[yellow]No files found matching the specified patterns.[/yellow]")
        sys.exit(0)

    file_paths_str = [str(p) for p in file_paths]
    remote_dir = args.dest

    if args.skip_existing:
        remote_sizes = get_remote_file_sizes(args.server, remote_dir, port=args.port)
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
            console.print("[bold green]All files already exist on remote.[/bold green]")
            if not args.verify:
                sys.exit(0)
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

    total_files = len(file_paths_str)
    with create_upload_progress(
        total_files, args.server, remote_dir,
        num_workers=min(args.threads, total_files) if total_files else args.threads,
        disable=args.no_progress,
    ) as progress:
        ok_count, fail_count = parallel_upload(
            args.server,
            file_paths_str,
            remote_dir,
            progress,
            num_workers=min(args.threads, total_files) if total_files else args.threads,
            port=args.port,
            idle_timeout=args.idle_timeout,
        )

    all_success = fail_count == 0
    failed_count = fail_count

    if total_files > 1:
        if failed_count == 0:
            console.print(f"[bold green]Success[/bold green] — {total_files}/{total_files} files uploaded")
        else:
            console.print(f"[bold red]Failed[/bold red] — {failed_count}/{total_files} files failed, {total_files - failed_count} succeeded")

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
        if total_files <= 1:
            console.print(
                f"[bold red]Failed:[/bold red] {failed_count} file"
                f"{'s' if failed_count != 1 else ''} failed"
            )
        sys.exit(74)


if __name__ == "__main__":
    main()