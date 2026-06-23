"""Tests for core.cli.cmd_stop."""
from unittest.mock import MagicMock, patch

import pytest

from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli import cmd_stop


def _args(timeout: int = 10, force: bool = False, json: bool = False):
    a = MagicMock()
    a.timeout = timeout
    a.force = force
    a.json = json
    a.verbose = 0
    return a


def _app():
    return MagicMock()


def _ok_result(stopped=True, pid=1234):
    return {"stopped": stopped, "pid": pid, "elapsed_sec": 1.5}


def _noop_result():
    return {"stopped": False, "pid": None, "elapsed_sec": 0.05}


class TestStopSuccess:
    def test_stop_returns_exit_ok(self, capsys):
        args = _args()
        app = _app()
        with patch("core.cli.cmd_stop.stop_service", return_value=_ok_result()):
            rc = cmd_stop.run(args, app)
        assert rc == EXIT_OK
        captured = capsys.readouterr()
        assert "stopped" in captured.out
        assert "1234" in captured.out

    def test_timeout_and_force_passed_through(self):
        args = _args(timeout=20, force=True)
        app = _app()
        with patch("core.cli.cmd_stop.stop_service", return_value=_ok_result()) as mock_svc:
            cmd_stop.run(args, app)
        assert mock_svc.call_args.kwargs.get("timeout") == 20
        assert mock_svc.call_args.kwargs.get("force") is True

    def test_no_op_when_not_running(self, capsys):
        """未运行时 stop 是 no-op，仍返回 0。"""
        args = _args()
        app = _app()
        with patch("core.cli.cmd_stop.stop_service", return_value=_noop_result()):
            rc = cmd_stop.run(args, app)
        assert rc == EXIT_OK
