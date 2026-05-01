"""Tests for sftp_parallel.batch."""

from __future__ import annotations

import warnings

import pytest

from sftp_parallel.batch import (
    build_batch_commands,
    sftp_escape,
    validate_filename,
    validate_host,
    validate_port,
    validate_remote_dir,
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


# --- build_batch_commands ---


class TestBuildBatchCommands:
    def test_single_file(self):
        result = build_batch_commands("/remote", ["/local/file.txt"])
        assert 'cd "/remote"' in result
        assert 'put -f "/local/file.txt"' in result
        assert result.endswith("bye")

    def test_multiple_files(self):
        result = build_batch_commands("/remote", ["/local/a.txt", "/local/b.txt"])
        assert result.count("put -f") == 2

    def test_newline_in_remote_dir_rejected(self):
        with pytest.raises(ValueError, match="contains"):
            build_batch_commands("/tmp/a\nb", ["/local/f.txt"])

    def test_newline_in_file_path_rejected(self):
        with pytest.raises(ValueError, match="contains"):
            build_batch_commands("/remote", ["/tmp/a\nb/f.txt"])

    def test_nul_in_remote_dir_rejected(self):
        with pytest.raises(ValueError, match="contains"):
            build_batch_commands("/tmp/a\x00b", ["/local/f.txt"])

    def test_nul_in_file_path_rejected(self):
        with pytest.raises(ValueError, match="contains"):
            build_batch_commands("/remote", ["/tmp/a\x00b/f.txt"])

    def test_escape_needed(self):
        result = build_batch_commands('/remote "dir"', ['/local/a\\"file'])
        assert '\\"' in result or '\\\\' in result


class TestBuildBatchCommandsMultiSource:
    def test_three_files(self):
        result = build_batch_commands("/remote", ["/a", "/b", "/c"])
        lines = result.split("\n")
        assert lines[0].startswith("cd")
        assert lines[-1] == "bye"
        put_lines = [line for line in lines if line.startswith("put")]
        assert len(put_lines) == 3
