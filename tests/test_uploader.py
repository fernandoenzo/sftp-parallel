"""Tests for the uploader module."""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from sftp_parallel.uploader import (
    build_batch_commands,
    distribute_files,
    run_parallel_uploads,
    run_sftp,
)


class TestRunSftpSuccess(unittest.TestCase):
    @patch("sftp_parallel.uploader.subprocess.run")
    def test_successful_upload(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        success, output = run_sftp("user@host", "cd /tmp\nbye")
        assert success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "sftp"
        assert "-N" in cmd
        assert "-b" in cmd
        assert "-" in cmd
        assert "user@host" in cmd

    @patch("sftp_parallel.uploader.subprocess.run")
    def test_batch_commands_passed_as_stdin(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run_sftp("user@host", "cd /tmp\nbye")
        assert mock_run.call_args[1]["input"] == "cd /tmp\nbye"

    @patch("sftp_parallel.uploader.subprocess.run")
    def test_connect_timeout_option(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        run_sftp("user@host", "bye", timeout=30)
        cmd = mock_run.call_args[0][0]
        assert "ConnectTimeout=30" in cmd


class TestRunSftpFailure(unittest.TestCase):
    @patch("sftp_parallel.uploader.subprocess.run")
    def test_failed_upload_nonzero_returncode(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Connection refused\n"
        )
        success, output = run_sftp("user@host", "cd /tmp\nbye")
        assert success is False
        assert "Connection refused" in output

    @patch("sftp_parallel.uploader.subprocess.run")
    def test_output_combines_stdout_and_stderr(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="warn\n")
        _, output = run_sftp("user@host", "bye")
        assert "ok" in output
        assert "warn" in output


class TestRunSftpExceptions(unittest.TestCase):
    @patch("sftp_parallel.uploader.subprocess.run", side_effect=FileNotFoundError)
    def test_sftp_binary_not_found(self, mock_run: MagicMock) -> None:
        success, output = run_sftp("user@host", "bye")
        assert success is False
        assert "not found" in output

    @patch(
        "sftp_parallel.uploader.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="sftp", timeout=10),
    )
    def test_timeout_handling(self, mock_run: MagicMock) -> None:
        success, output = run_sftp("user@host", "bye")
        assert success is False
        assert "timed out" in output

    @patch(
        "sftp_parallel.uploader.subprocess.run",
        side_effect=OSError("Permission denied"),
    )
    def test_os_error_handling(self, mock_run: MagicMock) -> None:
        success, output = run_sftp("user@host", "bye")
        assert success is False
        assert "OS error" in output


class TestDistributeFiles(unittest.TestCase):
    def test_two_sessions(self) -> None:
        result = distribute_files(["a", "b", "c", "d", "e"], 2)
        assert result == [["a", "c", "e"], ["b", "d"]]

    def test_four_sessions(self) -> None:
        result = distribute_files(["a", "b", "c", "d", "e", "f", "g", "h"], 4)
        assert result == [["a", "e"], ["b", "f"], ["c", "g"], ["d", "h"]]

    def test_more_sessions_than_files(self) -> None:
        result = distribute_files(["a", "b", "c"], 4)
        assert result == [["a"], ["b"], ["c"], []]

    def test_empty_file_list(self) -> None:
        result = distribute_files([], 2)
        assert result == [[], []]

    def test_preserves_order_within_buckets(self) -> None:
        files = ["f1", "f2", "f3", "f4", "f5", "f6"]
        result = distribute_files(files, 3)
        assert result == [["f1", "f4"], ["f2", "f5"], ["f3", "f6"]]
        for bucket in result:
            assert bucket == sorted(bucket, key=files.index)


class TestBuildBatchCommands(unittest.TestCase):
    def test_single_file(self) -> None:
        result = build_batch_commands(["/tmp/a.txt"])
        assert result == "put /tmp/a.txt\nbye"

    def test_multiple_files(self) -> None:
        result = build_batch_commands(["a.txt", "b.txt"])
        assert result == "put a.txt\nput b.txt\nbye"

    def test_empty_files(self) -> None:
        result = build_batch_commands([])
        assert result == "bye"


def _make_mock_proc(returncode: int = 0) -> MagicMock:
    mock = MagicMock()
    mock.communicate.return_value = ("", "")
    mock.returncode = returncode
    mock.stdin = MagicMock()
    mock.stdout = MagicMock()
    mock.stderr = MagicMock()
    return mock


class TestRunParallelUploadsAllSucceed(unittest.TestCase):
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_all_succeed(self, mock_popen: MagicMock) -> None:
        mock_popen.return_value = _make_mock_proc(returncode=0)
        success, failed = run_parallel_uploads(
            "user@host", [["a.txt", "b.txt"], ["c.txt"]]
        )
        assert success is True
        assert failed == 0
        assert mock_popen.call_count == 2

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_communicate_receives_batch_commands(self, mock_popen: MagicMock) -> None:
        mock_popen.return_value = _make_mock_proc(returncode=0)
        run_parallel_uploads("user@host", [["a.txt"], ["b.txt"]])
        call_args_list = mock_popen.return_value.communicate.call_args_list
        assert call_args_list[0][1]["input"] == "put a.txt\nbye"
        assert call_args_list[1][1]["input"] == "put b.txt\nbye"

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_sftp_command_includes_host_and_options(
        self, mock_popen: MagicMock
    ) -> None:
        mock_popen.return_value = _make_mock_proc(returncode=0)
        run_parallel_uploads("user@host", [["a.txt"]], timeout=30)
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "sftp"
        assert "-N" in cmd
        assert "ConnectTimeout=30" in cmd
        assert "BatchMode=yes" in cmd
        assert "-b" in cmd
        assert "-" in cmd
        assert "user@host" in cmd


class TestRunParallelUploadsSomeFail(unittest.TestCase):
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_some_fail(self, mock_popen: MagicMock) -> None:
        procs = [_make_mock_proc(returncode=0), _make_mock_proc(returncode=1)]
        mock_popen.side_effect = procs
        success, failed = run_parallel_uploads("user@host", [["a.txt"], ["b.txt"]])
        assert success is False
        assert failed == 1

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_all_fail(self, mock_popen: MagicMock) -> None:
        procs = [_make_mock_proc(returncode=1), _make_mock_proc(returncode=2)]
        mock_popen.side_effect = procs
        success, failed = run_parallel_uploads("user@host", [["a.txt"], ["b.txt"]])
        assert success is False
        assert failed == 2

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_communicate_exception_counts_as_failure(
        self, mock_popen: MagicMock
    ) -> None:
        proc = _make_mock_proc(returncode=0)
        proc.communicate.side_effect = OSError("broken pipe")
        mock_popen.return_value = proc
        success, failed = run_parallel_uploads("user@host", [["a.txt"]])
        assert success is False
        assert failed == 1


class TestRunParallelUploadsEmptyBuckets(unittest.TestCase):
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_empty_buckets_skipped(self, mock_popen: MagicMock) -> None:
        success, failed = run_parallel_uploads("user@host", [[], [], []])
        assert success is True
        assert failed == 0
        mock_popen.assert_not_called()

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_mixed_empty_and_nonempty(self, mock_popen: MagicMock) -> None:
        mock_popen.return_value = _make_mock_proc(returncode=0)
        success, failed = run_parallel_uploads("user@host", [["a.txt"], [], ["b.txt"]])
        assert success is True
        assert failed == 0
        assert mock_popen.call_count == 2

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_completely_empty_list(self, mock_popen: MagicMock) -> None:
        success, failed = run_parallel_uploads("user@host", [])
        assert success is True
        assert failed == 0
        mock_popen.assert_not_called()
