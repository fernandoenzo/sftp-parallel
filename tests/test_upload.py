"""Tests for sftp_parallel.upload."""

from __future__ import annotations

import tempfile
import os
from unittest.mock import MagicMock, patch

from rich.progress import Progress

from sftp_parallel.upload import parallel_upload
from sftp_parallel.worker import WorkerResult


class TestParallelUploadEmptyList:
    def test_returns_zero_zero_on_empty(self):
        progress = Progress()
        ok, fail = parallel_upload(
            "user@host", [], "/remote", progress, port=22
        )
        assert ok == 0
        assert fail == 0


class TestParallelUploadSuccess:
    @patch("sftp_parallel.upload.Worker")
    def test_all_succeed(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(success=True, file_path=tmp_path)
            mock_cls.return_value = mock_worker

            progress = Progress()
            with progress:
                ok, fail = parallel_upload(
                    "user@host", [tmp_path], "/remote", progress, num_workers=1, port=22
                )
            assert ok == 1
            assert fail == 0
        finally:
            os.unlink(tmp_path)

    @patch("sftp_parallel.upload.Worker")
    def test_multiple_files_succeed(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as f1, \
             tempfile.NamedTemporaryFile(delete=False) as f2:
            path1 = f1.name
            path2 = f2.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(success=True, file_path=path1)
            mock_cls.return_value = mock_worker

            progress = Progress()
            with progress:
                ok, fail = parallel_upload(
                    "user@host", [path1, path2], "/remote", progress, num_workers=2, port=22
                )
            assert ok == 2
            assert fail == 0
        finally:
            os.unlink(path1)
            os.unlink(path2)


class TestParallelUploadFailure:
    @patch("sftp_parallel.upload.Worker")
    def test_worker_failure(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(
                success=False, file_path=tmp_path, error_message="SFTP error"
            )
            mock_cls.return_value = mock_worker

            progress = Progress()
            with progress:
                ok, fail = parallel_upload(
                    "user@host", [tmp_path], "/remote", progress, num_workers=1, port=22
                )
            assert ok == 0
            assert fail == 1
        finally:
            os.unlink(tmp_path)

    @patch("sftp_parallel.upload.Worker")
    def test_worker_exception_counted_as_failure(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.side_effect = RuntimeError("unexpected crash")
            mock_cls.return_value = mock_worker

            progress = Progress()
            with progress:
                ok, fail = parallel_upload(
                    "user@host", [tmp_path], "/remote", progress, num_workers=1, port=22
                )
            assert ok == 0
            assert fail == 1
        finally:
            os.unlink(tmp_path)

    @patch("sftp_parallel.upload.Worker")
    def test_mixed_success_and_failure(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as f1, \
             tempfile.NamedTemporaryFile(delete=False) as f2:
            path1 = f1.name
            path2 = f2.name

        try:
            call_count = 0
            def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return WorkerResult(success=True, file_path=path1)
                return WorkerResult(success=False, file_path=path2, error_message="fail")

            mock_worker = MagicMock()
            mock_worker.run.side_effect = side_effect
            mock_cls.return_value = mock_worker

            progress = Progress()
            with progress:
                ok, fail = parallel_upload(
                    "user@host", [path1, path2], "/remote", progress, num_workers=1, port=22
                )
            assert ok == 1
            assert fail == 1
        finally:
            os.unlink(path1)
            os.unlink(path2)


class TestParallelUploadCallback:
    @patch("sftp_parallel.upload.Worker")
    def test_completion_callback_called_on_success(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(success=True, file_path=tmp_path)
            mock_cls.return_value = mock_worker

            callback_calls = []

            def on_complete(fp, success):
                callback_calls.append((fp, success))

            progress = Progress()
            with progress:
                parallel_upload(
                    "user@host", [tmp_path], "/remote", progress,
                    num_workers=1, port=22, completion_callback=on_complete
                )

            assert len(callback_calls) == 1
            assert callback_calls[0][0] == tmp_path
            assert callback_calls[0][1] is True
        finally:
            os.unlink(tmp_path)

    @patch("sftp_parallel.upload.Worker")
    def test_completion_callback_called_on_failure(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(
                success=False, file_path=tmp_path, error_message="error"
            )
            mock_cls.return_value = mock_worker

            callback_calls = []

            def on_complete(fp, success):
                callback_calls.append((fp, success))

            progress = Progress()
            with progress:
                parallel_upload(
                    "user@host", [tmp_path], "/remote", progress,
                    num_workers=1, port=22, completion_callback=on_complete
                )

            assert len(callback_calls) == 1
            assert callback_calls[0][1] is False
        finally:
            os.unlink(tmp_path)

    @patch("sftp_parallel.upload.Worker")
    def test_completion_callback_exception_swallowed(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(success=True, file_path=tmp_path)
            mock_cls.return_value = mock_worker

            def bad_callback(fp, success):
                raise RuntimeError("callback exploded")

            progress = Progress()
            with progress:
                ok, fail = parallel_upload(
                    "user@host", [tmp_path], "/remote", progress,
                    num_workers=1, port=22, completion_callback=bad_callback
                )

            assert ok == 1
            assert fail == 0
        finally:
            os.unlink(tmp_path)

    @patch("sftp_parallel.upload.logger")
    @patch("sftp_parallel.upload.Worker")
    def test_callback_exception_logged(self, mock_cls, mock_logger):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(success=True, file_path=tmp_path)
            mock_cls.return_value = mock_worker

            def failing_callback(fp, success):
                raise ValueError("callback failure")

            progress = Progress()
            with progress:
                parallel_upload(
                    "user@host", [tmp_path], "/remote", progress,
                    num_workers=1, port=22, completion_callback=failing_callback
                )

            assert mock_logger.debug.called
            has_exc_info = any(
                call.kwargs.get("exc_info", False) or
                (len(call.args) > 2 and call.args[2] is True)
                for call in mock_logger.debug.call_args_list
            )
            assert has_exc_info
        finally:
            os.unlink(tmp_path)


class TestParallelUploadSignalHandlers:
    @patch("sftp_parallel.upload.signal")
    @patch("sftp_parallel.upload.Worker")
    def test_signal_handlers_restored_after_upload(self, mock_cls, mock_signal):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(success=True, file_path=tmp_path)
            mock_cls.return_value = mock_worker

            original_sigint = MagicMock()
            original_sigterm = MagicMock()
            mock_signal.getsignal.side_effect = [original_sigint, original_sigterm]
            mock_signal.SIGINT = 2
            mock_signal.SIGTERM = 15

            progress = Progress()
            with progress:
                parallel_upload(
                    "user@host", [tmp_path], "/remote", progress,
                    num_workers=1, port=22
                )

            set_calls = mock_signal.signal.call_args_list
            assert len(set_calls) == 4
            mock_signal.signal.assert_any_call(2, original_sigint)
            mock_signal.signal.assert_any_call(15, original_sigterm)
        finally:
            os.unlink(tmp_path)

    @patch("sftp_parallel.upload.Worker")
    def test_signal_handlers_restored_on_exception(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            original_sigint = __import__("signal").getsignal(__import__("signal").SIGINT)
            original_sigterm = __import__("signal").getsignal(__import__("signal").SIGTERM)

            mock_worker = MagicMock()
            mock_worker.run.side_effect = RuntimeError("boom")
            mock_cls.return_value = mock_worker

            progress = Progress()
            with progress:
                parallel_upload(
                    "user@host", [tmp_path], "/remote", progress,
                    num_workers=1, port=22
                )

            import signal
            assert signal.getsignal(signal.SIGINT) is original_sigint
            assert signal.getsignal(signal.SIGTERM) is original_sigterm
        finally:
            os.unlink(tmp_path)


class TestParallelUploadTaskStart:
    """Verify that progress tasks are created with start=False, visible=False
    and that start_task + visible=True are called before worker.run()."""

    @patch("sftp_parallel.upload.Worker")
    def test_add_task_called_with_start_false_visible_false(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(success=True, file_path=tmp_path)
            mock_cls.return_value = mock_worker

            progress = MagicMock(spec=Progress)
            task_id = MagicMock()
            progress.add_task.return_value = task_id

            with progress:
                parallel_upload(
                    "user@host", [tmp_path], "/remote", progress,
                    num_workers=1, port=22
                )

            add_task_call = progress.add_task.call_args
            assert add_task_call.kwargs.get("start") is False
            assert add_task_call.kwargs.get("visible") is False
        finally:
            os.unlink(tmp_path)

    @patch("sftp_parallel.upload.Worker")
    def test_start_task_and_visible_called_before_worker_run(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(success=True, file_path=tmp_path)
            mock_cls.return_value = mock_worker

            progress = MagicMock(spec=Progress)
            task_id = MagicMock()
            progress.add_task.return_value = task_id

            with progress:
                parallel_upload(
                    "user@host", [tmp_path], "/remote", progress,
                    num_workers=1, port=22
                )

            progress.start_task.assert_called_once_with(task_id)
            visible_call = [c for c in progress.update.call_args_list
                           if c.kwargs.get("visible") is True]
            assert len(visible_call) >= 1
            assert any(c.args[0] == task_id for c in visible_call)
        finally:
            os.unlink(tmp_path)

    @patch("sftp_parallel.upload.Worker")
    def test_start_task_called_before_worker_run(self, mock_cls):
        """Verify start_task is called before worker.run() in execution order."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            call_order = []

            mock_worker = MagicMock()

            def mock_run():
                call_order.append("worker.run")
                return WorkerResult(success=True, file_path=tmp_path)

            mock_worker.run.side_effect = mock_run
            mock_cls.return_value = mock_worker

            progress = MagicMock(spec=Progress)
            task_id = MagicMock()
            progress.add_task.return_value = task_id

            def mock_start_task(tid):
                call_order.append("start_task")

            def mock_update(*args, **kwargs):
                if kwargs.get("visible") is True:
                    call_order.append("visible_update")

            progress.start_task.side_effect = mock_start_task
            progress.update.side_effect = mock_update

            with progress:
                parallel_upload(
                    "user@host", [tmp_path], "/remote", progress,
                    num_workers=1, port=22
                )

            start_idx = call_order.index("start_task")
            visible_idx = call_order.index("visible_update")
            run_idx = call_order.index("worker.run")
            assert start_idx < run_idx
            assert visible_idx < run_idx
        finally:
            os.unlink(tmp_path)


class TestParallelUploadWorkers:
    @patch("sftp_parallel.upload.Worker")
    def test_max_workers_capped_by_file_count(self, mock_cls):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        try:
            mock_worker = MagicMock()
            mock_worker.run.return_value = WorkerResult(success=True, file_path=tmp_path)
            mock_cls.return_value = mock_worker

            progress = Progress()
            with patch("sftp_parallel.upload.ThreadPoolExecutor") as mock_executor_cls:
                mock_executor = MagicMock()
                mock_executor.__enter__ = MagicMock(return_value=mock_executor)
                mock_executor.__exit__ = MagicMock(return_value=False)

                future = MagicMock()
                future.result.return_value = True
                mock_executor.submit.return_value = future
                mock_executor_cls.return_value = mock_executor

                with progress:
                    parallel_upload(
                        "user@host", [tmp_path], "/remote", progress,
                        num_workers=10, port=22
                    )

                mock_executor_cls.assert_called_once_with(max_workers=1)
        finally:
            os.unlink(tmp_path)