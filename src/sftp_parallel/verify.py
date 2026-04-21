"""Remote file verification via checksums."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess

from sftp_parallel.batch import (
    MIN_TRANSFER_RATE,
    CONNECTION_OVERHEAD,
    validate_filename,
    validate_host,
    validate_port,
    validate_remote_dir,
)


def compute_local_checksum(filepath: str, algorithm: str = "sha256") -> str:
    """Compute the checksum of a local file.

    Parameters
    ----------
    filepath:
        Path to the local file.
    algorithm:
        Hash algorithm name (e.g. ``"sha256"``, ``"md5"``).

    Returns
    -------
    str
        Hex digest of the file's content.
    """
    h = hashlib.new(algorithm)
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_checksum_output(output: str) -> dict[str, str]:
    """Parse ``sha256sum``-style output into a basename -> digest mapping.

    Parameters
    ----------
    output:
        Raw stdout from a ``sha256sum`` command.

    Returns
    -------
    dict[str, str]
        Mapping of basename to hex digest.  Lines that cannot be parsed are
        silently skipped.
    """
    result: dict[str, str] = {}
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            parts = line.split(" *", 1)
            if len(parts) != 2:
                continue
        checksum, filepath = parts
        filename = os.path.basename(filepath.rstrip())
        result[filename] = checksum.strip()
    return result


def compute_remote_checksums(
    host: str,
    remote_dir: str,
    filenames: list[str],
    algorithm: str = "sha256",
    timeout: int = 10,
    port: int = 22,
) -> dict[str, str] | None:
    """Compute checksums of remote files via SSH.

    Connects to *host* and runs ``{algorithm}sum`` in *remote_dir* for the
    given *filenames*.

    Parameters
    ----------
    host:
        Remote host specification (e.g. ``user@host``).
    remote_dir:
        Path to the remote directory containing the files.
    filenames:
        List of basenames to checksum on the remote.
    algorithm:
        Hash algorithm (default ``"sha256"``).
    timeout:
        Connection timeout in seconds.
    port:
        Remote port number.

    Returns
    -------
    dict[str, str] | None
        Mapping of basename -> hex digest.  Partial results are returned
        even if some files could not be hashed.  Returns ``None`` if the
        SSH connection fails entirely.

    Raises
    ------
    ValueError
        If *host*, *remote_dir*, or *port* is invalid, or if *algorithm*
        contains disallowed characters.

    Note
    ----
    There is no check for ``ARG_MAX`` — if *filenames* is very large,
    the constructed shell command may exceed the remote system's
    ``ARG_MAX`` limit, causing the ``ssh`` invocation to fail with
    ``E2BIG``.  In practice this is extremely unlikely for typical usage
    (hundreds of files), but is a theoretical limit.
    """
    validate_host(host)
    validate_remote_dir(remote_dir)
    validate_port(port)

    if not re.fullmatch(r"[a-zA-Z0-9_-]+", algorithm):
        raise ValueError(
            f"invalid algorithm '{algorithm}': "
            "must contain only letters, digits, hyphens, or underscores"
        )

    if not filenames:
        return None

    for fn in filenames:
        if not validate_filename(fn):
            raise ValueError(f"invalid remote filename: {fn!r}")

    sum_cmd = f"{algorithm}sum"
    files_str = " ".join(shlex.quote(f) for f in filenames)
    remote_cmd = f"cd {shlex.quote(remote_dir)} && {sum_cmd} {files_str}"

    cmd: list[str] = [
        "ssh",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        "BatchMode=yes",
        "-o",
        f"Port={port}",
        host,
        remote_cmd,
    ]

    dynamic_timeout = max(
        timeout * 3,
        int(len(filenames) * 32768 / MIN_TRANSFER_RATE) + CONNECTION_OVERHEAD,
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=dynamic_timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    return parse_checksum_output(result.stdout)


def verify_uploads(
    host: str,
    remote_dir: str,
    local_dir: str,
    local_files: list[str],
    algorithm: str = "sha256",
    timeout: int = 10,
    port: int = 22,
) -> tuple[list[str], list[str]]:
    """Compare local and remote checksums for uploaded files.

    Note
    ----
    This function is not used by the CLI, which implements its own
    verification logic inline.  It is kept as a public API for
    programmatic use.

    Parameters
    ----------
    host:
        Remote host specification.
    remote_dir:
        Path to the remote directory where files were uploaded.
    local_dir:
        Local directory containing the original files.
    local_files:
        List of basenames to verify.
    algorithm:
        Hash algorithm (default ``"sha256"``).
    timeout:
        Connection timeout in seconds.
    port:
        Remote port number.

    Returns
    -------
    tuple[list[str], list[str]]
        ``(matched, mismatched)`` — two lists of filenames.
    """
    remote_checksums = compute_remote_checksums(
        host, remote_dir, local_files, algorithm=algorithm, timeout=timeout, port=port
    )
    if remote_checksums is None:
        remote_checksums = {}
    matched: list[str] = []
    mismatched: list[str] = []
    for filename in local_files:
        local_path = os.path.join(local_dir, filename)
        try:
            local_hash = compute_local_checksum(local_path, algorithm=algorithm)
        except OSError:
            mismatched.append(filename)
            continue
        remote_hash = remote_checksums.get(filename)
        if remote_hash is not None and remote_hash == local_hash:
            matched.append(filename)
        else:
            mismatched.append(filename)
    return matched, mismatched
