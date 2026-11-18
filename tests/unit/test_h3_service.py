"""Tests for the h3-engine service end to end inside the framework (no real spawn).

覆盖这几条真机语义:
  - runtime 提供启动步骤 (build_steps) 的新链路, 老 runtime 仍走兼容路径;
  - 长驻服务用「文件直写」日志 (CLI 退出后子进程还能写日志);
  - pidstore 跨环境共用 → 必须有环境闸门, 否则会动别的环境的实例;
  - CLI 的 info 用**所选服务自己的 runtime** 查依赖; stop 要把 --env 透传下去.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _App:
    def __init__(self, cwd=None, cfg=None):
        self._cwd = str(cwd) if cwd else "."
        self.config = cfg if cfg is not None else {}
        self.logger = type("L", (), {"info": lambda *a, **kw: None,
                                     "warning": lambda *a, **kw: None})()


def _mk_pkg(tmp_path: Path, *, env_id="env_a", with_engine=True,
            with_mie_nodes=True) -> Path:
    pkg = tmp_path / f"pkg_{env_id}"
    custom_nodes = pkg / "ComfyUI" / "custom_nodes"
    custom_nodes.mkdir(parents=True)
    if with_engine:
        engine = custom_nodes / "ComfyUI-Mie-H3-Engine"
        (engine / "webapp").mkdir(parents=True)
        (engine / "webapp" / "__main__.py").write_text("# entry", encoding="utf-8")
    if with_mie_nodes:
        nodes = custom_nodes / "comfyui_mienodes"
        (nodes / "asset_library").mkdir(parents=True)
    py_dir = pkg / "python_embeded"
    py_dir.mkdir(parents=True, exist_ok=True)
    (py_dir / "python.exe").write_text("# fake", encoding="utf-8")
    return pkg


def _cfg(pkg: Path, env_id="env_a"):
    return {
        "environments": [
            {"id": env_id, "comfyui_root": str(pkg),
             "python_path": "python_embeded/python.exe"},
        ],
        "active_env_id": env_id,
    }


def _mgr(app, env_id=None):
    from core.companion.manager import CompanionServiceManager
    return CompanionServiceManager(app, "h3-engine", env_id=env_id)


# ---------------- manager: runtime 提供步骤 ----------------

def test_manager_start_uses_runtime_steps_and_writes_pidstore(tmp_path, monkeypatch):
    """runtime 给的 build_steps 被真正执行 (新链路), pidstore 落盘."""
    from core.companion import h3_runtime
    pkg = _mk_pkg(tmp_path)
    app = _App(tmp_path, _cfg(pkg))
    m = _mgr(app)
    monkeypatch.setattr(h3_runtime, "_probe_imports",
                        lambda py, timeout=20: (True, []))
    steps = [{
        "role": "app", "kind": "long",
        "cmd": [sys.executable, "-c", "import time; time.sleep(30)"],
        "env": {}, "cwd": str(tmp_path),
    }]
    monkeypatch.setattr(h3_runtime, "build_steps",
                        lambda paths, ports, comfy_port: steps)
    try:
        res = m.start(no_wait=True)
        assert res["ok"] is True
        assert res["exit_code"] == 0
        raw = m._raw_store()
        assert raw is not None
        assert raw["service_id"] == "h3-engine"
        assert raw["env_id"] == "env_a"
        assert raw["processes"][0]["role"] == "app"
    finally:
        m.stop(force=True)


def test_manager_uses_file_log_mode_for_long_running_service(tmp_path, monkeypatch):
    """文件直写: 没有 drain 线程, 子进程输出直接落到日志文件."""
    from core.companion import h3_runtime
    pkg = _mk_pkg(tmp_path)
    app = _App(tmp_path, _cfg(pkg))
    m = _mgr(app)
    monkeypatch.setattr(h3_runtime, "_probe_imports",
                        lambda py, timeout=20: (True, []))
    steps = [{
        "role": "app", "kind": "long",
        "cmd": [sys.executable, "-c",
                "import sys,time; print('hello-from-child', flush=True); time.sleep(30)"],
        "env": {}, "cwd": str(tmp_path),
    }]
    monkeypatch.setattr(h3_runtime, "build_steps",
                        lambda paths, ports, comfy_port: steps)
    try:
        res = m.start(no_wait=True)
        assert res["ok"] is True
        # 文件直写模式下不建 drain 线程
        assert m._procs["app"]["thread"] is None
        log_path = m._log_path()
        deadline = time.time() + 10
        text = ""
        while time.time() < deadline:
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
            if "hello-from-child" in text:
                break
            time.sleep(0.2)
        assert "hello-from-child" in text, "子进程输出没落进服务日志"
    finally:
        m.stop(force=True)


def test_manager_env_gate_ignores_other_env_instance(tmp_path):
    """pidstore 里是**别的环境**的实例 → 不认 (也不杀)."""
    from core.companion import pidstore
    pkg = _mk_pkg(tmp_path, env_id="env_a")
    app = _App(tmp_path, _cfg(pkg, "env_a"))
    m = _mgr(app)
    pidstore.write(m._pidfile_path(), "h3-engine",
                   [{"pid": os.getpid(), "role": "app"}],
                   {"app": 8200}, None, env_id="env_b")
    assert m._live_processes() == []
    assert m.status()["running"] is False
    # stop 不能去动它
    with patch("core.companion.proctree.kill_tree", return_value=True) as killer:
        m.stop()
    assert not killer.called
    assert m._raw_store()["env_id"] == "env_b"


def test_manager_status_reports_health_when_running(tmp_path, monkeypatch):
    """running 时 status 带上 runtime 的语义健康信息 (H3 的 /api/health)."""
    from core.companion import h3_runtime
    pkg = _mk_pkg(tmp_path)
    app = _App(tmp_path, _cfg(pkg))
    m = _mgr(app)
    monkeypatch.setattr(h3_runtime, "health_info",
                        lambda paths, ports: {"status": "ok",
                                              "app": "comfyui-mie-web",
                                              "plugin_root_ok": True})
    with patch("core.companion.manager.CompanionServiceManager._live_processes",
               return_value=[{"pid": 4242, "role": "app"}]), \
            patch("core.companion.manager._port_listening", return_value=True):
        st = m.status()
    assert st["running"] is True
    assert st["health"]["app"] == "comfyui-mie-web"


# ---------------- CLI ----------------

def test_cli_info_uses_selected_runtime_deps(tmp_path, capsys):
    """service info h3-engine 的依赖检查走 h3_runtime (不是 openjutsu)."""
    from core.cli.cmd_service import run
    pkg = _mk_pkg(tmp_path)
    # 去掉环境的 python → 依赖检查应报「python 不可用」这类 H3 自己的缺项,
    # 而不是 openjutsu 的 node / .proxy-site
    import shutil
    shutil.rmtree(pkg / "python_embeded", ignore_errors=True)
    app = _App(cwd=tmp_path, cfg=_cfg(pkg))
    args = SimpleNamespace(service_action="info", service_id="h3-engine",
                           json=True, env=None)
    rc = run(args, app)
    assert rc == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert payload["service_id"] == "h3-engine"
    assert payload["runtime"] == "h3-engine"
    assert payload["deps_ok"] is False
    assert any("python" in m for m in payload["deps_missing"])
    assert not any("node" in m or ".proxy-site" in m for m in payload["deps_missing"])


def test_cli_stop_passes_env_to_manager(tmp_path):
    """service stop 的 --env 必须透传给 manager (否则会动别的环境)."""
    from core.cli import cmd_service
    captured = {}

    class _FakeMgr:
        def __init__(self, app, service_id, env_id=None):
            captured["service_id"] = service_id
            captured["env_id"] = env_id

        def stop(self, force=False):
            return {"ok": True, "killed": False, "residual_ports": [],
                    "elapsed_sec": 0.0, "error": None, "service_id": "h3-engine"}

    args = SimpleNamespace(service_action="stop", service_id="h3-engine",
                           json=True, env="env_b", force=False)
    with patch("core.companion.manager.CompanionServiceManager", _FakeMgr):
        rc = cmd_service.run(args, _App(cwd=tmp_path))
    assert rc == 0
    assert captured["service_id"] == "h3-engine"
    assert captured["env_id"] == "env_b"


def test_cli_logs_target_includes_h3_engine():
    """logs h3-engine 是合法目标 (日志路径由注册表通用解析)."""
    from core.cli.parser import LOGS_TARGETS
    assert "h3-engine" in LOGS_TARGETS
    from core.cli.runner import resolve_log_path
    app = _App(cwd=Path("."))
    path = resolve_log_path(app, "h3-engine")
    assert path is not None
    assert path.name == "h3-engine.log"


# ---------------- 安装链 (下载 / 依赖) ----------------

def _make_local_repo(tmp_path: Path) -> Path:
    """造一个本地 git 仓库当下载源 (不起网络)."""
    import subprocess
    repo = tmp_path / "src_repo"
    repo.mkdir()
    (repo / "webapp").mkdir()
    (repo / "webapp" / "__main__.py").write_text("# entry", encoding="utf-8")
    (repo / "requirements.txt").write_text("flask>=3.0\n", encoding="utf-8")
    (repo / ".gitignore").write_text("asset_library/\nmie_llm_keys.json\n",
                                     encoding="utf-8")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": os.environ.get("PATH", "")}
    for args in (["init", "-q", "."], ["add", "-A"], ["commit", "-qm", "init"]):
        r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                           env=env, timeout=60)
        assert r.returncode == 0, r.stderr
    return repo


def test_manager_install_clones_engine(tmp_path):
    """install: 真 clone 到 <包根>/ComfyUI/custom_nodes/ 下."""
    from core.companion import h3_runtime
    pkg = _mk_pkg(tmp_path)
    repo = _make_local_repo(tmp_path)
    app = _App(tmp_path, _cfg(pkg))
    m = _mgr(app)
    # 把仓库地址指到本地源 (spec 的默认是 GitHub)
    import core.companion.spec as spec_mod
    orig = spec_mod.H3_ENGINE_SPEC.repo_url
    try:
        object.__setattr__(spec_mod.H3_ENGINE_SPEC, "repo_url", str(repo))
        res = m.install()
    finally:
        object.__setattr__(spec_mod.H3_ENGINE_SPEC, "repo_url", orig)
    assert res["ok"] is True, res.get("error")
    target = pkg / "ComfyUI" / "custom_nodes" / "ComfyUI-Mie-H3-Engine"
    assert (target / "webapp" / "__main__.py").exists()
    # 装完不建空的 asset_library (那会遮住老用户的资产)
    assert not (target / "asset_library").exists()


def test_manager_install_is_idempotent(tmp_path):
    """已装 → 再 install 不重下, 也不删目录."""
    pkg = _mk_pkg(tmp_path)
    repo = _make_local_repo(tmp_path)
    app = _App(tmp_path, _cfg(pkg))
    m = _mgr(app)
    import core.companion.spec as spec_mod
    orig = spec_mod.H3_ENGINE_SPEC.repo_url
    try:
        object.__setattr__(spec_mod.H3_ENGINE_SPEC, "repo_url", str(repo))
        first = m.install()
        second = m.install()
    finally:
        object.__setattr__(spec_mod.H3_ENGINE_SPEC, "repo_url", orig)
    assert first["ok"] is True
    assert second["ok"] is True
    assert second.get("already_exists") is True
    target = pkg / "ComfyUI" / "custom_nodes" / "ComfyUI-Mie-H3-Engine"
    assert (target / "webapp" / "__main__.py").exists()


def test_cli_install_and_setup_actions_exist():
    """CLI 有 install / setup 两个 action (与 webui 同构)."""
    from core.cli.cmd_service import SERVICE_ACTIONS
    assert "install" in SERVICE_ACTIONS
    assert "setup" in SERVICE_ACTIONS
    from core.cli.parser import SERVICE_ACTIONS as PARSER_ACTIONS
    assert set(PARSER_ACTIONS) == set(SERVICE_ACTIONS)
