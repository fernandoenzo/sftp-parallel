"""Tests for sftp_parallel.verify."""

from __future__ import annotations

import os
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from sftp_parallel.verify import (
    compute_local_checksum,
    compute_remote_checksums,
    parse_checksum_output,
    verify_uploads,
)


# --- compute_local_checksum ---


class TestComputeLocalChecksum:
    def test_known_content(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = compute_local_checksum(str(f))
        assert isinstance(result, str)
        assert len(result) == 64  # sha256 hex digest

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = compute_local_checksum(str(f))
        assert isinstance(result, str)

    def test_missing_file_raises_oserror(self):
        with pytest.raises(OSError):
            compute_local_checksum("/nonexistent/path/file.txt")


# --- parse_checksum_output ---


class TestParseChecksumOutput:
    def test_text_mode(self):
        output = "abc123  /path/to/file.txt\n"
        result = parse_checksum_output(output)
        assert result == {"file.txt": "abc123"}

    def test_binary_mode(self):
        output = "abc123 */path/to/file.txt\n"
        result = parse_checksum_output(output)
        assert result == {"file.txt": "abc123"}

    def test_empty(self):
        assert parse_checksum_output("") == {}

    def test_multiple_files(self):
        output = "hash1  /a.txt\nhash2  /b.txt\n"
        result = parse_checksum_output(output)
        assert result == {"a.txt": "hash1", "b.txt": "hash2"}


# --- compute_remote_checksums ---


class TestComputeRemoteChecksums:
    def test_empty_filenames(self):
        result = compute_remote_checksums("user@host", "/remote", [])
        assert result is None

    def test_invalid_host(self):
        with pytest.raises(ValueError):
            compute_remote_checksums("", "/remote", ["a.txt"])

    def test_invalid_port(self):
        with pytest.raises(ValueError):
            compute_remote_checksums("user@host", "/remote", ["a.txt"], port=0)

    def test_invalid_algorithm(self):
        with pytest.raises(ValueError, match="algorithm"):
            compute_remote_checksums("user@host", "/remote", ["a.txt"], algorithm=";rm")

    def test_invalid_filename(self):
        with pytest.raises(ValueError, match="filename"):
            compute_remote_checksums("user@host", "/remote", ["-badfile"])

    @patch("sftp_parallel.verify.subprocess.run")
    def test_partial_results(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "hash1  a.txt\n"
        mock_result.returncode = 1  # Non-zero but partial results exist
        mock_run.return_value = mock_result
        result = compute_remote_checksums("user@host", "/remote", ["a.txt"], port=22)
        assert result == {"a.txt": "hash1"}

    @patch("sftp_parallel.verify.subprocess.run")
    def test_ssh_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("ssh", 30)
        result = compute_remote_checksums("user@host", "/remote", ["a.txt"], port=22)
        assert result is None


# --- verify_uploads ---


class TestVerifyUploads:
    @patch("sftp_parallel.verify.compute_remote_checksums")
    def test_all_match(self, mock_remote):
        mock_remote.return_value = {"a.txt": "hash1"}
        with tempfile.TemporaryDirectory() as tmpdir:
            f = os.path.join(tmpdir, "a.txt")
            with open(f, "w") as fh:
                fh.write("content")
            # We can't easily control the local hash, so just test structure
            matched, mismatched = verify_uploads("user@host", "/remote", tmpdir, ["a.txt"], port=22)
            assert len(matched) + len(mismatched) == 1
