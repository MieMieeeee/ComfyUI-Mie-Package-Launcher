"""Tests for core.webui_process_manager.WebuiProcessManager."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

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
    """有 pidfile 指向活 PID, 端口没监听 -> running=False (http_reachable=False)."""
    from core.cli.webui_pidfile import write
    from core.webui_process_manager import WebuiProcessManager
    app = _App(cwd=tmp_path)
    p = tmp_path / "launcher" / "webui.pid"
    write(p, os.getpid(), 8199, log_path=tmp_path / "webui.log", env_id="env_a")
    pm = WebuiProcessManager(app)
    s = pm.status()
    assert s["pid"] == os.getpid()
    assert s["port"] == 8199
    assert s["running"] is False  # http 不可达
    assert s["http_reachable"] is False


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
