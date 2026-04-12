"""SFTP uploader module – subprocess wrapper for single sftp invocation."""

from __future__ import annotations

import os
import re
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def distribute_files(files: list[str], num_sessions: int) -> list[list[str]]:
    """Distribute *files* across *num_sessions* buckets in round-robin fashion.

    Parameters
    ----------
    files:
        List of file paths to distribute.
    num_sessions:
        Number of parallel sessions (buckets) to distribute into.

    Returns
    -------
    list[list[str]]
        A list of *num_sessions* buckets.  Each bucket contains the files
        assigned to that session.  Bucket *i* receives files at indices
        ``i, i+num_sessions, i+2*num_sessions, …``.

    Examples
    --------
    >>> distribute_files(['a', 'b', 'c', 'd', 'e'], 2)
    [['a', 'c', 'e'], ['b', 'd']]
    >>> distribute_files(['a', 'b', 'c'], 4)
    [['a'], ['b'], ['c'], []]
    >>> distribute_files([], 2)
    [[], []]
    """
    buckets: list[list[str]] = [[] for _ in range(num_sessions)]
    for idx, file in enumerate(files):
        buckets[idx % num_sessions].append(file)
    return buckets


def build_batch_commands(files: list[str]) -> str:
    """Build newline-separated sftp batch directives for a list of *files*.

    Each file gets a ``put`` directive.  A trailing ``bye`` is appended
    to gracefully close the sftp session.

    Parameters
    ----------
    files:
        List of local file paths to upload via sftp ``put`` commands.

    Returns
    -------
    str
        Newline-separated sftp batch commands ready for stdin.
    """
    lines: list[str] = [f"put {f}" for f in files]
    lines.append("bye")
    return "\n".join(lines)


def run_sftp(
    host: str,
    batch_commands: str,
    timeout: int = 10,
) -> tuple[bool, str]:
    """Invoke ``sftp -N -b -`` with *batch_commands* piped via stdin.

    Parameters
    ----------
    host:
        Remote host specification (e.g. ``user@host``).
    batch_commands:
        Newline-separated sftp batch directives to send on stdin.
    timeout:
        Connection timeout in seconds (passed as ``ConnectTimeout``).

    Returns
    -------
    tuple[bool, str]
        A ``(success, output)`` pair where *success* is ``True`` when the
        sftp process exited with code 0, and *output* combines stdout and
        stderr for diagnostics.
    """
    cmd: list[str] = [
        "sftp",
        "-N",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        "BatchMode=yes",
        "-b",
        "-",
        host,
    ]

    try:
        result = subprocess.run(
            cmd,
            input=batch_commands,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, "sftp binary not found"
    except subprocess.TimeoutExpired:
        return False, "sftp process timed out"
    except OSError as exc:
        return False, f"OS error: {exc}"

    output: str = result.stdout + result.stderr
    success: bool = result.returncode == 0
    return success, output


def run_parallel_uploads(
    host: str,
    buckets: list[list[str]],
    timeout: int = 10,
) -> tuple[bool, int]:
    """Spawn parallel SFTP processes, one per bucket, and collect results."""
    non_empty_buckets = [b for b in buckets if b]
    if not non_empty_buckets:
        return True, 0

    proc_bucket_pairs: list[tuple[subprocess.Popen[str], str]] = []

    for bucket in non_empty_buckets:
        batch_commands: str = build_batch_commands(bucket)
        cmd: list[str] = [
            "sftp",
            "-N",
            "-o",
            f"ConnectTimeout={timeout}",
            "-o",
            "BatchMode=yes",
            "-b",
            "-",
            host,
        ]
        proc: subprocess.Popen[str] = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        proc_bucket_pairs.append((proc, batch_commands))

    failed_count: int = 0
    for proc, batch_cmds in proc_bucket_pairs:
        try:
            proc.communicate(input=batch_cmds)
        except Exception:  # noqa: BLE001
            failed_count += 1
            continue

        if proc.returncode != 0:
            failed_count += 1

    all_success: bool = failed_count == 0
    return all_success, failed_count


def parse_ls_output(ls_output: str) -> dict[str, int]:
    """Parse ``ls -l`` output from SFTP into a filename → size mapping.

    Parameters
    ----------
    ls_output:
        Raw output from ``ls -l`` run inside an SFTP session.  Each line
        has the standard format::

            -rw-r--r--   1 user     group        1234 Jan  1 12:00 file.txt

    Returns
    -------
    dict[str, int]
        Mapping of filename to file size in bytes.

    Examples
    --------
    >>> parse_ls_output("-rw-r--r-- 1 user group 1234 Jan  1 12:00 file.txt\\n")
    {'file.txt': 1234}
    """
    result: dict[str, int] = {}
    for line in ls_output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # ls -l format: permissions links owner group size month day time/year name
        match = re.match(
            r"^([\-ldrwx]{10})\s+\d+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+\d+\s+\S+\s+(.+)$",
            line,
        )
        if match:
            size = int(match.group(2))
            name = match.group(3).strip()
            result[name] = size
    return result


def get_remote_file_sizes(
    host: str,
    remote_dir: str,
    timeout: int = 10,
) -> dict[str, int]:
    """Retrieve filename → size mapping from a remote directory via SFTP.

    Connects to *host* and runs ``ls -l`` in *remote_dir* to enumerate
    remote files and their sizes.

    Parameters
    ----------
    host:
        Remote host specification (e.g. ``user@host``).
    remote_dir:
        Path to the remote directory to list.
    timeout:
        Connection timeout in seconds.

    Returns
    -------
    dict[str, int]
        Mapping of filename to file size in bytes.  Empty dict on failure.
    """
    batch_commands: str = f'cd "{remote_dir}"\nls -l\nbye'
    success, output = run_sftp(host, batch_commands, timeout=timeout)
    if not success:
        return {}
    return parse_ls_output(output)


def filter_existing_files(
    local_dir: str,
    local_files: list[str],
    remote_sizes: dict[str, int],
) -> list[str]:
    """Return files from *local_files* that need uploading.

    A file **needs** uploading when it either does not exist on the remote,
    or when its local size differs from the remote size.

    Parameters
    ----------
    local_dir:
        Local directory containing the files.
    local_files:
        List of filenames (not full paths) to check.
    remote_sizes:
        Mapping of remote filename → size in bytes (as returned by
        :func:`get_remote_file_sizes`).

    Returns
    -------
    list[str]
        Subset of *local_files* that must be uploaded.

    Examples
    --------
    >>> filter_existing_files("/tmp", ["a.txt", "b.txt"], {"a.txt": 100})
    ['b.txt']
    """
    need_upload: list[str] = []
    for filename in local_files:
        local_path = os.path.join(local_dir, filename)
        try:
            local_size = os.path.getsize(local_path)
        except OSError:
            continue
        remote_size = remote_sizes.get(filename)
        if remote_size is None or remote_size != local_size:
            need_upload.append(filename)
    return need_upload
