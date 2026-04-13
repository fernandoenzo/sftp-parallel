# sftp-parallel

Parallel SFTP uploader with fsync guarantee and checksum verification.

Upload local directories to remote servers via parallel SFTP sessions. Uses `sftp -f` (fsync) for data integrity, with optional checksum verification via SSH.

## Features

*   Parallel uploads via `-t/--threads` (1-16 worker threads, each file gets its own SFTP session)
*   `put -f` (fsync) guarantee via subprocess to real `sftp`
*   `--verify` with SHA-256 checksums via SSH
*   `--skip-existing` via size comparison
*   Rich progress bar
*   Per-file progress: shows ✓ filename for each completed upload in real time
*   Clean SIGINT/SIGTERM handling (Ctrl+C terminates all child processes)
*   No paramiko — subprocess to `sftp` preserves fsync behavior

## How It Works

`sftp-parallel` uses a per-file worker queue model:

1.  You specify `-t N` (number of parallel workers, default 2).
2.  Each worker thread picks one file from a shared queue, opens a dedicated SFTP session, uploads that file with `put -f`, then picks the next file.
3.  Progress advances per-file — you see `✓ filename` for each completed upload.
4.  On interrupt (Ctrl+C), all child SFTP processes are terminated cleanly.

This gives true parallelism: all workers share the work, not just the first N buckets.

## Requirements

*   Python 3.13+
*   `sftp` and `ssh` commands available
*   SSH key-based authentication

## Installation

From the repository:

```bash
pip install -e .
```

Future PyPI install:

```bash
pip install sftp-parallel
```

## Usage Examples

**Basic upload:**

```bash
sftp-parallel upload /local/dir user@host:/remote/dir
```

**With threads:**

```bash
sftp-parallel upload -t 4 /local/dir user@host:/remote/dir
```

**With verification:**

```bash
sftp-parallel upload --verify /local/dir user@host:/remote/dir
```

**Skip existing:**

```bash
sftp-parallel upload --skip-existing /local/dir user@host:/remote/dir
```

**Combined options:**

```bash
sftp-parallel upload -t 8 --verify --skip-existing /data/backups server:/backups
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 2 | Usage error |
| 1 | Verification failure |
| 74 | Upload failure |
| 130 | SIGINT (Ctrl+C) |
| 143 | SIGTERM |

## License

GPL-3.0
