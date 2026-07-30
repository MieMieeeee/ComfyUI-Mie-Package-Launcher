"""Tests for core.cli.runner.

runner 是 CLI 命令（start / stop / status）和现有 GUI 启动 / 停止路径之间
的桥梁。它提供一个 PM shim（让 core.runner_start / core.runner_stop 可以
无修改调用）和几个面向子命令的高层函数。

约定：
- CliProcessManager 是 PM 替身，实现与 GUI ProcessManager 一样的
  接口（comfyui_process / on_start_success / on_start_failed）。
- start_service / stop_service / service_status 都返回 dict，
  不直接 print，调用方（cmd_*.py）决定如何渲染。
- 所有 IO 都走 HeadlessAppContext，不引入 PyQt 依赖。
"""
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.cli.runner import (
    CliProcessManager,
    start_service,
    stop_service,
    service_status,
    resolve_log_path,
)


# ---------- helpers ----------

def _make_app(tmp_path, *, port: str = "8188", has_config: bool = True):
    """Create a mock app with just enough surface for runner."""
    app = MagicMock()
    app._cwd = str(tmp_path)
    if has_config:
        app.config = {
            "paths": {
                "comfyui_root": str(tmp_path),
                "python_path": "python_embeded/python.exe",
            },
            "launch_options": {
                "default_port": port,
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
            "proxy_settings": {
                "hf_mirror_mode": "",
                "hf_mirror_url": "",
                "git_proxy_mode": "",
                "git_proxy_url": "",
            },
        }
    else:
        app.config = {}
    app.custom_port.get.return_value = port
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


# ---------- CliProcessManager ----------

class TestCliProcessManager:
    """CliProcessManager 是 core.runner_start 用的 PM 替身。"""

    def test_initially_pending(self):
        pm = CliProcessManager()
        assert pm.comfyui_process is None
        assert pm.start_outcome == "pending"
        assert pm.failure_reason is None

    def test_on_start_success_marks_success(self):
        pm = CliProcessManager()
        pm.on_start_success()
        assert pm.start_outcome == "success"
        assert pm.failure_reason is None
        # event 应立刻 set
        assert pm.wait_for_start(timeout=0.01) is True

    def test_on_start_failed_records_reason(self):
        pm = CliProcessManager()
        pm.on_start_failed("端口占用")
        assert pm.start_outcome == "failed"
        assert pm.failure_reason == "端口占用"
        assert pm.wait_for_start(timeout=0.01) is True

    def test_wait_times_out_when_never_called(self):
        pm = CliProcessManager()
        # 0.05s 内没人调用 on_start_* 就 timeout
        assert pm.wait_for_start(timeout=0.05) is False
        assert pm.start_outcome == "pending"

    def test_comfyui_process_settable_via_attribute(self):
        """_spawn_process 直接赋值 pm.comfyui_process = Popen(...)。"""
        pm = CliProcessManager()
        fake = MagicMock(pid=123)
        pm.comfyui_process = fake
        assert pm.comfyui_process is fake


# ---------- resolve_log_path ----------

class TestResolveLogPath:
    def test_comfyui_target_uses_paths_logs_file(self, tmp_path):
        """comfyui 日志走 utils.paths.logs_file，路径是 <root>/ComfyUI/user/comfyui.log。"""
        app = _make_app(tmp_path)
        p = resolve_log_path(app, "comfyui")
        assert p == tmp_path / "ComfyUI" / "user" / "comfyui.log"

    def test_launcher_target_under_launcher_dir(self, tmp_path):
        """launcher 日志路径固定在 <cwd>/launcher/launcher.log。"""
        app = _make_app(tmp_path)
        p = resolve_log_path(app, "launcher")
        assert p == tmp_path / "launcher" / "launcher.log"

    def test_unknown_target_returns_none(self, tmp_path):
        app = _make_app(tmp_path)
        assert resolve_log_path(app, "nope") is None

    def test_comfyui_target_with_empty_config_falls_back_to_cwd(self, tmp_path):
        """config 是空 dict 时仍返回一个 fallback 路径（cwd/ComfyUI/user/comfyui.log），不抛。"""
        app = _make_app(tmp_path, has_config=False)
        p = resolve_log_path(app, "comfyui")
        # 不抛异常，且是一个 Path 对象
        assert isinstance(p, Path)
        assert p.name == "comfyui.log"


# ---------- start_service ----------

class TestStartService:
    def test_already_running_returns_existing_pid(self, tmp_path):
        """pidfile 显示服务在跑时，start_service 不再启动新进程。"""
        app = _make_app(tmp_path)
        # 写一个 fresh pidfile（当前进程 PID）
        from core.cli.pidfile import default_path, write
        write(default_path(tmp_path), pid=os.getpid(), port=8188, log_path=None)

        with patch("core.cli.runner._is_http_reachable", return_value=True):
            result = start_service(app, no_wait=False, timeout=5)
        assert result["started"] is False
        assert result["pid"] == os.getpid()
        assert result["port"] == 8188
        # PID 活着 + HTTP 可达（mock）= ready
        assert result["ready"] is True

    def test_success_writes_pidfile_and_returns_ready(self, tmp_path):
        """成功启动后应写 pidfile，result 含 ready=True。"""
        app = _make_app(tmp_path)

        fake_proc = MagicMock(pid=88888)
        fake_proc.poll.return_value = None

        def fake_runner_start(a, pm, cmd, env, run_cwd, log_path=None):
            pm.comfyui_process = fake_proc
            pm.on_start_success()

        with patch("core.cli.runner.runner_start", side_effect=fake_runner_start), \
             patch("core.cli.runner.build_launch_params") as mock_build, \
             patch("core.cli.runner._resolve_log_path") as mock_log:
            # 让 build_launch_params 返回合法路径
            fake_py = tmp_path / "python.exe"
            fake_py.write_text("")
            fake_main = tmp_path / "main.py"
            fake_main.write_text("")
            mock_build.return_value = (
                ["python", str(fake_main)],
                {},
                str(tmp_path),
                fake_py,
                fake_main,
            )
            mock_log.return_value = tmp_path / "logs" / "x.log"

            result = start_service(app, no_wait=False, timeout=5)

        assert result["started"] is True
        assert result["pid"] == 88888
        assert result["port"] == 8188
        assert result["ready"] is True

        # pidfile 已写（用 is_stale 而不是 read，因为 mock PID 88888 假死）
        from core.cli.pidfile import default_path, is_stale
        # 文件存在且非 stale 意味着写过（write() 一定写盘）
        assert default_path(tmp_path).exists()

    def test_success_syncs_comfyui_button_to_running(self, tmp_path):
        """成功启动后应同步首页 ComfyUI 大按钮到"运行中" (回归).

        start_service 用 CliProcessManager (PM 替身), 它的 on_start_success 只 set event,
        不更新 app.big_btn. 结果从 WebUI 工作台"同时启动"调 start_service 时, ComfyUI
        起来了但首页大按钮一直卡在"启动中…". 修复: ready=True 时经 ui_post 投递
        _apply_comfyui_running_ui(True) 到主线程.
        """
        app = _make_app(tmp_path)
        # app 是 MagicMock, _apply_comfyui_running_ui / ui_post 自动存在; 但要确认
        # ui_post 被调用并投递了 fn. 让 ui_post 立即执行 fn 以便断言.
        posted = {"called": False, "running": None}

        def fake_ui_post(fn):
            posted["called"] = True
            try:
                fn()
            except Exception:
                pass

        app.ui_post = fake_ui_post
        app._apply_comfyui_running_ui = lambda running: posted.__setitem__("running", running)

        fake_proc = MagicMock(pid=88888)
        fake_proc.poll.return_value = None

        def fake_runner_start(a, pm, cmd, env, run_cwd, log_path=None):
            pm.comfyui_process = fake_proc
            pm.on_start_success()

        with patch("core.cli.runner.runner_start", side_effect=fake_runner_start), \
             patch("core.cli.runner.build_launch_params") as mock_build, \
             patch("core.cli.runner._resolve_log_path") as mock_log:
            fake_py = tmp_path / "python.exe"
            fake_py.write_text("")
            fake_main = tmp_path / "main.py"
            fake_main.write_text("")
            mock_build.return_value = (["python", str(fake_main)], {}, str(tmp_path), fake_py, fake_main)
            mock_log.return_value = tmp_path / "logs" / "x.log"

            start_service(app, no_wait=False, timeout=5)

        assert posted["called"], "应经 ui_post 投递 UI 同步"
        assert posted["running"] is True, "ready=True 应把大按钮同步到运行中"

    def test_not_ready_does_not_force_reset_button(self, tmp_path):
        """ready=False 时不强制重置大按钮 (进程可能仍在启动中).

        runner_start 的 120s 轮询可能跑赢 start_service 的 60s 等待, 此时 ready=False
        但 ComfyUI 仍在启动, 不应贸然把按钮重置为 idle. 仅 ready=True 才同步.
        """
        app = _make_app(tmp_path)
        posted = {"called": False}

        def fake_ui_post(fn):
            posted["called"] = True

        app.ui_post = fake_ui_post
        app._apply_comfyui_running_ui = MagicMock()

        fake_proc = MagicMock(pid=77777)
        fake_proc.poll.return_value = None

        def fake_runner_start(a, pm, cmd, env, run_cwd, log_path=None):
            pm.comfyui_process = fake_proc
            pm.on_start_failed("启动超时")  # ready=False

        with patch("core.cli.runner.runner_start", side_effect=fake_runner_start), \
             patch("core.cli.runner.build_launch_params") as mock_build, \
             patch("core.cli.runner._resolve_log_path") as mock_log:
            fake_py = tmp_path / "python.exe"
            fake_py.write_text("")
            fake_main = tmp_path / "main.py"
            fake_main.write_text("")
            mock_build.return_value = (["python", str(fake_main)], {}, str(tmp_path), fake_py, fake_main)
            mock_log.return_value = tmp_path / "logs" / "x.log"

            start_service(app, no_wait=False, timeout=5)

        assert posted["called"] is False, "ready=False 不应同步 UI (避免误重置)"

    def test_failure_returns_ready_false(self, tmp_path):
        """启动失败时 ready=False，pidfile 不应被写。"""
        app = _make_app(tmp_path)

        fake_proc = MagicMock(pid=77777)
        fake_proc.poll.return_value = None

        def fake_runner_start(a, pm, cmd, env, run_cwd, log_path=None):
            pm.comfyui_process = fake_proc
            pm.on_start_failed("端口占用")

        with patch("core.cli.runner.runner_start", side_effect=fake_runner_start), \
             patch("core.cli.runner.build_launch_params") as mock_build, \
             patch("core.cli.runner._resolve_log_path") as mock_log:
            fake_py = tmp_path / "python.exe"
            fake_py.write_text("")
            fake_main = tmp_path / "main.py"
            fake_main.write_text("")
            mock_build.return_value = ([], {}, str(tmp_path), fake_py, fake_main)
            mock_log.return_value = None

            result = start_service(app, no_wait=False, timeout=5)

        # started=True：本次调用确实 spawn 了进程
        # ready=False：进程没就绪就死了
        assert result["started"] is True
        assert result["pid"] == 77777
        assert result["ready"] is False

        # pidfile 不应被写
        from core.cli.pidfile import default_path
        assert not default_path(tmp_path).exists()

    def test_no_wait_returns_immediately_after_spawn(self, tmp_path):
        """--no-wait 时不等 /system_stats 就绪，立即返回 started=True。"""
        app = _make_app(tmp_path)

        fake_proc = MagicMock(pid=66666)
        fake_proc.poll.return_value = None

        def fake_runner_start(a, pm, cmd, env, run_cwd, log_path=None):
            pm.comfyui_process = fake_proc
            # 不调用 on_start_success：模拟 spawn 后还没就绪

        with patch("core.cli.runner.runner_start", side_effect=fake_runner_start), \
             patch("core.cli.runner.build_launch_params") as mock_build, \
             patch("core.cli.runner._resolve_log_path") as mock_log:
            fake_py = tmp_path / "python.exe"
            fake_py.write_text("")
            fake_main = tmp_path / "main.py"
            fake_main.write_text("")
            mock_build.return_value = ([], {}, str(tmp_path), fake_py, fake_main)
            mock_log.return_value = None

            t0 = time.time()
            result = start_service(app, no_wait=True, timeout=5)
            elapsed = time.time() - t0

        assert result["started"] is True
        assert result["pid"] == 66666
        assert result["ready"] is False  # 没等就绪
        # 应在 0.3s 内返回（远小于 fake_runner_start 的 0.5s sleep）
        assert elapsed < 0.3

    def test_python_missing_returns_error(self, tmp_path):
        """python 可执行文件不存在时返回 error。"""
        app = _make_app(tmp_path)

        with patch("core.cli.runner.build_launch_params") as mock_build:
            fake_py = tmp_path / "missing-python.exe"  # 不存在
            fake_main = tmp_path / "main.py"
            mock_build.return_value = ([], {}, str(tmp_path), fake_py, fake_main)

            result = start_service(app, no_wait=False, timeout=5)

        assert result["started"] is False
        assert result["ready"] is False
        assert "python" in (result.get("error") or "").lower() or \
               "not found" in (result.get("error") or "").lower()

    def test_main_py_missing_returns_error(self, tmp_path):
        """ComfyUI main.py 不存在时返回 error。"""
        app = _make_app(tmp_path)

        with patch("core.cli.runner.build_launch_params") as mock_build:
            fake_py = tmp_path / "python.exe"
            fake_py.write_text("")
            fake_main = tmp_path / "missing-main.py"  # 不存在
            mock_build.return_value = ([], {}, str(tmp_path), fake_py, fake_main)

            result = start_service(app, no_wait=False, timeout=5)

        assert result["started"] is False
        assert "main.py" in (result.get("error") or "").lower() or \
               "not found" in (result.get("error") or "").lower()


# ---------- stop_service ----------

class TestStopService:
    def test_stop_when_not_running_returns_stopped_false(self, tmp_path):
        """pidfile 不存在或 stale 时 stop 是 no-op，stopped=False。"""
        app = _make_app(tmp_path)

        with patch("core.cli.runner.runner_stop", return_value=False) as mock_stop:
            result = stop_service(app, timeout=5, force=False)

        assert result["stopped"] is False
        assert result["pid"] is None
        # runner_stop 不应被调用（连 PID 都没有）
        mock_stop.assert_not_called()

    def test_stop_clears_pidfile(self, tmp_path):
        """成功 stop 后应清理 pidfile。"""
        from core.cli.pidfile import default_path, write
        write(default_path(tmp_path), pid=os.getpid(), port=8188, log_path=None)

        app = _make_app(tmp_path)
        with patch("core.cli.runner.runner_stop", return_value=True):
            result = stop_service(app, timeout=5, force=False)

        assert result["stopped"] is True
        assert result["pid"] == os.getpid()
        # pidfile 应被删
        assert not default_path(tmp_path).exists()

    def test_stop_passes_force_flag(self, tmp_path):
        """--force 应被透传给 runner_stop。"""
        from core.cli.pidfile import default_path, write
        write(default_path(tmp_path), pid=os.getpid(), port=8188, log_path=None)

        app = _make_app(tmp_path)
        with patch("core.cli.runner.runner_stop", return_value=True) as mock_stop:
            stop_service(app, timeout=5, force=True)
        # runner_stop 收到 force=True（通过 app 的 _force attr 暴露）
        assert mock_stop.call_args is not None
        # 实际是 app._force = True
        assert getattr(app, "_force", False) is True


# ---------- service_status ----------

class TestServiceStatus:
    def test_status_running_true(self, tmp_path):
        """pidfile 显示服务在跑 + HTTP 可达 → running=True。"""
        from core.cli.pidfile import default_path, write
        write(default_path(tmp_path), pid=os.getpid(), port=8188, log_path=None)

        app = _make_app(tmp_path)
        with patch("core.cli.runner._is_http_reachable", return_value=True):
            result = service_status(app)

        assert result["running"] is True
        assert result["pid"] == os.getpid()
        assert result["port"] == 8188
        assert result["http_reachable"] is True
        assert result["url"] == "http://127.0.0.1:8188"

    def test_status_not_running(self, tmp_path):
        """pidfile 不存在 → running=False。"""
        app = _make_app(tmp_path)
        # mock 掉真实 HTTP 探活: 本机若正好有服务跑在 8188 (如开发时的 ComfyUI),
        # 会让 http_reachable=True 造成假阳性. running 由 pidfile 决定, 不依赖网络.
        with patch("core.cli.runner._is_http_reachable", return_value=False):
            result = service_status(app)
        assert result["running"] is False
        assert result["pid"] is None
        assert result["http_reachable"] is False
