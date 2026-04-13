"""SFTP uploader module – subprocess wrapper for single sftp invocation."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable

from sftp_parallel.batch import build_batch_commands
from sftp_parallel.signals import cleanup_signal_handlers, setup_signal_handlers


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
    if num_sessions <= 0:
        raise ValueError(f"num_sessions must be positive, got {num_sessions}")
    buckets: list[list[str]] = [[] for _ in range(num_sessions)]
    for idx, file in enumerate(files):
        buckets[idx % num_sessions].append(file)
    return buckets


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
    remote_dir: str,
    local_dir: str,
    timeout: int = 10,
    progress_callback: Callable[[int], None] | None = None,
) -> tuple[bool, int]:
    """Spawn parallel SFTP processes, one per bucket, and collect results.

    .. deprecated::
        Use :func:`upload_files` instead, which provides per-file progress
        and true parallelism via a worker queue.

    Parameters
    ----------
    host:
        Remote host specification (e.g. ``user@host``).
    buckets:
        List of file buckets, where each bucket is a list of filenames
        (basenames only) to upload in a single session.
    remote_dir:
        Remote directory path to upload files to.
    local_dir:
        Local directory path containing the files to upload.
    timeout:
        Connection timeout in seconds (passed as ``ConnectTimeout``).
    progress_callback:
        Optional callback function that receives the number of files
        completed when each bucket finishes. Signature: ``callback(int) -> None``.
        Typically used with :func:`sftp_parallel.progress.advance_progress`.

    Returns
    -------
    tuple[bool, int]
        A ``(all_success, failed_count)`` pair where *all_success* is ``True``
        when all buckets completed successfully, and *failed_count* is the
        number of buckets that failed.
    """
    non_empty_buckets = [b for b in buckets if b]
    if not non_empty_buckets:
        return True, 0

    proc_bucket_pairs: list[tuple[subprocess.Popen[str], list[str]]] = []

    for bucket in non_empty_buckets:
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
            start_new_session=True,
        )
        proc_bucket_pairs.append((proc, bucket))

    popens = [proc for proc, _bucket in proc_bucket_pairs]
    setup_signal_handlers(popens)
    try:
        failed_count: int = 0
        for proc, bucket in proc_bucket_pairs:
            batch_cmds = build_batch_commands(remote_dir, local_dir, bucket)
            try:
                proc.communicate(input=batch_cmds)
            except Exception:  # noqa: BLE001
                failed_count += 1
                continue

            if proc.returncode != 0:
                failed_count += 1
            else:
                if progress_callback is not None:
                    progress_callback(len(bucket))

        all_success: bool = failed_count == 0
        return all_success, failed_count
    finally:
        cleanup_signal_handlers()


def upload_files(
    host: str,
    files: list[str],
    remote_dir: str,
    local_dir: str,
    num_workers: int = 2,
    timeout: int = 10,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[bool, int]:
    """Upload files using *num_workers* parallel sftp sessions.

    Each worker picks one file from a shared queue, opens an sftp
    session, uploads that single file with ``put -f``, then picks the next.
    Progress advances per-file, giving real-time visibility.

    Parameters
    ----------
    host:
        Remote host specification (e.g. ``user@host``).
    files:
        List of filenames (basenames only) to upload.
    remote_dir:
        Remote directory path to upload files to.
    local_dir:
        Local directory path containing the files to upload.
    num_workers:
        Number of parallel worker threads (default 2).
    timeout:
        Connection timeout in seconds (passed as ``ConnectTimeout``).
    progress_callback:
        Optional callback invoked per successfully uploaded file with
        the filename.  Signature: ``callback(str) -> None``.

    Returns
    -------
    tuple[bool, int]
        ``(all_success, failed_count)`` where *all_success* is ``True``
        when every file uploaded successfully.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    if not files:
        return True, 0

    file_queue = list(files)
    failed_count = 0
    lock = threading.Lock()
    active_popens: list[subprocess.Popen[str]] = []
    popen_lock = threading.Lock()

    def upload_one(filename: str) -> bool:
        batch_cmds = build_batch_commands(remote_dir, local_dir, [filename])
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
            start_new_session=True,
        )
        with popen_lock:
            active_popens.append(proc)
        try:
            proc.communicate(input=batch_cmds, timeout=timeout * 3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return False
        except Exception:  # noqa: BLE001
            return False
        finally:
            with popen_lock:
                if proc in active_popens:
                    active_popens.remove(proc)
        if proc.returncode != 0:
            return False
        if progress_callback is not None:
            progress_callback(filename)
        return True

    setup_signal_handlers(active_popens)
    try:
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {executor.submit(upload_one, f): f for f in file_queue}
            for future in as_completed(futures):
                if not future.result():
                    with lock:
                        failed_count += 1
    finally:
        cleanup_signal_handlers()

    return failed_count == 0, failed_count


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
        # Note: sftp may use '?' instead of a digit for the link count
        match = re.match(
            r"^-[-rwx]{9}\s+\S+\s+\S+\s+\S+\s+(\d+)\s+\S+\s+\d+\s+\S+\s+(.+)$",
            line,
        )
        if match:
            size = int(match.group(1))
            name = match.group(2).strip()
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
