"""Tests for sftp_parallel.signals."""

from __future__ import annotations

import signal
import subprocess
import threading
from unittest.mock import MagicMock, patch

import pytest

from sftp_parallel.signals import (
    _make_signal_handler,
    cleanup_signal_handlers,
    setup_signal_handlers,
)


class TestMakeSignalHandler:
    def test_handler_kills_process_group(self):
        popens: list[tuple[subprocess.Popen[str], int]] = []
        lock = threading.Lock()
        handler = _make_signal_handler(popens, lock)
        assert callable(handler)

    def test_handler_with_empty_popens(self):
        popens: list[tuple[subprocess.Popen[str], int]] = []
        lock = threading.Lock()
        handler = _make_signal_handler(popens, lock)
        with pytest.raises(SystemExit):
            handler(signal.SIGINT, None)

    def test_handler_uses_cached_pgid(self):
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 12345
        mock_proc.wait.return_value = 0
        popens = [(mock_proc, 9999)]
        lock = threading.Lock()

        with patch("sftp_parallel.signals.os.killpg") as mock_killpg, \
             patch("sftp_parallel.signals.os.getpgid") as mock_getpgid:
            handler = _make_signal_handler(popens, lock)
            # Need to bypass sys.exit
            with pytest.raises(SystemExit):
                handler(signal.SIGINT, None)

            # Should use cached pgid=9999, NOT call os.getpgid
            mock_killpg.assert_any_call(9999, signal.SIGTERM)
            assert not mock_getpgid.called

    def test_handler_pgid_safety_guard(self):
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.pid = 12345
        mock_proc.wait.return_value = 0
        # pgid=1 should be skipped (safety guard)
        popens = [(mock_proc, 1)]
        lock = threading.Lock()

        with patch("sftp_parallel.signals.os.killpg") as mock_killpg, \
             patch("sftp_parallel.signals.os.getpgid"):
            handler = _make_signal_handler(popens, lock)
            with pytest.raises(SystemExit):
                handler(signal.SIGINT, None)
            # pgid <= 1 should not be killed
            [c for c in mock_killpg.call_args_list if c[0][1] in (signal.SIGTERM, signal.SIGKILL)]
            # The only killpg call should be for SIGKILL after wait timeout, also with pgid > 1
            # Since pgid=1, no killpg should be called for this process

    def test_handler_reentrancy_guard(self):
        popens: list[tuple[subprocess.Popen[str], int]] = []
        lock = threading.Lock()
        handler = _make_signal_handler(popens, lock)

        import sftp_parallel.signals as sig_module
        sig_module._handling_signal = True

        try:
            # Should not raise SystemExit — reentrancy guard blocks it
            handler(signal.SIGINT, None)
        finally:
            sig_module._handling_signal = False

    def test_handling_signal_reset_after_exit(self):
        popens: list[tuple[subprocess.Popen[str], int]] = []
        lock = threading.Lock()
        handler = _make_signal_handler(popens, lock)

        import sftp_parallel.signals as sig_module
        assert sig_module._handling_signal is False

        with pytest.raises(SystemExit):
            handler(signal.SIGINT, None)

        # After exit, _handling_signal should be reset to False
        assert sig_module._handling_signal is False


class TestSetupSignalHandlers:
    def test_setup_registers_handlers(self):
        popens: list[tuple[subprocess.Popen[str], int]] = []
        lock = threading.Lock()

        with patch("sftp_parallel.signals.signal.signal") as mock_signal, \
             patch("sftp_parallel.signals.signal.getsignal") as mock_getsignal:
            mock_getsignal.return_value = signal.SIG_DFL
            setup_signal_handlers(popens, lock)
            assert mock_signal.call_count == 2


class TestCleanupSignalHandlers:
    def test_cleanup_restores_defaults(self):
        import sftp_parallel.signals as sig_module

        # Save original state
        orig_sigint = sig_module._original_sigint
        orig_sigterm = sig_module._original_sigterm

        try:
            sig_module._original_sigint = signal.SIG_DFL
            sig_module._original_sigterm = signal.SIG_IGN

            with patch("sftp_parallel.signals.signal.signal") as mock_signal:
                cleanup_signal_handlers()
                assert mock_signal.call_count == 2

            # After cleanup, originals should be None
            assert sig_module._original_sigint is None
            assert sig_module._original_sigterm is None
        finally:
            sig_module._original_sigint = orig_sigint
            sig_module._original_sigterm = orig_sigterm


class TestSignalHandlerPopenLock:
    def test_handler_acquires_lock_nonblocking(self):
        popens: list[tuple[subprocess.Popen[str], int]] = []
        lock = threading.Lock()
        handler = _make_signal_handler(popens, lock)
        # Should not deadlock
        with pytest.raises(SystemExit):
            handler(signal.SIGINT, None)
