"""Shared test fixtures for sftp-parallel test suite."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_popen_for_cleanup():
    """Popen mock for cleanup tests: stdin/stdout/stderr=None, returncode not set."""
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.stdin = None
    mock_proc.stdout = None
    mock_proc.stderr = None
    mock_proc.wait.return_value = 0
    return mock_proc


@pytest.fixture
def mock_popen_success():
    """Popen mock for successful sftp: returncode=0, pid=12345, empty output."""
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = ("", "")
    mock_proc.returncode = 0
    mock_proc.pid = 12345
    return mock_proc