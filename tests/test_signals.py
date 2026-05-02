"""Tests for sftp_parallel.signals."""

from __future__ import annotations

import signal
import threading
from unittest.mock import MagicMock, patch

import pytest

from sftp_parallel.signals import (
    _make_signal_handler,
    cleanup_signal_handlers,
    setup_signal_handlers,
)


@pytest.fixture(autouse=True)
def _reset_handling_flags():
    import sftp_parallel.signals as sig_module
    sig_module._handling_sigint = False
    sig_module._handling_sigterm = False


class TestMakeSignalHandler:
    def test_handler_is_callable(self):
        workers: list[MagicMock] = []
        lock = threading.Lock()
        handler = _make_signal_handler(workers, lock)
        assert callable(handler)

    def test_handler_with_empty_workers(self):
        workers: list[MagicMock] = []
        lock = threading.Lock()
        handler = _make_signal_handler(workers, lock)
        with pytest.raises(SystemExit):
            handler(signal.SIGINT, None)

    def test_handler_terminates_workers(self):
        mock_worker = MagicMock()
        workers = [mock_worker]
        lock = threading.Lock()

        handler = _make_signal_handler(workers, lock)
        with pytest.raises(SystemExit):
            handler(signal.SIGINT, None)

        mock_worker.terminate.assert_called_once()

    def test_handler_reentrancy_guard(self):
        workers: list[MagicMock] = []
        lock = threading.Lock()
        handler = _make_signal_handler(workers, lock)

        import sftp_parallel.signals as sig_module
        sig_module._handling_sigint = True

        # Should not raise SystemExit — reentrancy guard blocks it
        handler(signal.SIGINT, None)


class TestSetupSignalHandlers:
    def test_setup_registers_handlers(self):
        workers: list[MagicMock] = []
        lock = threading.Lock()

        with patch("sftp_parallel.signals.signal.signal") as mock_signal, \
             patch("sftp_parallel.signals.signal.getsignal") as mock_getsignal:
            mock_getsignal.return_value = signal.SIG_DFL
            setup_signal_handlers(workers, lock)
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


class TestSignalHandlerWorkerLock:
    def test_handler_acquires_lock_nonblocking(self):
        workers: list[MagicMock] = []
        lock = threading.Lock()
        handler = _make_signal_handler(workers, lock)
        # Should not deadlock
        with pytest.raises(SystemExit):
            handler(signal.SIGINT, None)

    def test_sigint_during_sigint_is_ignored(self):
        workers: list[MagicMock] = []
        lock = threading.Lock()
        handler = _make_signal_handler(workers, lock)

        import sftp_parallel.signals as sig_module
        sig_module._handling_sigint = True

        handler(signal.SIGINT, None)

    def test_sigterm_not_ignored_during_sigint(self):
        workers: list[MagicMock] = []
        lock = threading.Lock()
        handler = _make_signal_handler(workers, lock)

        import sftp_parallel.signals as sig_module
        sig_module._handling_sigint = True

        with pytest.raises(SystemExit):
            handler(signal.SIGTERM, None)

    def test_sigterm_during_sigterm_is_ignored(self):
        workers: list[MagicMock] = []
        lock = threading.Lock()
        handler = _make_signal_handler(workers, lock)

        import sftp_parallel.signals as sig_module
        sig_module._handling_sigterm = True

        handler(signal.SIGTERM, None)