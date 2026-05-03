# AGENTS.md — sftp-parallel

## Project Overview

`sftp-parallel` is a command-line tool for uploading local directories to remote servers via parallel SFTP sessions. Unlike Python SFTP libraries (paramiko), it spawns real `sftp` subprocesses to preserve the `put -f` (fsync) guarantee for data integrity.

### Architecture

The tool uploads files using a per-file worker queue. Each worker spawns an **interactive SFTP session via PTY** (`pty.fork()`), sends commands one-by-one (`cd`, `put -f`, `bye`), and parses output in real time using a `select()` loop inside the `Worker` class. This gives true parallelism, per-file byte-level progress visibility, and idle timeout detection. Signal handlers ensure clean termination of all child processes on interrupt.

## Project Structure

```
src/sftp_parallel/
├── __init__.py      # Public API exports
├── __main__.py      # Entry point
├── cli.py           # CLI entry point, argparse, main()
├── lib.py           # Pure functions: validation, escaping,
│                    # checksums, parsing, remote file listing
├── worker.py        # Worker class (PTY + select() loop),
│                    # WorkerResult dataclass, regex patterns
├── upload.py        # parallel_upload() orchestration,
│                    # signal handling, ThreadPoolExecutor
└── progress.py      # Rich progress bars, FileProgress dataclass
```

## Module Responsibilities

### cli.py
Argument parsing with argparse. Entry point is `main()`. Orchestrates the upload flow: parse destination, list files, filter existing, run uploads, verify checksums. Flags: `--no-progress` and `--idle-timeout`.

### lib.py
Consolidates all pure stateless functions from the former batch.py, verify.py, and uploader.py:
- **Validation**: `validate_host()`, `validate_port()`, `validate_remote_dir()`, `validate_filename()`
- **Escaping**: `sftp_escape()` (batch mode), `escape_interactive()` (PTY mode), `_validate_sftp_path()`, `build_interactive_commands()`
- **Checksums**: `compute_local_checksum()`, `compute_remote_checksums()`, `parse_checksum_output()`, `verify_uploads()`
- **Remote listing**: `get_remote_file_sizes()`, `parse_ls_output()`, `run_sftp()`, `filter_existing_files()`
- **Progress parsing**: `parse_progress()`, `_parse_formatted_bytes()`
- **Constants**: `DEFAULT_TIMEOUT`, `DEFAULT_IDLE_TIMEOUT`, `MIN_TRANSFER_RATE`, `CONNECTION_OVERHEAD`

### worker.py
PTY interaction engine. `Worker` class uses `pty.fork()` to allocate a controlling terminal (required for OpenSSH's `can_output()` progress check). A single `select()` loop reads PTY output, parses progress via `parse_progress()` from lib.py, detects `sftp>` prompts, and identifies errors. `WorkerResult` dataclass: `success`, `file_path`, `bytes_transferred`, `file_size`, `error_message`.

### upload.py
Core upload orchestration. `parallel_upload()` uses `Worker` instances via `ThreadPoolExecutor`. Manages progress bars via Rich, signal handler registration, and per-file success/failure counting. Returns `(ok_count, fail_count)`.

### progress.py
Rich progress bar integration. `create_upload_progress()` context manager, `add_file_task()`, `update_file_progress()`, `complete_file_task()`. `FileProgress` dataclass tracks per-file state. `BinaryDownloadColumn` and `StatusColumn` for rich formatting.

## Key Design Decisions

1.  **PTY-based interactive SFTP instead of batch mode**: `pty.fork()` allocates a controlling terminal so OpenSSH's `can_output()` check passes, enabling real-time per-byte progress. Batch mode (`sftp -b -`) never shows progress.
2.  **Single select() loop instead of reader/writer threads**: The `Worker` class uses a single-threaded `select()` loop to read PTY output, eliminating race conditions between reader and writer threads.
3.  **Per-file worker queue**: Each worker thread picks one file, spawns a dedicated PTY/SFTP session, uploads, then picks the next.
4.  **Real-time progress parsing**: `parse_progress()` in lib.py matches SFTP progress output patterns. Stalled/ETA-only lines update the progress timer without resetting byte counts.
5.  **Idle timeout**: Checked inside the select() loop via `time.monotonic() - last_progress_time > idle_timeout`.
6.  **Shell escaping**: `sftp_escape()` for batch mode (double-quotes), `escape_interactive()` for PTY mode (backslashes).
7.  **Subprocess to `ssh` for `--verify`**: Runs `sha256sum` remotely, avoiding library dependencies.
8.  **Rich progress bars**: Per-file tasks with `BinaryDownloadColumn`, `TransferSpeedColumn`, `TimeElapsedColumn`.

## Module Dependencies

```
cli.py → lib.py, upload.py, progress.py
upload.py → worker.py, lib.py
worker.py → lib.py
progress.py → rich (external)
lib.py → (stdlib only)
```

## CLI Entry Point

Defined in `pyproject.toml`:

```toml
[project.scripts]
sftp-parallel = "sftp_parallel.cli:main"
```

## Testing

Run tests with pytest:

```bash
python3 -m pytest tests/ -v
```

All tests mock subprocess/PTY calls to avoid requiring real SSH connections.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Usage error |
| 1 | Verification failure |
| 74 | Upload failure |
| 130 | SIGINT (Ctrl+C) |
| 143 | SIGTERM |

## Constraints

*   Python 3.13+ required
*   No paramiko library
*   No automatic retry logic
*   SSH key-based authentication only (no password prompts)