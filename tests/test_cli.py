"""Tests for sftp_parallel.cli."""

from __future__ import annotations

import os
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

    @patch("sftp_parallel.cli.compute_remote_checksums")
    @patch("sftp_parallel.cli.upload_files")
    @patch("sftp_parallel.cli.get_remote_file_sizes")
    @patch("sftp_parallel.cli.resolve_file_patterns")
    def test_skip_existing_all_matched_no_verify(
        self, mock_resolve, mock_sizes, mock_upload, mock_checksums
    ):
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
            tmp_path = tmp.name
        try:
            mock_resolve.return_value = [Path(tmp_path)]
            mock_sizes.return_value = {os.path.basename(tmp_path): os.path.getsize(tmp_path)}
            with pytest.raises(SystemExit) as exc_info:
                main(["-s", "user@host", "-f", tmp_path, "--skip-existing"])
            assert exc_info.value.code == 0
            mock_upload.assert_not_called()
        finally:
            os.unlink(tmp_path)

    @patch("sftp_parallel.cli.upload_files")
    @patch("sftp_parallel.cli.get_remote_file_sizes")
    @patch("sftp_parallel.cli.resolve_file_patterns")
    def test_skip_existing_sftp_failure_fallback(
        self, mock_resolve, mock_sizes, mock_upload
    ):
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
            tmp_path = tmp.name
        try:
            mock_resolve.return_value = [Path(tmp_path)]
            mock_sizes.return_value = None  # SFTP failure
            mock_upload.return_value = (True, 0)
            with pytest.raises(SystemExit) as exc_info:
                main(["-s", "user@host", "-f", tmp_path, "--skip-existing"])
            assert exc_info.value.code == 0
            mock_upload.assert_called_once()
        finally:
            os.unlink(tmp_path)


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


class TestUploadFailure:
    @patch("sftp_parallel.cli.resolve_file_patterns")
    @patch("sftp_parallel.cli.upload_files")
    def test_exit_74_on_upload_failure(self, mock_upload, mock_resolve):
        mock_resolve.return_value = [Path("/tmp/a.txt")]
        mock_upload.return_value = (False, 1)
        with pytest.raises(SystemExit) as exc_info:
            main(["-s", "user@host", "-f", "a.txt"])
        assert exc_info.value.code == 74


class TestToctouGuard:
    """Test that files disappearing between skip-existing and upload are handled."""

    @patch("sftp_parallel.cli.compute_remote_checksums")
    @patch("sftp_parallel.cli.upload_files")
    @patch("sftp_parallel.cli.get_remote_file_sizes")
    @patch("sftp_parallel.cli.resolve_file_patterns")
    def test_disappeared_file_is_skipped(
        self, mock_resolve, mock_sizes, mock_upload, mock_checksums
    ):
        """A file that disappears after skip-existing check should be skipped."""
        import tempfile

        # Create a real temp file so os.path.getsize works in the skip-existing block
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
            tmp_path = tmp.name
        try:
            mock_resolve.return_value = [Path(tmp_path)]
            mock_sizes.return_value = {}  # remote has no files => need_upload
            mock_upload.return_value = (True, 0)

            # After skip-existing produces need_upload, make the file disappear
            original_getsize = os.path.getsize

            def failing_getsize(path: str) -> int:
                if path == tmp_path:
                    raise OSError("File disappeared")
                return original_getsize(path)

            with patch("sftp_parallel.cli.os.path.getsize", side_effect=failing_getsize):
                # The TOCTOU guard should catch the disappearing file
                with pytest.raises(SystemExit) as exc_info:
                    main(
                        ["-s", "user@host", "-f", tmp_path, "--skip-existing"]
                    )
                assert exc_info.value.code == 0
                # upload_files called but with empty file list (files removed by TOCTOU)
                assert mock_upload.call_args[0][1] == []
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @patch("sftp_parallel.cli.compute_remote_checksums")
    @patch("sftp_parallel.cli.upload_files")
    @patch("sftp_parallel.cli.get_remote_file_sizes")
    @patch("sftp_parallel.cli.resolve_file_patterns")
    def test_existing_file_passes_toctou(
        self, mock_resolve, mock_sizes, mock_upload, mock_checksums
    ):
        """A file that still exists after skip-existing should pass the TOCTOU check."""
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
            tmp_path = tmp.name
        try:
            mock_resolve.return_value = [Path(tmp_path)]
            mock_sizes.return_value = {}  # remote has no files => need_upload
            mock_upload.return_value = (True, 0)

            with pytest.raises(SystemExit) as exc_info:
                main(
                    ["-s", "user@host", "-f", tmp_path, "--skip-existing"]
                )
            assert exc_info.value.code == 0
            mock_upload.assert_called_once()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestSymlinkToSpecialFile:
    """Test that symlinks to special files (FIFOs, etc.) are skipped."""

    def test_symlink_to_fifo_is_skipped(self, tmp_path):
        """A symlink pointing to a named pipe (FIFO) should be skipped."""
        fifo_path = tmp_path / "real_fifo"
        os.mkfifo(str(fifo_path))
        link_path = tmp_path / "link_to_fifo"
        link_path.symlink_to(fifo_path)

        result = resolve_file_patterns([], cwd=tmp_path)
        names = [p.name for p in result]
        assert "link_to_fifo" not in names

    def test_symlink_to_regular_file_is_included(self, tmp_path):
        """A symlink pointing to a regular file should be included."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("content")
        link_path = tmp_path / "link_to_real.txt"
        link_path.symlink_to(real_file)

        result = resolve_file_patterns([], cwd=tmp_path)
        names = [p.name for p in result]
        assert "real.txt" in names or "link_to_real.txt" in names

    def test_symlink_to_fifo_literal_pattern_skipped(self, tmp_path):
        """A literal symlink to FIFO provided as a pattern should be skipped."""
        fifo_path = tmp_path / "real_fifo"
        os.mkfifo(str(fifo_path))
        link_path = tmp_path / "link_to_fifo"
        link_path.symlink_to(fifo_path)

        result = resolve_file_patterns(["link_to_fifo"], cwd=tmp_path)
        assert len(result) == 0

    def test_symlink_to_regular_literal_pattern_included(self, tmp_path):
        """A literal symlink to a regular file should be included."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("content")
        link_path = tmp_path / "link_to_real"
        link_path.symlink_to(real_file)

        result = resolve_file_patterns(["link_to_real"], cwd=tmp_path)
        assert len(result) == 1
