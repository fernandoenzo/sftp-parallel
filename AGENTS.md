# AGENTS.md — sftp-parallel

## Project Overview

`sftp-parallel` is a command-line tool for uploading local directories to remote servers via parallel SFTP sessions. Unlike Python SFTP libraries (paramiko), it spawns real `sftp` subprocesses to preserve the `put -f` (fsync) guarantee for data integrity.

### Architecture

The tool uploads files using a per-file worker queue. Each worker thread picks one file from a shared queue, opens a dedicated SFTP session, uploads that single file with `put -f`, then picks the next. This gives true parallelism and per-file progress visibility. Signal handlers ensure clean termination of all child processes on interrupt.

## Project Structure

```
src/sftp_parallel/
├── __init__.py      # Version constant
├── cli.py           # CLI entry point, argparse, _handle_upload()
├── batch.py         # sftp_escape(), build_batch_commands()
├── uploader.py      # upload_files(), run_sftp(), distribute_files() (deprecated),
│                    # run_parallel_uploads() (deprecated), parse_ls_output(),
│                    # get_remote_file_sizes(), filter_existing_files()
├── verify.py        # compute_local_checksum(), parse_checksum_output(),
│                    # compute_remote_checksums(), verify_uploads()
├── progress.py      # create_upload_progress(), advance_progress() (Rich progress bar)
├── signals.py       # setup_signal_handlers(), cleanup_signal_handlers() (SIGINT/SIGTERM)
└── utils.py         # (currently empty)

```

## Module Responsibilities

### cli.py
Argument parsing with argparse. Entry point is `main()`. `_handle_upload()` orchestrates the upload flow: parse destination, list files, filter existing, run uploads, verify checksums.

### batch.py
SFTP batch command generation. `sftp_escape()` handles path escaping for quotes and backslashes. `build_batch_commands()` generates `cd`, `put -f`, and `bye` directives.

### uploader.py
Core upload logic. `upload_files()` is the primary entry point — it uses a `ThreadPoolExecutor` worker queue where each worker uploads one file per SFTP session. `run_sftp()` invokes `sftp -N -b -` with timeout options. `distribute_files()` and `run_parallel_uploads()` are deprecated (bucket-based approach, replaced by per-file workers). `get_remote_file_sizes()` and `filter_existing_files()` support `--skip-existing` via size comparison.

### verify.py
Checksum verification via SSH. `compute_local_checksum()` uses hashlib. `compute_remote_checksums()` runs `{algorithm}sum` via SSH. `verify_uploads()` compares local and remote hashes, returning matched and mismatched lists.

### progress.py
Rich progress bar using context manager pattern. Tracks files completed (not bytes) since batch SFTP lacks per-byte progress.

### signals.py
Signal handling for clean shutdown. Registers SIGINT/SIGTERM handlers that kill process groups via `os.killpg()`. Uses `start_new_session=True` on Popen for process group isolation.

## Key Design Decisions

1.  **Subprocess to `sftp -f` instead of paramiko**: Preserves fsync behavior. Python libraries cannot guarantee server-side fsync.
2.  **Subprocess to `ssh` for `--verify`**: Runs `sha256sum` remotely, avoiding library dependencies.
3.  **`start_new_session=True` on Popen**: Enables process group kill for clean Ctrl+C handling.
4.  **Per-file worker queue**: Each worker thread picks one file, uploads it in its own SFTP session, then gets the next. Provides true parallelism and per-file progress visibility.
5.  **Rich progress tracks per-file completion**: Shows `✓ filename` for each uploaded file in real-time.
6.  **`shlex.quote()` for shell safety**: Remote paths and filenames in SSH commands are quoted to prevent command injection.

## Module Dependencies

```
cli.py → batch.py, uploader.py, verify.py, progress.py, signals.py
uploader.py → batch.py, signals.py
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

198+ tests. All tests mock subprocess calls to avoid requiring real SSH connections.

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
