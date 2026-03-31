"""Tests for core.runner_start subprocess spawning module."""

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest


class TestStartFunction:
    """Tests for the start() function."""

    @pytest.fixture
    def mock_app(self):
        """Mock app object."""
        app = MagicMock()
        app.big_btn = MagicMock()
        app._launching = False
        app.logger = MagicMock()
        return app

    @pytest.fixture
    def mock_pm(self):
        """Mock process manager."""
        pm = MagicMock()
        pm.comfyui_process = None
        pm.on_start_success = MagicMock()
        pm.on_start_failed = MagicMock()
        return pm

    @pytest.fixture
    def mock_popen(self):
        """Mock subprocess.Popen."""
        with patch("core.runner_start.subprocess.Popen") as mock:
            yield mock

    @pytest.fixture
    def mock_thread(self):
        """Mock threading.Thread to capture worker function."""
        with patch("core.runner_start.threading.Thread") as mock:
            yield mock

    def test_start_sets_app_state(self, mock_app, mock_pm, mock_thread):
        """start() sets UI state before spawning thread."""
        mock_thread_instance = MagicMock()
        mock_thread.return_value = mock_thread_instance

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {"ENV": "val"}, "/cwd")

        assert mock_app.big_btn.set_state.call_args[0][0] == "starting"
        assert mock_app.big_btn.set_display.call_args[0][0] == "启动中…"
        assert mock_app.big_btn.set_display.call_args[0][1] == "点击停止"
        assert mock_app._launching is True

    def test_start_creates_daemon_thread(self, mock_app, mock_pm, mock_thread):
        """start() creates daemon thread with worker target."""
        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {"ENV": "val"}, "/cwd")

        mock_thread.assert_called_once()
        call_kwargs = mock_thread.call_args[1]
        assert call_kwargs["daemon"] is True
        assert callable(call_kwargs["target"])

    def test_popen_called_with_correct_args_unix(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Popen receives correct cmd, env, cwd on Unix (posix)."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        from core.runner_start import start

        start(mock_app, mock_pm, ["python", "script.py"], {"KEY": "val"}, "/workdir")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_popen.assert_called_once_with(
            ["python", "script.py"],
            env={"KEY": "val"},
            cwd="/workdir",
        )

    def test_popen_called_with_correct_args_windows(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Popen receives startupinfo and CREATE_NEW_CONSOLE on Windows (nt)."""
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(subprocess, "CREATE_NEW_CONSOLE", 0x10, raising=False)
        monkeypatch.setattr(subprocess, "STARTUPINFO", MagicMock, raising=False)
        monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x4, raising=False)
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        from core.runner_start import start

        start(mock_app, mock_pm, ["python", "script.py"], {"KEY": "val"}, "/workdir")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args[1]
        assert "creationflags" in call_kwargs
        assert call_kwargs["creationflags"] == 0x10
        assert "startupinfo" in call_kwargs

    def test_success_path_calls_on_start_success(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Process still running calls on_start_success via ui_post."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_app.ui_post.assert_called_with(mock_pm.on_start_success)

    def test_failure_path_calls_on_start_failed(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Process exit calls on_start_failed with '进程退出'."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = 1
        mock_popen.return_value = mock_process

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_app.ui_post.assert_called_once()
        callback = mock_app.ui_post.call_args[0][0]
        callback()
        mock_pm.on_start_failed.assert_called_once_with("进程退出")

    def test_exception_path_calls_on_start_failed(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Popen exception calls on_start_failed with error message."""
        monkeypatch.setattr(os, "name", "posix")
        mock_popen.side_effect = OSError("Permission denied")

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_app.ui_post.assert_called_once()
        callback = mock_app.ui_post.call_args[0][0]
        callback()
        mock_pm.on_start_failed.assert_called_once_with("Permission denied")

    def test_worker_falls_back_to_root_after_when_ui_post_raises(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_app.ui_post.side_effect = RuntimeError("ui unavailable")
        mock_app.root = MagicMock()

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        mock_app.root.after.assert_called_once()
        mock_app.root.after.assert_called_with(0, mock_pm.on_start_success)

    def test_env_and_cwd_passed_to_popen(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """env and cwd are correctly passed to subprocess.Popen."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        test_env = {"COMFYUI_DIR": "/opt/ComfyUI", "PYTHONPATH": "/custom"}
        test_cwd = "/mnt/models"

        from core.runner_start import start

        start(mock_app, mock_pm, ["python", "main.py"], test_env, test_cwd)

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs["env"] == test_env
        assert call_kwargs["cwd"] == test_cwd

    def test_pm_comfyui_process_set(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """pm.comfyui_process is set to the Popen result."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        assert mock_pm.comfyui_process is mock_process

    def test_cwd_logged_if_possible(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """cwd is logged if logger doesn't raise."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_app.logger.info = MagicMock()

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/custom/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        assert any("/custom/cwd" in str(c) for c in mock_app.logger.info.call_args_list)

    def test_logger_exception_does_not_crash_worker(
        self, mock_app, mock_pm, mock_popen, mock_thread, monkeypatch
    ):
        """Logger exception is silently caught."""
        monkeypatch.setattr(os, "name", "posix")
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        mock_app.logger.info.side_effect = Exception("Log failed")

        from core.runner_start import start

        start(mock_app, mock_pm, ["cmd"], {}, "/cwd")

        worker_func = mock_thread.call_args[1]["target"]
        worker_func()

        assert mock_pm.comfyui_process is not None
