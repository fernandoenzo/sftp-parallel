"""Tests for sftp_parallel.lib."""

from __future__ import annotations

import os
import subprocess
import tempfile
import warnings
from unittest.mock import MagicMock, patch

import pytest

from sftp_parallel.lib import (
    ChecksumResult,
    build_interactive_commands,
    compute_local_checksum,
    compute_remote_checksums,
    escape_interactive,
    get_remote_file_sizes,
    parse_checksum_output,
    parse_ls_output,
    parse_progress,
    sftp_escape,
    validate_filename,
    validate_host,
    validate_port,
    validate_remote_dir,
    _parse_formatted_bytes,
    _validate_sftp_path,
)


# --- validate_host ---


class TestValidateHost:
    def test_valid_host(self):
        validate_host("user@example.com")

    def test_valid_ipv4(self):
        validate_host("192.168.1.1")

    def test_empty_host(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_host("")

    def test_whitespace_host(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_host("   ")

    def test_control_char_host(self):
        with pytest.raises(ValueError, match="control character"):
            validate_host("user\x01host")

    def test_embedded_port_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_host("user@host:22")
            assert len(w) == 1
            assert "embedded port" in str(w[0].message)

    def test_host_with_ssh_option_injection(self):
        with pytest.raises(ValueError, match="argument-like segment"):
            validate_host("user@host -oProxyCommand=evil")

    def test_host_starting_with_dash(self):
        with pytest.raises(ValueError, match="must not start with '-'"):
            validate_host("-oProxyCommand=evil")

    def test_host_with_ssh_port_option(self):
        with pytest.raises(ValueError, match="argument-like segment"):
            validate_host("user@host -o Port=22")

    def test_host_with_embedded_port_only_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            validate_host("user@host:2222")
            assert len(w) == 1
            assert "embedded port" in str(w[0].message)


# --- validate_port ---


class TestValidatePort:
    def test_valid_port(self):
        validate_port(22)

    def test_port_range_low(self):
        with pytest.raises(ValueError, match="1-65535"):
            validate_port(0)

    def test_port_range_high(self):
        with pytest.raises(ValueError, match="1-65535"):
            validate_port(70000)

    def test_port_string_rejected(self):
        with pytest.raises(ValueError, match="integer"):
            validate_port("22")  # type: ignore[arg-type]


# --- validate_remote_dir ---


class TestValidateRemoteDir:
    def test_valid_dir(self):
        validate_remote_dir("/tmp/uploads")

    def test_empty_dir(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_remote_dir("")

    def test_newline_dir(self):
        with pytest.raises(ValueError, match="contains"):
            validate_remote_dir("/tmp/a\nb")

    def test_nul_dir(self):
        with pytest.raises(ValueError):
            validate_remote_dir("/tmp/a\x00b")

    def test_leading_dash(self):
        with pytest.raises(ValueError, match="starts with '-'"):
            validate_remote_dir("-option")

    def test_spaces_accepted(self):
        validate_remote_dir("/tmp/my uploads")


# --- validate_filename ---


class TestValidateFilename:
    def test_valid_filename(self):
        assert validate_filename("hello.txt") is True

    def test_dot(self):
        assert validate_filename(".") is False

    def test_dotdot(self):
        assert validate_filename("..") is False

    def test_empty(self):
        assert validate_filename("") is False

    def test_slash(self):
        assert validate_filename("a/b") is False

    def test_backslash(self):
        assert validate_filename("a\\b") is False

    def test_newline(self):
        assert validate_filename("a\nb") is False

    def test_nul(self):
        assert validate_filename("a\x00b") is False

    def test_leading_dash(self):
        assert validate_filename("-file") is False

    def test_double_dot_substring_accepted(self):
        assert validate_filename("file..txt") is True

    def test_long_filename(self):
        assert validate_filename("x" * 300) is False

    def test_path_component(self):
        assert validate_filename("dir/file") is False

    def test_tab(self):
        assert validate_filename("a\tb") is False

    def test_carriage_return(self):
        assert validate_filename("a\rb") is False


class TestValidateFilenameEdgeCases:
    @pytest.mark.parametrize(
        "name",
        ["hello.txt", "my file.dat", "archive.tar.gz", "...hidden", "file..txt"],
    )
    def test_valid_names(self, name):
        assert validate_filename(name) is True

    @pytest.mark.parametrize(
        "name",
        ["", ".", "..", "/", "\\", "a/b", "a\nb", "\x00", "-file"],
    )
    def test_invalid_names(self, name):
        assert validate_filename(name) is False


# --- sftp_escape ---


class TestSftpEscape:
    def test_no_escape(self):
        assert sftp_escape("/tmp/file.txt") == "/tmp/file.txt"

    def test_backslash(self):
        assert sftp_escape("C:\\Users") == "C:\\\\Users"

    def test_double_quote(self):
        assert sftp_escape('say "hello"') == 'say \\"hello\\"'


# --- escape_interactive ---


class TestEscapeInteractive:
    def test_no_escape(self):
        assert escape_interactive("/tmp/file.txt") == "/tmp/file.txt"

    def test_space(self):
        assert escape_interactive("/tmp/my file.txt") == "/tmp/my\\ file.txt"

    def test_backslash(self):
        assert escape_interactive("C:\\Users") == "C:\\\\Users"

    def test_double_quote(self):
        assert escape_interactive('say "hello"') == 'say\\ \\"hello\\"'

    def test_single_quote(self):
        assert escape_interactive("it's") == "it\\'s"

    def test_multiple_special_chars(self):
        assert escape_interactive("my file.txt") == "my\\ file.txt"

    def test_already_escaped_backslash(self):
        assert escape_interactive("a\\b") == "a\\\\b"


# --- _validate_sftp_path ---


class TestValidateSftpPath:
    def test_valid_path(self):
        _validate_sftp_path("/tmp/uploads")

    def test_control_char_rejected(self):
        with pytest.raises(ValueError, match="control character"):
            _validate_sftp_path("/tmp/a\x01b")

    def test_newline_rejected(self):
        with pytest.raises(ValueError, match="control character"):
            _validate_sftp_path("/tmp/a\nb")

    def test_custom_label(self):
        with pytest.raises(ValueError, match="remote directory"):
            _validate_sftp_path("/tmp/a\x01b", "remote directory")


# --- build_interactive_commands ---


class TestBuildInteractiveCommands:
    def test_basic_commands(self):
        cmds = build_interactive_commands("/uploads", "video.mp4")
        assert cmds[0].startswith("cd ")
        assert cmds[1].startswith("put -f ")
        assert cmds[2] == "bye"

    def test_path_with_spaces(self):
        cmds = build_interactive_commands("/my uploads", "my file.mp4")
        assert "\\ " in cmds[0]
        assert "\\ " in cmds[1]

    def test_control_char_rejected(self):
        with pytest.raises(ValueError, match="control character"):
            build_interactive_commands("/tmp/a\x01b", "file.txt")

    def test_control_char_in_file_rejected(self):
        with pytest.raises(ValueError, match="control character"):
            build_interactive_commands("/tmp", "a\nb")


# --- parse_progress ---


class TestParseProgress:
    def test_typical_progress_line(self):
        result = parse_progress("video.mp4  15%  150MB  10.5MB/s 00:01:20 ETA")
        assert result is not None
        pct, transferred = result
        assert pct == 15
        assert transferred == 150 * 1024 * 1024

    def test_progress_with_kib(self):
        result = parse_progress("file.txt  50%  1024KiB  512KB/s 00:00:05")
        assert result is not None
        pct, transferred = result
        assert pct == 50
        assert transferred == 1024 * 1024

    def test_progress_with_bytes_only(self):
        result = parse_progress("small.txt  100%  2048  1KB/s 00:00")
        assert result is not None
        pct, transferred = result
        assert pct == 100
        assert transferred == 2048

    def test_stalled_line(self):
        result = parse_progress("- stalled -")
        assert result is None or (isinstance(result, tuple) and result[0] is None)

    def test_no_match(self):
        result = parse_progress("some random text")
        assert result is None

    def test_eta_format(self):
        result = parse_progress("big.iso  75%  4.7GB  25.1MB/s --:-- ETA")
        assert result is not None
        pct, transferred = result
        assert pct == 75

    def test_progress_with_comma(self):
        result = parse_progress("data.bin  10%  1,5MB  500KB/s 00:30")
        assert result is not None
        pct, transferred = result
        assert pct == 10

    def test_progress_pib_suffix(self):
        result = parse_progress("huge.bin  5% 1PiB 500MB/s 1:00:00")
        assert result is not None
        pct, transferred = result
        assert pct == 5
        assert transferred == 1125899906842624

    def test_progress_pb_suffix(self):
        result = parse_progress("big.bin  10% 1PB 100MB/s 00:30")
        assert result is not None
        pct, transferred = result
        assert pct == 10
        assert transferred == 1125899906842624

    def test_progress_eib_suffix(self):
        result = parse_progress("data.bin  5% 1.5EiB 1GB/s 01:00:00")
        assert result is not None
        assert result[0] == 5
        assert result[1] >= 10**18

    def test_speed_with_pib(self):
        result = parse_progress("file.bin  20% 500GiB 1PiB/s 00:00")
        assert result is not None
        pct, transferred = result
        assert pct == 20


# --- _parse_formatted_bytes ---


class TestParseFormattedBytes:
    def test_bytes(self):
        assert _parse_formatted_bytes("2048") == 2048

    def test_kb(self):
        assert _parse_formatted_bytes("100KB") == 100 * 1024

    def test_kib(self):
        assert _parse_formatted_bytes("100KiB") == 100 * 1024

    def test_mb(self):
        assert _parse_formatted_bytes("1MB") == 1024 * 1024

    def test_mib(self):
        assert _parse_formatted_bytes("1MiB") == 1024 * 1024

    def test_gb(self):
        assert _parse_formatted_bytes("1GB") == 1024 ** 3

    def test_gib(self):
        assert _parse_formatted_bytes("1GiB") == 1024 ** 3

    def test_decimal_with_comma(self):
        assert _parse_formatted_bytes("1,5MB") == int(1.5 * 1024 * 1024)

    def test_zero(self):
        assert _parse_formatted_bytes("0") == 0

    def test_parse_pib(self):
        assert _parse_formatted_bytes("1PiB") == 1125899906842624

    def test_parse_pb(self):
        assert _parse_formatted_bytes("1PB") == 1125899906842624

    def test_parse_eib(self):
        assert _parse_formatted_bytes("1EiB") == 1152921504606846976

    def test_parse_eb(self):
        assert _parse_formatted_bytes("1EB") == 1152921504606846976


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
        result = parse_ls_output(
            "-rw-r--r-- 1 user group 1234 Jan  1 12:00 bad/file\n"
        )
        assert result == {}


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

    def test_all_unparseable_returns_empty(self):
        result = parse_checksum_output("garbage line 1\ngarbage line 2\n")
        assert result == {}


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


# --- compute_remote_checksums ---


class TestComputeRemoteChecksums:
    def test_empty_filenames(self):
        result = compute_remote_checksums("user@host", "/remote", [])
        assert isinstance(result, ChecksumResult)
        assert result.data is None
        assert result.error is None

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

    @patch("sftp_parallel.lib.subprocess.run")
    def test_partial_results(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = "hash1  a.txt\n"
        mock_result.returncode = 1  # Non-zero but partial results exist
        mock_run.return_value = mock_result
        result = compute_remote_checksums("user@host", "/remote", ["a.txt"], port=22)
        assert isinstance(result, ChecksumResult)
        assert result.data == {"a.txt": "hash1"}
        assert result.error is None

    @patch("sftp_parallel.lib.subprocess.run")
    def test_ssh_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("ssh", 30)
        result = compute_remote_checksums("user@host", "/remote", ["a.txt"], port=22)
        assert isinstance(result, ChecksumResult)
        assert result.data is None
        assert result.error is not None
        assert "timeout" in result.error

    @patch("sftp_parallel.lib.subprocess.run")
    def test_ssh_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        result = compute_remote_checksums("user@host", "/remote", ["a.txt"], port=22)
        assert isinstance(result, ChecksumResult)
        assert result.data is None
        assert result.error == "ssh binary not found"

    @patch("sftp_parallel.lib.subprocess.run")
    def test_oserror_permission_denied(self, mock_run):
        import errno
        mock_run.side_effect = OSError(errno.EACCES, "Permission denied")
        result = compute_remote_checksums("user@host", "/remote", ["a.txt"], port=22)
        assert isinstance(result, ChecksumResult)
        assert result.data is None
        assert result.error is not None
        assert "permission denied" in result.error.lower()


# --- get_remote_file_sizes ---


class TestGetRemoteFileSizes:
    @patch("sftp_parallel.lib.subprocess.Popen")
    def test_success(self, mock_popen_cls):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (
            "-rw-r--r-- 1 user group 100 Jan  1 12:00 a.txt\n",
            "",
        )
        mock_proc.returncode = 0
        mock_proc.pid = 12345
        mock_popen_cls.return_value = mock_proc
        result = get_remote_file_sizes("user@host", "/remote", port=22)
        assert result == {"a.txt": 100}

    @patch("sftp_parallel.lib.subprocess.Popen")
    def test_failure_returns_none(self, mock_popen_cls):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "error")
        mock_proc.returncode = 1
        mock_proc.pid = 12345
        mock_popen_cls.return_value = mock_proc
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

    @patch("sftp_parallel.lib.subprocess.Popen")
    def test_sftp_binary_not_found(self, mock_popen_cls):
        mock_popen_cls.side_effect = FileNotFoundError("sftp not found")
        result = get_remote_file_sizes("user@host", "/remote", port=22)
        assert result is None

    @patch("sftp_parallel.lib.subprocess.Popen")
    def test_timeout_returns_none(self, mock_popen_cls):
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired("sftp", 30)
        mock_proc.pid = 12345
        mock_proc.kill = MagicMock()
        mock_proc.wait = MagicMock()
        mock_popen_cls.return_value = mock_proc
        result = get_remote_file_sizes("user@host", "/remote", port=22)
        assert result is None