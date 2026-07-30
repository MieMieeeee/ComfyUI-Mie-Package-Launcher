"""E2E tests for WebuiProcessManager full lifecycle.

跟 unit test 不同, 本份走真实 subprocess 路径 (不是 mock):
- 真 spawn 一个 Python HTTP server (模拟 webui)
- 真 HTTP probe
- 真 pidfile 读写
- 真 stop / cleanup

Server 用 stdlib http.server 一行写一个 long-running handler, 避免依赖 webui
项目本身. 测的是 launcher 跟子进程的集成.
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


# === helpers ===

def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port_listening(port, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _is_pid_alive(pid):
    if not pid or pid <= 0:
        return False
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        return bool(ok) and code.value == STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


# === fake_webui_script: 写个 stdlib HTTP server 模拟 webui ===

def _write_fake_webui_script(path: Path) -> None:
    """写个 stdlib HTTP server, 监听 port, 写一行到 log."""
    # 用 + chr(10) 而不是 b'\\n' 避免源文件 \n 转义问题
    lines = [
        "import http.server, socketserver, sys, os",
        "port = int(sys.argv[1])",
        "log_path = sys.argv[2]",
        "log = open(log_path, 'ab', buffering=0)",
        "log.write(('fake webui started, pid=%d' % os.getpid()).encode() + bytes([10]))",
        "log.flush()",
        "class Q(http.server.BaseHTTPRequestHandler):",
        "    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b'ok')",
        "    def log_message(self, *a, **k): pass",
        "socketserver.TCPServer.allow_reuse_address = True",
        "with socketserver.TCPServer(('127.0.0.1', port), Q) as srv:",
        "    srv.serve_forever()",
        "",
    ]
    # lines 是 str 列表, 用 \n join 后写到文件
    path.write_text(chr(10).join(lines), encoding="utf-8")


@pytest.fixture
def fake_webui_script(tmp_path):
    script = tmp_path / "fake_webui.py"
    _write_fake_webui_script(script)
    return script


@pytest.fixture
def fake_app(tmp_path, fake_webui_script):
    webui_root = tmp_path / "Comfyui-Workbench-Mie"
    (webui_root / "app").mkdir(parents=True)
    (webui_root / "app" / "flask_app.py").write_text("# stub - real server is fake_webui.py")

    app = MagicMock()
    app.config = {
        "environments": [
            {
                "id": "env_a",
                "comfyui_root": str(tmp_path),
                "python_path": sys.executable,
            }
        ],
        "active_env_id": "env_a",
        "webui_options": {"port": str(_free_port()), "display_host": "127.0.0.1"},
    }
    app._cwd = str(Path(str(tmp_path)).resolve())
    app.custom_port = MagicMock()
    app.custom_port.get = lambda: "8188"
    app.pypi_proxy_mode = MagicMock()
    app.pypi_proxy_mode.get = lambda: "none"
    app.pypi_proxy_url = MagicMock()
    app.pypi_proxy_url.get = lambda: ""
    app.logger = MagicMock()
    app._fake_webui_script = str(fake_webui_script)
    return app


@pytest.fixture(autouse=True)
def _patch_build_webui_launch_params():
    from core import webui_launcher_cmd

    def patched(app, env_id=None):
        port_str = app.config.get("webui_options", {}).get("port") or "8199"
        log_path = Path(app._cwd) / "launcher" / "webui.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable, str(app._fake_webui_script),
            str(port_str), str(log_path),
        ]
        env = os.environ.copy()
        env["PYTHONLEGACYWINDOWSSTDIO"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return cmd, env, app._cwd, sys.executable, Path(app._cwd) / "Comfyui-Workbench-Mie"

    with patch.object(webui_launcher_cmd, "build_webui_launch_params", patched):
        yield


# === Tests ===

def test_full_start_status_stop_lifecycle(fake_app):
    """start 真 spawn → status reports running → stop 真 kill → status reports stopped."""
    from core.webui_process_manager import WebuiProcessManager
    pm = WebuiProcessManager(fake_app)
    port = int(fake_app.config["webui_options"]["port"])

    res = pm.start_webui(timeout=15.0)
    assert res["ok"] is True, f"start_webui failed: {res}"
    pid = res["pid"]
    assert pid is not None
    assert _wait_port_listening(port, timeout=10.0), "spawn 后端口未监听"
    assert _is_pid_alive(pid), f"spawn 后 PID {pid} 不在跑"

    try:
        st = pm.status()
        assert st["running"] is True
        assert st["pid"] == pid
        assert st["port"] == port
        assert pm.is_http_reachable(port=port, timeout=2.0) is True

        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as resp:
            assert resp.status == 200
            assert resp.read() == b"ok"
    finally:
        stop_res = pm.stop_webui(timeout=5.0)
        assert stop_res["ok"] is True
        assert stop_res["killed"] is True
        time.sleep(1.0)
        assert not _is_pid_alive(pid), f"stop 后 PID {pid} 还活着"

    st = pm.status()
    assert st["running"] is False
    assert st["pid"] is None


def test_start_writes_pidfile_with_real_process(fake_app):
    """start 真 spawn 时, pidfile 含真 pid + port + env_id."""
    from core.webui_process_manager import WebuiProcessManager
    from core.cli import webui_pidfile
    pm = WebuiProcessManager(fake_app)
    port = int(fake_app.config["webui_options"]["port"])
    res = pm.start_webui(timeout=10.0)
    assert res["ok"] is True
    try:
        cwd_resolved = Path(fake_app._cwd)
        pidfile = webui_pidfile.default_path(cwd_resolved)
        assert pidfile.exists()
        data = webui_pidfile.read(pidfile)
        assert data is not None
        assert data["pid"] == res["pid"]
        assert data["port"] == port
        assert data["env_id"] == "env_a"
        assert _is_pid_alive(data["pid"])
    finally:
        pm.stop_webui(timeout=3.0)


def test_start_when_already_running_short_circuits(fake_app):
    """已有 pidfile + pid 在跑 -> start 返 already_running=True."""
    from core.webui_process_manager import WebuiProcessManager
    pm = WebuiProcessManager(fake_app)
    port = int(fake_app.config["webui_options"]["port"])

    res1 = pm.start_webui(timeout=10.0)
    assert res1["ok"] is True
    pid1 = res1["pid"]
    try:
        res2 = pm.start_webui(timeout=2.0)
        assert res2["ok"] is True
        assert res2.get("already_running") is True
        assert res2["pid"] == pid1
        assert res2.get("elapsed_sec", 0) < 1.0
    finally:
        pm.stop_webui(timeout=3.0)


def test_log_file_contains_real_process_output(fake_app):
    """log 文件含真 spawn 出的子进程输出."""
    from core.webui_process_manager import WebuiProcessManager
    pm = WebuiProcessManager(fake_app)
    port = int(fake_app.config["webui_options"]["port"])
    res = pm.start_webui(timeout=10.0)
    assert res["ok"] is True
    try:
        log_path = Path(res["log_path"])
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8", errors="ignore")
        assert "fake webui started" in content
        assert "=== webui spawn at" in content
        assert "cmd:" in content
    finally:
        pm.stop_webui(timeout=3.0)


def test_stop_kills_real_process_via_pidfile(fake_app):
    """stop 通过 pidfile 找 PID 杀, 即使 pm 内部 Popen 句柄丢了也能 kill."""
    from core.webui_process_manager import WebuiProcessManager
    pm = WebuiProcessManager(fake_app)
    port = int(fake_app.config["webui_options"]["port"])
    res = pm.start_webui(timeout=10.0)
    assert res["ok"] is True
    pid = res["pid"]
    assert _is_pid_alive(pid)
    pm.webui_process = None
    stop_res = pm.stop_webui(timeout=5.0)
    assert stop_res["ok"] is True
    assert stop_res["killed"] is True
    time.sleep(0.5)
    assert not _is_pid_alive(pid)


def test_double_stop_is_idempotent(fake_app):
    """stop 2 次: 第一次 kill, 第二次 no-op."""
    from core.webui_process_manager import WebuiProcessManager
    pm = WebuiProcessManager(fake_app)
    res = pm.start_webui(timeout=10.0)
    assert res["ok"] is True
    stop1 = pm.stop_webui(timeout=5.0)
    assert stop1["killed"] is True
    stop2 = pm.stop_webui(timeout=2.0)
    assert stop2["ok"] is True
    assert stop2["killed"] is False
    assert stop2["pid"] is None


def test_is_http_reachable_against_real_server(fake_app):
    """is_http_reachable 对真 webui (fake) 返 True."""
    from core.webui_process_manager import WebuiProcessManager
    pm = WebuiProcessManager(fake_app)
    port = int(fake_app.config["webui_options"]["port"])
    res = pm.start_webui(timeout=10.0)
    assert res["ok"] is True
    try:
        assert _wait_port_listening(port, timeout=10.0)
        assert pm.is_http_reachable(port=port, timeout=2.0) is True
    finally:
        pm.stop_webui(timeout=3.0)
