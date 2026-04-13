"""Tests for the signal handling module."""

from __future__ import annotations

import signal
import unittest
from unittest.mock import MagicMock, call, patch

import pytest

from sftp_parallel.signals import (
    _make_signal_handler,
    cleanup_signal_handlers,
    setup_signal_handlers,
)


class TestMakeSignalHandler(unittest.TestCase):
    def test_handler_kills_process_group_with_sigterm(self) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        handler = _make_signal_handler([mock_proc])
        with (
            patch("sftp_parallel.signals.os.killpg") as mock_killpg,
            patch("sftp_parallel.signals.os.getpgid", return_value=12345),
            patch("sftp_parallel.signals.console"),
            pytest.raises(SystemExit),
        ):
            handler(signal.SIGINT, None)
        mock_killpg.assert_called_with(12345, signal.SIGTERM)

    def test_handler_exits_130_on_sigint(self) -> None:
        handler = _make_signal_handler([])
        with (
            patch("sftp_parallel.signals.console"),
            pytest.raises(SystemExit) as exc_info,
        ):
            handler(signal.SIGINT, None)
        assert exc_info.value.code == 130

    def test_handler_exits_143_on_sigterm(self) -> None:
        handler = _make_signal_handler([])
        with (
            patch("sftp_parallel.signals.console"),
            pytest.raises(SystemExit) as exc_info,
        ):
            handler(signal.SIGTERM, None)
        assert exc_info.value.code == 143

    def test_handler_prints_interrupted_message(self) -> None:
        handler = _make_signal_handler([])
        with (
            patch("sftp_parallel.signals.console") as mock_console,
            pytest.raises(SystemExit),
        ):
            handler(signal.SIGINT, None)
        mock_console.print.assert_called_with("[bold red]Interrupted[/bold red]")

    def test_handler_ignores_process_lookup_error_on_killpg(self) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        with (
            patch("sftp_parallel.signals.os.getpgid", return_value=99999),
            patch("sftp_parallel.signals.os.killpg", side_effect=ProcessLookupError),
            patch("sftp_parallel.signals.console"),
            pytest.raises(SystemExit),
        ):
            handler = _make_signal_handler([mock_proc])
            handler(signal.SIGINT, None)

    def test_handler_prints_interrupted_message_on_sigterm(self) -> None:
        handler = _make_signal_handler([])
        with (
            patch("sftp_parallel.signals.console") as mock_console,
            pytest.raises(SystemExit),
        ):
            handler(signal.SIGTERM, None)
        mock_console.print.assert_called_with("[bold red]Interrupted[/bold red]")

    def test_handler_ignores_oserror_on_killpg(self) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        with (
            patch("sftp_parallel.signals.os.getpgid", return_value=99999),
            patch("sftp_parallel.signals.os.killpg", side_effect=OSError),
            patch("sftp_parallel.signals.console"),
            pytest.raises(SystemExit),
        ):
            handler = _make_signal_handler([mock_proc])
            handler(signal.SIGINT, None)

    def test_handler_waits_for_processes_after_sigterm(self) -> None:
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        handler = _make_signal_handler([mock_proc])
        with (
            patch("sftp_parallel.signals.os.killpg"),
            patch("sftp_parallel.signals.os.getpgid", return_value=12345),
            patch("sftp_parallel.signals.console"),
            pytest.raises(SystemExit),
        ):
            handler(signal.SIGINT, None)
        mock_proc.wait.assert_called_with(timeout=2)

    def test_handler_sends_sigkill_after_timeout(self) -> None:
        import subprocess

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="sftp", timeout=2)
        handler = _make_signal_handler([mock_proc])
        with (
            patch("sftp_parallel.signals.os.killpg") as mock_killpg,
            patch("sftp_parallel.signals.os.getpgid", return_value=12345),
            patch("sftp_parallel.signals.console"),
            pytest.raises(SystemExit),
        ):
            handler(signal.SIGINT, None)
        sigterm_call = call(12345, signal.SIGTERM)
        sigkill_call = call(12345, signal.SIGKILL)
        mock_killpg.assert_has_calls([sigterm_call, sigkill_call])

    def test_handler_handles_multiple_processes(self) -> None:
        proc1 = MagicMock()
        proc1.pid = 111
        proc2 = MagicMock()
        proc2.pid = 222
        handler = _make_signal_handler([proc1, proc2])
        with (
            patch("sftp_parallel.signals.os.killpg") as mock_killpg,
            patch("sftp_parallel.signals.os.getpgid", side_effect=[111, 222, 111, 222]),
            patch("sftp_parallel.signals.console"),
            pytest.raises(SystemExit),
        ):
            handler(signal.SIGTERM, None)
        assert mock_killpg.call_count >= 2


class TestSetupSignalHandlers(unittest.TestCase):
    @patch("sftp_parallel.signals.signal.signal")
    @patch("sftp_parallel.signals.signal.getsignal", return_value=signal.SIG_DFL)
    def test_registers_sigint_handler(
        self, mock_getsignal: MagicMock, mock_signal: MagicMock
    ) -> None:
        mock_proc = MagicMock()
        setup_signal_handlers([mock_proc])
        sigint_calls = [
            c for c in mock_signal.call_args_list if c[0][0] == signal.SIGINT
        ]
        assert len(sigint_calls) == 1

    @patch("sftp_parallel.signals.signal.signal")
    @patch("sftp_parallel.signals.signal.getsignal", return_value=signal.SIG_DFL)
    def test_registers_sigterm_handler(
        self, mock_getsignal: MagicMock, mock_signal: MagicMock
    ) -> None:
        mock_proc = MagicMock()
        setup_signal_handlers([mock_proc])
        sigterm_calls = [
            c for c in mock_signal.call_args_list if c[0][0] == signal.SIGTERM
        ]
        assert len(sigterm_calls) == 1

    @patch("sftp_parallel.signals.signal.signal")
    @patch("sftp_parallel.signals.signal.getsignal", return_value=signal.SIG_DFL)
    def test_stores_original_handlers(
        self, mock_getsignal: MagicMock, mock_signal: MagicMock
    ) -> None:
        cleanup_signal_handlers()
        setup_signal_handlers([MagicMock()])
        mock_getsignal.assert_any_call(signal.SIGINT)
        mock_getsignal.assert_any_call(signal.SIGTERM)

    @patch("sftp_parallel.signals.signal.signal")
    @patch("sftp_parallel.signals.signal.getsignal", return_value=signal.SIG_IGN)
    def test_custom_handler_replaces_previous(
        self, mock_getsignal: MagicMock, mock_signal: MagicMock
    ) -> None:
        setup_signal_handlers([MagicMock()])
        assert mock_signal.call_count == 2


class TestCleanupSignalHandlers(unittest.TestCase):
    @patch("sftp_parallel.signals.signal.signal")
    @patch("sftp_parallel.signals.signal.getsignal", return_value=signal.SIG_DFL)
    def test_restores_sigint(
        self, mock_getsignal: MagicMock, mock_signal: MagicMock
    ) -> None:
        cleanup_signal_handlers()
        setup_signal_handlers([MagicMock()])
        mock_signal.reset_mock()
        cleanup_signal_handlers()
        sigint_calls = [
            c for c in mock_signal.call_args_list if c[0][0] == signal.SIGINT
        ]
        assert len(sigint_calls) == 1

    @patch("sftp_parallel.signals.signal.signal")
    @patch("sftp_parallel.signals.signal.getsignal", return_value=signal.SIG_DFL)
    def test_restores_sigterm(
        self, mock_getsignal: MagicMock, mock_signal: MagicMock
    ) -> None:
        cleanup_signal_handlers()
        setup_signal_handlers([MagicMock()])
        mock_signal.reset_mock()
        cleanup_signal_handlers()
        sigterm_calls = [
            c for c in mock_signal.call_args_list if c[0][0] == signal.SIGTERM
        ]
        assert len(sigterm_calls) == 1

    @patch("sftp_parallel.signals.signal.signal")
    @patch("sftp_parallel.signals.signal.getsignal", return_value=signal.SIG_DFL)
    def test_idempotent_without_setup(
        self, mock_getsignal: MagicMock, mock_signal: MagicMock
    ) -> None:
        cleanup_signal_handlers()
        cleanup_signal_handlers()
        # Should not call signal.signal when originals are None
        mock_signal.assert_not_called()

    @patch("sftp_parallel.signals.signal.signal")
    @patch("sftp_parallel.signals.signal.getsignal", return_value=signal.SIG_DFL)
    def test_cleanup_clears_stored_handlers(
        self, mock_getsignal: MagicMock, mock_signal: MagicMock
    ) -> None:
        cleanup_signal_handlers()
        setup_signal_handlers([MagicMock()])
        cleanup_signal_handlers()
        # Second cleanup should be a no-op since originals are cleared
        mock_signal.reset_mock()
        cleanup_signal_handlers()
        mock_signal.assert_not_called()


class TestRunParallelUploadsWithSignals(unittest.TestCase):
    @patch("sftp_parallel.uploader.subprocess.Popen")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    def test_setup_signal_handlers_called_with_popen_list(
        self, mock_cleanup: MagicMock, mock_setup: MagicMock, mock_popen: MagicMock
    ) -> None:
        from sftp_parallel.uploader import run_parallel_uploads

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        run_parallel_uploads("user@host", [["a.txt"]], "/remote", "/local")
        mock_setup.assert_called_once()
        popens_arg = mock_setup.call_args[0][0]
        assert len(popens_arg) == 1

    @patch("sftp_parallel.uploader.subprocess.Popen")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    def test_cleanup_called_after_success(
        self, mock_cleanup: MagicMock, mock_setup: MagicMock, mock_popen: MagicMock
    ) -> None:
        from sftp_parallel.uploader import run_parallel_uploads

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        run_parallel_uploads("user@host", [["a.txt"]], "/remote", "/local")
        mock_cleanup.assert_called_once()

    @patch("sftp_parallel.uploader.subprocess.Popen")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    def test_cleanup_called_after_failure(
        self, mock_cleanup: MagicMock, mock_setup: MagicMock, mock_popen: MagicMock
    ) -> None:
        from sftp_parallel.uploader import run_parallel_uploads

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        run_parallel_uploads("user@host", [["a.txt"]], "/remote", "/local")
        mock_cleanup.assert_called_once()

    @patch("sftp_parallel.uploader.subprocess.Popen")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    def test_popen_uses_start_new_session(
        self, mock_cleanup: MagicMock, mock_setup: MagicMock, mock_popen: MagicMock
    ) -> None:
        from sftp_parallel.uploader import run_parallel_uploads

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        run_parallel_uploads("user@host", [["a.txt"]], "/remote", "/local")
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("start_new_session") is True

    @patch("sftp_parallel.uploader.subprocess.Popen")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    def test_no_signal_handlers_for_empty_buckets(
        self, mock_cleanup: MagicMock, mock_setup: MagicMock, mock_popen: MagicMock
    ) -> None:
        from sftp_parallel.uploader import run_parallel_uploads

        run_parallel_uploads("user@host", [[], [], []], "/remote", "/local")
        mock_setup.assert_not_called()
        mock_cleanup.assert_not_called()

    @patch("sftp_parallel.uploader.subprocess.Popen")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    def test_cleanup_called_even_on_communicate_exception(
        self, mock_cleanup: MagicMock, mock_setup: MagicMock, mock_popen: MagicMock
    ) -> None:
        from sftp_parallel.uploader import run_parallel_uploads

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = OSError("broken pipe")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        run_parallel_uploads("user@host", [["a.txt"]], "/remote", "/local")
        mock_cleanup.assert_called_once()

    @patch("sftp_parallel.uploader.subprocess.Popen")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    def test_multiple_buckets_signal_handlers(
        self, mock_cleanup: MagicMock, mock_setup: MagicMock, mock_popen: MagicMock
    ) -> None:
        from sftp_parallel.uploader import run_parallel_uploads

        proc1 = MagicMock()
        proc1.communicate.return_value = ("", "")
        proc1.returncode = 0
        proc2 = MagicMock()
        proc2.communicate.return_value = ("", "")
        proc2.returncode = 0
        mock_popen.side_effect = [proc1, proc2]

        run_parallel_uploads("user@host", [["a.txt"], ["b.txt"]], "/remote", "/local")
        popens_arg = mock_setup.call_args[0][0]
        assert len(popens_arg) == 2
