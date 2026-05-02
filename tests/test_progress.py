"""Tests for the progress module."""

from unittest.mock import MagicMock, patch

from rich.progress import Progress

from sftp_parallel.pty_worker import WorkerResult
from sftp_parallel.uploader import upload_files


def _make_worker_factory(success: bool = True):
    """Return a factory that creates PTYWorker mocks."""

    def factory(*args, **kwargs):
        mock = MagicMock()
        file_path = kwargs.get("file_path", "unknown")

        def run():
            return WorkerResult(
                success=success,
                file_path=file_path,
            )

        mock.run.side_effect = run
        return mock

    return factory


class TestProgressIntegration:
    """Integration tests for progress with upload_files."""

    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.PTYWorker", side_effect=_make_worker_factory(success=False))
    def test_failed_file_does_not_advance_progress(
        self,
        MockPTYWorker: MagicMock,
        mock_setup: MagicMock,
        mock_cleanup: MagicMock,
    ):
        all_success, failed = upload_files(
            "user@host",
            ["a.txt", "b.txt"],
            "/remote",
            num_workers=2,
            port=22,
        )

        assert all_success is False
        assert failed == 2

    @patch("sftp_parallel.uploader.cleanup_signal_handlers")
    @patch("sftp_parallel.uploader.setup_signal_handlers")
    @patch("sftp_parallel.uploader.PTYWorker", side_effect=_make_worker_factory(success=True))
    def test_no_progress_callback_works_normally(
        self,
        MockPTYWorker: MagicMock,
        mock_setup: MagicMock,
        mock_cleanup: MagicMock,
    ):
        all_success, failed_count = upload_files(
            "user@host",
            ["a.txt", "b.txt"],
            "/remote",
            num_workers=2,
            port=22,
            progress_callback=None,
        )

        assert all_success is True
        assert failed_count == 0
