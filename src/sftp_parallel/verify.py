"""Verification module – checksum comparison for uploaded files."""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess


def compute_local_checksum(local_path: str, algorithm: str = "sha256") -> str:
    """Compute the checksum of a local file.

    Parameters
    ----------
    local_path:
        Absolute or relative path to the local file.
    algorithm:
        Hash algorithm name recognised by :func:`hashlib.new`
        (default ``"sha256"``).

    Returns
    -------
    str
        Hex-encoded digest of the file contents.

    Raises
    ------
    FileNotFoundError
        If *local_path* does not exist.
    """
    h = hashlib.new(algorithm)
    with open(local_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_checksum_output(output: str) -> dict[str, str]:
    """Parse output from ``sha256sum`` (or similar) into a filename → hash mapping.

    Each line of *output* is expected to be in the format::

        {hash}  {filepath}

    (two spaces between hash and path).  The filename key in the returned
    dict is the **basename** of *filepath*, making it easy to compare with
    local filenames.

    Parameters
    ----------
    output:
        Raw stdout from a ``sha256sum`` command.

    Returns
    -------
    dict[str, str]
        Mapping of basename → hex digest.  Lines that cannot be parsed are
        silently skipped.
    """
    result: dict[str, str] = {}
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # sha256sum format: "{hash}  {path}" (two spaces, text mode)
        # or: "{hash} *{path}" (space + asterisk, binary mode)
        # Try text mode first (two spaces), then binary mode (space + asterisk)
        parts = line.split("  ", 1)
        if len(parts) != 2:
            # Try binary mode: "{hash} *{path}"
            parts = line.split(" *", 1)
            if len(parts) != 2:
                continue
        checksum, filepath = parts
        filename = os.path.basename(filepath.strip())
        result[filename] = checksum.strip()
    return result


def compute_remote_checksums(
    host: str,
    remote_dir: str,
    filenames: list[str],
    algorithm: str = "sha256",
    timeout: int = 10,
) -> dict[str, str]:
    """Compute checksums of remote files via SSH.

    Connects to *host* and runs ``{algorithm}sum`` in *remote_dir* for the
    given *filenames*, returning a mapping of filename → hex digest.

    Parameters
    ----------
    host:
        Remote host specification (e.g. ``user@host``).
    remote_dir:
        Path to the remote directory containing the files.
    filenames:
        List of filenames (basenames only) to checksum on the remote.
    algorithm:
        Hash algorithm (default ``"sha256"``).  The corresponding
        ``{algorithm}sum`` binary must exist on the remote server.
    timeout:
        SSH connection timeout in seconds.

    Returns
    -------
    dict[str, str]
        Mapping of filename → hex digest.  Returns an empty dict on
        connection failure or other errors.
    """
    if not filenames:
        return {}

    sum_cmd = f"{algorithm}sum"
    files_str = " ".join(shlex.quote(f) for f in filenames)
    remote_cmd = f"cd {shlex.quote(remote_dir)} && {sum_cmd} {files_str}"

    cmd: list[str] = [
        "ssh",
        "-o",
        f"ConnectTimeout={timeout}",
        "-o",
        "BatchMode=yes",
        host,
        remote_cmd,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout * 3,
        )
    except FileNotFoundError:
        return {}
    except subprocess.TimeoutExpired:
        return {}
    except OSError:
        return {}

    if result.returncode != 0:
        return {}

    return parse_checksum_output(result.stdout)


def verify_uploads(
    host: str,
    remote_dir: str,
    local_dir: str,
    local_files: list[str],
    algorithm: str = "sha256",
    timeout: int = 10,
) -> tuple[list[str], list[str]]:
    """Compare local and remote checksums for uploaded files.

    For each file in *local_files*, computes the local checksum and the
    remote checksum (via SSH), then categorises files as *matched* or
    *mismatched*.

    Parameters
    ----------
    host:
        Remote host specification (e.g. ``user@host``).
    remote_dir:
        Path to the remote directory where files were uploaded.
    local_dir:
        Path to the local directory containing the original files.
    local_files:
        List of filenames (basenames) that were uploaded.
    algorithm:
        Hash algorithm (default ``"sha256"``).
    timeout:
        SSH connection timeout in seconds.

    Returns
    -------
    tuple[list[str], list[str]]
        ``(matched, mismatched)`` where *matched* lists filenames whose
        checksums agree and *mismatched* lists filenames that differ.
        Files whose remote checksum could not be obtained are treated as
        *mismatched*.
    """
    remote_checksums = compute_remote_checksums(
        host, remote_dir, local_files, algorithm=algorithm, timeout=timeout
    )

    matched: list[str] = []
    mismatched: list[str] = []

    for filename in local_files:
        local_path = os.path.join(local_dir, filename)
        try:
            local_hash = compute_local_checksum(local_path, algorithm=algorithm)
        except (OSError, FileNotFoundError):
            mismatched.append(filename)
            continue

        remote_hash = remote_checksums.get(filename)
        if remote_hash is not None and remote_hash == local_hash:
            matched.append(filename)
        else:
            mismatched.append(filename)

    return matched, mismatched
