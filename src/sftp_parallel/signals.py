"""Signal handling module – clean shutdown of child SFTP processes on SIGINT/SIGTERM."""

from __future__ import annotations

import signal
import sys
import threading
from types import FrameType
from typing import TYPE_CHECKING, Callable

from rich.console import Console

if TYPE_CHECKING:
    from sftp_parallel.pty_worker import PTYWorker

console = Console()

_original_sigint: Callable[[int, FrameType | None], None] | int | None = None
_original_sigterm: Callable[[int, FrameType | None], None] | int | None = None

# NOTE: _handling_sigint and _handling_sigterm are module-level booleans
# accessed from signal handlers. They are not protected by a lock because:
# 1. Python's GIL makes single-byte bool reads/writes atomic on CPython
# 2. The worst case (both signals fire simultaneously) results in one
#    signal being handled and the other calling sys.exit() — acceptable.
_handling_sigint = False
_handling_sigterm = False


def _make_signal_handler(
    active_workers: list[PTYWorker],
    worker_lock: threading.Lock,
) -> Callable[[int, FrameType | None], None]:
    """Create a signal handler that terminates all PTYWorker instances.

    Parameters
    ----------
    active_workers:
        List of :class:`~sftp_parallel.pty_worker.PTYWorker` instances.
    worker_lock:
        A threading lock protecting *active_workers* from concurrent
        modification.

    Returns
    -------
    Callable[[int, FrameType | None], None]
        A signal handler suitable for ``signal.signal()``.
    """

    def handler(signum: int, frame: FrameType | None) -> None:
        global _handling_sigint, _handling_sigterm
        if signum == signal.SIGINT:
            if _handling_sigint:
                return
            _handling_sigint = True
        elif signum == signal.SIGTERM:
            if _handling_sigterm:
                return
            _handling_sigterm = True
            # SIGTERM always overrides SIGINT in progress
        # Non-blocking acquisition is intentional: if we can't get the lock,
        # we proceed with a possibly-stale snapshot. Workers added after the
        # snapshot are still cleaned up by their own finally block in
        # _upload_one_via_pty, and workers removed are harmless (terminate()
        # is idempotent).
        locked = worker_lock.acquire(blocking=False)
        try:
            snapshot = list(active_workers)
        finally:
            if locked:
                worker_lock.release()

        for worker in snapshot:
            worker.terminate()

        console.print("[bold red]Interrupted[/bold red]")
        sys.exit(128 + signum)

    return handler


def setup_signal_handlers(
    active_workers: list[PTYWorker],
    worker_lock: threading.Lock,
) -> None:
    """Register SIGINT and SIGTERM handlers that terminate PTYWorker instances.

    Parameters
    ----------
    active_workers:
        List of :class:`~sftp_parallel.pty_worker.PTYWorker` instances.
    worker_lock:
        A threading lock protecting *active_workers*.
    """
    global _original_sigint, _original_sigterm

    _original_sigint = signal.getsignal(signal.SIGINT)
    _original_sigterm = signal.getsignal(signal.SIGTERM)

    handler = _make_signal_handler(active_workers, worker_lock)
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