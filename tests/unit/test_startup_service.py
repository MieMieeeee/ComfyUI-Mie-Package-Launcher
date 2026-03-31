"""
Tests for services.startup_service module.

Tests the StartupService class that manages application startup operations.
"""

import pytest
import threading
from unittest.mock import MagicMock, patch


class TestStartupServiceInit:
    """Test StartupService initialization."""

    def test_init_assigns_app(self):
        """StartupService should assign the app instance."""
        from services.startup_service import StartupService

        app = MagicMock()
        service = StartupService(app)

        assert service.app is app


class TestStartAll:
    """Test the start_all method."""

    def test_start_all_calls_refresh_version_info(self):
        """start_all should call refresh_version_info with scope='all'."""
        from services.startup_service import StartupService

        app = MagicMock()

        with patch('core.version_service.refresh_version_info') as mock_refresh:
            service = StartupService(app)
            service.start_all()

            mock_refresh.assert_called_once_with(app, scope="all")

    def test_start_all_handles_exception(self):
        """start_all should catch and suppress any exception from refresh_version_info."""
        from services.startup_service import StartupService

        app = MagicMock()

        with patch('core.version_service.refresh_version_info', side_effect=RuntimeError("test error")):
            service = StartupService(app)
            service.start_all()

    def test_start_all_does_not_raise_when_import_fails(self):
        """start_all should handle case where refresh_version_info import fails."""
        from services.startup_service import StartupService

        app = MagicMock()

        with patch('core.version_service.refresh_version_info', side_effect=ImportError("module not found")):
            service = StartupService(app)
            service.start_all()


class TestStartAnnouncementsOnly:
    """Test the start_announcements_only method."""

    def test_announcements_only_uses_thread_pool_executor_when_available(self):
        """start_announcements_only should use ThreadPoolExecutor when creation succeeds."""
        from services.startup_service import StartupService

        app = MagicMock()

        with patch('services.startup_service.ThreadPoolExecutor') as mock_executor:
            mock_thread_pool = MagicMock()
            mock_executor.return_value = mock_thread_pool

            service = StartupService(app)
            service.start_announcements_only()

            mock_executor.assert_called_once_with(max_workers=1)
            mock_thread_pool.submit.assert_called_once()

    def test_announcements_only_falls_back_to_threading_when_executor_fails(self):
        """start_announcements_only should fall back to threading.Thread when ThreadPoolExecutor fails."""
        from services.startup_service import StartupService

        app = MagicMock()

        with patch('services.startup_service.ThreadPoolExecutor', side_effect=RuntimeError("cannot create")):
            with patch('threading.Thread') as mock_thread:
                mock_thread_instance = MagicMock()
                mock_thread.return_value = mock_thread_instance

                service = StartupService(app)
                service.start_announcements_only()

                mock_thread.assert_called_once()
                mock_thread_instance.start.assert_called_once()

    def test_announcements_only_skips_submit_if_executor_is_none(self):
        """start_announcements_only should skip submit when executor creation returns None."""
        from services.startup_service import StartupService

        app = MagicMock()

        with patch('services.startup_service.ThreadPoolExecutor', return_value=None):
            with patch('threading.Thread') as mock_thread:
                mock_thread_instance = MagicMock()
                mock_thread.return_value = mock_thread_instance

                service = StartupService(app)
                service.start_announcements_only()

                mock_thread.assert_called_once()

    def test_announcements_only_handles_submit_exception(self):
        """start_announcements_only should handle exceptions from executor.submit."""
        from services.startup_service import StartupService

        app = MagicMock()

        mock_thread_pool = MagicMock()
        mock_thread_pool.submit.side_effect = RuntimeError("submit failed")

        with patch('services.startup_service.ThreadPoolExecutor', return_value=mock_thread_pool):
            service = StartupService(app)
            service.start_announcements_only()

    def test_announcements_only_handles_thread_start_exception(self):
        """start_announcements_only should handle exceptions from threading.Thread.start."""
        from services.startup_service import StartupService

        app = MagicMock()

        with patch('services.startup_service.ThreadPoolExecutor', return_value=None):
            mock_thread_instance = MagicMock()
            mock_thread_instance.start.side_effect = RuntimeError("start failed")

            with patch('threading.Thread', return_value=mock_thread_instance):
                service = StartupService(app)
                service.start_announcements_only()

    def test_announcements_task_calls_show_if_available(self):
        """The announcement task should call show_if_available on the announcement service."""
        from services.startup_service import StartupService

        app = MagicMock()
        mock_announcement = MagicMock()
        app.services = MagicMock()
        app.services.announcement = mock_announcement

        submitted_task = None

        with patch('services.startup_service.ThreadPoolExecutor') as mock_executor:
            mock_thread_pool = MagicMock()
            mock_executor.return_value = mock_thread_pool

            def capture_submit(task):
                nonlocal submitted_task
                submitted_task = task
            mock_thread_pool.submit.side_effect = capture_submit

            service = StartupService(app)
            service.start_announcements_only()

            submitted_task()
            mock_announcement.show_if_available.assert_called_once()

    def test_announcements_task_handles_missing_services(self):
        """The announcement task should handle missing services attribute gracefully."""
        from services.startup_service import StartupService

        app = MagicMock()
        del app.services

        submitted_task = None

        with patch('services.startup_service.ThreadPoolExecutor') as mock_executor:
            mock_thread_pool = MagicMock()
            mock_executor.return_value = mock_thread_pool

            def capture_submit(task):
                nonlocal submitted_task
                submitted_task = task
            mock_thread_pool.submit.side_effect = capture_submit

            service = StartupService(app)
            service.start_announcements_only()
            submitted_task()

    def test_announcements_task_handles_missing_announcement(self):
        """The announcement task should handle missing announcement service gracefully."""
        from services.startup_service import StartupService

        app = MagicMock()
        app.services = MagicMock()
        del app.services.announcement

        submitted_task = None

        with patch('services.startup_service.ThreadPoolExecutor') as mock_executor:
            mock_thread_pool = MagicMock()
            mock_executor.return_value = mock_thread_pool

            def capture_submit(task):
                nonlocal submitted_task
                submitted_task = task
            mock_thread_pool.submit.side_effect = capture_submit

            service = StartupService(app)
            service.start_announcements_only()
            submitted_task()

    def test_announcements_task_handles_announcement_exception(self):
        """The announcement task should handle exceptions from show_if_available gracefully."""
        from services.startup_service import StartupService

        app = MagicMock()
        mock_announcement = MagicMock()
        mock_announcement.show_if_available.side_effect = RuntimeError("show failed")
        app.services = MagicMock()
        app.services.announcement = mock_announcement

        submitted_task = None

        with patch('services.startup_service.ThreadPoolExecutor') as mock_executor:
            mock_thread_pool = MagicMock()
            mock_executor.return_value = mock_thread_pool

            def capture_submit(task):
                nonlocal submitted_task
                submitted_task = task
            mock_thread_pool.submit.side_effect = capture_submit

            service = StartupService(app)
            service.start_announcements_only()
            submitted_task()
