"""Tests for core.cli.cmd_restart."""
import json
from unittest.mock import MagicMock, patch

import pytest

from core.cli.exitcodes import EXIT_OK, EXIT_ALREADY_RUNNING, EXIT_ERROR
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


def _stale_old_instance_result():
    """stop 没停掉（收养前）+ start 收养拒绝的返回形态——2026-11-05 事故实录。

    旧实例占着 8188 应答探针：ready=true 但进程根本没换。"""
    return {
        "started": False, "ready": True,
        "elapsed_sec": 3.2,
        "pid": 44288, "port": 8188,
        "url": "http://127.0.0.1:8188",
        "log_path": "C:/ComfyUI/user/comfyui.log",
        "since": "2026-11-05T10:00:00",
        "running_env_id": "env_default",
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


class TestRestartSwapVerification:
    """退出码语义收紧（2026-11-05 缺陷报告）：ready=true 绝不能掩盖「没换进程」。"""

    def test_stale_old_instance_returns_already_running_not_ok(self, capsys):
        """旧实例仍在应答（started:false + ready:true + pid）→ 退出码 2，不是 0。

        事故形态：restart 返回 0，调用方以为代码换上了，实际整晚跑旧代码。"""
        args = _args(json=True)
        app = _app()
        with patch("core.cli.cmd_restart.stop_service", return_value={"stopped": False, "pid": None, "elapsed_sec": 0.0}), \
             patch("core.cli.cmd_restart.start_service", return_value=_stale_old_instance_result()):
            rc = cmd_restart.run(args, app)

        assert rc == EXIT_ALREADY_RUNNING
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert out["started"] is False
        assert out["pid"] == 44288
        assert out["running_env_id"] == "env_default"  # 拒绝原因透传
        assert "error" not in out

    def test_start_error_propagates_and_returns_exit_error(self, capsys):
        """start 带明确 error（环境冲突 / bind 失败）→ 退出码 1 + error 透传。"""
        args = _args(json=True)
        app = _app()
        fail = {
            "started": True, "ready": False, "pid": 75820, "port": 8188,
            "url": "http://127.0.0.1:8188", "log_path": None,
            "elapsed_sec": 3.0,
            "error": "端口 8188 未由本进程（pid 75820）监听，当前监听者 pid 44288",
        }
        with patch("core.cli.cmd_restart.stop_service", return_value={"stopped": False, "pid": None, "elapsed_sec": 0.0}), \
             patch("core.cli.cmd_restart.start_service", return_value=fail):
            rc = cmd_restart.run(args, app)

        assert rc == EXIT_ERROR
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert "44288" in out["error"]

    def test_stopped_pid_included_in_output(self, capsys):
        """stop 杀掉的 pid 应以 stopped_pid 出现（调用方要知道谁被换了下去）。"""
        args = _args(json=True)
        app = _app()
        with patch("core.cli.cmd_restart.stop_service", return_value={"stopped": True, "pid": 44288, "elapsed_sec": 1.0}), \
             patch("core.cli.cmd_restart.start_service", return_value=_ok_result()):
            rc = cmd_restart.run(args, app)

        assert rc == EXIT_OK
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert out["stopped_pid"] == 44288

    def test_human_mode_prints_swap_failure_line(self, capsys):
        """人类通道必须显式说「重启未生效」，不能让人从两行 bool 里自己猜。"""
        args = _args(json=False)
        app = _app()
        with patch("core.cli.cmd_restart.stop_service", return_value={"stopped": False, "pid": None, "elapsed_sec": 0.0}), \
             patch("core.cli.cmd_restart.start_service", return_value=_stale_old_instance_result()):
            rc = cmd_restart.run(args, app)

        assert rc == EXIT_ALREADY_RUNNING
        out = capsys.readouterr().out
        assert "重启未生效" in out
        assert "44288" in out

    def test_json_mode_keeps_single_line_contract(self, capsys):
        """--json 是单行 JSON 契约：失败提示不得混进 stdout 多打一行。"""
        args = _args(json=True)
        app = _app()
        with patch("core.cli.cmd_restart.stop_service", return_value={"stopped": False, "pid": None, "elapsed_sec": 0.0}), \
             patch("core.cli.cmd_restart.start_service", return_value=_stale_old_instance_result()):
            cmd_restart.run(args, app)

        lines = [l for l in capsys.readouterr().out.strip().splitlines() if l]
        assert len(lines) == 1
        json.loads(lines[0])  # 单行且可解析
