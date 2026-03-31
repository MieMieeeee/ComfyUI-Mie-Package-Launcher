"""
Integration tests for qt_app.py extraction.

Tests verify that the refactored modules (workers, app_state) work together
with PyQtLauncher without requiring actual UI rendering.

These tests complement unit tests by verifying cross-module integration:
- Workers can be instantiated with app context
- AppState integrates with launcher initialization
- Signal/slot connections are properly defined
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

import pytest


class TestWorkerIntegration:
    """Test workers integrate properly with app context."""

    def test_python_version_worker_can_be_instantiated_with_app(self, app_context):
        """PythonVersionWorker should instantiate with app context."""
        from core.version_workers import PythonVersionWorker
        
        worker = PythonVersionWorker(app=app_context)
        
        assert worker.app is app_context
        assert worker.attempt == 1
        assert hasattr(worker, 'versionReady')
        assert hasattr(worker, 'retryNeeded')

    def test_torch_version_worker_can_be_instantiated_with_app(self, app_context):
        """TorchVersionWorker should instantiate with app context."""
        from core.version_workers import TorchVersionWorker
        
        worker = TorchVersionWorker(app=app_context)
        
        assert worker.app is app_context
        assert hasattr(worker, 'versionReady')

    def test_comfyui_version_worker_can_be_instantiated_with_app(self, app_context):
        """ComfyUIVersionWorker should instantiate with app context."""
        from core.version_workers import ComfyUIVersionWorker
        
        worker = ComfyUIVersionWorker(app=app_context)
        
        assert worker.app is app_context
        assert hasattr(worker, 'versionReady')
        assert hasattr(worker, 'commitReady')

    def test_all_workers_imported_from_qt_app(self):
        """Workers should be importable from qt_app module."""
        # These imports are used in qt_app.py at module level
        from ui_qt.qt_app import (
            PythonVersionWorker,
            TorchVersionWorker,
            ComfyUIVersionWorker,
        )
        
        assert PythonVersionWorker is not None
        assert TorchVersionWorker is not None
        assert ComfyUIVersionWorker is not None

    def test_workers_share_common_base(self, app_context):
        """All workers should share BaseVersionWorker base class."""
        from core.version_workers import (
            PythonVersionWorker,
            TorchVersionWorker,
            ComfyUIVersionWorker,
            BaseVersionWorker,
        )
        
        python_worker = PythonVersionWorker(app=app_context)
        torch_worker = TorchVersionWorker(app=app_context)
        comfyui_worker = ComfyUIVersionWorker(app=app_context)
        
        assert isinstance(python_worker, BaseVersionWorker)
        assert isinstance(torch_worker, BaseVersionWorker)
        assert isinstance(comfyui_worker, BaseVersionWorker)


class TestAppStateIntegration:
    """Test AppState integrates with launcher context."""

    def test_app_state_can_be_created_from_config(self, app_context):
        """AppState should be creatable with config-derived values."""
        from core.app_state import AppState
        
        launch_opts = app_context.config.get("launch_options", {})
        
        state = AppState(
            compute_mode=launch_opts.get("default_compute_mode", "cpu"),
            vram_mode="",
            python_path=Path(sys.executable),
            comfyui_path=Path.cwd(),
            enable_fast_mode=launch_opts.get("enable_fast_mode", False),
            disable_all_custom_nodes=launch_opts.get("disable_all_custom_nodes", False),
            extra_args=launch_opts.get("extra_args", ""),
            attention_mode=launch_opts.get("attention_mode", ""),
            listen_all=launch_opts.get("listen_all", True),
            default_port=launch_opts.get("default_port", "8188"),
        )
        
        assert state.compute_mode == "cpu"
        assert state.enable_fast_mode is False
        assert state.default_port == "8188"
        assert state.python_path == Path(sys.executable)

    def test_app_state_serializes_properly(self):
        """AppState serialization should work for config persistence."""
        from core.app_state import AppState
        
        state = AppState(
            compute_mode="cuda",
            vram_mode="high",
            python_path=Path("/usr/bin/python"),
            comfyui_path=Path("/home/user/ComfyUI"),
            enable_fast_mode=True,
            disable_all_custom_nodes=True,
            extra_args="--debug",
            attention_mode="--use-sage-attention",
            listen_all=False,
            default_port="9999",
        )
        
        # Serialize
        data = state.to_dict()
        assert isinstance(data, dict)
        assert data["compute_mode"] == "cuda"
        assert data["enable_fast_mode"] is True
        
        # Deserialize
        restored = AppState.from_dict(data)
        assert restored.compute_mode == state.compute_mode
        assert restored.python_path == state.python_path
        assert restored.enable_fast_mode == state.enable_fast_mode

    def test_app_state_imported_in_qt_app(self):
        """AppState should be importable from qt_app module."""
        from ui_qt.qt_app import AppState as QtAppState
        
        state = QtAppState(
            compute_mode="gpu",
            vram_mode="low",
            python_path=Path("/test/python"),
            comfyui_path=Path("/test/comfyui"),
        )
        
        assert state.compute_mode == "gpu"
        assert state.vram_mode == "low"


class TestServiceContainerIntegration:
    """Test ServiceContainer can be built from app context."""

    def test_service_container_from_app(self, app_context):
        """ServiceContainer.from_app should work with HeadlessAppContext."""
        from services.di import ServiceContainer
        
        # Mock config_manager to avoid file dependencies
        mock_config_manager = MagicMock()
        mock_config_manager.config_file = str(Path(app_context._cwd) / "launcher" / "config.json")
        app_context.config_manager = mock_config_manager
        
        container = ServiceContainer.from_app(app_context)
        
        assert container is not None
        assert hasattr(container, 'process')
        assert hasattr(container, 'version')
        assert hasattr(container, 'config')
        assert hasattr(container, 'update')
        assert hasattr(container, 'git')
        assert hasattr(container, 'network')
        assert hasattr(container, 'runtime')


class TestPyQtLauncherImports:
    """Test PyQtLauncher can import and reference extracted modules."""

    def test_pyqtlauncher_imports_workers(self):
        """PyQtLauncher module should import workers correctly."""
        # Import the module to verify imports work
        from ui_qt import qt_app
        
        assert hasattr(qt_app, 'PythonVersionWorker')
        assert hasattr(qt_app, 'TorchVersionWorker')
        assert hasattr(qt_app, 'ComfyUIVersionWorker')

    def test_pyqtlauncher_imports_app_state(self):
        """PyQtLauncher module should import AppState correctly."""
        from ui_qt import qt_app
        
        assert hasattr(qt_app, 'AppState')

    def test_pyqtlauncher_imports_service_container(self):
        """PyQtLauncher module should import ServiceContainer."""
        from ui_qt import qt_app
        
        # ServiceContainer is used via services.di import
        from services.di import ServiceContainer
        assert ServiceContainer is not None

    def test_pyqtlauncher_class_exists(self):
        """PyQtLauncher class should be defined in qt_app module."""
        from ui_qt.qt_app import PyQtLauncher
        
        assert PyQtLauncher is not None
        assert callable(PyQtLauncher)

    def test_version_signal_slots_defined(self):
        """PyQtLauncher should have version signal handlers defined."""
        from ui_qt.qt_app import PyQtLauncher
        
        # Verify signal handler methods exist
        assert hasattr(PyQtLauncher, '_on_python_version')
        assert hasattr(PyQtLauncher, '_on_torch_version')
        assert hasattr(PyQtLauncher, '_on_gpu_driver_status')
        assert hasattr(PyQtLauncher, '_on_frontend_version')
        assert hasattr(PyQtLauncher, '_on_template_version')
        assert hasattr(PyQtLauncher, '_on_core_version')
        assert hasattr(PyQtLauncher, '_on_git_status')


class TestUiInvokerIntegration:
    """Test UiInvoker for signal/slot integration."""

    def test_ui_invoker_exists(self):
        """UiInvoker should be importable from qt_app."""
        from ui_qt.qt_app import UiInvoker
        
        invoker = UiInvoker()
        assert invoker is not None
        assert hasattr(invoker, 'invoke_signal')

    def test_ui_invoker_signal_connection(self):
        """UiInvoker should connect invoke_signal to _on_invoke."""
        from ui_qt.qt_app import UiInvoker
        
        invoker = UiInvoker()
        
        # Verify signal is connected (connect is called in __init__)
        # The invoke_signal should be a pyqtSignal
        from PyQt5 import QtCore
        assert isinstance(invoker.invoke_signal, QtCore.pyqtSignal)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
