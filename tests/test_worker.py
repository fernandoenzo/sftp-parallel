"""Tests for sftp_parallel.worker."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from rich.progress import Progress, TaskID

from sftp_parallel.worker import (
    Worker,
    WorkerResult,
    _ANSI_ESCAPE_RE,
    _SFTP_ERROR_RE,
    _SFTP_SAFE_PREFIXES,
)


def _make_worker(**overrides: Any) -> Worker:
    """Create a Worker bypassing __init__ validation."""
    from sftp_parallel.worker import Worker as _W
    worker: Worker = _W.__new__(_W)
    worker.host = overrides.get("host", "user@host")
    worker.file_path = overrides.get("file_path", "/tmp/test.txt")
    worker.remote_dir = overrides.get("remote_dir", "/remote/dir")
    worker.port = overrides.get("port", 22)
    worker.connect_timeout = overrides.get("connect_timeout", 10)
    worker.idle_timeout = overrides.get("idle_timeout", 30)
    worker.progress = overrides.get("progress", None)
    worker.task_id = overrides.get("task_id", None)
    worker.pid = 0
    worker.master_fd = -1
    worker._stop = False
    worker._prompt_count = 0
    worker._error_message = ""
    worker._bytes_transferred = 0
    worker._file_size = overrides.get("_file_size", 10_000_000)
    worker._last_progress_time = 0.0
    worker._linebuf = ""
    return worker


class TestWorkerResult:
    def test_construction_all_fields(self) -> None:
        result = WorkerResult(success=True, file_path="/tmp/a.txt", error_message="")
        assert result.success is True
        assert result.file_path == "/tmp/a.txt"
        assert result.error_message == ""

    def test_default_error_message(self) -> None:
        result = WorkerResult(success=False, file_path="/tmp/b.txt")
        assert result.error_message == ""

    def test_with_error_message(self) -> None:
        result = WorkerResult(success=False, file_path="/tmp/c.txt", error_message="Permission denied")
        assert result.error_message == "Permission denied"


class TestWorkerValidation:
    def test_invalid_host_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            Worker(host="", file_path="/tmp/test.txt", remote_dir="/remote/dir")

    def test_invalid_port_zero(self) -> None:
        with pytest.raises(ValueError, match="1-65535"):
            Worker(host="user@host", file_path="/tmp/test.txt", remote_dir="/remote/dir", port=0)

    def test_invalid_port_too_high(self) -> None:
        with pytest.raises(ValueError, match="1-65535"):
            Worker(host="user@host", file_path="/tmp/test.txt", remote_dir="/remote/dir", port=70000)

    def test_invalid_remote_dir_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            Worker(host="user@host", file_path="/tmp/test.txt", remote_dir="")


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

    def test_broken_pipe(self) -> None:
        assert _SFTP_ERROR_RE.search("Broken pipe") is not None

    def test_no_space_left_on_device(self) -> None:
        assert _SFTP_ERROR_RE.search("No space left on device") is not None

    def test_read_only_file_system(self) -> None:
        assert _SFTP_ERROR_RE.search("Read-only file system") is not None

    def test_ssh_exchange_identification(self) -> None:
        assert _SFTP_ERROR_RE.search("ssh_exchange_identification") is not None

    def test_case_insensitive(self) -> None:
        assert _SFTP_ERROR_RE.search("permission denied") is not None
        assert _SFTP_ERROR_RE.search("ERROR: bad") is not None

    def test_no_match(self) -> None:
        assert _SFTP_ERROR_RE.search("Uploading file.txt") is None


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

    def test_sftp_prompt_increments_count(self) -> None:
        worker = _make_worker()
        worker._parse_line("sftp> ")
        assert worker._prompt_count == 1
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

    def test_progress_bytes_not_overwritten_by_lower(self) -> None:
        worker = _make_worker()
        worker._bytes_transferred = 8_000_000
        worker._parse_line("file.txt  50% 5000000 10.0MB/s 00:00")
        assert worker._bytes_transferred == 8_000_000

    def test_non_monotonic_bytes_updates_progress_time(self) -> None:
        worker = _make_worker()
        worker._bytes_transferred = 8_000_000
        worker._last_progress_time = 0.0
        worker._parse_line("file.txt  50% 5000000 10.0MB/s 00:00")
        assert worker._bytes_transferred == 8_000_000
        assert worker._last_progress_time > 0

    def test_progress_after_ansi_stripped(self) -> None:
        worker = _make_worker()
        worker._parse_line("\x1b[1mfile.txt  75% 7864320 20.0MB/s 00:00\x1b[0m")
        assert worker._bytes_transferred == 7864320

    def test_error_not_matched_when_progress_matches(self) -> None:
        worker = _make_worker()
        worker._parse_line("Error file.txt  45% 5242880 10.0MB/s 00:00")
        assert worker._error_message == ""
        assert worker._bytes_transferred == 5242880

    def test_prompt_with_trailing_error(self) -> None:
        worker = _make_worker()
        worker._parse_line("sftp> Permission denied")
        assert worker._prompt_count == 1
        assert worker._error_message == "Permission denied"

    def test_safe_prefix_cd(self) -> None:
        worker = _make_worker()
        worker._parse_line("cd /remote/dir")
        assert worker._error_message == ""
        assert worker._prompt_count == 0

    def test_safe_prefix_put(self) -> None:
        worker = _make_worker()
        worker._parse_line("put -f /tmp/test.txt")
        assert worker._error_message == ""

    def test_safe_prefix_bye(self) -> None:
        worker = _make_worker()
        worker._parse_line("bye")
        assert worker._error_message == ""

    def test_progress_with_formatted_bytes_kb(self) -> None:
        worker = _make_worker()
        worker._parse_line("test.bin  100%  100KB  14.5MB/s 00:00")
        assert worker._bytes_transferred == 102400

    def test_progress_with_formatted_bytes_mb(self) -> None:
        worker = _make_worker()
        worker._parse_line("test.bin  100%  1MB  44.4MB/s 00:00")
        assert worker._bytes_transferred == 1048576

    def test_progress_with_mmss_eta(self) -> None:
        worker = _make_worker()
        worker._parse_line("file.txt  50% 5242880 10.0MB/s 05:30 ETA")
        assert worker._bytes_transferred == 5242880

    def test_progress_with_hms_eta(self) -> None:
        worker = _make_worker()
        worker._parse_line("file.txt  50% 5242880 10.0MB/s 1:23:45 ETA")
        assert worker._bytes_transferred == 5242880


class TestSplitLines:
    def test_splits_on_cr(self) -> None:
        worker = _make_worker()
        lines = worker._split_lines("line1\rline2\r")
        assert "line1" in lines
        assert "line2" in lines

    def test_splits_on_newline(self) -> None:
        worker = _make_worker()
        lines = worker._split_lines("line1\nline2\n")
        assert "line1" in lines
        assert "line2" in lines

    def test_incomplete_line_buffered(self) -> None:
        worker = _make_worker()
        lines = worker._split_lines("incom")
        assert lines == []
        assert worker._linebuf == "incom"

    def test_incomplete_line_completed_on_next_call(self) -> None:
        worker = _make_worker()
        worker._split_lines("sftp")
        assert worker._linebuf == "sftp"
        lines = worker._split_lines("> \n")
        assert "sftp> " in lines
        assert worker._linebuf == ""

    def test_buffer_overflow_truncation(self) -> None:
        worker = _make_worker()
        worker._linebuf = "A" * 9000
        worker._split_lines("B")
        assert len(worker._linebuf) <= 4097

    def test_mixed_cr_and_newline(self) -> None:
        worker = _make_worker()
        lines = worker._split_lines("line1\r\nline2\r\n")
        assert "line1" in lines
        assert "line2" in lines

    def test_empty_text_returns_empty(self) -> None:
        worker = _make_worker()
        lines = worker._split_lines("\r\n\r\n")
        assert all(seg == "" for seg in lines) or lines == []

    def test_returns_list(self) -> None:
        worker = _make_worker()
        result = worker._split_lines("hello\n")
        assert isinstance(result, list)


class TestProcessOutput:
    def test_splits_on_cr(self) -> None:
        worker = _make_worker()
        worker._process_output("file.txt  10% 1000000 5.0MB/s 00:00\rfile.txt  20% 2000000 5.0MB/s 00:00\r")
        assert worker._bytes_transferred == 2000000

    def test_splits_on_newline(self) -> None:
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

    def test_progress_then_prompt_combined(self) -> None:
        worker = _make_worker()
        worker._file_size = 102400
        worker._process_output("test.bin  100%  100KB  14.5MB/s 00:00\r\nsftp> ")
        assert worker._bytes_transferred == 102400
        assert worker._prompt_count == 1

    def test_prompt_in_linebuf_with_trailing_data(self) -> None:
        worker = _make_worker()
        worker._process_output("sftp> some trailing text")
        assert worker._prompt_count == 1

    def test_idle_timer_reset_on_any_output(self) -> None:
        worker = _make_worker()
        worker._last_progress_time = 100.0
        worker._process_output("sftp> \n")
        assert worker._last_progress_time > 100.0

    def test_formatted_bytes_kb_in_progress(self) -> None:
        worker = _make_worker()
        worker._file_size = 102400
        worker._process_output("test.bin  100%  100KB  14.5MB/s 00:00\r\n")
        assert worker._bytes_transferred == 102400

    def test_connected_line_updates_progress_time(self) -> None:
        worker = _make_worker()
        worker._last_progress_time = 0
        worker._process_output("Connected to host.\r\n")
        assert worker._last_progress_time > 0


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


class TestTerminate:
    def test_terminate_sets_stop_flag(self) -> None:
        worker = _make_worker()
        assert worker._stop is False
        worker.terminate()
        assert worker._stop is True

    @patch("sftp_parallel.worker.Worker._kill_process")
    def test_terminate_calls_kill_process(self, mock_kill: MagicMock) -> None:
        worker = _make_worker()
        worker.terminate()
        mock_kill.assert_called_once()

    @patch("sftp_parallel.worker.Worker._kill_process")
    def test_terminate_idempotent(self, mock_kill: MagicMock) -> None:
        worker = _make_worker()
        worker.terminate()
        worker.terminate()
        assert mock_kill.call_count == 2


class TestDetermineSuccess:
    def test_error_means_failure(self) -> None:
        worker = _make_worker()
        worker._error_message = "Permission denied"
        assert worker._determine_success() is False

    def test_bytes_match_means_success(self) -> None:
        worker = _make_worker()
        worker._file_size = 10_000_000
        worker._bytes_transferred = 10_000_000
        assert worker._determine_success() is True

    def test_bytes_mismatch_means_failure(self) -> None:
        worker = _make_worker()
        worker._file_size = 10_000_000
        worker._bytes_transferred = 5_000_000
        assert worker._determine_success() is False

    def test_zero_byte_file_three_prompts_means_success(self) -> None:
        worker = _make_worker()
        worker._file_size = 0
        worker._prompt_count = 3
        assert worker._determine_success() is True

    def test_zero_byte_file_fewer_prompts_means_failure(self) -> None:
        worker = _make_worker()
        worker._file_size = 0
        worker._prompt_count = 2
        assert worker._determine_success() is False

    def test_error_overrides_byte_match(self) -> None:
        worker = _make_worker()
        worker._file_size = 10_000_000
        worker._bytes_transferred = 10_000_000
        worker._error_message = "Something failed"
        assert worker._determine_success() is False

    def test_bytes_override_prompts(self) -> None:
        worker = _make_worker()
        worker._file_size = 10_000_000
        worker._bytes_transferred = 5_000_000
        worker._prompt_count = 3
        assert worker._determine_success() is False

    def test_bytes_full_with_few_prompts(self) -> None:
        worker = _make_worker()
        worker._file_size = 10_000_000
        worker._bytes_transferred = 10_000_000
        worker._prompt_count = 2
        assert worker._determine_success() is True


class TestRun:
    @patch("sftp_parallel.worker.Worker._cleanup")
    @patch("sftp_parallel.worker.Worker._loop")
    @patch("sftp_parallel.worker.Worker._spawn")
    def test_run_success(
        self,
        mock_spawn: MagicMock,
        mock_loop: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        worker = _make_worker()
        worker._bytes_transferred = 10_000_000
        worker._file_size = 10_000_000
        mock_loop.return_value = WorkerResult(success=True, file_path=worker.file_path)
        result = worker.run()
        assert result.success is True
        mock_spawn.assert_called_once()
        mock_loop.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch("sftp_parallel.worker.Worker._cleanup")
    @patch("sftp_parallel.worker.Worker._spawn")
    def test_run_spawn_failure_file_not_found(
        self,
        mock_spawn: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        mock_spawn.side_effect = FileNotFoundError("sftp not found")
        worker = _make_worker()
        result = worker.run()
        assert result.success is False
        assert result.error_message == "sftp binary not found"

    @patch("sftp_parallel.worker.Worker._cleanup")
    @patch("sftp_parallel.worker.Worker._spawn")
    def test_run_spawn_failure_oserror(
        self,
        mock_spawn: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        mock_spawn.side_effect = OSError("pty fork failed")
        worker = _make_worker()
        result = worker.run()
        assert result.success is False
        assert "pty fork failed" in result.error_message

    @patch("sftp_parallel.worker.Worker._cleanup")
    @patch("sftp_parallel.worker.Worker._loop")
    @patch("sftp_parallel.worker.Worker._spawn")
    def test_run_cleanup_called_on_error(
        self,
        mock_spawn: MagicMock,
        mock_loop: MagicMock,
        mock_cleanup: MagicMock,
    ) -> None:
        mock_loop.side_effect = RuntimeError("crash")
        worker = _make_worker()
        with pytest.raises(RuntimeError):
            worker.run()
        mock_cleanup.assert_called_once()


class TestUpdateProgress:
    def test_update_with_rich(self) -> None:
        mock_progress = MagicMock()
        worker = _make_worker(progress=mock_progress, task_id=42)
        worker._bytes_transferred = 5000
        worker._update_progress()
        mock_progress.update.assert_called_once_with(42, completed=5000)

    def test_no_update_without_progress(self) -> None:
        worker = _make_worker()
        worker._bytes_transferred = 5000
        worker._update_progress()

    def test_no_update_without_task_id(self) -> None:
        mock_progress = MagicMock()
        worker = _make_worker(progress=mock_progress, task_id=None)
        worker._bytes_transferred = 5000
        worker._update_progress()
        mock_progress.update.assert_not_called()

    def test_update_exception_swallowed(self) -> None:
        mock_progress = MagicMock()
        mock_progress.update.side_effect = RuntimeError("rich error")
        worker = _make_worker(progress=mock_progress, task_id=42)
        worker._bytes_transferred = 5000
        worker._update_progress()


class TestKillProcess:
    @patch("sftp_parallel.worker.os.waitpid")
    @patch("sftp_parallel.worker.os.killpg")
    def test_kill_process_sends_sigterm(self, mock_killpg: MagicMock, mock_waitpid: MagicMock) -> None:
        import signal as signal_mod
        mock_waitpid.return_value = (0, 0)
        worker = _make_worker()
        worker.pid = 1234
        worker._kill_process()
        mock_killpg.assert_any_call(1234, signal_mod.SIGTERM)

    def test_kill_process_no_pid(self) -> None:
        worker = _make_worker()
        worker.pid = 0
        worker._kill_process()


class TestCleanup:
    @patch("sftp_parallel.worker.os.waitpid")
    @patch("sftp_parallel.worker.os.close")
    def test_cleanup_closes_fd(self, mock_close: MagicMock, mock_waitpid: MagicMock) -> None:
        mock_waitpid.side_effect = ChildProcessError()
        worker = _make_worker()
        worker.master_fd = 99
        worker.pid = 0
        worker._cleanup()
        mock_close.assert_called_once_with(99)
        assert worker.master_fd == -1

    @patch("sftp_parallel.worker.os.waitpid")
    def test_cleanup_reaps_child(self, mock_waitpid: MagicMock) -> None:
        mock_waitpid.return_value = (1234, 0)
        worker = _make_worker()
        worker.master_fd = -1
        worker.pid = 1234
        worker._cleanup()
        assert worker.pid == 0


class TestSftpSafePrefixes:
    def test_cd_prefix(self) -> None:
        assert "cd " in _SFTP_SAFE_PREFIXES

    def test_put_prefix(self) -> None:
        assert "put " in _SFTP_SAFE_PREFIXES

    def test_bye_prefix(self) -> None:
        assert "bye" in _SFTP_SAFE_PREFIXES

    def test_sftp_prompt_prefix(self) -> None:
        assert "sftp>" in _SFTP_SAFE_PREFIXES

    def test_uploading_prefix(self) -> None:
        assert "Uploading " in _SFTP_SAFE_PREFIXES


class TestAnsiEscapeRE:
    def test_strips_color_codes(self) -> None:
        result = _ANSI_ESCAPE_RE.sub("", "\x1b[1mheader\x1b[0m")
        assert result == "header"

    def test_strips_256_color(self) -> None:
        result = _ANSI_ESCAPE_RE.sub("", "\x1b[38;5;196mred\x1b[0m")
        assert result == "red"

    def test_no_ansi_unchanged(self) -> None:
        text = "plain text"
        assert _ANSI_ESCAPE_RE.sub("", text) == text


class TestTerminateUrgent:
    @patch("sftp_parallel.worker.os.waitpid")
    @patch("sftp_parallel.worker.os.killpg")
    def test_urgent_sends_sigkill(self, mock_killpg: MagicMock, mock_waitpid: MagicMock) -> None:
        import signal as signal_mod
        mock_waitpid.return_value = (1234, 0)
        worker = _make_worker()
        worker.pid = 1234
        worker.terminate_urgent()
        mock_killpg.assert_called_with(1234, signal_mod.SIGKILL)
        assert worker._stop is True
        assert worker.pid == 0

    def test_urgent_no_pid(self) -> None:
        worker = _make_worker()
        worker.pid = 0
        worker.terminate_urgent()
        # Should not crash, just return


class TestReapPid:
    @patch("sftp_parallel.worker.os.waitpid")
    def test_reap_pid_claims_and_reaps(self, mock_waitpid: MagicMock) -> None:
        mock_waitpid.return_value = (1234, 0)
        worker = _make_worker()
        worker.pid = 1234
        result = worker._reap_pid(1234)
        assert result is True
        assert worker.pid == 0

    def test_reap_pid_already_claimed(self) -> None:
        worker = _make_worker()
        worker.pid = 0
        result = worker._reap_pid(1234)
        assert result is False

    @patch("sftp_parallel.worker.os.waitpid", side_effect=ChildProcessError)
    def test_reap_pid_handles_child_process_error(self, mock_waitpid: MagicMock) -> None:
        worker = _make_worker()
        worker.pid = 1234
        result = worker._reap_pid(1234)
        assert result is True
        assert worker.pid == 0


class TestSpawnFDs:
    @patch("sftp_parallel.worker.os._exit")
    @patch("sftp_parallel.worker.os.execvp")
    @patch("sftp_parallel.worker.os.listdir")
    @patch("sftp_parallel.worker.os.close")
    @patch("sftp_parallel.worker.pty.fork")
    def test_spawn_closes_fds_in_child(
        self,
        mock_fork: MagicMock,
        mock_close: MagicMock,
        mock_listdir: MagicMock,
        mock_execvp: MagicMock,
        mock_exit: MagicMock,
    ) -> None:
        # Simulate child process (pid == 0)
        mock_fork.return_value = (0, 99)
        mock_listdir.return_value = ["0", "1", "2", "3", "10"]
        # Prevent actual execvp/exit from running
        mock_execvp.side_effect = OSError("test mock")
        mock_exit.side_effect = SystemExit(74)
        worker = _make_worker()
        try:
            worker._spawn()
        except (SystemExit, OSError):
            pass
        # In child process, close should be called for FDs > 2
        fd_args = [call[0][0] for call in mock_close.call_args_list]
        assert 3 in fd_args
        assert 10 in fd_args