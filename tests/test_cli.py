"""Tests for the CLI module."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from sftp_parallel.cli import (
    list_local_files,
    main,
    parse_destination,
)


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
    @patch("sftp_parallel.cli.run_parallel_uploads")
    def test_successful_upload_exits_zero(
        self, mock_run_parallel: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_run_parallel.return_value = (True, 0)

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "user@host:/remote"])

        assert exc_info.value.code == 0
        mock_run_parallel.assert_called_once()

    @patch("sftp_parallel.cli.run_parallel_uploads")
    def test_upload_prints_success(
        self, mock_run_parallel: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_run_parallel.return_value = (True, 0)

        with patch("sftp_parallel.cli.console") as mock_console:
            with pytest.raises(SystemExit) as exc_info:
                main(["upload", str(tmp), "user@host:/remote"])

        assert exc_info.value.code == 0
        success_calls = [
            c for c in mock_console.print.call_args_list if "Success" in str(c)
        ]
        assert len(success_calls) > 0

    @patch("sftp_parallel.cli.run_parallel_uploads")
    def test_upload_shows_file_count(
        self, mock_run_parallel: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "a.txt").write_text("a")
        (tmp / "b.txt").write_text("b")
        mock_run_parallel.return_value = (True, 0)

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
    @patch("sftp_parallel.cli.run_parallel_uploads")
    def test_failed_upload_exits_74(
        self, mock_run_parallel: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_run_parallel.return_value = (False, 1)

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "user@host:/remote"])

        assert exc_info.value.code == 74

    @patch("sftp_parallel.cli.run_parallel_uploads")
    def test_failed_upload_prints_failure(
        self, mock_run_parallel: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_run_parallel.return_value = (False, 1)

        with patch("sftp_parallel.cli.console") as mock_console:
            with pytest.raises(SystemExit):
                main(["upload", str(tmp), "user@host:/remote"])

        failed_calls = [
            c for c in mock_console.print.call_args_list if "Failed" in str(c)
        ]
        assert len(failed_calls) > 0


class TestSingularFileMessage:
    @patch("sftp_parallel.cli.run_parallel_uploads")
    def test_singular_file_count(
        self, mock_run_parallel: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "only.txt").write_text("data")
        mock_run_parallel.return_value = (True, 0)

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
    @patch("sftp_parallel.cli.run_parallel_uploads")
    def test_run_parallel_uploads_called_with_correct_args(
        self, mock_run_parallel: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "alpha.txt").write_text("aaa")
        (tmp / "beta.txt").write_text("bbb")
        mock_run_parallel.return_value = (True, 0)

        with pytest.raises(SystemExit):
            main(["upload", str(tmp), "user@host:/data"])

        call_args = mock_run_parallel.call_args
        assert call_args[0][0] == "user@host"
        assert call_args[0][2] == "/data"
        buckets = call_args[0][1]
        all_files = []
        for bucket in buckets:
            all_files.extend(bucket)
        assert "alpha.txt" in all_files
        assert "beta.txt" in all_files

    @patch("sftp_parallel.cli.run_parallel_uploads")
    def test_host_passed_correctly(
        self, mock_run_parallel: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "file.txt").write_text("data")
        mock_run_parallel.return_value = (True, 0)

        with pytest.raises(SystemExit):
            main(["upload", str(tmp), "deploy@server.example.com:/var/www"])

        host = mock_run_parallel.call_args[0][0]
        assert host == "deploy@server.example.com"

    @patch("sftp_parallel.cli.run_parallel_uploads")
    def test_threads_flag_distributes_into_correct_buckets(
        self, mock_run_parallel: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        for name in ["a.txt", "b.txt", "c.txt", "d.txt"]:
            (tmp / name).write_text("data")
        mock_run_parallel.return_value = (True, 0)

        with pytest.raises(SystemExit):
            main(["upload", "-t", "4", str(tmp), "user@host:/remote"])

        buckets = mock_run_parallel.call_args[0][1]
        assert len(buckets) == 4


class TestMainNoCommand:
    def test_no_command_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 0


class TestMainVersion:
    def test_version_flag_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0


class TestMainInvalidDestination:
    def test_invalid_destination_exits_two(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "nohost"])

        assert exc_info.value.code == 2


class TestMainNonexistentLocalDir:
    def test_nonexistent_local_dir_exits_two(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["upload", "/nonexistent/dir", "user@host:/remote"])

        assert exc_info.value.code == 2


class TestMainEmptyDir:
    def test_empty_local_dir_exits_zero(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "user@host:/remote"])

        assert exc_info.value.code == 0


class TestSkipExisting:
    @patch("sftp_parallel.cli.run_parallel_uploads")
    @patch("sftp_parallel.cli.get_remote_file_sizes")
    def test_skip_existing_filters_files(
        self,
        mock_remote_sizes: MagicMock,
        mock_run_parallel: MagicMock,
        tmp_path: object,
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "a.txt").write_text("hello")
        (tmp / "b.txt").write_text("world")

        a_size = os.path.getsize(os.path.join(str(tmp), "a.txt"))
        mock_remote_sizes.return_value = {"a.txt": a_size}
        mock_run_parallel.return_value = (True, 0)

        with patch("sftp_parallel.cli.console"):
            with pytest.raises(SystemExit) as exc_info:
                main(["upload", "--skip-existing", str(tmp), "user@host:/remote"])

        assert exc_info.value.code == 0
        mock_remote_sizes.assert_called_once_with("user@host", "/remote")
        call_args = mock_run_parallel.call_args
        buckets = call_args[0][1]
        all_files = []
        for bucket in buckets:
            all_files.extend(bucket)
        assert "b.txt" in all_files
        assert "a.txt" not in all_files

    @patch("sftp_parallel.cli.run_parallel_uploads")
    @patch("sftp_parallel.cli.get_remote_file_sizes")
    def test_skip_existing_prints_skip_message(
        self,
        mock_remote_sizes: MagicMock,
        mock_run_parallel: MagicMock,
        tmp_path: object,
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "a.txt").write_text("hello")
        (tmp / "b.txt").write_text("world")

        a_size = os.path.getsize(os.path.join(str(tmp), "a.txt"))
        mock_remote_sizes.return_value = {"a.txt": a_size}
        mock_run_parallel.return_value = (True, 0)

        with patch("sftp_parallel.cli.console") as mock_console:
            with pytest.raises(SystemExit):
                main(["upload", "--skip-existing", str(tmp), "user@host:/remote"])

        skip_calls = [
            c for c in mock_console.print.call_args_list if "Skipping" in str(c)
        ]
        assert len(skip_calls) > 0

    @patch("sftp_parallel.cli.get_remote_file_sizes")
    def test_all_files_exist_on_remote(
        self, mock_remote_sizes: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "a.txt").write_text("hello")

        a_size = os.path.getsize(os.path.join(str(tmp), "a.txt"))
        mock_remote_sizes.return_value = {"a.txt": a_size}

        with patch("sftp_parallel.cli.console") as mock_console:
            with pytest.raises(SystemExit) as exc_info:
                main(["upload", "--skip-existing", str(tmp), "user@host:/remote"])

        assert exc_info.value.code == 0
        all_exist_calls = [
            c for c in mock_console.print.call_args_list if "already exist" in str(c)
        ]
        assert len(all_exist_calls) > 0

    @patch("sftp_parallel.cli.run_parallel_uploads")
    @patch("sftp_parallel.cli.get_remote_file_sizes")
    def test_skip_existing_not_called_without_flag(
        self,
        mock_remote_sizes: MagicMock,
        mock_run_parallel: MagicMock,
        tmp_path: object,
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "a.txt").write_text("hello")
        mock_run_parallel.return_value = (True, 0)

        with pytest.raises(SystemExit):
            main(["upload", str(tmp), "user@host:/remote"])

        mock_remote_sizes.assert_not_called()


class TestVerifyWithSkipExisting:
    @patch("sftp_parallel.cli.verify_uploads")
    @patch("sftp_parallel.cli.run_parallel_uploads")
    @patch("sftp_parallel.cli.get_remote_file_sizes")
    def test_verify_and_skip_existing_combined(
        self,
        mock_remote_sizes: MagicMock,
        mock_run_parallel: MagicMock,
        mock_verify: MagicMock,
        tmp_path: object,
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "a.txt").write_text("aaa")
        (tmp / "b.txt").write_text("bbb")

        a_size = os.path.getsize(os.path.join(str(tmp), "a.txt"))
        mock_remote_sizes.return_value = {"a.txt": a_size}
        mock_run_parallel.return_value = (True, 0)
        mock_verify.return_value = (["b.txt"], [])

        with pytest.raises(SystemExit) as exc_info:
            main(
                ["upload", "--skip-existing", "--verify", str(tmp), "user@host:/remote"]
            )

        assert exc_info.value.code == 0
        mock_remote_sizes.assert_called_once_with("user@host", "/remote")
        mock_verify.assert_called_once()
        verify_files = mock_verify.call_args[0][3]
        assert "a.txt" not in verify_files
        assert "b.txt" in verify_files
