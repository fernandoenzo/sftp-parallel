"""Tests for the uploader module."""

import os
import subprocess
import tempfile
import unittest

import pytest
from unittest.mock import MagicMock, patch

from sftp_parallel.batch import build_batch_commands
from sftp_parallel.uploader import (
    distribute_files,
    filter_existing_files,
    get_remote_file_sizes,
    parse_ls_output,
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
        assert "BatchMode=yes" in cmd

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

    def test_zero_sessions_raises(self) -> None:
        with pytest.raises(ValueError, match="num_sessions must be positive"):
            distribute_files(["a", "b"], 0)

    def test_negative_sessions_raises(self) -> None:
        with pytest.raises(ValueError, match="num_sessions must be positive"):
            distribute_files(["a", "b"], -1)

    def test_single_session(self) -> None:
        result = distribute_files(["a", "b", "c"], 1)
        assert result == [["a", "b", "c"]]


class TestBuildBatchCommands(unittest.TestCase):
    def test_single_file(self) -> None:
        result = build_batch_commands("/remote", "/local", ["a.txt"])
        assert result == 'cd "/remote"\nput -f "/local/a.txt"\nbye'

    def test_multiple_files(self) -> None:
        result = build_batch_commands("/remote", "/local", ["a.txt", "b.txt"])
        assert (
            result == 'cd "/remote"\nput -f "/local/a.txt"\nput -f "/local/b.txt"\nbye'
        )

    def test_empty_files(self) -> None:
        result = build_batch_commands("/remote", "/local", [])
        assert result == 'cd "/remote"\nbye'


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
            "user@host", [["a.txt", "b.txt"], ["c.txt"]], "/remote", "/local"
        )
        assert success is True
        assert failed == 0
        assert mock_popen.call_count == 2

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_communicate_receives_batch_commands(self, mock_popen: MagicMock) -> None:
        mock_popen.return_value = _make_mock_proc(returncode=0)
        run_parallel_uploads("user@host", [["a.txt"], ["b.txt"]], "/remote", "/local")
        call_args_list = mock_popen.return_value.communicate.call_args_list
        assert (
            call_args_list[0][1]["input"] == 'cd "/remote"\nput -f "/local/a.txt"\nbye'
        )
        assert (
            call_args_list[1][1]["input"] == 'cd "/remote"\nput -f "/local/b.txt"\nbye'
        )

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_sftp_command_includes_host_and_options(
        self, mock_popen: MagicMock
    ) -> None:
        mock_popen.return_value = _make_mock_proc(returncode=0)
        run_parallel_uploads("user@host", [["a.txt"]], "/remote", "/local", timeout=30)
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
        success, failed = run_parallel_uploads(
            "user@host", [["a.txt"], ["b.txt"]], "/remote", "/local"
        )
        assert success is False
        assert failed == 1

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_all_fail(self, mock_popen: MagicMock) -> None:
        procs = [_make_mock_proc(returncode=1), _make_mock_proc(returncode=2)]
        mock_popen.side_effect = procs
        success, failed = run_parallel_uploads(
            "user@host", [["a.txt"], ["b.txt"]], "/remote", "/local"
        )
        assert success is False
        assert failed == 2

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_communicate_exception_counts_as_failure(
        self, mock_popen: MagicMock
    ) -> None:
        proc = _make_mock_proc(returncode=0)
        proc.communicate.side_effect = OSError("broken pipe")
        mock_popen.return_value = proc
        success, failed = run_parallel_uploads(
            "user@host", [["a.txt"]], "/remote", "/local"
        )
        assert success is False
        assert failed == 1


class TestRunParallelUploadsEmptyBuckets(unittest.TestCase):
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_empty_buckets_skipped(self, mock_popen: MagicMock) -> None:
        success, failed = run_parallel_uploads(
            "user@host", [[], [], []], "/remote", "/local"
        )
        assert success is True
        assert failed == 0
        mock_popen.assert_not_called()

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_mixed_empty_and_nonempty(self, mock_popen: MagicMock) -> None:
        mock_popen.return_value = _make_mock_proc(returncode=0)
        success, failed = run_parallel_uploads(
            "user@host", [["a.txt"], [], ["b.txt"]], "/remote", "/local"
        )
        assert success is True
        assert failed == 0
        assert mock_popen.call_count == 2

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_completely_empty_list(self, mock_popen: MagicMock) -> None:
        success, failed = run_parallel_uploads("user@host", [], "/remote", "/local")
        assert success is True
        assert failed == 0
        mock_popen.assert_not_called()


class TestParseLsOutput(unittest.TestCase):
    def test_single_file(self) -> None:
        result = parse_ls_output("-rw-r--r-- 1 user group 1234 Jan  1 12:00 file.txt\n")
        assert result == {"file.txt": 1234}

    def test_multiple_files(self) -> None:
        output = (
            "-rw-r--r-- 1 user group 1234 Jan  1 12:00 a.txt\n"
            "-rw-r--r-- 1 user group 5678 Jan  2 13:00 b.txt\n"
        )
        result = parse_ls_output(output)
        assert result == {"a.txt": 1234, "b.txt": 5678}

    def test_empty_output(self) -> None:
        result = parse_ls_output("")
        assert result == {}

    def test_whitespace_only(self) -> None:
        result = parse_ls_output("   \n  \n")
        assert result == {}

    def test_filename_with_spaces(self) -> None:
        result = parse_ls_output(
            "-rw-r--r-- 1 user group 100 Jan  1 12:00 my file.txt\n"
        )
        assert result == {"my file.txt": 100}

    def test_ignores_non_matching_lines(self) -> None:
        result = parse_ls_output(
            "some random text\n-rw-r--r-- 1 u g 50 Jan 1 00:00 ok.txt\n"
        )
        assert result == {"ok.txt": 50}

    def test_zero_size_file(self) -> None:
        result = parse_ls_output("-rw-r--r-- 1 user group 0 Jan  1 12:00 empty.dat\n")
        assert result == {"empty.dat": 0}

    def test_directory_line_not_excluded(self) -> None:
        """Directory lines (d prefix) are parsed by the regex and included.

        This documents current behavior — parse_ls_output does not
        distinguish files from directories.
        """
        result = parse_ls_output("drwxr-xr-x 2 user group 4096 Jan  1 12:00 subdir\n")
        assert "subdir" in result
        assert result["subdir"] == 4096

    def test_symlink_line_not_excluded(self) -> None:
        """Symlink lines (l prefix) are parsed by the regex and included.

        This documents current behavior — parse_ls_output does not
        distinguish files from symlinks.
        """
        result = parse_ls_output("lrwxrwxrwx 1 user group 5 Jan  1 12:00 link.txt\n")
        assert "link.txt" in result
        assert result["link.txt"] == 5


class TestGetRemoteFileSizes(unittest.TestCase):
    @patch("sftp_parallel.uploader.run_sftp")
    def test_returns_parsed_sizes(self, mock_run_sftp: MagicMock) -> None:
        mock_run_sftp.return_value = (
            True,
            "-rw-r--r-- 1 user group 100 Jan  1 12:00 a.txt\n"
            "-rw-r--r-- 1 user group 200 Jan  2 13:00 b.txt\n",
        )
        result = get_remote_file_sizes("user@host", "/remote/dir")
        assert result == {"a.txt": 100, "b.txt": 200}
        mock_run_sftp.assert_called_once_with(
            "user@host", 'cd "/remote/dir"\nls -l\nbye', timeout=10
        )

    @patch("sftp_parallel.uploader.run_sftp")
    def test_custom_timeout(self, mock_run_sftp: MagicMock) -> None:
        mock_run_sftp.return_value = (True, "")
        get_remote_file_sizes("user@host", "/dir", timeout=30)
        mock_run_sftp.assert_called_once_with(
            "user@host", 'cd "/dir"\nls -l\nbye', timeout=30
        )

    @patch("sftp_parallel.uploader.run_sftp")
    def test_returns_empty_on_failure(self, mock_run_sftp: MagicMock) -> None:
        mock_run_sftp.return_value = (False, "Connection refused")
        result = get_remote_file_sizes("user@host", "/dir")
        assert result == {}


class TestFilterExistingFiles(unittest.TestCase):
    def test_skips_matching_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "a.txt")
            with open(path, "wb") as f:
                f.write(b"x" * 100)
            result = filter_existing_files(tmpdir, ["a.txt"], {"a.txt": 100})
            assert result == []

    def test_includes_when_remote_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "a.txt")
            with open(path, "wb") as f:
                f.write(b"x" * 100)
            result = filter_existing_files(tmpdir, ["a.txt"], {})
            assert result == ["a.txt"]

    def test_includes_when_size_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "a.txt")
            with open(path, "wb") as f:
                f.write(b"x" * 100)
            result = filter_existing_files(tmpdir, ["a.txt"], {"a.txt": 999})
            assert result == ["a.txt"]

    def test_mixed_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, size in [("a.txt", 100), ("b.txt", 200), ("c.txt", 300)]:
                with open(os.path.join(tmpdir, name), "wb") as f:
                    f.write(b"x" * size)
            remote = {"a.txt": 100, "b.txt": 999}
            result = filter_existing_files(tmpdir, ["a.txt", "b.txt", "c.txt"], remote)
            assert result == ["b.txt", "c.txt"]

    def test_skips_oserror_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = filter_existing_files(
                tmpdir, ["nonexistent.txt"], {"nonexistent.txt": 10}
            )
            assert result == []
