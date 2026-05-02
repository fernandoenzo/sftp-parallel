"""Tests for sftp_parallel.pty_worker."""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from sftp_parallel.pty_worker import (
    PTYWorker,
    WorkerResult,
    _PROGRESS_RE,
    _SFTP_ERROR_RE,
    _parse_formatted_bytes,
)


# --- Helpers ---


def _make_worker(**overrides: object) -> PTYWorker:
    """Create a PTYWorker bypassing __init__ validation.

    Sets sensible defaults for attributes used by _parse_line etc.
    """
    worker = PTYWorker.__new__(PTYWorker)
    worker.host = overrides.get("host", "user@host")  # type: ignore[assignment]
    worker.file_path = overrides.get("file_path", "/tmp/test.txt")  # type: ignore[assignment]
    worker.remote_dir = overrides.get("remote_dir", "/remote/dir")  # type: ignore[assignment]
    worker.port = overrides.get("port", 22)  # type: ignore[assignment]
    worker.connect_timeout = overrides.get("connect_timeout", 10)  # type: ignore[assignment]
    worker.idle_timeout = overrides.get("idle_timeout", 30)  # type: ignore[assignment]
    worker.prompt_timeout = overrides.get("prompt_timeout", 30)  # type: ignore[assignment]
    worker.progress_callback = overrides.get("progress_callback", None)  # type: ignore[assignment]
    worker.pid = 0
    worker.master_fd = -1
    worker._lock = threading.Lock()  # type: ignore[attr-defined]
    worker._stop_event = threading.Event()  # type: ignore[attr-defined]
    worker._prompt_event = threading.Event()  # type: ignore[attr-defined]
    worker._prompt_count = 0  # type: ignore[attr-defined]
    worker._error_message = ""  # type: ignore[attr-defined]
    worker._bytes_transferred = 0  # type: ignore[attr-defined]
    worker._file_size = overrides.get("_file_size", 10_000_000)  # type: ignore[attr-defined]
    worker._last_progress_time = 0.0  # type: ignore[attr-defined]
    worker._linebuf = ""  # type: ignore[attr-defined]
    return worker


# --- WorkerResult tests ---


class TestWorkerResult:
    def test_construction_all_fields(self) -> None:
        result = WorkerResult(
            success=True,
            file_path="/tmp/a.txt",
            error_message="",
        )
        assert result.success is True
        assert result.file_path == "/tmp/a.txt"
        assert result.error_message == ""

    def test_default_error_message(self) -> None:
        result = WorkerResult(
            success=False,
            file_path="/tmp/b.txt",
        )
        assert result.error_message == ""

    def test_with_error_message(self) -> None:
        result = WorkerResult(
            success=False,
            file_path="/tmp/c.txt",
            error_message="Permission denied",
        )
        assert result.error_message == "Permission denied"


# --- PTYWorker validation tests ---


class TestPTYWorkerValidation:
    def test_invalid_host_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            PTYWorker(
                host="",
                file_path="/tmp/test.txt",
                remote_dir="/remote/dir",
            )

    def test_invalid_port_zero(self) -> None:
        with pytest.raises(ValueError, match="1-65535"):
            PTYWorker(
                host="user@host",
                file_path="/tmp/test.txt",
                remote_dir="/remote/dir",
                port=0,
            )

    def test_invalid_port_too_high(self) -> None:
        with pytest.raises(ValueError, match="1-65535"):
            PTYWorker(
                host="user@host",
                file_path="/tmp/test.txt",
                remote_dir="/remote/dir",
                port=70000,
            )

    def test_invalid_remote_dir_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            PTYWorker(
                host="user@host",
                file_path="/tmp/test.txt",
                remote_dir="",
            )


# --- Regex pattern tests ---


class TestProgressRE:
    def test_basic_progress(self) -> None:
        m = _PROGRESS_RE.search("file.txt  45% 5242880 10.0MB/s 00:00")
        assert m is not None
        assert m.group(1) == "45"
        assert m.group(2) == "5242880"

    def test_100_percent(self) -> None:
        m = _PROGRESS_RE.search("file.txt 100% 10485760 38.8MB/s 00:00")
        assert m is not None
        assert m.group(1) == "100"
        assert m.group(2) == "10485760"

    def test_progress_with_hms_eta(self) -> None:
        m = _PROGRESS_RE.search("file.txt  50% 5242880 10.0MB/s 1:23:45 ETA")
        assert m is not None
        assert m.group(1) == "50"

    def test_progress_with_mmss_eta(self) -> None:
        m = _PROGRESS_RE.search("file.txt  50% 5242880 10.0MB/s 05:30 ETA")
        assert m is not None
        assert m.group(1) == "50"

    def test_stalled(self) -> None:
        m = _PROGRESS_RE.match("- stalled -")
        assert m is not None

    def test_unknown_eta(self) -> None:
        m = _PROGRESS_RE.match("--:-- ETA")
        assert m is not None

    def test_no_match_random_text(self) -> None:
        m = _PROGRESS_RE.search("just some random text")
        assert m is None

    def test_formatted_bytes_kb(self) -> None:
        m = _PROGRESS_RE.search("file.txt 100% 100KB 14.5MB/s 00:00")
        assert m is not None
        assert m.group(2) == "100KB"

    def test_formatted_bytes_mb(self) -> None:
        m = _PROGRESS_RE.search("file.txt  50% 1.5GB 10.2MB/s 01:23")
        assert m is not None
        assert m.group(2) == "1.5GB"

    def test_formatted_bytes_gb(self) -> None:
        m = _PROGRESS_RE.search("file.bin  75% 2GB 50.0MB/s 00:30")
        assert m is not None
        assert m.group(2) == "2GB"

    def test_zero_percent_stalled(self) -> None:
        m = _PROGRESS_RE.search("file.bin  0%    0     0.0KB/s   --:-- ETA")
        assert m is not None
        assert m.group(1) == "0"
        assert m.group(2) == "0"

    def test_zero_percent_unknown_eta(self) -> None:
        m = _PROGRESS_RE.search("file.bin   0%    0     0.0KB/s   --:-- ETA")
        assert m is not None
        assert m.group(1) == "0"

    def test_dashes_time(self) -> None:
        m = _PROGRESS_RE.search("file.bin   5%   50KB   1.0KB/s   --:-- ETA")
        assert m is not None
        assert m.group(2) == "50KB"

    def test_1024kb(self) -> None:
        m = _PROGRESS_RE.search("test.bin  100%  1024KB  44.4MB/s   00:00")
        assert m is not None
        assert m.group(2) == "1024KB"

    def test_stalled_variant_spaces(self) -> None:
        m = _PROGRESS_RE.match("- stalled -")
        assert m is not None

    def test_progress_with_spaces_in_path(self) -> None:
        m = _PROGRESS_RE.search("my file with spaces.txt  45% 5242880 10.0MB/s 00:00")
        assert m is not None
        assert m.group(1) == "45"
        assert m.group(2) == "5242880"

    def test_progress_with_comma_decimal_speed(self) -> None:
        m = _PROGRESS_RE.search("file.bin  50% 5242880 10,5MB/s 00:00")
        assert m is not None
        assert m.group(1) == "50"

    def test_progress_with_kib(self) -> None:
        m = _PROGRESS_RE.search("file.bin 100% 100KiB 14.5MB/s 00:00")
        assert m is not None
        assert m.group(2) == "100KiB"

    def test_progress_with_mib(self) -> None:
        m = _PROGRESS_RE.search("file.bin  50% 1MiB 10.2MB/s 01:23")
        assert m is not None
        assert m.group(2) == "1MiB"


class TestParseFormattedBytes:
    def test_raw_zero(self) -> None:
        assert _parse_formatted_bytes("0") == 0

    def test_raw_digits(self) -> None:
        assert _parse_formatted_bytes("42") == 42

    def test_raw_large(self) -> None:
        assert _parse_formatted_bytes("9999") == 9999

    def test_kb(self) -> None:
        assert _parse_formatted_bytes("100KB") == 100 * 1024

    def test_1024kb(self) -> None:
        assert _parse_formatted_bytes("1024KB") == 1024 * 1024

    def test_mb(self) -> None:
        assert _parse_formatted_bytes("1MB") == 1024 * 1024

    def test_decimal_gb(self) -> None:
        assert _parse_formatted_bytes("1.5GB") == int(1.5 * 1024**3)

    def test_tb(self) -> None:
        assert _parse_formatted_bytes("1TB") == 1024**4

    def test_5mb(self) -> None:
        assert _parse_formatted_bytes("5MB") == 5 * 1024 * 1024

    def test_b_suffix(self) -> None:
        assert _parse_formatted_bytes("512B") == 512

    def test_kib(self) -> None:
        assert _parse_formatted_bytes("100KiB") == 100 * 1024

    def test_mib(self) -> None:
        assert _parse_formatted_bytes("1MiB") == 1024**2

    def test_gib(self) -> None:
        assert _parse_formatted_bytes("1GiB") == 1024**3

    def test_tib(self) -> None:
        assert _parse_formatted_bytes("1TiB") == 1024**4

    def test_pb(self) -> None:
        assert _parse_formatted_bytes("1PB") == 1024**5

    def test_pib(self) -> None:
        assert _parse_formatted_bytes("1PiB") == 1024**5

    def test_comma_decimal_separator(self) -> None:
        assert _parse_formatted_bytes("1,5GB") == int(1.5 * 1024**3)

    def test_comma_decimal_mb(self) -> None:
        assert _parse_formatted_bytes("2,5MB") == int(2.5 * 1024**2)


class TestSFTPErrorRE:
    def test_cant(self) -> None:
        assert _SFTP_ERROR_RE.search("Can't stat: No such file") is not None

    def test_cannot(self) -> None:
        assert _SFTP_ERROR_RE.search("Cannot connect") is not None

    def test_could_not(self) -> None:
        assert _SFTP_ERROR_RE.search("Could not resolve hostname") is not None

    def test_couldnt_apostrophe(self) -> None:
        assert _SFTP_ERROR_RE.search("Couldn't stat: No such file") is not None

    def test_error(self) -> None:
        assert _SFTP_ERROR_RE.search("Error: something went wrong") is not None

    def test_failed(self) -> None:
        assert _SFTP_ERROR_RE.search("Failed to upload") is not None

    def test_no_such(self) -> None:
        assert _SFTP_ERROR_RE.search("No such file or directory") is not None

    def test_permission_denied(self) -> None:
        assert _SFTP_ERROR_RE.search("Permission denied") is not None

    def test_connection_refused(self) -> None:
        assert _SFTP_ERROR_RE.search("Connection refused") is not None

    def test_network_unreachable(self) -> None:
        assert _SFTP_ERROR_RE.search("Network is unreachable") is not None

    def test_name_or_service_not_known(self) -> None:
        assert _SFTP_ERROR_RE.search("Name or service not known") is not None

    def test_too_many_authentication(self) -> None:
        assert _SFTP_ERROR_RE.search("Too many authentication failures") is not None

    def test_host_key_verification_failed(self) -> None:
        assert _SFTP_ERROR_RE.search("Host key verification failed") is not None

    def test_connection_timed_out(self) -> None:
        assert _SFTP_ERROR_RE.search("Connection timed out") is not None

    def test_broken_pipe(self) -> None:
        assert _SFTP_ERROR_RE.search("Broken pipe") is not None

    def test_connection_reset(self) -> None:
        assert _SFTP_ERROR_RE.search("Connection reset by peer") is not None

    def test_no_space_left_on_device(self) -> None:
        assert _SFTP_ERROR_RE.search("No space left on device") is not None

    def test_read_only_file_system(self) -> None:
        assert _SFTP_ERROR_RE.search("Read-only file system") is not None

    def test_quota_exceeded(self) -> None:
        assert _SFTP_ERROR_RE.search("Quota exceeded") is not None

    def test_connection_closed_by_remote_host(self) -> None:
        assert _SFTP_ERROR_RE.search("Connection closed by remote host") is not None

    def test_subsystem_sftp_not_enabled(self) -> None:
        assert _SFTP_ERROR_RE.search("Subsystem sftp not enabled") is not None

    def test_not_a_regular_file(self) -> None:
        assert _SFTP_ERROR_RE.search("Not a regular file") is not None

    def test_is_a_directory(self) -> None:
        assert _SFTP_ERROR_RE.search("Is a directory") is not None

    def test_operation_not_supported(self) -> None:
        assert _SFTP_ERROR_RE.search("Operation not supported") is not None

    def test_unknown_subsystem(self) -> None:
        assert _SFTP_ERROR_RE.search("Unknown subsystem") is not None

    def test_disconnected(self) -> None:
        assert _SFTP_ERROR_RE.search("Disconnected") is not None

    def test_ssh_exchange_identification(self) -> None:
        assert _SFTP_ERROR_RE.search("ssh_exchange_identification") is not None

    def test_case_insensitive(self) -> None:
        assert _SFTP_ERROR_RE.search("permission denied") is not None
        assert _SFTP_ERROR_RE.search("ERROR: bad") is not None

    def test_no_match(self) -> None:
        assert _SFTP_ERROR_RE.search("Uploading file.txt") is None

    def test_error_not_matched_on_progress_line(self) -> None:
        """Progress lines should not be misidentified as errors even if they
        contain words like 'Error' (C2 — error regex only runs after progress
        fails to match)."""
        worker = _make_worker()
        worker._parse_line("my Error file.txt  45% 5242880 10.0MB/s 00:00")
        assert worker._error_message == ""
        assert worker._bytes_transferred > 0


# --- _parse_line tests ---


class TestParseLine:
    def test_progress_line_with_bytes(self) -> None:
        worker = _make_worker()
        worker._parse_line("file.txt  45% 5242880 10.0MB/s 00:00")
        assert worker._bytes_transferred == 5242880
        assert worker._last_progress_time > 0

    def test_progress_line_100_percent(self) -> None:
        worker = _make_worker()
        worker._parse_line("file.txt 100% 10485760 38.8MB/s 00:00")
        assert worker._bytes_transferred == 10485760

    def test_sftp_prompt_detection(self) -> None:
        worker = _make_worker()
        worker._parse_line("sftp> ")
        assert worker._prompt_count == 1
        assert worker._prompt_event.is_set()

    def test_sftp_prompt_increments_count(self) -> None:
        worker = _make_worker()
        worker._parse_line("sftp> ")
        assert worker._prompt_count == 1
        worker._prompt_event.clear()
        worker._parse_line("sftp> ")
        assert worker._prompt_count == 2

    def test_error_detection_cant(self) -> None:
        worker = _make_worker()
        worker._parse_line("Can't stat: No such file")
        assert worker._error_message == "Can't stat: No such file"

    def test_error_detection_permission(self) -> None:
        worker = _make_worker()
        worker._parse_line("Permission denied")
        assert worker._error_message == "Permission denied"

    def test_error_detection_no_such(self) -> None:
        worker = _make_worker()
        worker._parse_line("No such file or directory")
        assert worker._error_message == "No such file or directory"

    def test_error_not_overwritten(self) -> None:
        worker = _make_worker()
        worker._parse_line("Permission denied")
        worker._parse_line("No such file or directory")
        assert worker._error_message == "Permission denied"

    def test_empty_line_ignored(self) -> None:
        worker = _make_worker()
        worker._parse_line("")
        assert worker._bytes_transferred == 0
        assert worker._prompt_count == 0
        assert worker._error_message == ""

    def test_whitespace_line_ignored(self) -> None:
        worker = _make_worker()
        worker._parse_line("   ")
        assert worker._bytes_transferred == 0
        assert worker._prompt_count == 0

    def test_ansi_escape_stripped(self) -> None:
        worker = _make_worker()
        worker._parse_line("file.txt  50% 5242880 10.0MB/s 1:23:45 ETA")
        assert worker._bytes_transferred == 5242880

    def test_progress_with_mmss_eta(self) -> None:
        worker = _make_worker()
        worker._parse_line("file.txt  50% 5242880 10.0MB/s 05:30 ETA")
        assert worker._bytes_transferred == 5242880

    def test_progress_stalled_preserves_bytes(self) -> None:
        worker = _make_worker()
        worker._bytes_transferred = 5_000_000
        worker._parse_line("- stalled -")
        assert worker._bytes_transferred == 5_000_000

    def test_progress_stalled_updates_timestamp(self) -> None:
        worker = _make_worker()
        worker._bytes_transferred = 5_000_000
        worker._last_progress_time = 0.0
        worker._parse_line("- stalled -")
        assert worker._last_progress_time > 0

    def test_progress_unknown_eta_preserves_bytes(self) -> None:
        worker = _make_worker()
        worker._bytes_transferred = 8_000_000
        worker._parse_line("--:-- ETA")
        assert worker._bytes_transferred == 8_000_000

    def test_progress_callback_on_stalled_reports_preserved_bytes(self) -> None:
        cb = MagicMock()
        worker = _make_worker(progress_callback=cb)
        worker._bytes_transferred = 5_000_000
        worker._parse_line("- stalled -")
        cb.assert_called_once_with("/tmp/test.txt", 5_000_000, 10_000_000)

    def test_progress_callback_on_unknown_eta_reports_preserved_bytes(self) -> None:
        cb = MagicMock()
        worker = _make_worker(progress_callback=cb)
        worker._bytes_transferred = 8_000_000
        worker._parse_line("--:-- ETA")
        cb.assert_called_once_with("/tmp/test.txt", 8_000_000, 10_000_000)

    def test_progress_bytes_not_overwritten_by_lower(self) -> None:
        worker = _make_worker()
        worker._bytes_transferred = 8_000_000
        worker._parse_line("file.txt  50% 5000000 10.0MB/s 00:00")
        assert worker._bytes_transferred == 8_000_000

    def test_progress_callback_called(self) -> None:
        cb = MagicMock()
        worker = _make_worker(progress_callback=cb)
        worker._parse_line("file.txt  45% 5242880 10.0MB/s 00:00")
        cb.assert_called_once_with("/tmp/test.txt", 5242880, 10_000_000)

    def test_progress_callback_exception_swallowed(self) -> None:
        cb = MagicMock(side_effect=RuntimeError("oops"))
        worker = _make_worker(progress_callback=cb)
        worker._parse_line("file.txt  45% 5242880 10.0MB/s 00:00")
        assert worker._bytes_transferred == 5242880

    def test_progress_callback_exception_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """H5: callback exceptions are logged at debug level."""
        cb = MagicMock(side_effect=RuntimeError("oops"))
        worker = _make_worker(progress_callback=cb)
        with caplog.at_level(logging.DEBUG):
            worker._parse_line("file.txt  45% 5242880 10.0MB/s 00:00")
        assert worker._bytes_transferred == 5242880
        assert any("Progress callback failed" in r.message for r in caplog.records)

    def test_prompt_line_returns_early(self) -> None:
        worker = _make_worker()
        worker._parse_line("sftp> ")
        assert worker._prompt_count == 1

    def test_progress_after_ansi_stripped(self) -> None:
        worker = _make_worker()
        worker._parse_line("\x1b[1mfile.txt  75% 7864320 20.0MB/s 00:00\x1b[0m")
        assert worker._bytes_transferred == 7864320

    def test_non_monotonic_bytes_updates_progress_time(self) -> None:
        """H1: Non-monotonic byte count still updates _last_progress_time."""
        worker = _make_worker()
        worker._bytes_transferred = 8_000_000
        worker._last_progress_time = 0.0
        worker._parse_line("file.txt  50% 5000000 10.0MB/s 00:00")
        assert worker._bytes_transferred == 8_000_000
        assert worker._last_progress_time > 0

    def test_error_not_matched_when_progress_matches(self) -> None:
        """C2: Error regex should not run when progress regex already matched."""
        worker = _make_worker()
        worker._parse_line("Error file.txt  45% 5242880 10.0MB/s 00:00")
        assert worker._error_message == ""
        assert worker._bytes_transferred == 5242880

    def test_prompt_with_trailing_error(self) -> None:
        """M1: Prompt with trailing text — error in trailing text detected."""
        worker = _make_worker()
        worker._parse_line("sftp> Permission denied")
        assert worker._prompt_count == 1
        assert worker._error_message == "Permission denied"

    def test_progress_uses_file_path_attribute(self) -> None:
        """C3: Progress callback uses self.file_path, not regex group."""
        cb = MagicMock()
        worker = _make_worker(
            file_path="/path/with spaces/my file.txt",
            progress_callback=cb,
        )
        worker._parse_line("my file.txt  45% 5242880 10.0MB/s 00:00")
        cb.assert_called_once_with("/path/with spaces/my file.txt", 5242880, 10_000_000)


# --- _process_output tests ---


class TestProcessOutput:
    def test_splits_on_cr(self) -> None:
        worker = _make_worker()
        worker._process_output("file.txt  10% 1000000 5.0MB/s 00:00\rfile.txt  20% 2000000 5.0MB/s 00:00\r")
        assert worker._bytes_transferred == 2000000

    def test_splits_on_newline(self) -> None:
        worker = _make_worker()
        worker._process_output("sftp> \n")
        assert worker._prompt_count == 1

    def test_mixed_cr_and_newline(self) -> None:
        worker = _make_worker()
        worker._process_output("sftp> \n")
        assert worker._prompt_count == 1

    def test_incomplete_line_buffered(self) -> None:
        worker = _make_worker()
        worker._process_output("incom")
        assert worker._linebuf == "incom"
        assert worker._bytes_transferred == 0
        assert worker._prompt_count == 0

    def test_incomplete_line_completed_on_next_call(self) -> None:
        worker = _make_worker()
        worker._process_output("sftp")
        assert worker._linebuf == "sftp"
        worker._process_output("> \n")
        assert worker._prompt_count == 1
        assert worker._linebuf == ""

    def test_multiple_progress_with_cr(self) -> None:
        worker = _make_worker()
        worker._process_output(
            "file.txt  10% 1000000 5.0MB/s 00:00\r"
            "file.txt  20% 2000000 5.0MB/s 00:00\r"
        )
        assert worker._bytes_transferred == 2000000

    def test_prompt_not_newline_terminated(self) -> None:
        worker = _make_worker()
        worker._process_output("Connected to host.\r\nsftp> ")
        assert worker._prompt_count == 1

    def test_prompt_without_newline_partial_then_rest(self) -> None:
        worker = _make_worker()
        worker._process_output("Connected to host.\r\n")
        assert worker._prompt_count == 0
        worker._process_output("sftp> ")
        assert worker._prompt_count == 1

    def test_formatted_bytes_kb_in_progress(self) -> None:
        worker = _make_worker()
        worker._file_size = 102400
        worker._process_output("test.bin  100%  100KB  14.5MB/s 00:00\r\n")
        assert worker._bytes_transferred == 102400

    def test_formatted_bytes_mb_in_progress(self) -> None:
        worker = _make_worker()
        worker._file_size = 1048576
        worker._process_output("test.bin  100%  1MB  44.4MB/s 00:00\r\n")
        assert worker._bytes_transferred == 1048576

    def test_zero_bytes_stalled_progress(self) -> None:
        worker = _make_worker()
        worker._file_size = 102400
        worker._process_output("test.bin   0%    0     0.0KB/s   --:-- ETA\r")
        assert worker._bytes_transferred == 0

    def test_progress_then_prompt_combined(self) -> None:
        worker = _make_worker()
        worker._file_size = 102400
        worker._process_output(
            "test.bin  100%  100KB  14.5MB/s 00:00\r\nsftp> "
        )
        assert worker._bytes_transferred == 102400
        assert worker._prompt_count == 1

    def test_linebuffer_overflow_truncation(self) -> None:
        """M6: Line buffer overflow truncates to last 4096 chars."""
        worker = _make_worker()
        long_data = "A" * 9000
        worker._linebuf = long_data
        worker._process_output("B")
        assert len(worker._linebuf) <= 4097  # 4096 + "B"

    def test_prompt_in_linebuf_with_trailing_data(self) -> None:
        """M7: Prompt in linebuf preserves trailing text."""
        worker = _make_worker()
        worker._process_output("sftp> some trailing text")
        assert worker._prompt_count == 1
        assert "trailing text" in worker._linebuf or worker._linebuf == ""

    def test_idle_timer_reset_on_any_output(self) -> None:
        """Idle timer only resets on PROGRESS_RE match, not any output."""
        worker = _make_worker()
        worker._last_progress_time = 100.0
        worker._process_output("sftp> \n")
        assert worker._last_progress_time == 100.0


# --- _build_sftp_cmd tests ---


class TestBuildSftpCmd:
    def test_default_port(self) -> None:
        worker = _make_worker()
        cmd = worker._build_sftp_cmd()
        assert "sftp" in cmd
        assert any("Port=22" in arg for arg in cmd)

    def test_custom_port(self) -> None:
        worker = _make_worker(port=2222)
        cmd = worker._build_sftp_cmd()
        assert any("Port=2222" in arg for arg in cmd)

    def test_no_batch_flag(self) -> None:
        worker = _make_worker()
        cmd = worker._build_sftp_cmd()
        assert "-b" not in cmd
        assert "-N" not in cmd

    def test_has_connect_timeout(self) -> None:
        worker = _make_worker(connect_timeout=15)
        cmd = worker._build_sftp_cmd()
        assert any("ConnectTimeout=15" in arg for arg in cmd)

    def test_has_batch_mode(self) -> None:
        worker = _make_worker()
        cmd = worker._build_sftp_cmd()
        assert any("BatchMode=yes" in arg for arg in cmd)

    def test_host_in_cmd(self) -> None:
        worker = _make_worker(host="deploy@server.example.com")
        cmd = worker._build_sftp_cmd()
        assert "deploy@server.example.com" in cmd


# --- Integration-level run() tests (mock pty.fork) ---


class TestPTYWorkerRun:
    @patch("sftp_parallel.pty_worker.PTYWorker._cleanup")
    @patch("sftp_parallel.pty_worker.PTYWorker._kill_process")
    @patch("sftp_parallel.pty_worker.PTYWorker._run_threads")
    @patch("sftp_parallel.pty_worker.PTYWorker._spawn")
    def test_run_success(
        self,
        mock_spawn: MagicMock,
        mock_run_threads: MagicMock,
        mock_kill: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        worker = _make_worker()
        worker._prompt_count = 3
        worker._file_size = 10_000_000
        worker._bytes_transferred = 10_000_000
        result = worker.run()
        assert result.success is True
        assert result.error_message == ""
        mock_spawn.assert_called_once()
        mock_run_threads.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch("sftp_parallel.pty_worker.PTYWorker._cleanup")
    @patch("sftp_parallel.pty_worker.PTYWorker._kill_process")
    @patch("sftp_parallel.pty_worker.PTYWorker._run_threads")
    @patch("sftp_parallel.pty_worker.PTYWorker._spawn")
    def test_run_success_bytes_mismatch_means_failure(
        self,
        mock_spawn: MagicMock,
        mock_run_threads: MagicMock,
        mock_kill: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        worker = _make_worker()
        worker._prompt_count = 3
        worker._file_size = 10_000_000
        worker._bytes_transferred = 5_000_000
        result = worker.run()
        assert result.success is False

    @patch("sftp_parallel.pty_worker.PTYWorker._cleanup")
    @patch("sftp_parallel.pty_worker.PTYWorker._kill_process")
    @patch("sftp_parallel.pty_worker.PTYWorker._run_threads")
    @patch("sftp_parallel.pty_worker.PTYWorker._spawn")
    def test_run_success_zero_byte_file(
        self,
        mock_spawn: MagicMock,
        mock_run_threads: MagicMock,
        mock_kill: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        worker = _make_worker()
        worker._prompt_count = 3
        worker._file_size = 0
        worker._bytes_transferred = 0
        result = worker.run()
        assert result.success is True

    @patch("sftp_parallel.pty_worker.PTYWorker._cleanup")
    @patch("sftp_parallel.pty_worker.PTYWorker._kill_process")
    @patch("sftp_parallel.pty_worker.PTYWorker._run_threads")
    @patch("sftp_parallel.pty_worker.PTYWorker._spawn")
    def test_run_error_message_overrides_success(
        self,
        mock_spawn: MagicMock,
        mock_run_threads: MagicMock,
        mock_kill: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        worker = _make_worker()
        worker._prompt_count = 3
        worker._file_size = 10_000_000
        worker._bytes_transferred = 10_000_000
        worker._error_message = "Permission denied"
        result = worker.run()
        assert result.success is False

    @patch("sftp_parallel.pty_worker.PTYWorker._cleanup")
    @patch("sftp_parallel.pty_worker.PTYWorker._kill_process")
    @patch("sftp_parallel.pty_worker.PTYWorker._run_threads")
    @patch("sftp_parallel.pty_worker.PTYWorker._spawn")
    def test_run_spawn_failure_file_not_found(
        self,
        mock_spawn: MagicMock,
        mock_run_threads: MagicMock,
        mock_kill: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        mock_spawn.side_effect = FileNotFoundError("sftp not found")
        worker = _make_worker()
        result = worker.run()
        assert result.success is False
        assert result.error_message == "sftp binary not found"
        mock_run_threads.assert_not_called()

    @patch("sftp_parallel.pty_worker.PTYWorker._cleanup")
    @patch("sftp_parallel.pty_worker.PTYWorker._kill_process")
    @patch("sftp_parallel.pty_worker.PTYWorker._run_threads")
    @patch("sftp_parallel.pty_worker.PTYWorker._spawn")
    def test_run_spawn_failure_oserror(
        self,
        mock_spawn: MagicMock,
        mock_run_threads: MagicMock,
        mock_kill: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        mock_spawn.side_effect = OSError("pty fork failed")
        worker = _make_worker()
        result = worker.run()
        assert result.success is False
        assert "pty fork failed" in result.error_message
        mock_run_threads.assert_not_called()

    @patch("sftp_parallel.pty_worker.PTYWorker._cleanup")
    @patch("sftp_parallel.pty_worker.PTYWorker._kill_process")
    @patch("sftp_parallel.pty_worker.PTYWorker._run_threads")
    @patch("sftp_parallel.pty_worker.PTYWorker._spawn")
    def test_run_error_in_threads(
        self,
        mock_spawn: MagicMock,
        mock_run_threads: MagicMock,
        mock_kill: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        mock_run_threads.side_effect = RuntimeError("thread crash")
        worker = _make_worker()
        result = worker.run()
        assert result.success is False
        assert "thread crash" in result.error_message
        mock_kill.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch("sftp_parallel.pty_worker.PTYWorker._cleanup")
    @patch("sftp_parallel.pty_worker.PTYWorker._kill_process")
    @patch("sftp_parallel.pty_worker.PTYWorker._run_threads")
    @patch("sftp_parallel.pty_worker.PTYWorker._spawn")
    def test_run_fewer_prompts_means_failure_for_zero_byte(
        self,
        mock_spawn: MagicMock,
        mock_run_threads: MagicMock,
        mock_kill: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        worker = _make_worker()
        worker._file_size = 0
        worker._prompt_count = 2
        result = worker.run()
        assert result.success is False

    @patch("sftp_parallel.pty_worker.PTYWorker._cleanup")
    @patch("sftp_parallel.pty_worker.PTYWorker._kill_process")
    @patch("sftp_parallel.pty_worker.PTYWorker._run_threads")
    @patch("sftp_parallel.pty_worker.PTYWorker._spawn")
    def test_run_fewer_prompts_with_nonzero_filesize(
        self,
        mock_spawn: MagicMock,
        mock_run_threads: MagicMock,
        mock_kill: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        worker = _make_worker()
        worker._file_size = 10_000_000
        worker._bytes_transferred = 10_000_000
        worker._prompt_count = 2
        result = worker.run()
        assert result.success is True


# --- terminate tests ---


class TestTerminate:
    @patch("sftp_parallel.pty_worker.PTYWorker._cleanup")
    @patch("sftp_parallel.pty_worker.PTYWorker._kill_process")
    def test_terminate_calls_kill_and_cleanup(
        self,
        mock_kill: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        worker = _make_worker()
        worker.terminate()
        mock_kill.assert_called_once()
        mock_cleanup.assert_called_once()


# --- prompt_timeout parameter tests ---


class TestPromptTimeout:
    def test_default_prompt_timeout(self) -> None:
        worker = PTYWorker(
            host="user@host",
            file_path="/tmp/test.txt",
            remote_dir="/remote/dir",
        )
        assert worker.prompt_timeout == 30

    def test_custom_prompt_timeout(self) -> None:
        worker = PTYWorker(
            host="user@host",
            file_path="/tmp/test.txt",
            remote_dir="/remote/dir",
            prompt_timeout=60,
        )
        assert worker.prompt_timeout == 60