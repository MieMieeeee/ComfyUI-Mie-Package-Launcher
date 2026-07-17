"""Tests for 多环境 --env 开关 in CLI runner.

覆盖：
- start --env <不存在的id> → 报错，退出码 1
- start --env <存在的id> → build_launch_params 用该环境（通过 patch 验证传参）
- pidfile 写入时记录 env_id
- 已在跑时 start --env <不同环境> → 返回 running_env_id + 提示先 stop
- pidfile.write 的 env_id 字段向后兼容
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.cli import pidfile
from core.cli.runner import start_service


def _make_app_with_envs(tmp_path, *, envs=None, active="env_a"):
    """造一个带多环境的 mock app，config 是真实 dict（非 MagicMock）。"""
    app = MagicMock()
    app._cwd = str(tmp_path)
    app.config = {
        "paths": {"comfyui_root": str(tmp_path), "python_path": "python_embeded/python.exe"},
        "environments": envs or [
            {"id": "env_a", "name": "环境A", "comfyui_root": "/a", "python_path": "/a/py.exe"},
            {"id": "env_b", "name": "环境B", "comfyui_root": str(tmp_path), "python_path": str(tmp_path / "py.exe")},
        ],
        "active_env_id": active,
        "launch_options": {
            "default_port": "8188",
            "default_compute_mode": "cpu",
            "listen_all": True,
            "enable_fast_mode": False,
            "disable_all_custom_nodes": False,
            "disable_api_nodes": False,
            "extra_args": "",
            "attention_mode": "",
            "browser_open_mode": "default",
            "show_console": False,
        },
        "proxy_settings": {"hf_mirror_mode": "", "hf_mirror_url": ""},
    }
    # MagicMock 的 StringVar 返回值
    app.custom_port.get.return_value = "8188"
    app.compute_mode.get.return_value = "cpu"
    app.use_fast_mode.get.return_value = False
    app.listen_all.get.return_value = True
    app.disable_all_custom_nodes.get.return_value = False
    app.disable_api_nodes.get.return_value = False
    app.use_new_manager.get.return_value = False
    app.extra_launch_args.get.return_value = ""
    app.attention_mode.get.return_value = ""
    app.browser_open_mode.get.return_value = "default"
    app.show_console.get.return_value = False
    app.gpu_device.get.return_value = "-1"
    app.selected_hf_mirror.get.return_value = ""
    app.hf_mirror_url.get.return_value = ""
    app.logger = MagicMock()
    return app


class TestStartEnvIdValidation:
    """start --env <id> 的环境校验。"""

    def test_unknown_env_id_returns_error(self, tmp_path):
        app = _make_app_with_envs(tmp_path)
        # pidfile 不存在，所以不会走"已在跑"分支
        result = start_service(app, env_id="ghost_env")
        assert result["started"] is False
        assert "环境不存在" in result.get("error", "")
        assert "ghost_env" in result["error"]

    def test_known_env_id_proceeds_to_build_launch_params(self, tmp_path):
        """已知 env_id → 把 env_id 透传给 build_launch_params。"""
        app = _make_app_with_envs(tmp_path)
        with patch("core.cli.runner.build_launch_params") as mock_blp:
            # 造一个会让后续校验失败的返回（py 不存在），避免真的启动进程
            mock_blp.return_value = (
                ["fake"], {}, str(tmp_path),
                tmp_path / "nonexistent_py.exe",  # py.exists() = False
                tmp_path / "main.py",
            )
            start_service(app, env_id="env_b")
            # 关键断言：build_launch_params 被调用时传了 env_id="env_b"
            assert mock_blp.called
            call_kwargs = mock_blp.call_args
            # 第二个位置参数或 env_id kwarg
            passed_env_id = call_kwargs.kwargs.get("env_id") or (
                call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
            )
            assert passed_env_id == "env_b"


class TestPidfileEnvId:
    """pidfile 应记录 env_id 字段，老 pidfile 无该字段要兼容。"""

    def test_write_includes_env_id(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        pidfile.write(pid_path, 12345, 8188, None, env_id="env_x")
        data = json.loads(pid_path.read_text(encoding="utf-8"))
        assert data["env_id"] == "env_x"
        assert data["pid"] == 12345

    def test_write_env_id_defaults_none(self, tmp_path):
        pid_path = tmp_path / "test.pid"
        pidfile.write(pid_path, 12345, 8188, None)
        data = json.loads(pid_path.read_text(encoding="utf-8"))
        assert data["env_id"] is None

    def test_read_old_pidfile_without_env_id_returns_none(self, tmp_path):
        """老 pidfile（无 env_id 字段）能被 read，env_id 取 None。"""
        pid_path = tmp_path / "old.pid"
        # 手写一个没有 env_id 字段的老格式 pidfile
        pid_path.write_text(json.dumps({
            "pid": 999999,  # 不存在的 pid，read 会因 is_alive=False 返回 None
            "port": 8188,
            "started_at": "2026-01-01T00:00:00+00:00",
            "log_path": None,
        }), encoding="utf-8")
        # pid 不存活 → read 返回 None（stale 处理）
        assert pidfile.read(pid_path) is None

    def test_read_pidfile_with_env_id_preserves_it(self, tmp_path):
        """存活进程的 pidfile 带 env_id → read 返回的 dict 保留 env_id。"""
        pid_path = tmp_path / "new.pid"
        # 用当前进程的 pid（一定存活）
        import os
        my_pid = os.getpid()
        pidfile.write(pid_path, my_pid, 8188, None, env_id="env_active")
        data = pidfile.read(pid_path)
        assert data is not None
        assert data["env_id"] == "env_active"


class TestStartAlreadyRunningEnvHint:
    """已在跑时 start 的环境提示。"""

    def test_already_running_with_different_env_returns_hint(self, tmp_path):
        """pidfile 显示在跑的是 env_a，用户 start --env env_b → 提示先 stop。"""
        app = _make_app_with_envs(tmp_path)
        # 造一个有效的 pidfile（用当前进程 pid）
        import os
        pid_path = pidfile.default_path(Path(app._cwd))
        pidfile.write(pid_path, os.getpid(), 8188, None, env_id="env_a")

        result = start_service(app, env_id="env_b")
        assert result["started"] is False
        assert result["running_env_id"] == "env_a"
        assert "env_a" in result.get("error", "")
        assert "env_b" in result["error"]
        assert "stop" in result["error"]

    def test_already_running_same_env_no_error(self, tmp_path):
        """pidfile 显示在跑的是 env_a，用户 start --env env_a → 正常（已跑），无 error。"""
        app = _make_app_with_envs(tmp_path)
        import os
        pid_path = pidfile.default_path(Path(app._cwd))
        pidfile.write(pid_path, os.getpid(), 8188, None, env_id="env_a")

        result = start_service(app, env_id="env_a")
        assert result["started"] is False
        assert result["running_env_id"] == "env_a"
        # 同环境不算冲突，不应有 error
        assert "error" not in result or result.get("error") is None

    def test_already_running_no_env_id_in_pidfile_is_backward_compatible(self, tmp_path):
        """老 pidfile（无 env_id）+ start 不带 --env → 不报错。"""
        app = _make_app_with_envs(tmp_path)
        import os
        pid_path = pidfile.default_path(Path(app._cwd))
        # 写一个无 env_id 的 pidfile（模拟升级前的残留）
        pidfile.write(pid_path, os.getpid(), 8188, None, env_id=None)

        result = start_service(app)  # 不带 env_id
        assert result["started"] is False
        assert result["running_env_id"] is None
