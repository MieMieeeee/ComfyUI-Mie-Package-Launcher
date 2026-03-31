"""
Tests for VersionWorkers in core.version_workers.

These tests verify:
- PythonVersionWorker: Python version detection
- TorchVersionWorker: PyTorch version detection
- ComfyUIVersionWorker: ComfyUI core version detection

Tests are designed to FAIL initially (import error - module doesn't exist yet).
Once core/version_workers.py is implemented, these tests should pass.
"""

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from PyQt5 import QtCore


class TestVersionWorkersImport:
    """Test that version_workers module can be imported."""

    def test_import_version_workers_module(self):
        """Module core.version_workers should exist."""
        from core import version_workers

        assert version_workers is not None

    def test_import_python_version_worker(self):
        """PythonVersionWorker should be importable."""
        from core.version_workers import PythonVersionWorker

        assert PythonVersionWorker is not None

    def test_import_torch_version_worker(self):
        """TorchVersionWorker should be importable."""
        from core.version_workers import TorchVersionWorker

        assert TorchVersionWorker is not None

    def test_import_comfyui_version_worker(self):
        """ComfyUIVersionWorker should be importable."""
        from core.version_workers import ComfyUIVersionWorker

        assert ComfyUIVersionWorker is not None

    def test_import_base_version_worker(self):
        """BaseVersionWorker should be importable."""
        from core.version_workers import BaseVersionWorker

        assert BaseVersionWorker is not None


class TestPythonVersionWorker:
    """Tests for PythonVersionWorker."""

    def test_worker_initialization(self, app_context):
        """Worker should initialize with app context."""
        from core.version_workers import PythonVersionWorker

        worker = PythonVersionWorker(app=app_context)
        assert worker.app is app_context
        assert worker.attempt == 1

    def test_worker_initialization_with_attempt(self, app_context):
        """Worker should accept attempt parameter."""
        from core.version_workers import PythonVersionWorker

        worker = PythonVersionWorker(app=app_context, attempt=2)
        assert worker.attempt == 2

    def test_worker_inherits_from_qthread(self, app_context):
        """Worker should inherit from QThread."""
        from core.version_workers import PythonVersionWorker
        from PyQt5 import QtCore

        worker = PythonVersionWorker(app=app_context)
        assert isinstance(worker, QtCore.QThread)

    def test_version_ready_signal_exists(self, app_context):
        """Worker should have versionReady signal."""
        from core.version_workers import PythonVersionWorker

        worker = PythonVersionWorker(app=app_context)
        assert hasattr(worker, "versionReady")
        assert hasattr(worker.versionReady, "connect")

    def test_retry_needed_signal_exists(self, app_context):
        """Worker should have retryNeeded signal."""
        from core.version_workers import PythonVersionWorker

        worker = PythonVersionWorker(app=app_context)
        assert hasattr(worker, "retryNeeded")
        assert hasattr(worker.retryNeeded, "connect")

    def test_successful_version_detection(self, qtbot, app_context):
        """Worker should emit version on successful Python --version."""
        from core.version_workers import PythonVersionWorker

        worker = PythonVersionWorker(app=app_context)

        received_versions = []
        worker.versionReady.connect(lambda v: received_versions.append(v))

        # Mock run_hidden to return successful Python version
        with mock.patch("core.version_workers.run_hidden") as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "Python 3.10.5"
            mock_run.return_value = mock_result

            with mock.patch.object(worker, "_get_paths") as mock_paths:
                mock_paths.return_value = Path(tempfile.gettempdir())
                worker.run()

        # Wait for signal to be processed
        qtbot.waitUntil(lambda: len(received_versions) > 0, timeout=5000)

        assert len(received_versions) == 1
        assert "3.10.5" in received_versions[0]

    def test_version_not_found_when_path_missing(self, qtbot, app_context):
        """Worker should emit '未找到' when ComfyUI path doesn't exist."""
        from core.version_workers import PythonVersionWorker

        worker = PythonVersionWorker(app=app_context)

        received_versions = []
        worker.versionReady.connect(lambda v: received_versions.append(v))

        with mock.patch.object(worker, "_get_paths") as mock_paths:
            mock_path = mock.MagicMock(spec=Path)
            mock_path.exists.return_value = False
            mock_paths.return_value = mock_path
            worker.run()

        qtbot.waitUntil(lambda: len(received_versions) > 0, timeout=5000)

        assert "未找到" in received_versions[0]

    def test_retry_signal_on_failure(self, qtbot, app_context):
        """Worker should emit retryNeeded on failure when attempts remain."""
        from core.version_workers import PythonVersionWorker

        worker = PythonVersionWorker(app=app_context, attempt=1)

        retry_signals = []
        worker.retryNeeded.connect(lambda a: retry_signals.append(a))

        with mock.patch("core.version_workers.run_hidden") as mock_run:
            mock_run.side_effect = Exception("Network error")

            with mock.patch.object(worker, "_get_paths") as mock_paths:
                mock_path = mock.MagicMock(spec=Path)
                mock_path.exists.return_value = True
                mock_paths.return_value = mock_path
                worker.run()

        qtbot.waitUntil(lambda: len(retry_signals) > 0, timeout=5000)

        assert len(retry_signals) == 1
        assert retry_signals[0] == 1

    def test_failure_after_max_retries(self, qtbot, app_context):
        """Worker should emit '获取失败' after MAX_RETRIES exceeded."""
        from core.version_workers import PythonVersionWorker

        worker = PythonVersionWorker(app=app_context, attempt=3)
        worker.MAX_RETRIES = 3

        received_versions = []
        worker.versionReady.connect(lambda v: received_versions.append(v))

        with mock.patch("core.version_workers.run_hidden") as mock_run:
            mock_run.side_effect = Exception("Network error")

            with mock.patch.object(worker, "_get_paths") as mock_paths:
                mock_path = mock.MagicMock(spec=Path)
                mock_path.exists.return_value = True
                mock_paths.return_value = mock_path
                worker.run()

        qtbot.waitUntil(lambda: len(received_versions) > 0, timeout=5000)

        assert "获取失败" in received_versions[0]


class TestTorchVersionWorker:
    """Tests for TorchVersionWorker."""

    def test_worker_initialization(self, app_context):
        """Worker should initialize with app context."""
        from core.version_workers import TorchVersionWorker

        worker = TorchVersionWorker(app=app_context)
        assert worker.app is app_context

    def test_version_ready_signal_exists(self, app_context):
        """Worker should have versionReady signal."""
        from core.version_workers import TorchVersionWorker

        worker = TorchVersionWorker(app=app_context)
        assert hasattr(worker, "versionReady")
        assert hasattr(worker.versionReady, "connect")

    def test_successful_torch_version_detection(self, qtbot, app_context):
        """Worker should emit torch version on success."""
        from core.version_workers import TorchVersionWorker

        worker = TorchVersionWorker(app=app_context)

        received_versions = []
        worker.versionReady.connect(lambda v: received_versions.append(v))

        with mock.patch(
            "core.version_workers.PIPUTILS.get_package_version"
        ) as mock_pip:
            mock_pip.return_value = "2.1.0+cu118"

            with mock.patch.object(worker, "_get_paths") as mock_paths:
                mock_path = mock.MagicMock(spec=Path)
                mock_path.exists.return_value = True
                mock_paths.return_value = mock_path
                worker.run()

        qtbot.waitUntil(lambda: len(received_versions) > 0, timeout=5000)

        assert "2.1.0+cu118" in received_versions[0]

    def test_torch_not_installed(self, qtbot, app_context):
        """Worker should emit '未安装' when torch is not installed."""
        from core.version_workers import TorchVersionWorker

        worker = TorchVersionWorker(app=app_context)

        received_versions = []
        worker.versionReady.connect(lambda v: received_versions.append(v))

        with mock.patch(
            "core.version_workers.PIPUTILS.get_package_version"
        ) as mock_pip:
            mock_pip.return_value = None

            with mock.patch.object(worker, "_get_paths") as mock_paths:
                mock_path = mock.MagicMock(spec=Path)
                mock_path.exists.return_value = True
                mock_paths.return_value = mock_path
                worker.run()

        qtbot.waitUntil(lambda: len(received_versions) > 0, timeout=5000)

        assert "未安装" in received_versions[0]

    def test_torch_network_error_handling(self, qtbot, app_context):
        """Worker should handle network errors gracefully."""
        from core.version_workers import TorchVersionWorker

        worker = TorchVersionWorker(app=app_context, attempt=3)
        worker.MAX_RETRIES = 3

        received_versions = []
        worker.versionReady.connect(lambda v: received_versions.append(v))

        with mock.patch(
            "core.version_workers.PIPUTILS.get_package_version"
        ) as mock_pip:
            mock_pip.side_effect = Exception("Network error")

            with mock.patch.object(worker, "_get_paths") as mock_paths:
                mock_path = mock.MagicMock(spec=Path)
                mock_path.exists.return_value = True
                mock_paths.return_value = mock_path
                worker.run()

        qtbot.waitUntil(lambda: len(received_versions) > 0, timeout=5000)

        assert "获取失败" in received_versions[0]


class TestComfyUIVersionWorker:
    """Tests for ComfyUIVersionWorker (Core version detection)."""

    def test_worker_initialization(self, app_context):
        """Worker should initialize with app context."""
        from core.version_workers import ComfyUIVersionWorker

        worker = ComfyUIVersionWorker(app=app_context)
        assert worker.app is app_context

    def test_version_ready_signal_exists(self, app_context):
        """Worker should have versionReady signal."""
        from core.version_workers import ComfyUIVersionWorker

        worker = ComfyUIVersionWorker(app=app_context)
        assert hasattr(worker, "versionReady")
        assert hasattr(worker.versionReady, "connect")

    def test_commit_ready_signal_exists(self, app_context):
        """Worker should have commitReady signal."""
        from core.version_workers import ComfyUIVersionWorker

        worker = ComfyUIVersionWorker(app=app_context)
        assert hasattr(worker, "commitReady")
        assert hasattr(worker.commitReady, "connect")

    def test_successful_version_detection_with_tag(self, qtbot, app_context):
        """Worker should emit version with git tag on success."""
        from core.version_workers import ComfyUIVersionWorker

        worker = ComfyUIVersionWorker(app=app_context)

        received_versions = []
        received_commits = []
        worker.versionReady.connect(lambda v: received_versions.append(v))
        worker.commitReady.connect(lambda c: received_commits.append(c))

        with mock.patch("core.version_workers.run_hidden") as mock_run:
            # First call: git describe --tags --abbrev=0 -> returns v1.0.0
            # Second call: git rev-parse --short HEAD -> returns abc1234
            mock_result1 = mock.MagicMock()
            mock_result1.returncode = 0
            mock_result1.stdout = "v1.0.0"

            mock_result2 = mock.MagicMock()
            mock_result2.returncode = 0
            mock_result2.stdout = "abc1234"

            mock_run.side_effect = [mock_result1, mock_result2]

            with mock.patch.object(worker, "_get_paths") as mock_paths:
                mock_path = mock.MagicMock(spec=Path)
                mock_path.exists.return_value = True
                mock_paths.return_value = mock_path

                with mock.patch.object(app_context, "resolve_git") as mock_git:
                    mock_git.return_value = ("git", "Git正常")
                    worker.run()

        qtbot.waitUntil(lambda: len(received_versions) > 0, timeout=5000)

        assert "v1.0.0" in received_versions[0]
        assert "abc1234" in received_commits[0]

    def test_no_git_command(self, qtbot, app_context):
        """Worker should handle missing git command gracefully."""
        from core.version_workers import ComfyUIVersionWorker

        worker = ComfyUIVersionWorker(app=app_context)

        received_versions = []
        worker.versionReady.connect(lambda v: received_versions.append(v))

        with mock.patch.object(worker, "_get_paths") as mock_paths:
            mock_path = mock.MagicMock(spec=Path)
            mock_path.exists.return_value = True
            mock_paths.return_value = mock_path

            with mock.patch.object(app_context, "resolve_git") as mock_git:
                mock_git.return_value = (None, "未找到Git命令")
                worker.run()

        qtbot.waitUntil(lambda: len(received_versions) > 0, timeout=5000)

        assert "未找到Git命令" in received_versions[0]

    def test_comfyui_not_found(self, qtbot, app_context):
        """Worker should emit '未找到' when ComfyUI path doesn't exist."""
        from core.version_workers import ComfyUIVersionWorker

        worker = ComfyUIVersionWorker(app=app_context)

        received_versions = []
        worker.versionReady.connect(lambda v: received_versions.append(v))

        with mock.patch.object(worker, "_get_paths") as mock_paths:
            mock_path = mock.MagicMock(spec=Path)
            mock_path.exists.return_value = False
            mock_paths.return_value = mock_path
            worker.run()

        qtbot.waitUntil(lambda: len(received_versions) > 0, timeout=5000)

        assert "未找到" in received_versions[0]


class TestBaseVersionWorkerConstants:
    """Tests for BaseVersionWorker constants and methods."""

    def test_max_retries_constant(self):
        """MAX_RETRIES should be 3."""
        from core.version_workers import BaseVersionWorker

        assert BaseVersionWorker.MAX_RETRIES == 3

    def test_retry_delay_constant(self):
        """RETRY_DELAY_MS should be 3000."""
        from core.version_workers import BaseVersionWorker

        assert BaseVersionWorker.RETRY_DELAY_MS == 3000

    def test_timeout_constant(self):
        """TIMEOUT should be 30."""
        from core.version_workers import BaseVersionWorker

        assert BaseVersionWorker.TIMEOUT == 30

    def test_get_paths_method_exists(self, app_context):
        """_get_paths method should exist."""
        from core.version_workers import BaseVersionWorker

        worker = BaseVersionWorker(app=app_context)
        assert hasattr(worker, "_get_paths")
        assert callable(worker._get_paths)

    def test_log_method_exists(self, app_context):
        """_log method should exist."""
        from core.version_workers import BaseVersionWorker

        worker = BaseVersionWorker(app=app_context)
        assert hasattr(worker, "_log")
        assert callable(worker._log)
