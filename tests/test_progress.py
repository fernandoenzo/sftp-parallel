"""Tests for the progress module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rich.progress import Progress

from sftp_parallel.progress import advance_progress, create_upload_progress
from sftp_parallel.uploader import upload_files


class TestCreateUploadProgress:
    """Tests for the create_upload_progress context manager."""

    def test_yields_progress_and_task_id(self) -> None:
        """Context manager yields Progress instance and task ID."""
        with create_upload_progress(10, "user@host", "/remote") as (progress, task_id):
            assert isinstance(progress, Progress)
            assert isinstance(task_id, int)

    def test_progress_has_correct_columns(self) -> None:
        """Progress bar has expected columns: description, spinner, bar, percentage, count."""
        with create_upload_progress(5, "user@host", "/data") as (progress, _):
            columns = progress.columns
            assert len(columns) == 5

    def test_description_includes_file_count_and_destination(self) -> None:
        """Task description includes total files and host:dir."""
        with create_upload_progress(15, "deploy@example.com", "/var/www") as (
            progress,
            task_id,
        ):
            task = progress._tasks[task_id]
            assert "Uploading 15 files" in task.description
            assert "deploy@example.com:/var/www" in task.description

    def test_total_set_to_file_count(self) -> None:
        """Task total is set to the number of files."""
        with create_upload_progress(42, "user@host", "/remote") as (progress, task_id):
            task = progress._tasks[task_id]
            assert task.total == 42

    def test_initial_completed_is_zero(self) -> None:
        """Task starts with zero completed."""
        with create_upload_progress(10, "user@host", "/remote") as (progress, task_id):
            task = progress._tasks[task_id]
            assert task.completed == 0

    def test_disable_true_hides_progress(self) -> None:
        """When disable=True, progress bar is hidden."""
        with create_upload_progress(5, "user@host", "/remote", disable=True) as (
            progress,
            _,
        ):
            assert progress.disable is True

    def test_disable_false_shows_progress(self) -> None:
        """When disable=False (default), progress bar is visible."""
        with create_upload_progress(5, "user@host", "/remote", disable=False) as (
            progress,
            _,
        ):
            assert progress.disable is False

    def test_zero_files(self) -> None:
        with create_upload_progress(0, "user@host", "/remote") as (progress, task_id):
            task = progress._tasks[task_id]
            assert task.total == 0
            assert task.completed == 0

    def test_singular_file_count_in_description(self) -> None:
        with create_upload_progress(1, "user@host", "/remote") as (
            progress,
            task_id,
        ):
            task = progress._tasks[task_id]
            assert "1 files" in task.description


class TestAdvanceProgress:
    """Tests for the advance_progress function (per-file signature)."""

    def test_advances_by_one_per_file(self) -> None:
        """Each call with a filename advances progress by 1."""
        with create_upload_progress(10, "user@host", "/remote") as (progress, task_id):
            advance_progress(progress, task_id, "a.txt")
            advance_progress(progress, task_id, "b.txt")
            advance_progress(progress, task_id, "c.txt")
            task = progress._tasks[task_id]
            assert task.completed == 3

    def test_multiple_advances_accumulate(self) -> None:
        """Multiple calls to advance accumulate."""
        with create_upload_progress(10, "user@host", "/remote") as (progress, task_id):
            for name in [
                "f1.txt",
                "f2.txt",
                "f3.txt",
                "f4.txt",
                "f5.txt",
                "f6.txt",
                "f7.txt",
                "f8.txt",
                "f9.txt",
                "f10.txt",
            ]:
                advance_progress(progress, task_id, name)
            task = progress._tasks[task_id]
            assert task.completed == 10

    def test_advance_to_completion(self) -> None:
        """Advancing all files marks task as complete."""
        with create_upload_progress(3, "user@host", "/remote") as (progress, task_id):
            advance_progress(progress, task_id, "a.txt")
            advance_progress(progress, task_id, "b.txt")
            advance_progress(progress, task_id, "c.txt")
            task = progress._tasks[task_id]
            assert task.completed == 3
            assert task.finished is True

    @patch("sftp_parallel.progress._console")
    def test_prints_checkmark_with_filename(self, mock_console: MagicMock) -> None:
        """advance_progress prints ✓ filename for each file."""
        with create_upload_progress(5, "user@host", "/remote") as (progress, task_id):
            advance_progress(progress, task_id, "data.csv")
        mock_console.print.assert_called_once()
        call_arg = mock_console.print.call_args[0][0]
        assert "✓" in call_arg
        assert "data.csv" in call_arg


class TestProgressIntegration:
    """Integration tests for progress with upload_files."""

    @patch("sftp_parallel.uploader.os.getpgid", return_value=12345)
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_progress_callback_advances_per_file(self, mock_popen: MagicMock, mock_getpgid: MagicMock, mock_popen_success: MagicMock) -> None:
        mock_popen.return_value = mock_popen_success
        files = ["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"]

        with create_upload_progress(len(files), "user@host", "/remote") as (
            progress,
            task_id,
        ):

            def progress_callback(filename: str) -> None:
                advance_progress(progress, task_id, filename)

            upload_files(
                "user@host",
                files,
                "/remote",
                num_workers=2,
                port=22,
                progress_callback=progress_callback,
            )

        task = progress._tasks[task_id]
        assert task.completed == 5

    @patch("sftp_parallel.uploader.os.getpgid", return_value=12345)
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_failed_file_does_not_advance_progress(self, mock_popen: MagicMock, mock_getpgid: MagicMock, mock_popen_success: MagicMock) -> None:
        mock_popen_success.returncode = 1
        mock_popen.return_value = mock_popen_success

        with create_upload_progress(2, "user@host", "/remote") as (progress, task_id):

            def progress_callback(filename: str) -> None:
                advance_progress(progress, task_id, filename)

            all_success, failed = upload_files(
                "user@host",
                ["a.txt", "b.txt"],
                "/remote",
                num_workers=2,
                port=22,
                progress_callback=progress_callback,
            )

        assert all_success is False
        assert failed == 2
        task = progress._tasks[task_id]
        assert task.completed == 0

    @patch("sftp_parallel.uploader.os.getpgid", return_value=12345)
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_mixed_success_and_failure(self, mock_popen: MagicMock, mock_getpgid: MagicMock, mock_popen_success: MagicMock) -> None:
        call_count = 0

        def make_proc():
            nonlocal call_count
            call_count += 1
            proc = MagicMock()
            proc.communicate.return_value = ("", "")
            proc.returncode = 0 if call_count <= 2 else 1
            proc.pid = 10000 + call_count
            return proc

        mock_popen.side_effect = [make_proc() for _ in range(4)]

        files = ["a.txt", "b.txt", "c.txt", "d.txt"]

        with create_upload_progress(len(files), "user@host", "/remote") as (
            progress,
            task_id,
        ):

            def progress_callback(filename: str) -> None:
                advance_progress(progress, task_id, filename)

            upload_files(
                "user@host",
                files,
                "/remote",
                num_workers=2,
                port=22,
                progress_callback=progress_callback,
            )

        task = progress._tasks[task_id]
        assert task.completed == 2

    @patch("sftp_parallel.uploader.os.getpgid", return_value=12345)
    @patch("sftp_parallel.uploader.subprocess.Popen")
    def test_no_progress_callback_works_normally(self, mock_popen: MagicMock, mock_getpgid: MagicMock, mock_popen_success: MagicMock) -> None:
        mock_popen.return_value = mock_popen_success

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


class TestProgressWithEmptyFiles:
    """Tests for progress with empty or edge-case file lists."""

    def test_empty_file_list(self) -> None:
        """Empty file list completes immediately."""
        from sftp_parallel.uploader import upload_files

        with create_upload_progress(0, "user@host", "/remote") as (progress, task_id):

            def progress_callback(filename: str) -> None:
                advance_progress(progress, task_id, filename)

            all_success, failed_count = upload_files(
                "user@host",
                [],
                "/remote",
                num_workers=2,
                port=22,
                progress_callback=progress_callback,
            )

        assert all_success is True
        assert failed_count == 0
