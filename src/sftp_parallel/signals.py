"""Signal handling module – clean shutdown of child SFTP processes on SIGINT/SIGTERM."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from types import FrameType
from typing import Any, Callable

from rich.console import Console

console = Console()

_original_sigint: Any = None
_original_sigterm: Any = None

_SIGTERM_WAIT_SECONDS = 2
_handling_signal = False


def _make_signal_handler(
    popens: list[tuple[subprocess.Popen[str], int]],
    popen_lock: threading.Lock,
) -> Callable[[int, FrameType | None], None]:
    """Create a signal handler that terminates all child Popen processes.

    Parameters
    ----------
    popens:
        List of ``(Popen, pgid)`` tuples.  Each process is expected to have
        been started with ``start_new_session=True`` so that ``os.killpg``
        can kill the entire process group.
    popen_lock:
        A threading lock protecting *popens* from concurrent modification.

    Returns
    -------
    Callable[[int, FrameType | None], None]
        A signal handler suitable for ``signal.signal()``.
    """

    def handler(signum: int, frame: FrameType | None) -> None:
        global _handling_signal
        if _handling_signal:
            return
        _handling_signal = True

        locked = popen_lock.acquire(blocking=False)
        try:
            snapshot = list(popens)
        finally:
            if locked:
                popen_lock.release()

        for _proc, pgid in snapshot:
            if pgid > 1:
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass

        for proc, pgid in snapshot:
            try:
                proc.wait(timeout=_SIGTERM_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                if pgid > 1:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        pass

        console.print("[bold red]Interrupted[/bold red]")
        _handling_signal = False
        sys.exit(128 + signum)

    return handler


def setup_signal_handlers(
    popens: list[tuple[subprocess.Popen[str], int]],
    popen_lock: threading.Lock,
) -> None:
    """Register SIGINT and SIGTERM handlers that terminate child processes.

    Parameters
    ----------
    popens:
        List of ``(Popen, pgid)`` tuples for running SFTP processes.
    popen_lock:
        A threading lock protecting *popens*.
    """
    global _original_sigint, _original_sigterm

    _original_sigint = signal.getsignal(signal.SIGINT)
    _original_sigterm = signal.getsignal(signal.SIGTERM)

    handler = _make_signal_handler(popens, popen_lock)
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