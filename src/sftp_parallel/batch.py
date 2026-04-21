"""Batch command generation and input validation."""

from __future__ import annotations

import os
import unicodedata
import warnings

_MAX_FILENAME_LENGTH = 255
DEFAULT_TIMEOUT = 10
MIN_TRANSFER_RATE = 256 * 1024
CONNECTION_OVERHEAD = 10


def validate_host(host: str) -> None:
    """Validate a remote host specification.

    Raises ``ValueError`` if *host* is empty, contains only whitespace,
    or contains control characters.

    Warns if *host* contains a colon (``:``), which typically indicates
    an embedded port (e.g., ``user@host:2222``). SSH will use the
    embedded port and silently ignore the ``-p/--port`` flag.
    """
    if not host or not host.strip():
        raise ValueError("host must not be empty")
    for char in host:
        cat = unicodedata.category(char)
        if cat.startswith("C"):
            raise ValueError(
                f"host contains control character ({repr(char)})"
            )
    if ":" in host:
        warnings.warn(
            f"Host {host!r} contains ':' — the embedded port will be used "
            "by SSH and the -p/--port flag will be silently ignored. "
            "Use the host without port and -p PORT to specify the port explicitly.",
            stacklevel=2,
        )


def validate_port(port: int) -> None:
    """Validate a network port number.

    Raises ``ValueError`` if *port* is not in the valid range 1–65535.
    """
    if not isinstance(port, int):
        raise ValueError(f"port must be an integer, got {type(port).__name__}")
    if port < 1 or port > 65535:
        raise ValueError(f"port must be 1-65535, got {port}")


def validate_remote_dir(remote_dir: str) -> None:
    """Validate a remote directory path.

    Raises ``ValueError`` if *remote_dir* is empty, contains control
    characters, or starts with a dash.

    Note
    ----
    This function does NOT reject shell metacharacters like ``;``, ``&``,
    or ``|`` because SFTP batch mode does not perform shell expansion.
    """
    if not remote_dir or not remote_dir.strip():
        raise ValueError("remote directory must not be empty")
    if remote_dir.startswith("-"):
        raise ValueError(
            f"remote directory starts with '-': {remote_dir!r} "
            "(could be interpreted as an option by remote commands)"
        )
    for char in remote_dir:
        if unicodedata.category(char).startswith("C"):
            raise ValueError(
                f"remote directory contains control character ({repr(char)}): {remote_dir!r}"
            )


def validate_filename(name: str) -> bool:
    """Return ``True`` if *name* is a safe, uploadable filename.

    A filename is rejected when it:

    - Is empty or whitespace-only
    - Is ``.`` or ``..``
    - Starts with ``-`` (could be interpreted as an option)
    - Exceeds 255 bytes when encoded as UTF-8
    - Contains NUL, newline, CR, TAB, ``/``, ``\\``, or any other Unicode control character (category ``C*``)
    - Is not a plain basename (i.e. contains a path separator)

    Filenames containing ``..`` as a substring (e.g. ``file..txt``) are
    accepted, as they cannot traverse directories without path separators.

    Note
    ----
    This function returns ``bool`` rather than raising because it is used as a
    filter (e.g., in ``resolve_file_patterns`` and ``parse_ls_output``) where invalid
    names are silently skipped.  For precondition checks that should fail loudly,
    see :func:`validate_remote_dir` which raises ``ValueError``.
    """
    if not name or not name.strip():
        return False
    if name == "." or name == "..":
        return False
    if name.startswith("-"):
        return False
    if len(name.encode()) > _MAX_FILENAME_LENGTH:
        return False
    if "\x00" in name:
        return False
    if "\n" in name or "\r" in name or "\t" in name:
        return False
    if "/" in name or "\\" in name:
        return False
    if os.path.basename(name) != name:
        return False
    for char in name:
        cat = unicodedata.category(char)
        if cat.startswith("C"):
            return False
    return True


def sftp_escape(path: str) -> str:
    """Escape a path for use inside double-quoted SFTP batch commands.

    Escapes backslashes and double quotes, which are the only characters
    that need escaping inside double-quoted strings in OpenSSH SFTP batch
    mode. This is NOT a general-purpose shell escaper — it assumes the
    result will be wrapped in double quotes by the caller.

    Note
    ----
    This function does **not** escape newlines. Callers must ensure that
    paths passed to SFTP batch commands do not contain ``\\n`` or ``\\r``,
    as these would break the line-oriented SFTP batch protocol.
    Use :func:`_validate_sftp_path` to check before calling this function.
    """
    escaped = path.replace("\\", "\\\\")
    return escaped.replace('"', '\\"')


def _validate_sftp_path(path: str, label: str = "path") -> None:
    """Validate a path is safe for SFTP batch commands (no control characters).

    Raises ``ValueError`` if the path contains control characters,
    which would break the line-oriented SFTP batch protocol.
    """
    for char in path:
        if unicodedata.category(char).startswith("C"):
            raise ValueError(
                f"{label} contains control character ({repr(char)}), "
                f"which would break SFTP batch commands: {path!r}"
            )


def build_batch_commands(remote_dir: str, file_paths: list[str]) -> str:
    """Generate SFTP batch commands for uploading files.

    Produces a newline-separated string of SFTP commands: ``cd`` into
    *remote_dir*, then ``put -f`` each file, then ``bye``.

    Parameters
    ----------
    remote_dir:
        Remote directory path to upload files to.
    file_paths:
        List of local file paths (absolute or relative) to upload.

    Returns
    -------
    str
        Newline-separated SFTP batch commands.

    Raises
    ------
    ValueError
        If any file path or the remote directory contains control
        characters that would break the SFTP batch protocol.

    Note
    ----
    This function does **not** validate *remote_dir* — callers are
    responsible for calling :func:`validate_remote_dir` separately.
    """
    _validate_sftp_path(remote_dir, "remote directory")
    for fp in file_paths:
        _validate_sftp_path(fp, "file path")

    commands: list[str] = []
    commands.append(f'cd "{sftp_escape(remote_dir)}"')

    for file_path in file_paths:
        escaped_local = sftp_escape(file_path)
        commands.append(f'put -f "{escaped_local}"')

    commands.append("bye")
    return "\n".join(commands)