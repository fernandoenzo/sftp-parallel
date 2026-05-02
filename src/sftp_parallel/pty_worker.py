"""PTY-based SFTP worker – interactive mode with real-time progress parsing."""

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
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from sftp_parallel.batch import (
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_TIMEOUT,
    build_interactive_commands,
    validate_host,
    validate_port,
    validate_remote_dir,
)

logger = logging.getLogger(__name__)

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
    """Convert a formatted byte string from OpenSSH sftp progress output to int.

    OpenSSH's ``format_size()`` outputs values like ``0``, ``100KB``,
    ``1MB``, ``1024KB``, ``1GB``.  This function converts them back to
    raw byte counts.
    """
    for suffix in sorted(_UNIT_MULTIPLIERS, key=len, reverse=True):
        if value.endswith(suffix):
            num_str = value[: -len(suffix)].replace(",", ".")
            return int(float(num_str) * _UNIT_MULTIPLIERS[suffix])
    return int(value)

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


@dataclass
class WorkerResult:
    """Result of a single file upload via PTY-based SFTP worker."""

    success: bool
    file_path: str
    error_message: str = ""


class PTYWorker:
    """Upload a single file via interactive SFTP over a PTY.

    Uses :func:`pty.fork` to allocate a real controlling terminal so that
    OpenSSH's ``can_output()`` progress-meter check (``getpgrp() ==
    tcgetpgrp(STDOUT_FILENO)``) evaluates to true.  Without a controlling
    terminal the progress meter is silently suppressed.

    The worker spawns an interactive ``sftp`` session, sends commands
    one-by-one (``cd``, ``put -f``, ``bye``), and parses the ``\\r``-delimited
    progress output in real time.

    Parameters
    ----------
    host:
        Remote host specification (e.g. ``user@host``).
    file_path:
        Local file path to upload.
    remote_dir:
        Remote directory path to upload to.
    port:
        Remote port number.
    connect_timeout:
        Connection timeout in seconds (passed as ``ConnectTimeout``).
    idle_timeout:
        Maximum seconds without progress output before killing the process.
    progress_callback:
        Optional callback ``(file_path, bytes_transferred, total_bytes)``.
        Called from the reader thread — must be thread-safe.
    """

    def __init__(
        self,
        host: str,
        file_path: str,
        remote_dir: str,
        port: int = 22,
        connect_timeout: int = DEFAULT_TIMEOUT,
        idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
        prompt_timeout: int = 30,
        progress_callback: Callable[[str, int, int], None] | None = None,
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
        self.prompt_timeout = prompt_timeout
        self.progress_callback = progress_callback

        self.pid: int = 0
        self.master_fd: int = -1

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._prompt_event = threading.Event()

        self._prompt_count: int = 0
        self._error_message: str = ""
        self._bytes_transferred: int = 0
        self._last_progress_time: float = 0.0

        # File size — best-effort
        try:
            self._file_size = os.path.getsize(file_path)
        except OSError:
            self._file_size = 0

        self._linebuf: str = ""

    def run(self) -> WorkerResult:
        """Execute the full upload lifecycle: spawn, run, cleanup.

        Returns
        -------
        WorkerResult
            Result indicating success/failure, bytes transferred, and any
            error message.
        """
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
            self._run_threads()
        except Exception as exc:
            logger.exception("Unexpected error in PTYWorker for %s", self.file_path)
            self._kill_process()
            with self._lock:
                err = self._error_message or str(exc)
            return WorkerResult(
                success=False,
                file_path=self.file_path,
                error_message=err,
            )
        finally:
            self._cleanup()

        with self._lock:
            # Primary check: byte count matches file size (definitive).
            # Fallback for 0-byte files: prompt count heuristic.
            if self._error_message:
                success = False
            elif self._file_size > 0:
                success = self._bytes_transferred == self._file_size
            else:
                success = self._prompt_count >= 3
            err = self._error_message

        return WorkerResult(
            success=success,
            file_path=self.file_path,
            error_message=err,
        )

    def terminate(self) -> None:
        """Public method for signal handlers to kill the worker and clean up.

        Safe to call from any thread.  Idempotent.
        """
        self._kill_process()
        self._cleanup()

    def _spawn(self) -> None:
        """Fork a child SFTP process via :func:`pty.fork`.

        In the child process, :func:`os.execvp` replaces the process image
        with ``sftp``.  Because :func:`pty.fork` calls :func:`os.login_tty`
        in the child, OpenSSH's ``can_output()`` check (``getpgrp() ==
        tcgetpgrp(STDOUT_FILENO)``) will pass and the progress meter will
        be emitted.

        In the parent, the master fd is configured with a large terminal
        size so that progress lines are not wrapped at 80 columns.

        SFTP args are pre-built before fork to avoid any Python allocation
        in the child process (eliminating fork-from-thread deadlock risk).
        """
        sftp_args = self._build_sftp_cmd()

        pid, master_fd = pty.fork()
        self.pid = pid
        self.master_fd = master_fd
        if pid == 0:
            os.environ["LC_ALL"] = "C"
            os.environ["LC_NUMERIC"] = "C"
            os.execvp("sftp", sftp_args)
            os._exit(74)  # pragma: no cover — execvp doesn't return on success

        # Set a large terminal size so progress lines don't wrap
        try:
            fcntl.ioctl(
                master_fd,
                termios.TIOCSWINSZ,
                struct.pack("HHHH", 24, 512, 0, 0),
            )
        except OSError:
            logger.debug("Could not set PTY window size")

    def _build_sftp_cmd(self) -> list[str]:
        """Build the sftp command-line arguments for interactive mode.

        Returns
        -------
        list[str]
            Argument list for :func:`os.execvp`.

        Note
        ----
        No ``-b`` (batch) or ``-N`` (no batch) flags — we use interactive
        mode and send commands one-by-one.
        """
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

    def _run_threads(self) -> None:
        """Start reader and writer daemon threads and join them."""
        reader = threading.Thread(
            target=self._reader_thread,
            name=f"sftp-reader-{self.file_path}",
            daemon=True,
        )
        writer = threading.Thread(
            target=self._writer_thread,
            name=f"sftp-writer-{self.file_path}",
            daemon=True,
        )
        reader.start()
        writer.start()
        reader.join()
        writer.join()

    def _reader_thread(self) -> None:
        """Read from the PTY master fd, parse output, detect prompts and errors.

        Uses :func:`select.select` with a 0.5-second timeout to avoid
        busy-waiting.  Handles both progress lines (``\\r``-delimited) and
        prompt lines (``\\n``-delimited).

        Detects two timeout conditions:

        1. **Connection timeout** — no bytes received at all within
           ``connect_timeout + 30`` seconds of starting.
        2. **Idle timeout** — no progress update within ``idle_timeout``
           seconds while bytes have been transferred (transfer stalled).
        """
        assert self.master_fd >= 0  # noqa: S101
        start_time = time.monotonic()
        saw_output = False
        connection_deadline = self.connect_timeout + 30

        while not self._stop_event.is_set():
            try:
                ready, _, _ = select.select([self.master_fd], [], [], 0.5)
            except (ValueError, OSError):
                break

            if not ready:
                now = time.monotonic()

                if not saw_output and now - start_time > connection_deadline:
                    with self._lock:
                        self._error_message = (
                            f"SFTP connection timed out after {connection_deadline}s"
                        )
                    self._kill_process()
                    break

                if (
                    self._bytes_transferred > 0
                    and self._last_progress_time > 0
                    and now - self._last_progress_time > self.idle_timeout
                ):
                    with self._lock:
                        self._error_message = (
                            f"Transfer stalled: no progress for {self.idle_timeout}s"
                        )
                    self._kill_process()
                    break

                continue

            try:
                data = os.read(self.master_fd, 4096)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                if exc.errno == errno.EBADF:
                    break
                logger.debug("OSError reading PTY master: %s", exc)
                break

            if not data:
                break

            saw_output = True
            encoding = locale.getpreferredencoding(False) or "utf-8"
            text = data.decode(encoding, errors="replace")
            self._process_output(text)

        self._stop_event.set()

    def _split_segments(self, text: str) -> tuple[list[str], str]:
        """Split PTY output into line segments, handling overflow and \\r/\\n delimiters.

        Returns (segments, remaining_linebuf) where segments are complete
        lines to parse and remaining_linebuf is the unparsed remainder.
        """
        self._linebuf += text

        if len(self._linebuf) > 8192:
            logger.warning("Line buffer overflow for %s, truncating", self.file_path)
            self._linebuf = self._linebuf[-4096:]

        segments = re.split(r"[\r\n]+", self._linebuf)

        if text and text[-1] not in ("\r", "\n"):
            remaining = segments[-1]
            segments = segments[:-1]
        else:
            remaining = ""

        return segments, remaining

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

    def _process_output(self, text: str) -> None:
        """Process raw text from the PTY, splitting on ``\\r`` and ``\\n``."""
        segments, remaining = self._split_segments(text)
        self._linebuf = remaining

        for segment in segments:
            self._parse_line(segment)

        self._check_pending_prompt()

    def _parse_line(self, line: str) -> None:
        """Parse a single output line from the SFTP process.

        Strips ANSI escape sequences, then matches against known patterns
        in priority order:

        1. :data:`_PROGRESS_RE` — updates ``_bytes_transferred`` and
           ``_last_progress_time``, calls ``progress_callback``.
        2. ``sftp>`` substring — increments ``_prompt_count``, sets
           ``_prompt_event``.  Trailing text after the prompt is checked
           for errors.
        3. :data:`_SFTP_ERROR_RE` — sets ``_error_message``.
        """
        line = _ANSI_ESCAPE_RE.sub("", line).strip()
        if not line:
            return

        match = _PROGRESS_RE.search(line)
        if match:
            bytes_str = match.group(2)
            transferred = 0
            if bytes_str is not None:
                try:
                    transferred = _parse_formatted_bytes(bytes_str)
                except (ValueError, OverflowError):
                    transferred = 0
            if transferred >= self._bytes_transferred:
                with self._lock:
                    self._bytes_transferred = transferred
                    self._last_progress_time = time.monotonic()
                    bt = self._bytes_transferred
            else:
                bt = self._bytes_transferred
                with self._lock:
                    self._last_progress_time = time.monotonic()

            if self.progress_callback is not None:
                try:
                    self.progress_callback(
                        self.file_path, bt, self._file_size
                    )
                except Exception:
                    logger.debug("Progress callback failed for %s", self.file_path, exc_info=True)
            return

        if "sftp>" in line:
            parts = line.split("sftp>", 1)
            with self._lock:
                self._prompt_count += 1
            self._prompt_event.set()
            if len(parts) > 1 and parts[1].strip():
                remaining = parts[1].strip()
                if _SFTP_ERROR_RE.search(remaining):
                    with self._lock:
                        if not self._error_message:
                            self._error_message = remaining
            return

        # Command echoes from our own writer thread — never error lines.
        # The PTY echoes back what we type (e.g. "put -f /path/Error.log").
        if any(line.startswith(prefix) for prefix in _SFTP_SAFE_PREFIXES):
            return

        if _SFTP_ERROR_RE.search(line):
            with self._lock:
                if not self._error_message:
                    self._error_message = line

    def _writer_thread(self) -> None:
        """Send SFTP commands one-by-one, waiting for prompts between each.

        After the initial ``sftp>`` prompt (connection established),
        commands from :func:`~sftp_parallel.batch.build_interactive_commands`
        are sent sequentially.  Each command (except ``bye``) is followed by
        waiting for the next ``sftp>`` prompt.
        """
        initial_timeout = self.connect_timeout + 30
        got_prompt = self._prompt_event.wait(timeout=initial_timeout)
        if not got_prompt or self._stop_event.is_set():
            self._kill_process()
            return

        commands = build_interactive_commands(self.remote_dir, self.file_path)

        for i, cmd in enumerate(commands):
            if self._stop_event.is_set():
                break

            self._prompt_event.clear()
            try:
                os.write(self.master_fd, (cmd + "\n").encode("utf-8"))
            except OSError:
                self._stop_event.set()
                break

            if cmd == "bye":
                break

            # put -f blocks until the entire file is uploaded — the prompt
            # won't arrive until transfer completes.  Rely on idle_timeout
            # (reader thread) to detect stalls; don't apply prompt_timeout.
            if cmd.startswith("put "):
                got_prompt = self._prompt_event.wait()
            else:
                got_prompt = self._prompt_event.wait(timeout=self.prompt_timeout)

            if not got_prompt or self._stop_event.is_set():
                # Timed out waiting for prompt — kill process
                with self._lock:
                    if not self._error_message:
                        self._error_message = (
                            f"Timed out waiting for sftp prompt after command: {cmd}"
                        )
                self._kill_process()
                break

    def _kill_process(self) -> None:
        """Kill the SFTP process group and signal shutdown.

        Sends SIGTERM to the process group.  If the process is still
        alive after 2 seconds, escalates to SIGKILL.

        Because :func:`pty.fork` creates a new session via
        :func:`os.setsid`, the PGID equals the child PID.
        """
        with self._lock:
            self._stop_event.set()
            self._prompt_event.set()  # unblock writer thread on error

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

        with self._lock:
            self.pid = 0

    def _cleanup(self) -> None:
        """Close the PTY master fd and reap the child process.

        Closes ``self.master_fd`` and calls :func:`os.waitpid` to collect
        any zombie process.  If the process is still alive, it is killed
        again.
        """
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = -1

        if self.pid > 0:
            try:
                os.waitpid(self.pid, 0)
            except ChildProcessError:
                pass
            except OSError:
                pass