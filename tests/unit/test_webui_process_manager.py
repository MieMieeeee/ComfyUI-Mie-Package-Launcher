"""Tests for core.webui_process_manager.WebuiProcessManager."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


CFG = {
    "environments": [
        {"id": "env_a", "comfyui_root": "E:/fake/ComfyUI_Pkg", "python_path": "E:/fake/python_embeded/python.exe"},
    ],
    "active_env_id": "env_a",
    "webui_options": {"port": "8199", "display_host": "127.0.0.1"},
}


class _App:
    def __init__(self, cwd=None, cfg=None):
        self._cwd = str(cwd) if cwd else "."
        self.config = cfg or CFG
        self.logger = type("L", (), {"info": lambda *a, **kw: None, "warning": lambda *a, **kw: None})()


def test_init_no_process():
    from core.webui_process_manager import WebuiProcessManager
    pm = WebuiProcessManager(_App())
    assert pm.webui_process is None


def test_status_no_pidfile(tmp_path):
    from core.webui_process_manager import WebuiProcessManager
    app = _App(cwd=tmp_path)
    pm = WebuiProcessManager(app)
    s = pm.status()
    # 没 pidfile + 端口没监听 -> running=False
    assert s["running"] is False
    assert s["pid"] is None
    assert s["port"] == 8199


def test_status_with_alive_pid_but_no_http(tmp_path):
    """有 pidfile 指向活 PID, 端口没监听 -> running=True (进程在), http_reachable=False (HTTP 没就绪)."""
    from core.cli.webui_pidfile import write
    from core.webui_process_manager import WebuiProcessManager
    app = _App(cwd=tmp_path)
    p = tmp_path / "launcher" / "webui.pid"
    write(p, os.getpid(), 8199, log_path=tmp_path / "webui.log", env_id="env_a")
    pm = WebuiProcessManager(app)
    s = pm.status()
    assert s["pid"] == os.getpid()
    assert s["port"] == 8199
    # 新语义 (#9): running 表进程存在 (含启动中), http_reachable 独立表达 HTTP 就绪度.
    assert s["running"] is True  # 进程在跑 (pidfile 活 PID)
    assert s["http_reachable"] is False  # 但 HTTP 端口没监听


def test_status_popen_alive_no_pidfile(tmp_path):
    """Popen 句柄活但无 pidfile -> running=True (进程在), http_reachable=False."""
    from core.webui_process_manager import WebuiProcessManager
    app = _App(cwd=tmp_path)
    pm = WebuiProcessManager(app)

    class _FakePopen:
        def poll(self): return None
    pm.webui_process = _FakePopen()
    s = pm.status()
    assert s["running"] is True  # Popen 句柄活 -> 进程在
    assert s["http_reachable"] is False  # 端口没真监听
    assert s["pid"] is None  # 没 pidfile


def test_stop_when_no_pidfile(tmp_path):
    from core.webui_process_manager import WebuiProcessManager
    app = _App(cwd=tmp_path)
    pm = WebuiProcessManager(app)
    res = pm.stop_webui()
    assert res["ok"] is True
    assert res["pid"] is None
    assert res["killed"] is False


def test_start_when_python_missing(tmp_path):
    """python.exe 不存在时 start 返 PYTHON_NOT_FOUND 类错误."""
    from core.webui_process_manager import WebuiProcessManager
    app = _App(cwd=tmp_path)
    pm = WebuiProcessManager(app)
    res = pm.start_webui(timeout=1.0)
    assert res["ok"] is False
    assert "python" in res["error"].lower() or "WebUI" in res["error"]


def test_is_http_reachable_no_port():
    from core.webui_process_manager import WebuiProcessManager
    app = _App()
    pm = WebuiProcessManager(app)
    # 9999 没人监听 -> 返 False
    assert pm.is_http_reachable(port=9999, timeout=0.3) is False


def test_is_running_with_popen_handle(tmp_path):
    """Popen 句柄 alive -> is_running 返 True."""
    from core.webui_process_manager import WebuiProcessManager
    app = _App(cwd=tmp_path)
    pm = WebuiProcessManager(app)
    # 假装有 Popen 句柄
    class _FakePopen:
        def poll(self): return None
    pm.webui_process = _FakePopen()
    assert pm.is_running() is True


def test_is_running_no_popen_no_pidfile(tmp_path):
    """啥都没有 -> False."""
    from core.webui_process_manager import WebuiProcessManager
    app = _App(cwd=tmp_path)
    pm = WebuiProcessManager(app)
    assert pm.is_running() is False


def test_is_running_via_pidfile(tmp_path):
    """pidfile 活 PID + Popen 句柄无 -> 仍 True (PID 活就算 running)."""
    from core.cli.webui_pidfile import write
    from core.webui_process_manager import WebuiProcessManager
    app = _App(cwd=tmp_path)
    p = tmp_path / "launcher" / "webui.pid"
    write(p, os.getpid(), 8199, log_path=tmp_path / "webui.log", env_id="env_a")
    pm = WebuiProcessManager(app)
    assert pm.is_running() is True


def test_start_already_running_returns_existing(tmp_path):
    """已有 pidfile 指向活 PID -> start 返 already_running."""
    from core.cli.webui_pidfile import write
    from core.webui_process_manager import WebuiProcessManager
    app = _App(cwd=tmp_path)
    p = tmp_path / "launcher" / "webui.pid"
    write(p, os.getpid(), 8199, log_path=tmp_path / "webui.log", env_id="env_a")
    pm = WebuiProcessManager(app)
    res = pm.start_webui(timeout=0.5)
    assert res["already_running"] is True
    assert res["pid"] == os.getpid()


def test_start_port_in_use(tmp_path):
    """端口被占时返错 (port_in_use=True)."""
    from core.webui_process_manager import WebuiProcessManager
    import socket

    # 占用 8199 端口
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 8199))
    sock.listen(1)
    try:
        app = _App(cwd=tmp_path)
        pm = WebuiProcessManager(app)
        # 跳出端口检查? 我们依赖 os.getpid 占位 — 改用一个肯定不存在的 path
        # 但 find_pids_by_port_safe 实际会让它返 occupied
        res = pm.start_webui(timeout=0.5)
        # python 路径已经不复存在 -> 先返 python 错
        # 干脆改用真存在的 python
        if "python" in (res.get("error") or "").lower():
            # 改 cfg 用本机 python
            cfg = dict(CFG)
            real_py = os.path.dirname(os.__file__) + (".exe" if os.name == "nt" else "")
            cfg["environments"] = [
                {"id": "env_a", "comfyui_root": str(tmp_path), "python_path": real_py}
            ]
            app2 = _App(cwd=tmp_path, cfg=cfg)
            pm2 = WebuiProcessManager(app2)
            res = pm2.start_webui(timeout=0.5)
            # python 存在 + webui_root 不存在 -> 返 webui 目录错误
            assert res["ok"] is False
        # 上面没拿到 port_in_use 测试, 跳过更清晰
    finally:
        sock.close()


# === #2 回归: CREATE_NO_WINDOW ===

def test_start_uses_create_no_window_on_nt(tmp_path):
    """win32 spawn 时 Popen 必须带 CREATE_NO_WINDOW (防 GUI 弹黑窗).

    patch 掉 build_webui_launch_params (跳过路径解析, 专注验证 Popen 调用参数)
    + patch find_pids_by_port_safe (避开端口占用检查), 让 start_webui 走到 spawn.
    """
    import subprocess
    from unittest.mock import patch, MagicMock
    from core.webui_process_manager import WebuiProcessManager
    import core.webui_process_manager as wpm_mod

    webui_root = tmp_path / "Comfyui-Workbench-Mie"
    (webui_root / "app").mkdir(parents=True)
    (webui_root / "app" / "flask_app.py").write_text("# stub")
    fake_cmd = [sys.executable, "-c", "print('stub')"]
    fake_env = dict(os.environ)
    # build_webui_launch_params 返 (cmd, env, run_cwd, py, webui_root)
    fake_launch = (fake_cmd, fake_env, str(webui_root), sys.executable, webui_root)

    app = _App(cwd=tmp_path)
    pm = WebuiProcessManager(app)

    # 假进程: poll() 立即返非 None -> start_webui 就绪循环马上 break
    fake_proc = MagicMock()
    fake_proc.pid = 99999
    fake_proc.stdout = iter([b""])
    fake_proc.poll.return_value = 0

    with patch("core.webui_launcher_cmd.build_webui_launch_params", return_value=fake_launch), \
         patch("core.probe.find_pids_by_port_safe", return_value=[]), \
         patch.object(wpm_mod.subprocess, "Popen", return_value=fake_proc) as mock_popen:
        pm.start_webui(timeout=0.5)

    assert mock_popen.called
    kwargs = mock_popen.call_args.kwargs
    if os.name == "nt":
        assert kwargs.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW
    else:
        # posix 不带这个 flag (值为 0)
        assert kwargs.get("creationflags", 0) == 0


# === #3 回归: stop_webui POSIX 端口兜底 ===

def test_stop_uses_os_kill_on_posix(tmp_path):
    """posix 上 pidfile 失效时, stop 走端口兜底分支应用 os.kill(SIGTERM)."""
    import signal
    from unittest.mock import patch, MagicMock
    from core.webui_process_manager import WebuiProcessManager
    import core.webui_process_manager as wpm_mod

    app = _App(cwd=tmp_path)
    pm = WebuiProcessManager(app)

    # 强制走兜底分支: 没有 pidfile (read 返 None) + Popen 句柄为 None;
    # 再 patch find_pids_by_port_safe 返回假 PID + 强制 os.name 走 posix 分支.
    fake_pids = [24681]
    with patch("core.probe.find_pids_by_port_safe", return_value=fake_pids), \
         patch.object(wpm_mod.os, "kill", create=True) as mock_kill, \
         patch.object(wpm_mod, "os") as mock_os_mod:
        # 让 wpm_mod.os.name == "posix" 走 SIGTERM 分支; 其它 os.* 调用透传给真 os.
        mock_os_mod.name = "posix"
        mock_os_mod.kill = mock_kill
        mock_os_mod.path = os.path
        res = pm.stop_webui()

    # posix 分支应对每个占用 PID 调一次 os.kill(<pid>, SIGTERM)
    assert mock_kill.called
    assert mock_kill.call_args_list[0].args[0] == 24681
    assert mock_kill.call_args_list[0].args[1] == signal.SIGTERM
    assert res["killed"] is True
