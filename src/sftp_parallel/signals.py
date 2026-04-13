"""Signal handling module – clean shutdown of child SFTP processes on SIGINT/SIGTERM."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from types import FrameType
from typing import Any, Callable

from rich.console import Console

console = Console()

_original_sigint: Any = None
_original_sigterm: Any = None


def _make_signal_handler(
    popens: list,
) -> Callable[[int, FrameType | None], None]:
    """Create a signal handler that terminates all child Popen processes.

    Parameters
    ----------
    popens:
        List of ``subprocess.Popen`` objects.  Each is expected to have
        been started with ``start_new_session=True`` so that
        ``os.killpg`` can kill the entire process group.

    Returns
    -------
    Callable[[int, FrameType | None], None]
        A signal handler suitable for ``signal.signal()``.
    """

    def handler(signum: int, frame: FrameType | None) -> None:
        for proc in popens:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass

        # SIGTERM → brief wait → SIGKILL for stubborn processes
        for proc in popens:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass

        console.print("[bold red]Interrupted[/bold red]")
        sys.exit(128 + signum)

    return handler


def setup_signal_handlers(popens: list) -> None:
    """Register SIGINT and SIGTERM handlers that terminate child processes.

    Parameters
    ----------
    popens:
        List of ``subprocess.Popen`` objects for running SFTP processes.
    """
    global _original_sigint, _original_sigterm

    _original_sigint = signal.getsignal(signal.SIGINT)
    _original_sigterm = signal.getsignal(signal.SIGTERM)

    handler = _make_signal_handler(popens)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def cleanup_signal_handlers() -> None:
    """Restore the default SIGINT and SIGTERM signal handlers."""
    global _original_sigint, _original_sigterm

    if _original_sigint is not None:
        signal.signal(signal.SIGINT, _original_sigint)
        _original_sigint = None
    if _original_sigterm is not None:
        signal.signal(signal.SIGTERM, _original_sigterm)
        _original_sigterm = None
