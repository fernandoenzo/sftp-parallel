# AGENTS.md — sftp-parallel

## Project Overview

`sftp-parallel` is a command-line tool for uploading local directories to remote servers via parallel SFTP sessions. Unlike Python SFTP libraries (paramiko), it spawns real `sftp` subprocesses to preserve the `put -f` (fsync) guarantee for data integrity.

### Architecture

The tool uploads files using a per-file worker queue. Each worker spawns an **interactive SFTP session via PTY** (`pty.fork()`), sends commands one-by-one (`cd`, `put -f`, `bye`), and parses `\r`-delimited progress output in real time. This gives true parallelism, per-file byte-level progress visibility, and idle timeout detection. Signal handlers ensure clean termination of all child processes on interrupt.

## Project Structure

```
src/sftp_parallel/
├── __init__.py      # Version constant
├── cli.py           # CLI entry point, argparse, _handle_upload()
├── batch.py         # sftp_escape(), sftp_escape_interactive(),
│                    # build_batch_commands(), build_interactive_commands()
├── uploader.py      # upload_files(), _upload_one_via_pty(),
│                    # run_sftp(), parse_ls_output(),
│                    # get_remote_file_sizes(), filter_existing_files()
├── verify.py        # compute_local_checksum(), parse_checksum_output(),
│                    # compute_remote_checksums(), verify_uploads()
├── progress.py      # create_upload_progress() (v1, per-file count),
│                    # create_upload_progress_v2() (v2, per-file bytes),
│                    # FileProgress dataclass, add_worker_task(),
│                    # update_worker_progress(), complete_worker_task(),
│                    # make_indeterminate_task()
├── pty_worker.py    # PTYWorker class, WorkerResult dataclass,
│                    # _PROGRESS_RE, _SFTP_PROMPT_RE, _SFTP_ERROR_RE,
│                    # reader/writer threads, idle timeout
├── signals.py       # setup_signal_handlers() (v1, Popen-based),
│                    # setup_signal_handlers_v2() (v2, PTYWorker-based),
│                    # cleanup_signal_handlers()
└── utils.py         # (currently empty)

```

## Module Responsibilities

### cli.py
Argument parsing with argparse. Entry point is `main()`. `_handle_upload()` orchestrates the upload flow: parse destination, list files, filter existing, run uploads, verify checksums. Flags: `--no-progress` and `--idle-timeout`.

### batch.py
SFTP command generation. `sftp_escape()` handles path escaping for double-quote batch mode. `sftp_escape_interactive()` handles backslash-escaping for interactive PTY mode. `build_batch_commands()` generates `cd`, `put -f`, and `bye` directives as a single string (batch mode). `build_interactive_commands()` returns them as a `list[str]` (interactive mode).

### uploader.py
Core upload logic. `upload_files()` uses PTY-based interactive SFTP with per-worker `PTYWorker` instances via `ThreadPoolExecutor`. Each worker calls `_upload_one_via_pty()` which creates a `PTYWorker`, runs it, and returns success/failure. `progress_callback` signature: `(file_path, bytes_transferred, total_bytes)`. `completion_callback` signature: `(file_path, success)`. Batch-mode functions (`run_sftp`, `_build_sftp_cmd`, `_cleanup_proc`) are retained for `get_remote_file_sizes()`.

### pty_worker.py
PTY interaction engine. `PTYWorker` uses `pty.fork()` to allocate a controlling terminal (required for OpenSSH's `can_output()` progress check). Reader thread parses `\r`-delimited progress output via `select.select()`. Writer thread sends commands after `sftp>` prompt detection. Idle timeout checked in reader loop. `WorkerResult` dataclass: `success`, `file_path`, `bytes_transferred`, `file_size`, `error_message`.

### verify.py
Checksum verification via SSH. `compute_local_checksum()` uses hashlib. `compute_remote_checksums()` runs `{algorithm}sum` via SSH. `verify_uploads()` compares local and remote hashes, returning matched and mismatched lists.

### progress.py
Two Rich progress bar versions: v1 (per-file count, `create_upload_progress`/`advance_progress`) and v2 (per-file byte-level, `create_upload_progress_v2`/`add_worker_task`/`update_worker_progress`/`complete_worker_task`). `FileProgress` dataclass tracks per-file state.

### signals.py
Two versions: v1 uses `list[tuple[Popen, int]]` for batch-mode, v2 uses `list[PTYWorker]` for interactive mode. Both register SIGINT/SIGTERM handlers. v2 calls `worker.terminate()` which kills process group and closes PTY master fd.

## Key Design Decisions

1.  **PTY-based interactive SFTP instead of batch mode**: `pty.fork()` allocates a controlling terminal so OpenSSH's `can_output()` check passes, enabling real-time per-byte progress. Batch mode (`sftp -b -`) never shows progress.
2.  **`pty.fork()` not `pty.openpty() + Popen`**: Only `pty.fork()` (which calls `os.login_tty()` → `setsid()` + `TIOCSCTTY`) sets the controlling terminal. `Popen(start_new_session=True)` only calls `setsid()` but not `TIOCSCTTY`.
3.  **Per-file worker queue**: Each worker thread picks one file, spawns a dedicated PTY/SFTP session, uploads, then picks the next.
4.  **Real-time progress parsing**: Reader thread splits PTY output on `\r` and `\n`, matches `_PROGRESS_RE` for byte-level progress, `_SFTP_PROMPT_RE` for command synchronization, `_SFTP_ERROR_RE` for error detection.
5.  **Idle timeout**: Checked in reader thread via `time.monotonic() - last_progress_time > idle_timeout`. No separate watchdog thread needed.
6.  **Shell escaping**: `sftp_escape()` for batch mode (double-quotes), `sftp_escape_interactive()` for PTY mode (backslashes).
7.  **Subprocess to `ssh` for `--verify`**: Runs `sha256sum` remotely, avoiding library dependencies.
8.  **Signal handling with PTYWorker**: v2 handlers call `worker.terminate()` which does SIGTERM → SIGKILL escalation and closes `master_fd`.
9.  **Rich progress v2**: Per-file tasks with `DownloadColumn`, `TransferSpeedColumn`, `TimeRemainingColumn`. Start as invisible, become visible on first byte progress.

## Module Dependencies

```
cli.py → batch.py, uploader.py, verify.py, progress.py, signals.py
uploader.py → batch.py, pty_worker.py, signals.py
pty_worker.py → batch.py
verify.py → subprocess (ssh)
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

224 tests. All tests mock subprocess/PTY calls to avoid requiring real SSH connections.

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