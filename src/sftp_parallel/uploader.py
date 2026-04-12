"""SFTP uploader module – subprocess wrapper for single sftp invocation."""

from __future__ import annotations

import subprocess


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

    output = result.stdout + result.stderr
    success = result.returncode == 0
    return success, output
