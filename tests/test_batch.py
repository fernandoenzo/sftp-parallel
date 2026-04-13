"""Tests for batch module."""

import unittest
from sftp_parallel.batch import sftp_escape, build_batch_commands


class TestSftpEscape(unittest.TestCase):
    def test_normal_filename(self):
        assert sftp_escape("file.txt") == "file.txt"

    def test_backslash_in_filename(self):
        assert sftp_escape("file\\backslash.txt") == "file\\\\backslash.txt"

    def test_quote_in_filename(self):
        assert sftp_escape('file"quote.txt') == 'file\\"quote.txt'

    def test_space_in_filename(self):
        assert sftp_escape("file with spaces.txt") == "file with spaces.txt"

    def test_multiple_special_chars(self):
        assert sftp_escape('path\\to"file.txt') == 'path\\\\to\\"file.txt'

    def test_empty_string(self):
        assert sftp_escape("") == ""

    def test_unicode_filename(self):
        assert sftp_escape("日本語.dat") == "日本語.dat"

    def test_consecutive_backslashes(self):
        assert sftp_escape("dir\\\\file.txt") == "dir\\\\\\\\file.txt"


class TestBuildBatchCommandsEscapePaths(unittest.TestCase):
    def test_remote_dir_with_quotes(self):
        result = build_batch_commands("/remote dir", "/local", ["a.txt"])
        lines = result.split("\n")
        assert lines[0] == 'cd "/remote dir"'

    def test_local_dir_with_special_chars(self):
        result = build_batch_commands("/remote", "/local dir", ["a.txt"])
        lines = result.split("\n")
        assert 'put -f "/local dir/a.txt"' == lines[1]

    def test_remote_dir_with_backslash(self):
        result = build_batch_commands("/remote\\path", "/local", ["a.txt"])
        lines = result.split("\n")
        assert lines[0] == 'cd "/remote\\\\path"'


class TestBuildBatchCommands(unittest.TestCase):
    def test_single_file(self):
        result = build_batch_commands("/remote", "/local", ["file1.txt"])
        lines = result.split("\n")
        assert lines[0] == 'cd "/remote"'
        assert lines[1] == 'put -f "/local/file1.txt"'
        assert lines[2] == "bye"

    def test_multiple_files(self):
        result = build_batch_commands("/remote", "/local", ["file1.txt", "file2.txt"])
        lines = result.split("\n")
        assert lines[0] == 'cd "/remote"'
        assert lines[1] == 'put -f "/local/file1.txt"'
        assert lines[2] == 'put -f "/local/file2.txt"'
        assert lines[3] == "bye"

    def test_empty_file_list(self):
        result = build_batch_commands("/remote", "/local", [])
        lines = result.split("\n")
        assert lines[0] == 'cd "/remote"'
        assert lines[1] == "bye"

    def test_escapes_special_chars_in_paths(self):
        result = build_batch_commands("/remote path", "/local", ['file"1.txt'])
        lines = result.split("\n")
        assert lines[0] == 'cd "/remote path"'
        assert lines[1] == 'put -f "/local/file\\"1.txt"'
