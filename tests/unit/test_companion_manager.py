"""Tests for core.companion.manager.CompanionServiceManager (fake runtime, 不真 spawn).

生命周期门槛 (7/8/6/端口占用) / already_running / 幽灵自愈 / 收养 / stop 幂等.
真 spawn 的完整链路在 tests/e2e/test_companion_lifecycle_e2e.py.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _mk_pkg(tmp_path: Path, env="openjutsu") -> Path:
    pkg = tmp_path / "pkg"
    root = pkg / env
    root.mkdir(parents=True)
    (root / "package.json").write_text("{}", encoding="utf-8")
    (root / "patch_proxy.py").write_text("# patch", encoding="utf-8")
    return pkg


def _app(tmp_path: Path, pkg: Path, ports: dict) -> SimpleNamespace:
    cfg = {
        "environments": [
            {"id": "env_a", "comfyui_root": str(pkg), "python_path": "py"},
        ],
        "active_env_id": "env_a",
        "services": {"openjutsu": {"proxy_port": ports["proxy"], "app_port": ports["app"]}},
    }
    return SimpleNamespace(
        _cwd=str(tmp_path), config=cfg,
        logger=type("L", (), {"info": lambda *a, **kw: None,
                              "warning": lambda *a, **kw: None})(),
    )


def _free_ports(n: int = 2) -> list:
    """拿 n 个当前空闲端口 (bind 后立刻关; 测试内占用风险可接受)."""
    socks, ports = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
        ports.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return ports


def _fake_runtime(paths: dict, *, deps_ok=True):
    """假 runtime: 不真跑命令 (gating 测试到不了 spawn)."""
    def build_step_cmd(p):
        return [sys.executable, "-c", "pass"], {}, str(p["root"])

    def build_proxy_cmd(p, port):
        return [sys.executable, "-c", "pass"], {}, str(p["root"])

    def build_app_cmd(p, app_port, proxy_port, comfy_port):
        return [sys.executable, "-c", "pass"], {}, str(p["root"])

    return SimpleNamespace(
        resolve_paths=lambda app, env_id=None: dict(paths, env_id="env_a"),
        check_deps=lambda p, **kw: {"ok": deps_ok, "missing": [] if deps_ok else ["node"],
                                    "available": [] if deps_ok else []},
        build_step_cmd=build_step_cmd,
        build_proxy_cmd=build_proxy_cmd,
        build_app_cmd=build_app_cmd,
        comfyui_port=lambda app: 8188,
        update=lambda app, p, on_progress=None: {"ok": True, "updated": True},
    )


def _mgr(app):
    from core.companion.manager import CompanionServiceManager
    return CompanionServiceManager(app, "openjutsu")


# ---------------- start 门槛 ----------------

def test_start_not_installed_exit7(tmp_path):
    pkg = _mk_pkg(tmp_path)
    (pkg / "openjutsu" / "package.json").unlink()  # 缺 marker
    app = _app(tmp_path, pkg, {"proxy": 18189, "app": 13000})
    m = _mgr(app)
    res = m.start()
    assert res["ok"] is False
    assert res["exit_code"] == 7
    assert "未安装" in res["error"]


def test_start_deps_missing_exit8(tmp_path):
    pkg = _mk_pkg(tmp_path)
    app = _app(tmp_path, pkg, {"proxy": 18189, "app": 13000})
    m = _mgr(app)
    paths = {"pkg_root": pkg, "root": pkg / "openjutsu",
             "node_exe": pkg / "node/node.exe", "npm_cli": pkg / "node/npm.js",
             "py": sys.executable, "proxy_site": pkg / "openjutsu/.proxy-site"}
    with patch.object(type(m), "_runtime", return_value=_fake_runtime(paths, deps_ok=False)):
        res = m.start()
    assert res["ok"] is False
    assert res["exit_code"] == 8
    assert "依赖缺失" in res["error"]


def test_start_requires_comfyui_exit6(tmp_path):
    pkg = _mk_pkg(tmp_path)
    app = _app(tmp_path, pkg, {"proxy": 18189, "app": 13000})
    m = _mgr(app)
    paths = {"pkg_root": pkg, "root": pkg / "openjutsu",
             "node_exe": pkg / "node/node.exe", "npm_cli": pkg / "node/npm.js",
             "py": sys.executable, "proxy_site": pkg / "openjutsu/.proxy-site"}
    with patch.object(type(m), "_runtime", return_value=_fake_runtime(paths)), \
            patch.object(type(m), "_comfyui_running", return_value=False):
        res = m.start()
    assert res["ok"] is False
    assert res["exit_code"] == 6
    assert "ComfyUI 未运行" in res["error"]


def test_start_port_in_use(tmp_path):
    pkg = _mk_pkg(tmp_path)
    p1, _p2 = _free_ports(2)
    app = _app(tmp_path, pkg, {"proxy": p1, "app": _p2})
    m = _mgr(app)
    paths = {"pkg_root": pkg, "root": pkg / "openjutsu",
             "node_exe": pkg / "node/node.exe", "npm_cli": pkg / "node/npm.js",
             "py": sys.executable, "proxy_site": pkg / "openjutsu/.proxy-site"}
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", p1))
    blocker.listen(1)
    try:
        with patch.object(type(m), "_runtime", return_value=_fake_runtime(paths)), \
                patch.object(type(m), "_comfyui_running", return_value=True):
            res = m.start()
    finally:
        blocker.close()
    assert res["ok"] is False
    assert res.get("port_in_use") is True
    assert str(p1) in res["error"]


# ---------------- already_running / 幽灵 / 收养 ----------------

def test_start_already_running_short_circuits(tmp_path):
    pkg = _mk_pkg(tmp_path)
    app = _app(tmp_path, pkg, {"proxy": 18189, "app": 13000})
    m = _mgr(app)
    # 写一个「活 PID + 身份通过」的 pidstore (身份 mock 成真, pid 用测试自身)
    from core.companion import pidstore
    pidstore.write(m._pidfile_path(), "openjutsu",
                   [{"pid": os.getpid(), "role": "proxy"}],
                   {"proxy": 18189, "app": 13000}, None, env_id="env_a")
    with patch("core.companion.proctree.is_service_pid", return_value=True):
        res = m.start()
    assert res["ok"] is True
    assert res["already_running"] is True
    assert res["exit_code"] == 0


def test_status_ghost_pidstore_selfheals(tmp_path):
    """pidstore 指向死 PID → status 判未跑 + 顺手清 pidfile (幽灵自愈)."""
    pkg = _mk_pkg(tmp_path)
    app = _app(tmp_path, pkg, {"proxy": 18189, "app": 13000})
    m = _mgr(app)
    from core.companion import pidstore
    p = m._pidfile_path()
    pidstore.write(p, "openjutsu", [{"pid": 999999, "role": "proxy"}],
                   {"proxy": 18189, "app": 13000}, None, env_id="env_a")
    with patch("core.companion.manager._port_listening", return_value=False):
        s = m.status()
    assert s["running"] is False
    assert not p.exists()  # 幽灵清理


def test_status_adoption_when_ports_owned_by_service(tmp_path):
    """pidstore 失联 + 端口被身份校验过的进程占 → 收养重写 pidstore."""
    pkg = _mk_pkg(tmp_path)
    app = _app(tmp_path, pkg, {"proxy": 18189, "app": 13000})
    m = _mgr(app)
    fake_pids = {18189: [4321], 13000: [4322]}  # 两端口各自的身份校验过占用者
    with patch("core.probe.find_pids_by_port_safe",
               side_effect=lambda port: fake_pids.get(int(port), [])), \
            patch("core.companion.proctree.is_our_pid", return_value=True), \
            patch("core.companion.proctree.is_service_pid", return_value=True), \
            patch("core.companion.pidstore.is_alive", return_value=True), \
            patch("core.companion.manager._port_listening", return_value=True):
        s = m.status()
    assert s["running"] is True
    assert s["ready"] is True
    raw = m._raw_store()
    assert raw is not None
    assert [e["pid"] for e in raw["processes"]] == [4321, 4322]


def test_status_no_adoption_when_port_foreign(tmp_path):
    """端口被无关节程占 → 不收养, 不误报 running."""
    pkg = _mk_pkg(tmp_path)
    app = _app(tmp_path, pkg, {"proxy": 18189, "app": 13000})
    m = _mgr(app)
    with patch("core.probe.find_pids_by_port_safe",
               side_effect=lambda port: [4321]), \
            patch("core.companion.proctree.is_our_pid", return_value=False):
        s = m.status()
    assert s["running"] is False
    assert m._raw_store() is None


# ---------------- stop / status 基线 ----------------

def test_stop_idempotent_when_not_running(tmp_path):
    pkg = _mk_pkg(tmp_path)
    app = _app(tmp_path, pkg, {"proxy": 18189, "app": 13000})
    m = _mgr(app)
    res = m.stop()
    assert res["ok"] is True
    assert res["residual_ports"] == []


def test_status_shape_not_running(tmp_path):
    pkg = _mk_pkg(tmp_path)
    app = _app(tmp_path, pkg, {"proxy": 18189, "app": 13000})
    m = _mgr(app)
    s = m.status()
    assert s["service_id"] == "openjutsu"
    assert s["running"] is False
    assert s["ready"] is False
    assert s["ports"]["proxy"]["port"] == 18189
    assert s["ports"]["app"]["port"] == 13000
    assert s["url"] == "http://127.0.0.1:13000"  # browser_url_role=app


def test_manager_rejects_webui_legacy():
    from core.companion.manager import CompanionServiceManager
    with pytest.raises(ValueError, match="webui 老五件套"):
        CompanionServiceManager(SimpleNamespace(_cwd=".", config={}), "webui")
