"""SFTP uploader module – subprocess wrapper for single sftp invocation."""

# Error handling convention: Functions return (bool, str/int) tuples.

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from sftp_parallel.batch import (
    DEFAULT_TIMEOUT,
    sftp_escape,
    validate_filename,
    validate_host,
    validate_port,
    validate_remote_dir,
    _validate_sftp_path,
)
from sftp_parallel.pty_worker import PTYWorker
from sftp_parallel.signals import (
    cleanup_signal_handlers,
    setup_signal_handlers_v2,
)

_PROCESS_KILL_WAIT_SECONDS = 5
_SFTP_TIMEOUT_MULTIPLIER = 3

logger = logging.getLogger(__name__)


def _build_sftp_cmd(host: str, timeout: int, port: int = 22) -> list[str]:
    """Build the sftp command-line arguments list."""
    return [
        "sftp",
        "-N",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        "BatchMode=yes",
        "-o",
        f"Port={port}",
        "-b",
        "-",
        host,
    ]


def _cleanup_proc(proc: subprocess.Popen[str], pgid: int = 0) -> None:
    """Kill a subprocess and close its pipes, swallowing all errors.

    Parameters
    ----------
    proc:
        The Popen process to clean up.
    pgid:
        Cached process group ID.  If greater than 1, used directly
        instead of re-fetching via :func:`os.getpgid` (avoids PID
        recycling race).  If 0, falls back to ``os.getpgid(proc.pid)``.
    """
    if pgid <= 1:
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, OSError):
            pgid = -1
    if pgid > 1:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except Exception:
                logger.debug("Error closing pipe during cleanup", exc_info=True)
    try:
        proc.wait(timeout=_PROCESS_KILL_WAIT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_sftp(
    host: str,
    batch_commands: str,
    timeout: int = 10,
    port: int = 22,
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
    port:
        Remote port number.

    Returns
    -------
    tuple[bool, str]
        A ``(success, output)`` pair where *success* is ``True`` when the
        sftp process exited with code 0.

    Raises
    ------
    ValueError
        If *host* or *port* fails validation.
    """
    validate_host(host)
    validate_port(port)

    cmd = _build_sftp_cmd(host, timeout, port=port)
    proc: subprocess.Popen[str] | None = None

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(
                input=batch_commands,
                timeout=timeout * _SFTP_TIMEOUT_MULTIPLIER,
            )
        except subprocess.TimeoutExpired:
            _cleanup_proc(proc)
            return False, "sftp process timed out"
    except FileNotFoundError:
        return False, "sftp binary not found"
    except OSError as exc:
        if proc is not None:
            _cleanup_proc(proc)
        return False, f"OS error: {exc}"

    output = stdout + stderr
    success = proc.returncode == 0
    return success, output


def _upload_one_via_pty(
    host: str,
    file_path: str,
    remote_dir: str,
    port: int,
    connect_timeout: int,
    idle_timeout: int,
    active_workers: list[PTYWorker],
    worker_lock: threading.Lock,
    progress_callback: Callable[[str, int, int], None] | None,
) -> bool:
    """Upload a single file via PTYWorker. Returns True on success."""
    worker = PTYWorker(
        host=host,
        file_path=file_path,
        remote_dir=remote_dir,
        port=port,
        connect_timeout=connect_timeout,
        idle_timeout=idle_timeout,
        prompt_timeout=idle_timeout,
        progress_callback=progress_callback,
    )
    with worker_lock:
        active_workers.append(worker)
    try:
        result = worker.run()
        if not result.success and result.error_message:
            logger.error(
                "Upload failed for %s: %s", result.file_path, result.error_message
            )
        return result.success
    except Exception:
        logger.exception("Unexpected error uploading %s", file_path)
        return False
    finally:
        with worker_lock:
            if worker in active_workers:
                active_workers.remove(worker)


def upload_files(
    host: str,
    file_paths: list[str],
    remote_dir: str,
    num_workers: int = 2,
    port: int = 22,
    progress_callback: Callable[[str, int, int], None] | None = None,
    completion_callback: Callable[[str, bool], None] | None = None,
    idle_timeout: int = 30,
) -> tuple[bool, int]:
    """Upload files using PTY-based interactive SFTP with real-time progress.

    Parameters
    ----------
    host:
        Remote host specification (e.g. ``user@host``).
    file_paths:
        List of local file paths to upload.
    remote_dir:
        Remote directory path to upload files to.
    num_workers:
        Number of parallel worker threads (default 2).
    port:
        Remote port number.
    progress_callback:
        Optional callback invoked with progress updates.
        Signature: ``callback(file_path, bytes_transferred, total_bytes)``.
    completion_callback:
        Optional callback invoked when each file upload completes.
        Signature: ``callback(file_path, success)`` where *success* is
        ``True`` when the upload succeeded.
    idle_timeout:
        Seconds without progress before killing SFTP process (default 30).

    Returns
    -------
    tuple[bool, int]
        ``(all_success, failed_count)`` where *all_success* is ``True``
        when every file uploaded successfully.

    Raises
    ------
    ValueError
        If *host*, *port*, or *remote_dir* fails validation.
    """
    validate_host(host)
    validate_port(port)
    validate_remote_dir(remote_dir)

    if not file_paths:
        return True, 0

    connect_timeout = DEFAULT_TIMEOUT
    lock = threading.Lock()
    active_workers: list[PTYWorker] = []
    worker_lock = threading.Lock()

    setup_signal_handlers_v2(active_workers, worker_lock)
    try:
        failed_count = 0
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {
                executor.submit(
                    _upload_one_via_pty,
                    host,
                    fp,
                    remote_dir,
                    port,
                    connect_timeout,
                    idle_timeout,
                    active_workers,
                    worker_lock,
                    progress_callback,
                ): fp
                for fp in file_paths
            }
            for future in futures:
                fp = futures[future]
                try:
                    success = future.result(timeout=idle_timeout * 2 + 120)
                    if not success:
                        with lock:
                            failed_count += 1
                    if completion_callback is not None:
                        try:
                            completion_callback(fp, success)
                        except Exception:
                            logger.debug("Completion callback failed for %s", fp, exc_info=True)
                except FuturesTimeoutError:
                    logger.error("Worker timed out for %s", fp)
                    with lock:
                        failed_count += 1
                    success = False
                    if completion_callback is not None:
                        try:
                            completion_callback(fp, success)
                        except Exception:
                            logger.debug("Completion callback failed for %s", fp, exc_info=True)
                except Exception:
                    logger.exception("Worker crashed unexpectedly")
                    with lock:
                        failed_count += 1
                    if completion_callback is not None:
                        try:
                            completion_callback(fp, False)
                        except Exception:
                            logger.debug("Completion callback failed for %s", fp, exc_info=True)
    finally:
        cleanup_signal_handlers()

    return failed_count == 0, failed_count


def parse_ls_output(ls_output: str) -> dict[str, int]:
    """Parse ``ls -l`` output from SFTP into a filename -> size mapping.

    Parameters
    ----------
    ls_output:
        Raw output from ``ls -l`` run inside an SFTP session.

    Returns
    -------
    dict[str, int]
        Mapping of filename to file size in bytes.

    Note
    ----
    Leading whitespace in filenames is not distinguishable from the
    column-separator whitespace in ``ls -l`` output.  Filenames with
    leading spaces will have those spaces stripped.
    """
    result: dict[str, int] = {}
    for line in ls_output.strip().splitlines():
        line = line.rstrip()
        if not line:
            continue
        match = re.match(
            r"^-[-rwxsStT]{9}[.+@]?\s+\S+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+\d+\s+\S+\s+(.+)$",
            line,
        )
        if match:
            size = int(match.group(1))
            name = match.group(2).rstrip()
            if validate_filename(name):
                result[name] = size
    return result


def get_remote_file_sizes(
    host: str,
    remote_dir: str,
    timeout: int = 10,
    port: int = 22,
) -> dict[str, int] | None:
    """Retrieve filename -> size mapping from a remote directory via SFTP.

    Parameters
    ----------
    host:
        Remote host specification (e.g. ``user@host``).
    remote_dir:
        Path to the remote directory to list.
    timeout:
        Connection timeout in seconds.
    port:
        Remote port number.

    Returns
    -------
    dict[str, int] | None
        Mapping of filename to file size in bytes.  Returns ``None``
        on failure (e.g., SFTP connection error).

    Raises
    ------
    ValueError
        If *host*, *port*, or *remote_dir* fails validation, or if
        *remote_dir* contains control characters (via :func:`~sftp_parallel.batch._validate_sftp_path`).
    """
    validate_host(host)
    validate_port(port)
    validate_remote_dir(remote_dir)
    _validate_sftp_path(remote_dir, "remote directory")

    batch_commands: str = f'cd "{sftp_escape(remote_dir)}"\nls -l\nbye'
    success, output = run_sftp(host, batch_commands, timeout=timeout, port=port)
    if not success:
        return None
    return parse_ls_output(output)


def filter_existing_files(
    local_dir: str,
    local_files: list[str],
    remote_sizes: dict[str, int],
) -> list[str]:
    """Return files from *local_files* that need uploading.

    A file **needs** uploading when it either does not exist on the remote,
    or when its local size differs from the remote size.

    Note
    ----
    This function is not used by the CLI, which implements its own
    skip-existing logic inline.  It is kept as a public API for
    programmatic use.

    Note
    ----
    There is a TOCTOU race condition: a file's size may change between
    the check performed here and the subsequent upload attempt.
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
