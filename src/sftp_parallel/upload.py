"""Parallel upload orchestration."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from rich.progress import Progress, TaskID

from sftp_parallel.worker import Worker, WorkerResult

logger = logging.getLogger(__name__)


def parallel_upload(
    host: str,
    file_paths: list[str],
    remote_dir: str,
    progress: Progress,
    num_workers: int = 2,
    port: int = 22,
    idle_timeout: int = 120,
    completion_callback: Callable[[str, bool], None] | None = None,
) -> tuple[int, int]:
    """Upload files in parallel with Rich progress. Returns (ok, fail)."""
    if not file_paths:
        return 0, 0

    tasks: dict[str, TaskID] = {}
    for fp in file_paths:
        name = os.path.basename(fp)
        try:
            size = os.path.getsize(fp)
        except OSError:
            size = 0
        tasks[fp] = progress.add_task(name, total=max(size, 1), _success=None, start=False, visible=False)

    active_workers: list[Worker] = []
    worker_lock = threading.Lock()
    ok_count = 0
    fail_count = 0
    count_lock = threading.Lock()

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def _handle_signal(signum: int, frame: object) -> None:
        with worker_lock:
            snapshot = list(active_workers)
        for w in snapshot:
            w.terminate_urgent()
        sys.exit(128 + signum)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        def _upload_one(fp: str) -> bool:
            task_id = tasks[fp]
            worker = Worker(
                host=host,
                file_path=fp,
                remote_dir=remote_dir,
                port=port,
                idle_timeout=idle_timeout,
                progress=progress,
                task_id=task_id,
            )
            with worker_lock:
                active_workers.append(worker)
            try:
                progress.start_task(task_id)
                progress.update(task_id, visible=True)
                result: WorkerResult = worker.run()
                success = result.success
            except Exception:
                success = False
            finally:
                with worker_lock:
                    if worker in active_workers:
                        active_workers.remove(worker)

            if success:
                progress.update(
                    task_id,
                    description=os.path.basename(fp),
                    completed=os.path.getsize(fp),
                    _success=True,
                )
            else:
                progress.update(
                    task_id,
                    description=f"✗ {os.path.basename(fp)}",
                    _success=False,
                )

            nonlocal ok_count, fail_count
            with count_lock:
                if success:
                    ok_count += 1
                else:
                    fail_count += 1

            if completion_callback is not None:
                try:
                    completion_callback(fp, success)
                except Exception:
                    logger.debug("Completion callback failed for %s", fp, exc_info=True)

            return success

        with ThreadPoolExecutor(max_workers=min(num_workers, len(file_paths))) as executor:
            futures = {executor.submit(_upload_one, fp): fp for fp in file_paths}
            for future in futures:
                future.result()
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)

    return ok_count, fail_count