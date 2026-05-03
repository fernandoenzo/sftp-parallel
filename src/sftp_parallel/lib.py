"""Pure utility functions for validation, escaping, parsing, and verification."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import unicodedata
import warnings

_MAX_FILENAME_LENGTH = 255
DEFAULT_TIMEOUT = 10
MIN_TRANSFER_RATE = 256 * 1024
CONNECTION_OVERHEAD = 10
DEFAULT_IDLE_TIMEOUT = 120
_PROCESS_KILL_WAIT_SECONDS = 5
_SFTP_TIMEOUT_MULTIPLIER = 3


def validate_host(host: str) -> None:
    if not host or not host.strip():
        raise ValueError("host must not be empty")
    if host.startswith("-"):
        raise ValueError("host must not start with '-'")
    for char in host:
        cat = unicodedata.category(char)
        if cat.startswith("C"):
            raise ValueError(
                f"host contains control character ({repr(char)})"
            )
    parts = host.split()
    for part in parts:
        if part.startswith("-"):
            raise ValueError(
                f"host contains argument-like segment {part!r} — "
                "to avoid SSH option injection, the host must not "
                "contain segments starting with '-'"
            )
    if ":" in host:
        warnings.warn(
            f"Host {host!r} contains ':' — the embedded port will be used "
            "by SSH and the -p/--port flag will be silently ignored. "
            "Use the host without port and -p PORT to specify the port explicitly.",
            stacklevel=2,
        )


def validate_port(port: int) -> None:
    if not isinstance(port, int):
        raise ValueError(f"port must be an integer, got {type(port).__name__}")
    if port < 1 or port > 65535:
        raise ValueError(f"port must be 1-65535, got {port}")


def validate_remote_dir(remote_dir: str) -> None:
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
    escaped = path.replace("\\", "\\\\")
    return escaped.replace('"', '\\"')


def escape_interactive(path: str) -> str:
    result = path.replace("\\", "\\\\")
    result = result.replace('"', '\\"')
    result = result.replace("'", "\\'")
    result = result.replace(" ", "\\ ")
    return result


def _validate_sftp_path(path: str, label: str = "path") -> None:
    for char in path:
        if unicodedata.category(char).startswith("C"):
            raise ValueError(
                f"{label} contains control character ({repr(char)}), "
                f"which would break SFTP commands: {path!r}"
            )


def build_interactive_commands(remote_dir: str, file_path: str) -> list[str]:
    _validate_sftp_path(remote_dir, "remote directory")
    _validate_sftp_path(file_path, "file path")

    return [
        f"cd {escape_interactive(remote_dir)}",
        f"put -f {escape_interactive(file_path)}",
        "bye",
    ]


# Progress regex: matches full progress lines, stalled, and unknown ETA
_PROGRESS_RE = re.compile(
    r"(\d{1,3})%"
    r"\s+"
    r"(\d+(?:[.,]\d+)?(?:[KMGT]?i?B)?)"
    r"\s+"
    r"[\d.,]+[KMGT]?i?B/s"
    r"\s+"
    r"(?:"
    r"\d+:\d{2}:\d{2}|"
    r"\d{2}:\d{2}|"
    r"--:\s*--"
    r")"
    r"\s*"
    r"(?:ETA)?"
    r"|"
    r"-\s*stalled\s*-"
    r"|"
    r"--:\s*--\s+ETA"
)

_UNIT_MULTIPLIERS: dict[str, int] = {
    "B": 1,
    "KB": 1024,
    "KiB": 1024,
    "MB": 1024 ** 2,
    "MiB": 1024 ** 2,
    "GB": 1024 ** 3,
    "GiB": 1024 ** 3,
    "TB": 1024 ** 4,
    "TiB": 1024 ** 4,
    "PB": 1024 ** 5,
    "PiB": 1024 ** 5,
}


def _parse_formatted_bytes(value: str) -> int:
    for suffix in sorted(_UNIT_MULTIPLIERS, key=len, reverse=True):
        if value.endswith(suffix):
            num_str = value[: -len(suffix)].replace(",", ".")
            return int(float(num_str) * _UNIT_MULTIPLIERS[suffix])
    return int(value)


def parse_progress(line: str) -> tuple[int, int] | None:
    """Returns (pct, bytes) or None if not progress (including stalled/ETA-only)."""
    m = _PROGRESS_RE.search(line)
    if not m:
        return None
    pct_str = m.group(1)
    bytes_str = m.group(2)
    if pct_str is None or bytes_str is None:
        return None
    pct = int(pct_str)
    transferred = _parse_formatted_bytes(bytes_str)
    return pct, transferred


def compute_local_checksum(filepath: str, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_checksum_output(output: str) -> dict[str, str]:
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


def _build_sftp_cmd(host: str, timeout: int, port: int = 22) -> list[str]:
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
    import signal as _signal

    if pgid <= 1:
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, OSError):
            pgid = -1
    if pgid > 1:
        try:
            os.killpg(pgid, _signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except Exception:
                pass
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


def parse_ls_output(ls_output: str) -> dict[str, int]:
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
