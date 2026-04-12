"""Tests for the CLI module."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from sftp_parallel.cli import _handle_upload, list_local_files, main, parse_destination


class TestParseDestination:
    def test_basic_destination(self) -> None:
        host, remote_dir = parse_destination("user@host:/remote/dir")
        assert host == "user@host"
        assert remote_dir == "/remote/dir"

    def test_ipv6_destination(self) -> None:
        host, remote_dir = parse_destination("[::1]:/remote/dir")
        assert host == "[::1]"
        assert remote_dir == "/remote/dir"

    def test_user_at_ipv6(self) -> None:
        host, remote_dir = parse_destination("user@[::1]:/tmp")
        assert host == "user@[::1]"
        assert remote_dir == "/tmp"

    def test_no_colon_raises(self) -> None:
        with pytest.raises(ValueError, match="expected HOST:REMOTE_DIR"):
            parse_destination("nohost")

    def test_uses_last_colon(self) -> None:
        host, remote_dir = parse_destination("user@host:22:/remote")
        assert host == "user@host:22"
        assert remote_dir == "/remote"

    def test_empty_host_raises(self) -> None:
        with pytest.raises(ValueError, match="host part is empty"):
            parse_destination(":/remote")

    def test_empty_remote_dir_raises(self) -> None:
        with pytest.raises(ValueError, match="remote directory is empty"):
            parse_destination("user@host:")


class TestListLocalFiles:
    def test_returns_only_regular_files(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "file1.txt").write_text("hello")
        (tmp / "file2.txt").write_text("world")
        (tmp / "subdir").mkdir()

        files = list_local_files(str(tmp))
        assert "file1.txt" in files
        assert "file2.txt" in files
        assert "subdir" not in files

    def test_returns_sorted(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "z.txt").write_text("z")
        (tmp / "a.txt").write_text("a")

        files = list_local_files(str(tmp))
        assert files == ["a.txt", "z.txt"]

    def test_empty_directory(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        assert list_local_files(str(tmp)) == []

    def test_nonexistent_directory_returns_empty(self) -> None:
        files = list_local_files("/nonexistent/path/xyz")
        assert files == []


class TestMainUploadSuccess:
    @patch("sftp_parallel.cli.run_sftp")
    def test_successful_upload_exits_zero(
        self, mock_run_sftp: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_run_sftp.return_value = (True, "")

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "user@host:/remote"])

        assert exc_info.value.code == 0
        mock_run_sftp.assert_called_once()
        call_args = mock_run_sftp.call_args
        assert call_args[0][0] == "user@host"
        assert "cd" in call_args[0][1]

    @patch("sftp_parallel.cli.run_sftp")
    def test_upload_prints_success(
        self, mock_run_sftp: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_run_sftp.return_value = (True, "")

        with patch("sftp_parallel.cli.console") as mock_console:
            with pytest.raises(SystemExit) as exc_info:
                main(["upload", str(tmp), "user@host:/remote"])

            assert exc_info.value.code == 0
            success_calls = [
                c for c in mock_console.print.call_args_list if "Success" in str(c)
            ]
            assert len(success_calls) > 0

    @patch("sftp_parallel.cli.run_sftp")
    def test_upload_shows_file_count(
        self, mock_run_sftp: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "a.txt").write_text("a")
        (tmp / "b.txt").write_text("b")
        mock_run_sftp.return_value = (True, "")

        with patch("sftp_parallel.cli.console") as mock_console:
            with pytest.raises(SystemExit):
                main(["upload", str(tmp), "user@host:/remote"])

            upload_calls = [
                c
                for c in mock_console.print.call_args_list
                if "Uploading 2 files" in str(c)
            ]
            assert len(upload_calls) > 0


class TestMainUploadFailure:
    @patch("sftp_parallel.cli.run_sftp")
    def test_failed_upload_exits_one(
        self, mock_run_sftp: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_run_sftp.return_value = (False, "Connection refused")

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "user@host:/remote"])

        assert exc_info.value.code == 1

    @patch("sftp_parallel.cli.run_sftp")
    def test_failed_upload_prints_failure(
        self, mock_run_sftp: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_run_sftp.return_value = (False, "Connection refused")

        with patch("sftp_parallel.cli.console") as mock_console:
            with pytest.raises(SystemExit):
                main(["upload", str(tmp), "user@host:/remote"])

            failed_calls = [
                c for c in mock_console.print.call_args_list if "Failed" in str(c)
            ]
            assert len(failed_calls) > 0


class TestVerboseOnFailure:
    @patch("sftp_parallel.cli.run_sftp")
    def test_verbose_output_on_failure(
        self, mock_run_sftp: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_run_sftp.return_value = (False, "Connection refused\ndetail line")

        with patch("sftp_parallel.cli.console") as mock_console:
            with pytest.raises(SystemExit):
                main(["upload", str(tmp), "user@host:/remote", "-v"])

            verbose_calls = [
                c
                for c in mock_console.print.call_args_list
                if "Connection refused" in str(c)
            ]
            assert len(verbose_calls) > 0

    @patch("sftp_parallel.cli.run_sftp")
    def test_no_verbose_output_on_failure_by_default(
        self, mock_run_sftp: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_run_sftp.return_value = (False, "Connection refused\ndetail line")

        with patch("sftp_parallel.cli.console") as mock_console:
            with pytest.raises(SystemExit):
                main(["upload", str(tmp), "user@host:/remote"])

            verbose_calls = [
                c
                for c in mock_console.print.call_args_list
                if "Connection refused" in str(c)
            ]
            assert len(verbose_calls) == 0


class TestSingularFileMessage:
    @patch("sftp_parallel.cli.run_sftp")
    def test_singular_file_count(
        self, mock_run_sftp: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "only.txt").write_text("data")
        mock_run_sftp.return_value = (True, "")

        with patch("sftp_parallel.cli.console") as mock_console:
            with pytest.raises(SystemExit):
                main(["upload", str(tmp), "user@host:/remote"])

            singular_calls = [
                c
                for c in mock_console.print.call_args_list
                if "Uploading 1 file " in str(c)
            ]
            assert len(singular_calls) > 0


class TestBatchCommandIntegration:
    @patch("sftp_parallel.cli.run_sftp")
    def test_batch_contains_put_commands(
        self, mock_run_sftp: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "alpha.txt").write_text("aaa")
        (tmp / "beta.txt").write_text("bbb")
        mock_run_sftp.return_value = (True, "")

        with pytest.raises(SystemExit):
            main(["upload", str(tmp), "user@host:/data"])

        batch_commands = mock_run_sftp.call_args[0][1]
        assert 'cd "/data"' in batch_commands
        assert "put -f" in batch_commands
        assert "alpha.txt" in batch_commands
        assert "beta.txt" in batch_commands
        assert "bye" in batch_commands

    @patch("sftp_parallel.cli.run_sftp")
    def test_batch_host_passed_correctly(
        self, mock_run_sftp: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "file.txt").write_text("data")
        mock_run_sftp.return_value = (True, "")

        with pytest.raises(SystemExit):
            main(["upload", str(tmp), "deploy@server.example.com:/var/www"])

        host = mock_run_sftp.call_args[0][0]
        assert host == "deploy@server.example.com"


class TestMainNoCommand:
    def test_no_command_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 0


class TestMainInvalidDestination:
    def test_invalid_destination_exits_one(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "nohost"])

        assert exc_info.value.code == 1


class TestMainNonexistentLocalDir:
    def test_nonexistent_local_dir_exits_one(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["upload", "/nonexistent/dir", "user@host:/remote"])

        assert exc_info.value.code == 1


class TestMainEmptyDir:
    def test_empty_local_dir_exits_zero(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "user@host:/remote"])

        assert exc_info.value.code == 0
