"""Tests for the uploader module."""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from sftp_parallel.uploader import build_batch_commands, distribute_files, run_sftp


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
