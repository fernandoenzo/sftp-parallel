"""Tests for the verify module."""

from __future__ import annotations

import hashlib
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import shlex

from sftp_parallel.cli import main
from sftp_parallel.verify import (
    compute_local_checksum,
    compute_remote_checksums,
    parse_checksum_output,
    verify_uploads,
)


class TestComputeLocalChecksum:
    def test_sha256_of_known_content(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        f = tmp / "hello.txt"
        f.write_text("hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert compute_local_checksum(str(f)) == expected

    def test_sha256_default_algorithm(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        f = tmp / "data.bin"
        f.write_bytes(b"\x00\x01\x02")
        assert (
            compute_local_checksum(str(f))
            == hashlib.sha256(b"\x00\x01\x02").hexdigest()
        )

    def test_md5_algorithm(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        f = tmp / "data.bin"
        f.write_bytes(b"abc")
        assert (
            compute_local_checksum(str(f), algorithm="md5")
            == hashlib.md5(b"abc").hexdigest()
        )

    def test_nonexistent_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            compute_local_checksum("/nonexistent/file.txt")

    def test_empty_file(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        f = tmp / "empty.txt"
        f.write_bytes(b"")
        assert compute_local_checksum(str(f)) == hashlib.sha256(b"").hexdigest()

    def test_large_file_chunked(self, tmp_path: object) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        f = tmp / "big.bin"
        content = b"x" * 20000
        f.write_bytes(content)
        assert compute_local_checksum(str(f)) == hashlib.sha256(content).hexdigest()


class TestParseChecksumOutput:
    def test_single_line_with_full_path(self) -> None:
        output = "abc123def456  /tmp/test/file.txt\n"
        result = parse_checksum_output(output)
        assert result == {"file.txt": "abc123def456"}

    def test_multiple_lines(self) -> None:
        output = "aaa111  /remote/a.txt\nbbb222  /remote/b.txt\n"
        result = parse_checksum_output(output)
        assert result == {"a.txt": "aaa111", "b.txt": "bbb222"}

    def test_basename_extraction(self) -> None:
        output = "deadbeef  /long/path/to/deep/dir/data.csv\n"
        result = parse_checksum_output(output)
        assert result == {"data.csv": "deadbeef"}

    def test_empty_output(self) -> None:
        assert parse_checksum_output("") == {}

    def test_whitespace_only_lines_skipped(self) -> None:
        output = "hash1  /remote/a.txt\n\n   \nhash2  /remote/b.txt\n"
        result = parse_checksum_output(output)
        assert result == {"a.txt": "hash1", "b.txt": "hash2"}

    def test_malformed_line_skipped(self) -> None:
        output = "nospaceshere\nhash1  /remote/a.txt\n"
        result = parse_checksum_output(output)
        assert result == {"a.txt": "hash1"}

    def test_single_space_not_enough(self) -> None:
        output = "hash1 /remote/a.txt\n"
        result = parse_checksum_output(output)
        assert result == {}

    def test_binary_mode_asterisk_in_filename(self) -> None:
        result = parse_checksum_output("abc123  *file.txt\n")
        assert result == {"*file.txt": "abc123"}

    def test_text_mode_hash(self) -> None:
        result = parse_checksum_output("abc123  file.txt\n")
        assert result == {"file.txt": "abc123"}

    def test_crlf_line_endings(self) -> None:
        output = "abc123  /remote/a.txt\r\nbbb456  /remote/b.txt\r\n"
        result = parse_checksum_output(output)
        assert result == {"a.txt": "abc123", "b.txt": "bbb456"}

    def test_binary_mode_asterisk_prefix(self) -> None:
        output = "abc123 *file.txt\n"
        result = parse_checksum_output(output)
        assert result == {"file.txt": "abc123"}

    def test_mixed_text_and_binary_lines(self) -> None:
        output = "aaa111  /remote/a.txt\nbbb222 *remote/b.txt\nccc333  /remote/c.txt\n"
        result = parse_checksum_output(output)
        assert result == {"a.txt": "aaa111", "b.txt": "bbb222", "c.txt": "ccc333"}


class TestComputeRemoteChecksums:
    @patch("sftp_parallel.verify.subprocess.run")
    def test_basic_remote_checksum(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc123  /remote/file.txt\n",
        )
        result = compute_remote_checksums("user@host", "/remote", ["file.txt"])
        assert result == {"file.txt": "abc123"}
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ssh"
        assert "user@host" in cmd
        assert "sha256sum" in cmd[-1]

    def test_empty_filenames_returns_empty(self) -> None:
        result = compute_remote_checksums("user@host", "/remote", [])
        assert result == {}

    @patch("sftp_parallel.verify.subprocess.run")
    def test_ssh_failure_returns_empty(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = compute_remote_checksums("user@host", "/remote", ["a.txt"])
        assert result == {}

    @patch("sftp_parallel.verify.subprocess.run")
    def test_file_not_found_returns_empty(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = FileNotFoundError
        result = compute_remote_checksums("user@host", "/remote", ["a.txt"])
        assert result == {}

    @patch("sftp_parallel.verify.subprocess.run")
    def test_timeout_returns_empty(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ssh", timeout=30)
        result = compute_remote_checksums("user@host", "/remote", ["a.txt"])
        assert result == {}

    @patch("sftp_parallel.verify.subprocess.run")
    def test_os_error_returns_empty(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = OSError("broken pipe")
        result = compute_remote_checksums("user@host", "/remote", ["a.txt"])
        assert result == {}

    @patch("sftp_parallel.verify.subprocess.run")
    def test_multiple_files_in_command(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="h1  /remote/a.txt\nh2  /remote/b.txt\n",
        )
        result = compute_remote_checksums("user@host", "/remote", ["a.txt", "b.txt"])
        assert result == {"a.txt": "h1", "b.txt": "h2"}
        remote_cmd = mock_run.call_args[0][0][-1]
        # shlex.quote leaves safe names unquoted, only quotes dangerous ones
        assert "a.txt" in remote_cmd
        assert "b.txt" in remote_cmd

    @patch("sftp_parallel.verify.subprocess.run")
    def test_custom_algorithm(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="h1  /remote/a.txt\n",
        )
        compute_remote_checksums("user@host", "/remote", ["a.txt"], algorithm="md5")
        remote_cmd = mock_run.call_args[0][0][-1]
        assert "md5sum" in remote_cmd

    @patch("sftp_parallel.verify.subprocess.run")
    def test_batchmode_yes_in_ssh_args(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        compute_remote_checksums("user@host", "/remote", ["a.txt"])
        cmd = mock_run.call_args[0][0]
        assert "BatchMode=yes" in cmd

    @patch("sftp_parallel.verify.subprocess.run")
    def test_filename_with_spaces_escaped(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="h1  /remote/file with spaces.txt\n"
        )
        compute_remote_checksums("user@host", "/remote", ["file with spaces.txt"])
        remote_cmd = mock_run.call_args[0][0][-1]
        assert shlex.quote("file with spaces.txt") in remote_cmd
        assert '"file with spaces.txt"' not in remote_cmd

    @patch("sftp_parallel.verify.subprocess.run")
    def test_filename_with_semicolon_escaped(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        compute_remote_checksums("user@host", "/remote", ["file;rm -rf /.txt"])
        remote_cmd = mock_run.call_args[0][0][-1]
        assert shlex.quote("file;rm -rf /.txt") in remote_cmd
        assert ";rm" not in remote_cmd or "'" in remote_cmd

    @patch("sftp_parallel.verify.subprocess.run")
    def test_filename_with_command_substitution_escaped(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        compute_remote_checksums("user@host", "/remote", ["file$(whoami).txt"])
        remote_cmd = mock_run.call_args[0][0][-1]
        assert shlex.quote("file$(whoami).txt") in remote_cmd
        assert "$(" not in remote_cmd or "'" in remote_cmd.split("$(")[0]

    @patch("sftp_parallel.verify.subprocess.run")
    def test_filename_with_single_quote_escaped(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        compute_remote_checksums("user@host", "/remote", ["file'quoted.txt"])
        remote_cmd = mock_run.call_args[0][0][-1]
        assert shlex.quote("file'quoted.txt") in remote_cmd

    @patch("sftp_parallel.verify.subprocess.run")
    def test_filename_with_backslash_escaped(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        compute_remote_checksums("user@host", "/remote", ["file\\backslash.txt"])
        remote_cmd = mock_run.call_args[0][0][-1]
        assert shlex.quote("file\\backslash.txt") in remote_cmd

    @patch("sftp_parallel.verify.subprocess.run")
    def test_filename_with_double_quote_escaped(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        compute_remote_checksums("user@host", "/remote", ['file"quote.txt'])
        remote_cmd = mock_run.call_args[0][0][-1]
        assert shlex.quote('file"quote.txt') in remote_cmd
        assert '"file"quote.txt"' not in remote_cmd

    @patch("sftp_parallel.verify.subprocess.run")
    def test_remote_dir_with_shell_metachar_escaped(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        compute_remote_checksums("user@host", "/remote;rm -rf /", ["a.txt"])
        remote_cmd = mock_run.call_args[0][0][-1]
        assert shlex.quote("/remote;rm -rf /") in remote_cmd

    @patch("sftp_parallel.verify.subprocess.run")
    def test_multiple_malicious_filenames_all_escaped(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        bad_files = [
            "file with spaces.txt",
            "file;rm.txt",
            "file$(cmd).txt",
            "file'q.txt",
        ]
        compute_remote_checksums("user@host", "/remote", bad_files)
        remote_cmd = mock_run.call_args[0][0][-1]
        for f in bad_files:
            assert shlex.quote(f) in remote_cmd


class TestVerifyUploads:
    @patch("sftp_parallel.verify.compute_remote_checksums")
    @patch("sftp_parallel.verify.compute_local_checksum")
    def test_all_matched(
        self, mock_local: MagicMock, mock_remote: MagicMock, tmp_path: object
    ) -> None:
        mock_local.return_value = "abc123"
        mock_remote.return_value = {"a.txt": "abc123", "b.txt": "def456"}
        matched, mismatched = verify_uploads(
            "user@host", "/remote", str(tmp_path), ["a.txt", "b.txt"]
        )
        assert matched == ["a.txt"]
        assert mismatched == ["b.txt"]

    @patch("sftp_parallel.verify.compute_remote_checksums")
    @patch("sftp_parallel.verify.compute_local_checksum")
    def test_all_matched_all_match(
        self, mock_local: MagicMock, mock_remote: MagicMock, tmp_path: object
    ) -> None:
        mock_local.return_value = "same_hash"
        mock_remote.return_value = {"a.txt": "same_hash", "b.txt": "same_hash"}
        matched, mismatched = verify_uploads(
            "user@host", "/remote", str(tmp_path), ["a.txt", "b.txt"]
        )
        assert matched == ["a.txt", "b.txt"]
        assert mismatched == []

    @patch("sftp_parallel.verify.compute_remote_checksums")
    @patch("sftp_parallel.verify.compute_local_checksum")
    def test_all_mismatched(
        self, mock_local: MagicMock, mock_remote: MagicMock, tmp_path: object
    ) -> None:
        mock_local.return_value = "local_hash"
        mock_remote.return_value = {"a.txt": "remote_hash"}
        matched, mismatched = verify_uploads(
            "user@host", "/remote", str(tmp_path), ["a.txt"]
        )
        assert matched == []
        assert mismatched == ["a.txt"]

    @patch("sftp_parallel.verify.compute_remote_checksums")
    @patch("sftp_parallel.verify.compute_local_checksum")
    def test_missing_remote_treated_as_mismatched(
        self, mock_local: MagicMock, mock_remote: MagicMock, tmp_path: object
    ) -> None:
        mock_local.return_value = "abc123"
        mock_remote.return_value = {}
        matched, mismatched = verify_uploads(
            "user@host", "/remote", str(tmp_path), ["a.txt", "b.txt"]
        )
        assert matched == []
        assert mismatched == ["a.txt", "b.txt"]

    @patch("sftp_parallel.verify.compute_remote_checksums")
    @patch("sftp_parallel.verify.compute_local_checksum")
    def test_local_checksum_different_per_file(
        self, mock_local: MagicMock, mock_remote: MagicMock, tmp_path: object
    ) -> None:
        mock_local.side_effect = ["hash_a", "hash_b"]
        mock_remote.return_value = {"a.txt": "hash_a", "b.txt": "hash_b_diff"}
        matched, mismatched = verify_uploads(
            "user@host", "/remote", str(tmp_path), ["a.txt", "b.txt"]
        )
        assert matched == ["a.txt"]
        assert mismatched == ["b.txt"]

    @patch("sftp_parallel.verify.compute_remote_checksums")
    @patch("sftp_parallel.verify.compute_local_checksum")
    def test_empty_file_list(
        self, mock_local: MagicMock, mock_remote: MagicMock, tmp_path: object
    ) -> None:
        mock_remote.return_value = {}
        matched, mismatched = verify_uploads("user@host", "/remote", str(tmp_path), [])
        assert matched == []
        assert mismatched == []
        mock_local.assert_not_called()

    @patch("sftp_parallel.verify.compute_remote_checksums")
    @patch("sftp_parallel.verify.compute_local_checksum")
    def test_local_file_not_found_treated_as_mismatched(
        self, mock_local: MagicMock, mock_remote: MagicMock, tmp_path: object
    ) -> None:
        mock_local.side_effect = FileNotFoundError
        mock_remote.return_value = {"a.txt": "some_hash"}
        matched, mismatched = verify_uploads(
            "user@host", "/remote", str(tmp_path), ["a.txt"]
        )
        assert matched == []
        assert mismatched == ["a.txt"]

    @patch("sftp_parallel.verify.compute_remote_checksums")
    @patch("sftp_parallel.verify.compute_local_checksum")
    def test_passes_algorithm_and_timeout(
        self, mock_local: MagicMock, mock_remote: MagicMock, tmp_path: object
    ) -> None:
        mock_local.return_value = "abc123"
        mock_remote.return_value = {"a.txt": "abc123"}
        verify_uploads(
            "user@host",
            "/remote",
            str(tmp_path),
            ["a.txt"],
            algorithm="sha256",
            timeout=30,
        )
        mock_remote.assert_called_once_with(
            "user@host", "/remote", ["a.txt"], algorithm="sha256", timeout=30
        )

    @patch("sftp_parallel.verify.compute_remote_checksums")
    @patch("sftp_parallel.verify.compute_local_checksum")
    def test_passes_algorithm_to_local_checksum(
        self, mock_local: MagicMock, mock_remote: MagicMock, tmp_path: object
    ) -> None:
        mock_local.return_value = "abc123"
        mock_remote.return_value = {"a.txt": "abc123"}
        verify_uploads(
            "user@host",
            "/remote",
            str(tmp_path),
            ["a.txt"],
            algorithm="md5",
        )
        mock_local.assert_called_with(
            os.path.join(str(tmp_path), "a.txt"), algorithm="md5"
        )


class TestComputeRemoteChecksumsTimeout:
    @patch("sftp_parallel.verify.subprocess.run")
    def test_ssh_timeout_is_three_times_connect_timeout(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="h1  /remote/a.txt\n")
        compute_remote_checksums("user@host", "/remote", ["a.txt"], timeout=10)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["timeout"] == 30


class TestVerifyIntegration:
    @patch("sftp_parallel.cli.verify_uploads")
    @patch("sftp_parallel.cli.upload_files")
    def test_verify_flag_triggers_verification(
        self, mock_upload_files: MagicMock, mock_verify: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_upload_files.return_value = (True, 0)
        mock_verify.return_value = (["test.txt"], [])

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "user@host:/remote", "--verify"])

        assert exc_info.value.code == 0
        mock_verify.assert_called_once()

    @patch("sftp_parallel.cli.verify_uploads")
    @patch("sftp_parallel.cli.upload_files")
    def test_verify_mismatch_exits_one(
        self, mock_upload_files: MagicMock, mock_verify: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_upload_files.return_value = (True, 0)
        mock_verify.return_value = ([], ["test.txt"])

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "user@host:/remote", "--verify"])

        assert exc_info.value.code == 1

    @patch("sftp_parallel.cli.verify_uploads")
    @patch("sftp_parallel.cli.upload_files")
    def test_verify_not_called_without_flag(
        self, mock_upload_files: MagicMock, mock_verify: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_upload_files.return_value = (True, 0)

        with pytest.raises(SystemExit):
            main(["upload", str(tmp), "user@host:/remote"])

        mock_verify.assert_not_called()

    @patch("sftp_parallel.cli.verify_uploads")
    @patch("sftp_parallel.cli.upload_files")
    def test_verify_all_matched_exits_zero(
        self, mock_upload_files: MagicMock, mock_verify: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_upload_files.return_value = (True, 0)
        mock_verify.return_value = (["test.txt"], [])

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "user@host:/remote", "--verify"])

        assert exc_info.value.code == 0

    @patch("sftp_parallel.cli.verify_uploads")
    @patch("sftp_parallel.cli.upload_files")
    def test_verify_mixed_results(
        self, mock_upload_files: MagicMock, mock_verify: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "a.txt").write_text("aaa")
        (tmp / "b.txt").write_text("bbb")
        mock_upload_files.return_value = (True, 0)
        mock_verify.return_value = (["a.txt"], ["b.txt"])

        with pytest.raises(SystemExit) as exc_info:
            main(["upload", str(tmp), "user@host:/remote", "--verify"])

        assert exc_info.value.code == 1

    @patch("sftp_parallel.cli.verify_uploads")
    @patch("sftp_parallel.cli.upload_files")
    def test_verify_not_called_on_failed_upload(
        self, mock_upload_files: MagicMock, mock_verify: MagicMock, tmp_path: object
    ) -> None:
        tmp = tmp_path  # type: ignore[attr-defined]
        (tmp / "test.txt").write_text("content")
        mock_upload_files.return_value = (False, 1)

        with pytest.raises(SystemExit):
            main(["upload", str(tmp), "user@host:/remote", "--verify"])

        mock_verify.assert_not_called()
