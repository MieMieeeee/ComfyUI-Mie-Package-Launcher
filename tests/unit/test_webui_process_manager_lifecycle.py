"""Tests for core.webui_process_manager.WebuiProcessManager lifecycle.

跟 test_webui_process_manager.py 互补 — 那份 11 个测覆盖
PM 的核心 API (start / stop / status / pidfile / is_running),
本份 12 个测覆盖真实 spawn / 真实 port probe / log 文件 / 
port collision 等偏 lifecycle 的场景.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# === 真实 socket probe 测试 ===

def _free_port() -> int:
    """拿一个 OS 空闲端口."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _is_port_listening(port: int, timeout: float = 0.3) -> bool:
    """端口是否在监听."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def test_is_http_reachable_returns_false_for_free_port():
    """空闲端口 -> is_http_reachable 返 False."""
    from core.webui_process_manager import WebuiProcessManager
    app = _make_app()
    pm = WebuiProcessManager(app)
    port = _free_port()
    assert pm.is_http_reachable(port=port, timeout=0.2) is False


def test_is_http_reachable_returns_true_for_listening_port():
    """真在监听的端口 -> is_http_reachable 返 True."""
    from core.webui_process_manager import WebuiProcessManager
    import time
    app = _make_app()
    pm = WebuiProcessManager(app)
    port = _free_port()
    # listen(5) 留 backlog 余量, sleep 100ms 让第一次 TCP accept 释放
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(5)
    try:
        assert _is_port_listening(port, timeout=0.3)
        time.sleep(0.1)
        assert pm.is_http_reachable(port=port, timeout=0.5) is True
    finally:
        server.close()


def test_is_http_reachable_timeout_falls_back_to_tcp_alive():
    """HTTP probe 超时但 TCP alive -> 仍返 True (Flask 启动中)."""
    from core.webui_process_manager import WebuiProcessManager
    app = _make_app()
    pm = WebuiProcessManager(app)
    port = _free_port()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(5)
    try:
        # 不响应 HTTP, 模拟"Flask 启动中但 HTTP 还没好"
        # PM 第一次 TCP probe 成功 -> 返 True
        assert pm.is_http_reachable(port=port, timeout=0.2) is True
    finally:
        server.close()


# === is_running 测试 ===

def test_is_running_no_popen_no_pidfile(tmp_path):
    """无 Popen handle + 无 pidfile -> is_running False."""
    from core.webui_process_manager import WebuiProcessManager
    app = _make_app(tmp_path=tmp_path)
    pm = WebuiProcessManager(app)
    assert pm.is_running() is False


def test_is_running_with_stale_pidfile(tmp_path):
    """pidfile PID 已死 (本机 999999 一般没) -> is_running False."""
    from core.cli import webui_pidfile
    from core.webui_process_manager import WebuiProcessManager
    app = _make_app(tmp_path=tmp_path)
    cwd_resolved = Path(str(tmp_path)).resolve()
    app._cwd = str(cwd_resolved)
    # 写个死的 PID
    pidfile_path = webui_pidfile.default_path(cwd_resolved)
    webui_pidfile.write(pidfile_path, 999999, 8199, log_path=cwd_resolved / "webui.log", env_id="env_a")
    pm = WebuiProcessManager(app)
    assert pm.is_running() is False  # 999999 不在跑, stale


# === port collision 测试 ===

def test_start_webui_detects_port_collision(tmp_path):
    """端口已被占时, start_webui 返 port_in_use error (不 spawn)."""
    from core.webui_process_manager import WebuiProcessManager
    port = _free_port()
    # 创个 webui 目录 + flask_app.py 让 start_webui 跳过 "not installed" 检查
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")

    class _App:
        pass
    app = _App()
    app.config = {
        "environments": [
            {"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable},
        ],
        "active_env_id": "env_a",
        "webui_options": {"port": str(port), "display_host": "127.0.0.1"},
    }
    app._cwd = str(Path(str(tmp_path)).resolve())
    app.logger = MagicMock()
    pm = WebuiProcessManager(app)
    # 占用端口
    port = int(app.config["webui_options"]["port"])
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(5)
    try:
        res = pm.start_webui(timeout=2.0)
        assert res["ok"] is False
        assert res.get("port_in_use") is True
        assert "已被占用" in res.get("error", "")
        assert res["port"] == port
    finally:
        server.close()


# === _pidfile_path 测试 ===

def test_pidfile_path_uses_app_cwd(tmp_path):
    """_pidfile_path 用 app._cwd (不是 CWD) 找 pidfile."""
    from core.webui_process_manager import WebuiProcessManager
    cwd_resolved = Path(str(tmp_path)).resolve()
    app = _make_app()
    app._cwd = str(cwd_resolved)
    pm = WebuiProcessManager(app)
    expected = cwd_resolved / "launcher" / "webui.pid"
    assert pm._pidfile_path() == expected


def test_pidfile_path_falls_back_to_cwd_when_app_cwd_missing(tmp_path):
    """app._cwd 不存在时, _pidfile_path 走 Path.cwd() 兜底."""
    from core.webui_process_manager import WebuiProcessManager
    app = _make_app()
    # 不设 app._cwd
    del app._cwd
    pm = WebuiProcessManager(app)
    p = pm._pidfile_path()
    assert p.parent.name == "launcher"
    assert p.name == "webui.pid"


# === log 文件测试 ===

def test_log_file_path_uses_app_cwd(tmp_path):
    """log 文件路径用 app._cwd / launcher / webui.log."""
    from core.webui_process_manager import _webui_log_path
    cwd_resolved = Path(str(tmp_path)).resolve()
    app = _make_app()
    app._cwd = str(cwd_resolved)
    p = _webui_log_path(app)
    assert p == cwd_resolved / "launcher" / "webui.log"


def test_log_file_path_falls_back_to_cwd(tmp_path, monkeypatch):
    """app._cwd 缺失时, 走 cwd."""
    from core.webui_process_manager import _webui_log_path
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    del app._cwd
    p = _webui_log_path(app)
    assert p.parent.name == "launcher"
    assert p.name == "webui.log"


# === is_alive (跨平台) ===

def test_is_alive_returns_false_for_zero_or_negative():
    """PID 0 / -1 / None -> is_alive False (不抛)."""
    from core.cli.webui_pidfile import is_alive
    assert is_alive(0) is False
    assert is_alive(-1) is False
    assert is_alive(None) is False  # type: ignore


def test_is_alive_returns_true_for_self():
    """is_alive(os.getpid()) 返 True (自己)."""
    from core.cli.webui_pidfile import is_alive
    assert is_alive(os.getpid()) is True


def test_is_alive_returns_false_for_dead_pid():
    """已知死 PID (999999 一般没在跑) -> False."""
    from core.cli.webui_pidfile import is_alive
    assert is_alive(999999) is False


# === pidfile round-trip 测试 (集成) ===

def test_pidfile_write_read_clear_round_trip(tmp_path):
    """完整 write -> read -> clear 流程, 用真实文件."""
    from core.cli import webui_pidfile
    p = tmp_path / "launcher" / "webui.pid"
    p.parent.mkdir(parents=True, exist_ok=True)

    webui_pidfile.write(p, os.getpid(), 8199, log_path=tmp_path / "webui.log", env_id="env_a")
    data = webui_pidfile.read(p)
    assert data is not None
    assert data["pid"] == os.getpid()
    assert data["port"] == 8199
    assert data["env_id"] == "env_a"

    # write 是 atomic (写 .tmp 再 rename), 写完后没 .tmp 残留
    assert not p.with_suffix(p.suffix + ".tmp").exists()

    webui_pidfile.clear(p)
    assert not p.exists()
    # clear 二次调用不抛
    webui_pidfile.clear(p)


def test_pidfile_corrupted_json_returns_none(tmp_path):
    """pidfile 写坏 JSON -> read 返 None, 不抛."""
    from core.cli import webui_pidfile
    p = tmp_path / "launcher" / "webui.pid"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json{", encoding="utf-8")
    assert webui_pidfile.read(p) is None


# === helpers ===

def _make_app(tmp_path=None, port=8199):
    """构造 app mock, webui_options 含指定 port."""
    class _App:
        pass
    app = _App()
    app.config = {
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/fake/Pkg", "python_path": "E:/fake/python/python.exe"},
        ],
        "active_env_id": "env_a",
        "webui_options": {"port": str(port), "display_host": "127.0.0.1"},
    }
    app._cwd = str(Path(str(tmp_path)).resolve()) if tmp_path else "."
    app.custom_port = MagicMock()
    app.custom_port.get = lambda: "8188"
    app.pypi_proxy_mode = MagicMock()
    app.pypi_proxy_mode.get = lambda: "none"
    app.pypi_proxy_url = MagicMock()
    app.pypi_proxy_url.get = lambda: ""
    app.logger = MagicMock()
    return app
