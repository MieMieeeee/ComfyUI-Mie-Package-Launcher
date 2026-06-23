"""Tests for core.cli.cmd_status.

status 子命令：调 runner.service_status，按 --json 选输出格式，
按 running 状态返回 EXIT_OK / EXIT_NOT_RUNNING。
"""
from unittest.mock import MagicMock, patch

import pytest

from core.cli.exitcodes import EXIT_OK, EXIT_NOT_RUNNING, EXIT_ERROR
from core.cli import cmd_status


def _args(json: bool = False):
    a = MagicMock()
    a.json = json
    a.verbose = 0
    return a


def _app():
    return MagicMock()


class TestStatusRunning:
    def test_returns_exit_ok_when_running(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_status.service_status") as mock_svc:
            mock_svc.return_value = {
                "running": True, "pid": 1234, "port": 8188,
                "url": "http://127.0.0.1:8188", "http_reachable": True,
                "log_path": "/tmp/x.log", "since": "2026-06-23T10:00:00+00:00",
            }
            rc = cmd_status.run(args, app)

        assert rc == EXIT_OK
        captured = capsys.readouterr()
        # human 模式：key: value 行
        assert "running" in captured.out
        assert "1234" in captured.out
        assert "8188" in captured.out

    def test_json_output_when_flag(self, capsys):
        args = _args(json=True)
        app = _app()
        with patch("core.cli.cmd_status.service_status") as mock_svc:
            mock_svc.return_value = {
                "running": True, "pid": 5678, "port": 8188,
                "url": "http://127.0.0.1:8188", "http_reachable": True,
                "log_path": None, "since": None,
            }
            rc = cmd_status.run(args, app)

        assert rc == EXIT_OK
        captured = capsys.readouterr()
        # JSON 模式
        import json
        parsed = json.loads(captured.out)
        assert parsed["running"] is True
        assert parsed["pid"] == 5678


class TestStatusNotRunning:
    def test_returns_exit_3_when_not_running(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_status.service_status") as mock_svc:
            mock_svc.return_value = {
                "running": False, "pid": None, "port": 8188,
                "url": "http://127.0.0.1:8188", "http_reachable": False,
                "log_path": None, "since": None,
            }
            rc = cmd_status.run(args, app)

        assert rc == EXIT_NOT_RUNNING


class TestStatusError:
    def test_returns_exit_1_on_exception(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_status.service_status") as mock_svc:
            mock_svc.side_effect = RuntimeError("probe failed")
            rc = cmd_status.run(args, app)

        assert rc == EXIT_ERROR
        captured = capsys.readouterr()
        # error 信息应被人看到
        assert "probe failed" in captured.out or "probe failed" in captured.err
