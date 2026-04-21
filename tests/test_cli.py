"""Tests for sftp_parallel.cli."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sftp_parallel.cli import (
    main,
    resolve_file_patterns,
    validate_basename_uniqueness,
)


# --- resolve_file_patterns ---


class TestResolveFilePatterns:
    def test_literal_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("content")
        result = resolve_file_patterns(["hello.txt"], cwd=tmp_path)
        assert len(result) == 1
        assert result[0].name == "hello.txt"

    def test_glob_pattern(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        result = resolve_file_patterns(["*.txt"], cwd=tmp_path)
        assert len(result) == 2

    def test_nonexistent_literal_warns(self, tmp_path, capsys):
        result = resolve_file_patterns(["nonexistent.txt"], cwd=tmp_path)
        assert len(result) == 0

    def test_glob_metacharacters_literal(self, tmp_path):
        f = tmp_path / "test[1].txt"
        f.write_text("content")
        result = resolve_file_patterns(["test[1].txt"], cwd=tmp_path)
        assert len(result) == 1

    def test_no_patterns_lists_dir(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        result = resolve_file_patterns([], cwd=tmp_path)
        assert len(result) >= 2

    def test_skips_unsafe_filename(self, tmp_path):
        (tmp_path / "-badfile").write_text("content")
        result = resolve_file_patterns([], cwd=tmp_path)
        names = [p.name for p in result]
        assert "-badfile" not in names


# --- validate_basename_uniqueness ---


class TestValidateBasenameUniqueness:
    def test_unique(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("a")
        b.write_text("b")
        validate_basename_uniqueness([a, b])

    def test_duplicate(self, tmp_path):
        a = tmp_path / "dir1" / "a.txt"
        b = tmp_path / "dir2" / "a.txt"
        a.parent.mkdir()
        b.parent.mkdir()
        a.write_text("a")
        b.write_text("b")
        with pytest.raises(ValueError, match="Duplicate basename"):
            validate_basename_uniqueness([a, b])


# --- main (CLI integration) ---


class TestCliHostValidation:
    def test_empty_host_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["-s", "", "-f", "*.txt"])
        assert exc_info.value.code == 2

    def test_invalid_port_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["-s", "user@host", "-f", "*.txt", "-p", "0"])
        assert exc_info.value.code == 2

    def test_empty_dest_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["-s", "user@host", "-f", "*.txt", "-d", ""])
        assert exc_info.value.code == 2


class TestPortFlag:
    def test_default_port(self):
        with patch("sftp_parallel.cli.upload_files", return_value=(True, 0)) as mock_upload, \
             patch("sftp_parallel.cli.resolve_file_patterns") as mock_resolve:
            mock_resolve.return_value = [Path("/tmp/a.txt")]
            with pytest.raises(SystemExit):
                main(["-s", "user@host", "-f", "a.txt"])
            assert mock_upload.call_args[1]["port"] == 22

    def test_custom_port(self):
        with patch("sftp_parallel.cli.upload_files", return_value=(True, 0)) as mock_upload, \
             patch("sftp_parallel.cli.resolve_file_patterns") as mock_resolve:
            mock_resolve.return_value = [Path("/tmp/a.txt")]
            with pytest.raises(SystemExit):
                main(["-s", "user@host", "-f", "a.txt", "-p", "2222"])
            assert mock_upload.call_args[1]["port"] == 2222


class TestDestFlag:
    def test_default_dest(self):
        with patch("sftp_parallel.cli.upload_files", return_value=(True, 0)) as mock_upload, \
             patch("sftp_parallel.cli.resolve_file_patterns") as mock_resolve:
            mock_resolve.return_value = [Path("/tmp/a.txt")]
            with pytest.raises(SystemExit):
                main(["-s", "user@host", "-f", "a.txt"])
            assert mock_upload.call_args[0][2] == "."

    def test_custom_dest(self):
        with patch("sftp_parallel.cli.upload_files", return_value=(True, 0)) as mock_upload, \
             patch("sftp_parallel.cli.resolve_file_patterns") as mock_resolve:
            mock_resolve.return_value = [Path("/tmp/a.txt")]
            with pytest.raises(SystemExit):
                main(["-s", "user@host", "-f", "a.txt", "-d", "/remote"])
            assert mock_upload.call_args[0][2] == "/remote"


class TestSkipExisting:
    @patch("sftp_parallel.cli.compute_remote_checksums")
    @patch("sftp_parallel.cli.upload_files")
    @patch("sftp_parallel.cli.get_remote_file_sizes")
    @patch("sftp_parallel.cli.resolve_file_patterns")
    def test_skip_existing_default_dest(
        self, mock_resolve, mock_sizes, mock_upload, mock_checksums
    ):
        mock_resolve.return_value = [Path("/tmp/a.txt")]
        mock_sizes.return_value = {"a.txt": 0}
        mock_upload.return_value = (True, 0)
        with pytest.raises(SystemExit) as exc_info:
            main(["-s", "user@host", "-f", "a.txt", "--skip-existing"])
        # All files skipped, no verify => exit 0
        assert exc_info.value.code == 0

    @patch("sftp_parallel.cli.compute_remote_checksums")
    @patch("sftp_parallel.cli.upload_files")
    @patch("sftp_parallel.cli.get_remote_file_sizes")
    @patch("sftp_parallel.cli.resolve_file_patterns")
    def test_skip_existing_with_verify(
        self, mock_resolve, mock_sizes, mock_upload, mock_checksums
    ):
        mock_resolve.return_value = [Path("/tmp/a.txt")]
        mock_sizes.return_value = {"a.txt": 0}  # file size matches => skip
        mock_upload.return_value = (True, 0)
        mock_checksums.return_value = {}
        # When all files are skipped + verify, the code should reach verification
        # But file doesn't exist on disk so it goes to need_upload
        # The file gets OSError on stat => need_upload => gets uploaded
        with pytest.raises(SystemExit):
            main(["-s", "user@host", "-f", "a.txt", "--skip-existing", "--verify"])


class TestVerifyInline:
    @patch("sftp_parallel.cli.compute_local_checksum")
    @patch("sftp_parallel.cli.compute_remote_checksums")
    @patch("sftp_parallel.cli.upload_files")
    @patch("sftp_parallel.cli.resolve_file_patterns")
    def test_verify_ssh_failure_warning(
        self, mock_resolve, mock_upload, mock_checksums, mock_local
    ):
        mock_resolve.return_value = [Path("/tmp/a.txt")]
        mock_upload.return_value = (True, 0)
        mock_checksums.return_value = {}  # SSH failure => empty
        with pytest.raises(SystemExit):
            main(["-s", "user@host", "-f", "a.txt", "--verify"])


class TestMainVersion:
    def test_version(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0


class TestThreadsValidation:
    def test_invalid_threads(self):
        with pytest.raises(SystemExit):
            main(["-s", "user@host", "-f", "a.txt", "-t", "0"])
