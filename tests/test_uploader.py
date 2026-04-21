"""Tests for sftp_parallel.uploader."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from sftp_parallel.uploader import (
    _build_sftp_cmd,
    _cleanup_proc,
    filter_existing_files,
    get_remote_file_sizes,
    parse_ls_output,
    run_sftp,
    upload_files,
)


# --- _build_sftp_cmd ---


class TestBuildSftpCmd:
    def test_default_port(self):
        cmd = _build_sftp_cmd("user@host", 10)
        assert cmd[0] == "sftp"
        assert "Port=22" in " ".join(cmd)

    def test_custom_port(self):
        cmd = _build_sftp_cmd("user@host", 10, port=2222)
        assert "Port=2222" in " ".join(cmd)

    def test_connect_timeout(self):
        cmd = _build_sftp_cmd("user@host", 30)
        assert "ConnectTimeout=30" in " ".join(cmd)


# --- _cleanup_proc ---


class TestCleanupProc:
    def test_uses_cached_pgid(self, mock_popen_for_cleanup):
        with patch("sftp_parallel.uploader.os.killpg") as mock_killpg:
            _cleanup_proc(mock_popen_for_cleanup, pgid=5000)
            mock_killpg.assert_called_with(5000, 9)

    def test_falls_back_to_getpgid(self, mock_popen_for_cleanup):
        mock_popen_for_cleanup.pid = 12345
        with patch("sftp_parallel.uploader.os.getpgid", return_value=5000) as mock_getpgid, \
             patch("sftp_parallel.uploader.os.killpg") as mock_killpg:
            _cleanup_proc(mock_popen_for_cleanup, pgid=0)
            mock_getpgid.assert_called_with(12345)
            mock_killpg.assert_called_with(5000, 9)

    def test_catches_timeout_expired(self, mock_popen_for_cleanup):
        mock_popen_for_cleanup.wait.side_effect = subprocess.TimeoutExpired("cmd", 5)
        with patch("sftp_parallel.uploader.os.killpg"):
            _cleanup_proc(mock_popen_for_cleanup, pgid=5000)


# --- parse_ls_output ---


class TestParseLsOutput:
    def test_single_file(self):
        result = parse_ls_output(
            "-rw-r--r-- 1 user group 1234 Jan  1 12:00 file.txt\n"
        )
        assert result == {"file.txt": 1234}

    def test_empty(self):
        assert parse_ls_output("") == {}

    def test_acl_marker_plus(self):
        result = parse_ls_output(
            "-rw-r--r--+ 1 user group 5678 Jan  1 12:00 acl.txt\n"
        )
        assert result == {"acl.txt": 5678}

    def test_acl_marker_dot(self):
        result = parse_ls_output(
            "-rw-r--r--. 1 user group 9999 Jan  1 12:00 selinux.txt\n"
        )
        assert result == {"selinux.txt": 9999}

    def test_macos_extended_attrs(self):
        result = parse_ls_output(
            "-rw-r--r--@ 1 user group 4321 Jan  1 12:00 mac.txt\n"
        )
        assert result == {"mac.txt": 4321}

    def test_setuid(self):
        result = parse_ls_output(
            "-rwsr-xr-x 1 user group 1111 Jan  1 12:00 setuid.bin\n"
        )
        assert result == {"setuid.bin": 1111}

    def test_setgid(self):
        result = parse_ls_output(
            "-rw-r-sr-x 1 user group 2222 Jan  1 12:00 setgid.bin\n"
        )
        assert result == {"setgid.bin": 2222}

    def test_sticky(self):
        result = parse_ls_output(
            "-rwxr-xr-t 1 user group 3333 Jan  1 12:00 sticky.dir\n"
        )
        assert result == {"sticky.dir": 3333}

    def test_invalid_filename_skipped(self):
        # Filename with slash should be skipped by validate_filename
        result = parse_ls_output(
            "-rw-r--r-- 1 user group 1234 Jan  1 12:00 bad/file\n"
        )
        assert result == {}


# --- get_remote_file_sizes ---


class TestGetRemoteFileSizes:
    @patch("sftp_parallel.uploader.run_sftp")
    def test_success(self, mock_run):
        mock_run.return_value = (True, "-rw-r--r-- 1 user group 100 Jan  1 12:00 a.txt\n")
        result = get_remote_file_sizes("user@host", "/remote", port=22)
        assert result == {"a.txt": 100}

    @patch("sftp_parallel.uploader.run_sftp")
    def test_failure_returns_none(self, mock_run):
        mock_run.return_value = (False, "error")
        result = get_remote_file_sizes("user@host", "/remote", port=22)
        assert result is None

    def test_invalid_host(self):
        with pytest.raises(ValueError):
            get_remote_file_sizes("", "/remote", port=22)

    def test_invalid_port(self):
        with pytest.raises(ValueError):
            get_remote_file_sizes("user@host", "/remote", port=0)

    def test_invalid_remote_dir(self):
        with pytest.raises(ValueError):
            get_remote_file_sizes("user@host", "", port=22)


# --- filter_existing_files ---


class TestFilterExistingFiles:
    def test_all_need_upload(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("bb")
        result = filter_existing_files(str(tmp_path), ["a.txt", "b.txt"], {})
        assert result == ["a.txt", "b.txt"]

    def test_some_exist(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("bb")
        # a.txt has size 1, but remote says size 1 => match
        result = filter_existing_files(str(tmp_path), ["a.txt", "b.txt"], {"a.txt": 1})
        # b.txt not in remote_sizes at all => needs upload
        assert "b.txt" in result

    def test_all_exist(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        result = filter_existing_files(str(tmp_path), ["a.txt"], {"a.txt": 1})
        assert result == []


# --- upload_files ---


class TestUploadFiles:
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    def test_empty_file_list(self, mock_cleanup, mock_setup):
        success, count = upload_files("user@host", [], "/remote", port=22)
        assert success is True
        assert count == 0

    def test_invalid_host(self):
        with pytest.raises(ValueError):
            upload_files("", ["/tmp/a.txt"], "/remote", port=22)

    def test_invalid_port(self):
        with pytest.raises(ValueError):
            upload_files("user@host", ["/tmp/a.txt"], "/remote", port=0)

    def test_invalid_remote_dir(self):
        with pytest.raises(ValueError):
            upload_files("user@host", ["/tmp/a.txt"], "", port=22)

    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_worker_exception_counted_as_failure(self, mock_popen_cls, mock_setup, mock_cleanup):
        call_count = 0

        def popen_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_proc = MagicMock()
            if call_count == 1:
                mock_proc.communicate.side_effect = RuntimeError("unexpected crash")
                mock_proc.pid = 10000 + call_count
                mock_proc.returncode = 1
            else:
                mock_proc.communicate.return_value = ("", "")
                mock_proc.returncode = 0
                mock_proc.pid = 10000 + call_count
            return mock_proc

        mock_popen_cls.side_effect = popen_side_effect

        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            success, failed_count = upload_files(
                "user@host", [tmp_path, tmp_path + "_2"], "/remote", num_workers=1, port=22
            )
            assert failed_count >= 1
        finally:
            import os
            os.unlink(tmp_path)
            if os.path.exists(tmp_path + "_2"):
                os.unlink(tmp_path + "_2")

    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.os.getpgid", return_value=999)
    @patch("sftp_parallel.uploader.os.path.getsize", return_value=100)
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_progress_callback_exception_swallowed(self, mock_popen_cls, mock_getsize, mock_getpgid, mock_setup, mock_cleanup):
        """If progress_callback raises, upload should continue for other files."""
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        def bad_callback(filename):
            raise RuntimeError("callback exploded")

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_proc.pid = 12345
        mock_popen_cls.return_value = mock_proc

        try:
            success, failed = upload_files(
                "user@host", [tmp_path], "/remote",
                num_workers=1, port=22, progress_callback=bad_callback
            )
            assert success is True
            assert failed == 0
        finally:
            import os
            os.unlink(tmp_path)

    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.os.getpgid", return_value=999)
    @patch("sftp_parallel.uploader.os.path.getsize")
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_getsize_oserror_continues_upload(self, mock_popen_cls, mock_getsize, mock_getpgid, mock_setup, mock_cleanup):
        """If os.path.getsize raises OSError, file_size defaults to 0 and upload continues."""
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        mock_getsize.side_effect = OSError("cannot stat")
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_proc.pid = 12345
        mock_popen_cls.return_value = mock_proc

        try:
            success, failed = upload_files(
                "user@host", [tmp_path], "/remote", num_workers=1, port=22
            )
            assert success is True
            assert failed == 0
        finally:
            import os
            os.unlink(tmp_path)


# --- run_sftp ---


class TestRunSftp:
    def test_invalid_host(self):
        with pytest.raises(ValueError):
            run_sftp("", "cd /tmp\nbye", port=22)

    def test_invalid_port(self):
        with pytest.raises(ValueError):
            run_sftp("user@host", "cd /tmp\nbye", port=0)

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_success(self, mock_popen_cls):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("output", "")
        mock_proc.returncode = 0
        mock_proc.pid = 12345
        mock_popen_cls.return_value = mock_proc
        success, output = run_sftp("user@host", "cd /tmp\nbye")
        assert success is True
        assert "output" in output

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_sftp_binary_not_found(self, mock_popen_cls):
        mock_popen_cls.side_effect = FileNotFoundError("sftp not found")
        success, output = run_sftp("user@host", "cd /tmp\nbye")
        assert success is False
        assert "not found" in output

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_os_error(self, mock_popen_cls):
        mock_popen_cls.side_effect = OSError("permission denied")
        success, output = run_sftp("user@host", "cd /tmp\nbye")
        assert success is False
        assert "OS error" in output

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_timeout_expired(self, mock_popen_cls):
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired("sftp", 30)
        mock_proc.pid = 12345
        mock_popen_cls.return_value = mock_proc
        success, output = run_sftp("user@host", "cd /tmp\nbye")
        assert success is False
        assert "timed out" in output

    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_nonzero_returncode(self, mock_popen_cls):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "error output")
        mock_proc.returncode = 1
        mock_proc.pid = 12345
        mock_popen_cls.return_value = mock_proc
        success, output = run_sftp("user@host", "cd /tmp\nbye")
        assert success is False
        assert "error output" in output
