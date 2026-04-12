"""Tests for the uploader module."""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from sftp_parallel.uploader import run_sftp


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
