"""Tests for core.cli.cmd_restart."""
from unittest.mock import MagicMock, patch

import pytest

from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli import cmd_restart


def _args(no_wait: bool = False, timeout: int = 60, json: bool = False):
    a = MagicMock()
    a.no_wait = no_wait
    a.timeout = timeout
    a.json = json
    a.verbose = 0
    return a


def _app():
    return MagicMock()


def _ok_result():
    return {
        "stopped": True, "started": True, "ready": True,
        "elapsed_sec": 5.0,
        "pid": 1234, "port": 8188,
        "url": "http://127.0.0.1:8188",
        "log_path": "C:/ComfyUI/user/comfyui.log",
    }


class TestRestart:
    def test_stop_then_start_called(self):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_restart.stop_service", return_value={"stopped": True, "pid": 1, "elapsed_sec": 1.0}), \
             patch("core.cli.cmd_restart.start_service", return_value=_ok_result()) as mock_start:
            cmd_restart.run(args, app)
        assert mock_start.called

    def test_success_returns_exit_ok(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_restart.stop_service", return_value={"stopped": True, "pid": 1, "elapsed_sec": 1.0}), \
             patch("core.cli.cmd_restart.start_service", return_value=_ok_result()):
            rc = cmd_restart.run(args, app)
        assert rc == EXIT_OK

    def test_start_failure_returns_exit_error(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_restart.stop_service", return_value={"stopped": True, "pid": 1, "elapsed_sec": 1.0}), \
             patch("core.cli.cmd_restart.start_service", return_value={"started": False, "ready": False, "error": "x"}):
            rc = cmd_restart.run(args, app)
        assert rc == EXIT_ERROR

    def test_no_stop_when_not_running(self):
        """之前没在跑时直接 start，不算错误。"""
        args = _args()
        app = _app()
        with patch("core.cli.cmd_restart.stop_service", return_value={"stopped": False, "pid": None, "elapsed_sec": 0.0}), \
             patch("core.cli.cmd_restart.start_service", return_value=_ok_result()) as mock_start:
            rc = cmd_restart.run(args, app)
        assert rc == EXIT_OK
        assert mock_start.called
