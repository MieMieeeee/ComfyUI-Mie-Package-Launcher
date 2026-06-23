"""Tests for core.cli.cmd_start."""
from unittest.mock import MagicMock, patch

import pytest

from core.cli.exitcodes import EXIT_OK, EXIT_ALREADY_RUNNING, EXIT_ERROR
from core.cli import cmd_start


def _args(no_wait: bool = False, timeout: int = 60, json: bool = False):
    a = MagicMock()
    a.no_wait = no_wait
    a.timeout = timeout
    a.json = json
    a.verbose = 0
    return a


def _app():
    return MagicMock()


def _ok_result(pid=1234, port=8188, ready=True):
    return {
        "started": True, "pid": pid, "port": port,
        "url": f"http://127.0.0.1:{port}", "ready": ready,
        "elapsed_sec": 3.2,
        "log_path": "C:/ComfyUI/user/comfyui.log",
    }


def _already_running_result(pid=1234, port=8188, ready=True):
    return {
        "started": False, "pid": pid, "port": port,
        "url": f"http://127.0.0.1:{port}", "ready": ready,
        "elapsed_sec": 0.1,
        "log_path": None,
        "since": "2026-06-23T10:00:00+00:00",
    }


class TestStartSuccess:
    def test_success_returns_exit_ok(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_start.start_service", return_value=_ok_result()):
            rc = cmd_start.run(args, app)
        assert rc == EXIT_OK
        captured = capsys.readouterr()
        # human 模式输出
        assert "started" in captured.out
        assert "1234" in captured.out

    def test_no_wait_passes_through(self):
        args = _args(no_wait=True)
        app = _app()
        with patch("core.cli.cmd_start.start_service", return_value=_ok_result(ready=False)) as mock_svc:
            cmd_start.run(args, app)
        # start_service 收到的 no_wait=True
        assert mock_svc.call_args.kwargs.get("no_wait") is True

    def test_timeout_passes_through(self):
        args = _args(timeout=30)
        app = _app()
        with patch("core.cli.cmd_start.start_service", return_value=_ok_result()) as mock_svc:
            cmd_start.run(args, app)
        assert mock_svc.call_args.kwargs.get("timeout") == 30

    def test_json_output(self, capsys):
        args = _args(json=True)
        app = _app()
        with patch("core.cli.cmd_start.start_service", return_value=_ok_result()):
            cmd_start.run(args, app)
        import json
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["started"] is True
        assert parsed["pid"] == 1234


class TestStartAlreadyRunning:
    def test_returns_exit_2(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_start.start_service", return_value=_already_running_result()):
            rc = cmd_start.run(args, app)
        assert rc == EXIT_ALREADY_RUNNING


class TestStartFailed:
    def test_returns_exit_1_on_error(self, capsys):
        args = _args()
        app = _app()
        fail_result = {**_ok_result(ready=False), "started": False, "error": "启动失败"}
        with patch("core.cli.cmd_start.start_service", return_value=fail_result):
            rc = cmd_start.run(args, app)
        assert rc == EXIT_ERROR
