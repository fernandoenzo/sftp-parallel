"""PTY-based SFTP worker with select() loop."""

from __future__ import annotations

import errno
import fcntl
import locale
import logging
import os
import pty
import re
import select
import signal
import struct
import termios
import time
from dataclasses import dataclass

from rich.progress import Progress, TaskID

from sftp_parallel.lib import (
    escape_interactive,
    parse_progress,
    validate_host,
    validate_port,
    validate_remote_dir,
)

logger = logging.getLogger(__name__)

_SFTP_ERROR_RE = re.compile(
    r"(?:Can't|Cannot|Could not|Couldn't|Error|Failed|No such"
    r"|Permission denied|Connection refused|Network is unreachable"
    r"|Name or service not known|Too many authentication"
    r"|Host key verification failed|Connection timed out"
    r"|Broken pipe|Connection reset"
    r"|No space left on device|Read-only file system"
    r"|Quota exceeded|Connection closed by remote host"
    r"|Subsystem sftp not enabled|Not a regular file"
    r"|Is a directory|Operation not supported"
    r"|Unknown subsystem|Disconnected"
    r"|ssh_exchange_identification)",
    re.IGNORECASE,
)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_SFTP_SAFE_PREFIXES = (
    "cd ", "put ", "bye", "lcd ", "lls ", "lpwd", "pwd ",
    "lmkdir ", "lmdir ", "ls ", "!!",
    "Uploading ", "Remote working", "sftp>", "Connected ",
)

_STALLED_RE = re.compile(r"-\s*stalled\s*-")
_ETA_UNKNOWN_RE = re.compile(r"--:\s*--\s+ETA")


@dataclass
class WorkerResult:
    """Result of a single file upload via PTY-based SFTP worker."""

    success: bool
    file_path: str
    error_message: str = ""


class Worker:
    """Upload a single file via interactive SFTP over a PTY.

    Uses pty.fork() to allocate a real controlling terminal so that
    OpenSSH's progress-meter check evaluates to true.  Uses select()
    in a single loop to read output AND write commands — no internal
    threads needed.

    Parameters
    ----------
    host:
        Remote host specification (e.g. user@host).
    file_path:
        Local file path to upload.
    remote_dir:
        Remote directory path to upload to.
    port:
        Remote port number.
    connect_timeout:
        Connection timeout in seconds (passed as ConnectTimeout).
    idle_timeout:
        Maximum seconds without progress before killing the process.
    progress:
        Optional Rich Progress instance for direct updates.
    task_id:
        Optional Rich TaskID for progress updates.
    """

    def __init__(
        self,
        host: str,
        file_path: str,
        remote_dir: str,
        port: int = 22,
        connect_timeout: int = 10,
        idle_timeout: int = 120,
        progress: Progress | None = None,
        task_id: TaskID | None = None,
    ) -> None:
        validate_host(host)
        validate_port(port)
        validate_remote_dir(remote_dir)

        self.host = host
        self.file_path = file_path
        self.remote_dir = remote_dir
        self.port = port
        self.connect_timeout = connect_timeout
        self.idle_timeout = idle_timeout
        self.progress = progress
        self.task_id = task_id

        self.pid: int = 0
        self.master_fd: int = -1
        self._stop: bool = False

        self._prompt_count: int = 0
        self._error_message: str = ""
        self._bytes_transferred: int = 0
        self._last_progress_time: float = 0.0

        try:
            self._file_size = os.path.getsize(file_path)
        except OSError:
            self._file_size = 0

        self._linebuf: str = ""

    def run(self) -> WorkerResult:
        """Execute the full upload lifecycle: spawn, loop, cleanup."""
        try:
            self._spawn()
        except FileNotFoundError:
            return WorkerResult(
                success=False,
                file_path=self.file_path,
                error_message="sftp binary not found",
            )
        except OSError as exc:
            return WorkerResult(
                success=False,
                file_path=self.file_path,
                error_message=f"Failed to spawn sftp process: {exc}",
            )
        try:
            return self._loop()
        finally:
            self._cleanup()

    def terminate(self) -> None:
        """Kill the worker process.  Idempotent, safe from any thread."""
        self._stop = True
        self._kill_process()

    def _spawn(self) -> None:
        """Fork a child SFTP process via pty.fork()."""
        sftp_args = self._build_sftp_cmd()

        pid, master_fd = pty.fork()
        self.pid = pid
        self.master_fd = master_fd

        if pid == 0:
            os.environ["LC_ALL"] = "C"
            os.environ["LC_NUMERIC"] = "C"
            os.execvp("sftp", sftp_args)
            os._exit(74)

        try:
            fcntl.ioctl(
                master_fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", 24, 512, 0, 0),
            )
        except OSError:
            logger.debug("Could not set PTY window size")

    def _build_sftp_cmd(self) -> list[str]:
        """Build the sftp command-line arguments for interactive mode."""
        return [
            "sftp",
            "-o",
            f"ConnectTimeout={self.connect_timeout}",
            "-o",
            "BatchMode=yes",
            "-o",
            f"Port={self.port}",
            self.host,
        ]

    def _loop(self) -> WorkerResult:
        """Main loop: select() for read and write."""
        commands = [
            f"cd {escape_interactive(self.remote_dir)}",
            f"put -f {escape_interactive(self.file_path)}",
            "bye",
        ]
        cmd_idx = 0
        prompt_seen = False
        start_time = time.monotonic()
        last_progress_time = 0.0

        while not self._stop:
            try:
                r, w, _ = select.select(
                    [self.master_fd],
                    [self.master_fd] if cmd_idx < len(commands) and prompt_seen else [],
                    [],
                    0.5,
                )
            except (ValueError, OSError):
                break

            now = time.monotonic()

            if not prompt_seen and now - start_time > self.connect_timeout + 30:
                self._error_message = f"SFTP connection timed out after {self.connect_timeout + 30}s"
                break

            if self._bytes_transferred > 0 and last_progress_time > 0 and now - last_progress_time > self.idle_timeout:
                self._error_message = f"Transfer stalled: no progress for {self.idle_timeout}s"
                break

            if self.master_fd in r:
                try:
                    data = os.read(self.master_fd, 4096)
                except OSError as exc:
                    if exc.errno in (errno.EIO, errno.EBADF):
                        break
                    logger.debug("OSError reading PTY master: %s", exc)
                    break

                if not data:
                    break

                encoding = locale.getpreferredencoding(False) or "utf-8"
                text = data.decode(encoding, errors="replace")
                self._process_output(text)

                if self._error_message:
                    break

            if self.master_fd in w and cmd_idx < len(commands) and prompt_seen:
                try:
                    os.write(self.master_fd, (commands[cmd_idx] + "\n").encode("utf-8"))
                except OSError:
                    break
                cmd_idx += 1

        success = self._determine_success()
        return WorkerResult(
            success=success,
            file_path=self.file_path,
            error_message=self._error_message,
        )

    def _determine_success(self) -> bool:
        """Determine if the upload was successful."""
        if self._error_message:
            return False
        if self._file_size > 0:
            return self._bytes_transferred == self._file_size
        return self._prompt_count >= 3

    def _process_output(self, text: str) -> None:
        """Process raw text from the PTY, splitting on \\r and \\n."""
        segments = self._split_lines(text)

        for segment in segments:
            self._parse_line(segment)

        self._check_pending_prompt()

    def _split_lines(self, text: str) -> list[str]:
        """Split PTY output into line segments, handling overflow and \\r/\\n delimiters."""
        self._linebuf += text

        if len(self._linebuf) > 8192:
            logger.warning("Line buffer overflow for %s, truncating", self.file_path)
            self._linebuf = self._linebuf[-4096:]

        segments = re.split(r"[\r\n]+", self._linebuf)

        if text and text[-1] not in ("\r", "\n"):
            self._linebuf = segments[-1]
            return segments[:-1]

        self._linebuf = ""
        return segments

    def _check_pending_prompt(self) -> None:
        """Check if the line buffer contains an sftp> prompt and process it."""
        if not self._linebuf:
            return
        stripped = _ANSI_ESCAPE_RE.sub("", self._linebuf).strip()
        if "sftp>" in stripped:
            idx = self._linebuf.find("sftp>")
            prompt_part = self._linebuf[: idx + 5]
            trailing = self._linebuf[idx + 5 :]
            self._parse_line(prompt_part)
            self._linebuf = trailing

    def _parse_line(self, line: str) -> None:
        """Parse a single output line from the SFTP process."""
        line = _ANSI_ESCAPE_RE.sub("", line).strip()
        if not line:
            return

        if _STALLED_RE.search(line) or _ETA_UNKNOWN_RE.search(line):
            self._last_progress_time = time.monotonic()
            self._update_progress()
            return

        prog = parse_progress(line)
        if prog is not None:
            _, transferred = prog
            if transferred >= self._bytes_transferred:
                self._bytes_transferred = transferred
            self._last_progress_time = time.monotonic()
            self._update_progress()
            return

        if "sftp>" in line:
            parts = line.split("sftp>", 1)
            self._prompt_count += 1
            if len(parts) > 1 and parts[1].strip():
                remaining = parts[1].strip()
                if _SFTP_ERROR_RE.search(remaining):
                    if not self._error_message:
                        self._error_message = remaining
            return

        if any(line.startswith(prefix) for prefix in _SFTP_SAFE_PREFIXES):
            return

        if _SFTP_ERROR_RE.search(line):
            if not self._error_message:
                self._error_message = line

    def _update_progress(self) -> None:
        """Update the Rich progress bar if available."""
        if self.progress is not None and self.task_id is not None:
            try:
                self.progress.update(self.task_id, completed=self._bytes_transferred)
            except Exception:
                logger.debug("Rich progress update failed for %s", self.file_path, exc_info=True)

    def _kill_process(self) -> None:
        """Kill the SFTP process group: SIGTERM → wait → SIGKILL."""
        if self.pid <= 0:
            return

        pid = self.pid

        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

        for _ in range(10):
            try:
                pid_, _status = os.waitpid(pid, os.WNOHANG)
                if pid_ != 0:
                    break
            except ChildProcessError:
                break
            time.sleep(0.2)

        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass

        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

        self.pid = 0

    def _cleanup(self) -> None:
        """Close the PTY master fd and reap the child process."""
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = -1

        if self.pid > 0:
            try:
                os.waitpid(self.pid, 0)
            except (ChildProcessError, OSError):
                pass
            self.pid = 0