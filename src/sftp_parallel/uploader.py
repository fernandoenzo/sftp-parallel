"""SFTP uploader module – subprocess wrapper for single sftp invocation."""

from __future__ import annotations

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
