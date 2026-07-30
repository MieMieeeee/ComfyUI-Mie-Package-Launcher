"""Tests for core.cli.cmd_webui._do_* action handlers.

8 个 action: start / stop / status / info / restart / install / setup / update.
每个有不同 exit code 语义:
  0  success
  1  general error
  2  start 拒绝重复 (已在跑)
  3  status 未在跑
  6  start --with-comfyui 时 ComfyUI 未跑
  7  WebUI 路径未安装
  8  WebUI 依赖缺失
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class _Args:
    """Namespace-like 替代 argparse Namespace, 仅作占位."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_app(config=None, **extra):
    """构造一个 app mock, 含 build_webui_launch_params / cmd_webui 需要的 attrs.

    用真 _App 类 (不是 MagicMock), 让 isinstance(cfg, dict) 能正常工作.
    """
    class _App:
        pass
    app = _App()
    app.config = config or {
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/fake/Pkg", "python_path": "E:/fake/python/python.exe"},
        ],
        "active_env_id": "env_a",
        "webui_options": {"port": "8199", "display_host": "127.0.0.1"},
    }
    app.custom_port = MagicMock()
    app.custom_port.get = lambda: "8188"
    app.pypi_proxy_mode = MagicMock()
    app.pypi_proxy_mode.get = lambda: "none"
    app.pypi_proxy_url = MagicMock()
    app.pypi_proxy_url.get = lambda: ""
    app.logger = MagicMock()
    for k, v in extra.items():
        setattr(app, k, v)
    return app


# === _do_info ===

def test_do_info_installed_and_available(tmp_path):
    """webui 已装 + 依赖齐 + deps_ok -> installed/available True."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    (webui_path / "requirements.txt").write_text("flask\n")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
        "webui_options": {"port": "8199"},
    })
    with patch("core.webui_dependencies.check_webui_dependencies",
               return_value={"ok": True, "missing": [], "available": ["flask", "requests", "websockets"]}):
        res = cmd_webui._do_info(app, _Args())
    assert res["installed"] is True
    assert res["available"] is True
    assert res["deps_ok"] is True
    assert res["port"] == 8199


def test_do_info_not_installed(tmp_path):
    """webui 路径不存在 -> installed False."""
    from core.cli import cmd_webui
    # 故意让 comfyui_root 指向不存在的目录 -> webui_path 不存在
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": "Z:/NoSuch/Dir", "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    # 用一个不存在的 python 路径避免 check_webui_dependencies 真的跑
    app.config["environments"][0]["python_path"] = "Z:/NoSuch/python.exe"
    res = cmd_webui._do_info(app, _Args())
    assert res["installed"] is False
    assert res["available"] is False
    # python 路径不存在, 不查 deps, deps_ok 是默认 False
    assert res["deps_ok"] is False


def test_do_info_no_deps(tmp_path):
    """webui 装了但依赖缺 -> installed True, available False."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    (webui_path / "requirements.txt").write_text("flask\n")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    with patch("core.webui_dependencies.check_webui_dependencies",
               return_value={"ok": False, "missing": ["flask"], "available": []}):
        res = cmd_webui._do_info(app, _Args())
    assert res["installed"] is True
    assert res["available"] is False
    assert res["deps_ok"] is False
    assert "flask" in res["deps_missing"]


# === _do_status ===

def test_do_status_not_running(tmp_path):
    """无 pidfile + 端口未监听 -> running False, exit_code 3."""
    from core.cli import cmd_webui
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": "Z:/NoSuch/Dir", "python_path": "Z:/NoSuch/python.exe"}],
        "active_env_id": "env_a",
    })
    app._cwd = str(tmp_path)
    res = cmd_webui._do_status(app, _Args())
    assert res["running"] is False
    assert res["pid"] is None
    assert res["port"] == 8199
    assert res["exit_code"] == 3


# === _do_start (核心: exit code 0/6/7/8) ===

def test_do_start_returns_7_when_webui_not_installed(tmp_path):
    """webui 路径不存在 -> exit_code 7 (未安装)."""
    from core.cli import cmd_webui
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    app._cwd = str(tmp_path)
    # 没建 webui 目录
    args = _Args(env=None, with_comfyui=False, no_wait=False, timeout=60)
    res = cmd_webui._do_start(app, args)
    assert res["ok"] is False
    assert res["exit_code"] == 7
    assert "未安装" in res["error"] or "install" in res["error"].lower()


def test_do_start_returns_8_when_deps_missing(tmp_path):
    """webui 装了但依赖缺 -> exit_code 8."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    app._cwd = str(tmp_path)
    with patch("core.webui_dependencies.check_webui_dependencies",
               return_value={"ok": False, "missing": ["flask"], "available": []}):
        args = _Args(env=None, with_comfyui=False, no_wait=False, timeout=60)
        res = cmd_webui._do_start(app, args)
    assert res["ok"] is False
    assert res["exit_code"] == 8
    assert "flask" in str(res.get("missing", []))


def test_do_start_returns_6_when_comfyui_not_running_and_with_comfyui_flag(tmp_path):
    """webui 装了 + deps OK + --with-comfyui 但 ComfyUI 没跑 -> exit_code 6."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    app._cwd = str(tmp_path)
    with patch("core.webui_dependencies.check_webui_dependencies",
               return_value={"ok": True, "missing": [], "available": ["flask", "requests", "websockets"]}):
        with patch("core.cli.cmd_webui._resolve_comfyui_status",
                   return_value={"running": False}):
            args = _Args(env=None, with_comfyui=True, no_wait=False, timeout=60)
            res = cmd_webui._do_start(app, args)
    assert res["ok"] is False
    assert res["exit_code"] == 6


def test_do_start_skips_comfyui_check_when_with_comfyui_false(tmp_path):
    """没传 --with-comfyui 时, 即使 ComfyUI 没跑也直接尝试启 webui."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    app._cwd = str(tmp_path)
    with patch("core.webui_dependencies.check_webui_dependencies",
               return_value={"ok": True, "missing": [], "available": ["flask", "requests", "websockets"]}):
        with patch("core.webui_process_manager.WebuiProcessManager") as MockPM:
            mock_pm = MagicMock()
            mock_pm.is_running.return_value = False
            mock_pm.start_webui.return_value = {
                "ok": True, "pid": 12345, "port": 8199, "url": "http://127.0.0.1:8199",
                "elapsed_sec": 0.5, "env_id": "env_a",
            }
            MockPM.return_value = mock_pm
            args = _Args(env=None, with_comfyui=False, no_wait=False, timeout=60)
            res = cmd_webui._do_start(app, args)
    assert res["ok"] is True
    assert res["pid"] == 12345
    assert res["exit_code"] == 0


def test_do_start_already_running_short_circuits(tmp_path):
    """webui 已在跑 (pidfile 活) -> 返 already_running, exit 0."""
    from core.cli import cmd_webui
    from core.cli import webui_pidfile
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    # 用 .resolve() 让 short / long path 统一, 避免 _pidfile_path 找不到
    cwd_resolved = Path(str(tmp_path)).resolve()
    app._cwd = str(cwd_resolved)
    # 写个活的 pidfile (用 os.getpid 模拟真 pid)
    pidfile_path = webui_pidfile.default_path(cwd_resolved)
    webui_pidfile.write(pidfile_path, os.getpid(), 8199, log_path=cwd_resolved / "webui.log", env_id="env_a")
    with patch("core.webui_dependencies.check_webui_dependencies",
               return_value={"ok": True, "missing": [], "available": ["flask", "requests", "websockets"]}):
        args = _Args(env=None, with_comfyui=False, no_wait=False, timeout=60)
        res = cmd_webui._do_start(app, args)
    assert res.get("already_running") is True
    assert res["pid"] == os.getpid()
    assert res["exit_code"] == 0


# === _do_stop ===

def test_do_stop_when_not_running(tmp_path):
    """无 pidfile -> ok=True, killed=False."""
    from core.cli import cmd_webui
    app = _make_app()
    app._cwd = str(Path(str(tmp_path)).resolve())
    args = _Args(force=False)
    res = cmd_webui._do_stop(app, args)
    assert res["ok"] is True
    assert res["killed"] is False
    assert res["pid"] is None
    assert res["exit_code"] == 0


def test_do_stop_with_force_flag(tmp_path):
    """force flag 透传到 stop_webui."""
    from core.cli import cmd_webui
    from core.cli import webui_pidfile
    app = _make_app()
    cwd_resolved = Path(str(tmp_path)).resolve()
    app._cwd = str(cwd_resolved)
    pidfile_path = webui_pidfile.default_path(cwd_resolved)
    webui_pidfile.write(pidfile_path, os.getpid(), 8199, log_path=cwd_resolved / "webui.log", env_id="env_a")
    with patch("core.webui_process_manager.WebuiProcessManager") as MockPM:
        mock_pm = MagicMock()
        mock_pm.stop_webui.return_value = {
            "ok": True, "pid": os.getpid(), "elapsed_sec": 0.1, "killed": True,
        }
        MockPM.return_value = mock_pm
        args = _Args(force=True)
        res = cmd_webui._do_stop(app, args)
    assert res["ok"] is True
    assert res["killed"] is True
    # force=True 透传到 stop_webui
    call = mock_pm.stop_webui.call_args
    # kw 可能是 force=, 也可能是 positional
    assert call.kwargs.get("force") is True or (len(call.args) >= 1 and call.args[0] is True)


# === _do_restart ===

def test_do_restart_calls_stop_then_start(tmp_path):
    """restart = stop + start."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    app._cwd = str(Path(str(tmp_path)).resolve())
    with patch("core.webui_dependencies.check_webui_dependencies",
               return_value={"ok": True, "missing": [], "available": ["flask", "requests", "websockets"]}):
        with patch("core.webui_process_manager.WebuiProcessManager") as MockPM:
            mock_pm = MagicMock()
            mock_pm.is_running.return_value = False
            mock_pm.stop_webui.return_value = {"ok": True, "pid": None, "elapsed_sec": 0.1, "killed": False}
            mock_pm.start_webui.return_value = {
                "ok": True, "pid": 999, "port": 8199, "url": "http://127.0.0.1:8199",
                "elapsed_sec": 0.3, "env_id": "env_a",
            }
            MockPM.return_value = mock_pm
            args = _Args(env=None, with_comfyui=False, no_wait=False, timeout=60, force=False)
            res = cmd_webui._do_restart(app, args)
    assert res["ok"] is True
    assert res["stopped"] is True
    assert res["started"] is True
    assert res["pid"] == 999
    assert res["exit_code"] == 0


def test_do_restart_propagates_start_failure(tmp_path):
    """start 失败时, restart 也 fail (exit code 透传)."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    app._cwd = str(Path(str(tmp_path)).resolve())
    with patch("core.webui_dependencies.check_webui_dependencies",
               return_value={"ok": True, "missing": [], "available": ["flask", "requests", "websockets"]}):
        with patch("core.webui_process_manager.WebuiProcessManager") as MockPM:
            mock_pm = MagicMock()
            mock_pm.is_running.return_value = False
            mock_pm.stop_webui.return_value = {"ok": True, "pid": None, "elapsed_sec": 0.1, "killed": False}
            mock_pm.start_webui.return_value = {
                "ok": False, "pid": None, "port": None, "url": None,
                "elapsed_sec": 0.5, "error": "start failed",
            }
            MockPM.return_value = mock_pm
            args = _Args(env=None, with_comfyui=False, no_wait=False, timeout=60, force=False)
            res = cmd_webui._do_restart(app, args)
    assert res["ok"] is False
    assert "start failed" in res["error"]


# === _do_install ===

def test_do_install_already_exists_short_circuits(tmp_path):
    """webui 目录已有内容时 install 跳过 clone (already_exists)."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    webui_path.mkdir()
    (webui_path / "app").mkdir()
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    # 创 requirements.txt 让 install 真的跑 deps
    (webui_path / "requirements.txt").write_text("flask\nrequests\nwebsockets\n")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    with patch("core.webui_installer.clone_webui",
               return_value={"ok": True, "already_exists": True, "log": "skipped"}) as mock_clone:
        with patch("core.webui_dependencies.install_webui_requirements",
                   return_value={"ok": True, "deps_ok": True, "deps_installed": [], "deps_satisfied": ["flask"]}):
            args = _Args(env=None, url=None)
            res = cmd_webui._do_install(app, args)
    assert res["ok"] is True
    # deps_ok 应该真返 True (因为创了 requirements.txt)
    assert res.get("deps_ok") is True
    # clone_webui 被调了一次
    assert mock_clone.call_count == 1


def test_do_install_clone_failure(tmp_path):
    """clone 失败 -> exit_code 1."""
    from core.cli import cmd_webui
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    with patch("core.webui_installer.clone_webui",
               return_value={"ok": False, "error": "git not found"}):
        args = _Args(env=None, url=None)
        res = cmd_webui._do_install(app, args)
    assert res["ok"] is False
    assert "git not found" in res["error"]
    assert res["exit_code"] == 1


def test_do_install_with_custom_url(tmp_path):
    """--url 透传到 clone_webui."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    webui_path.mkdir()
    (webui_path / "app").mkdir()
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    custom_url = "https://example.com/fork.git"
    with patch("core.webui_installer.clone_webui",
               return_value={"ok": True, "already_exists": True, "log": "ok"}) as mock_clone:
        with patch("core.webui_dependencies.install_webui_requirements",
                   return_value={"ok": True, "deps_ok": True}):
            args = _Args(env=None, url=custom_url)
            res = cmd_webui._do_install(app, args)
    assert res["ok"] is True
    # 透传 url
    call = mock_clone.call_args
    # 第二个位置 (target_dir) 之外: app, target_dir, repo_url=...
    # repo_url 是 kwargs
    assert call.kwargs.get("repo_url") == custom_url


# === _do_setup ===

def test_do_setup_when_requirements_missing(tmp_path):
    """webui 装了但 requirements.txt 不存在 -> ok=False, error."""
    from core.cli import cmd_webui
    # 创 webui 目录, 但不放 requirements.txt
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    args = _Args(env=None)
    res = cmd_webui._do_setup(app, args)
    assert res["ok"] is False
    assert "requirements.txt" in res["error"]


def test_do_setup_with_python_missing(tmp_path):
    """python 路径不存在 -> ok=False."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    (webui_path / "requirements.txt").write_text("flask\n")
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": "Z:/NoSuch/python.exe"}],
        "active_env_id": "env_a",
    })
    args = _Args(env=None)
    res = cmd_webui._do_setup(app, args)
    assert res["ok"] is False
    assert "python" in res["error"].lower()


def test_do_setup_with_pypi_proxy():
    """pypi proxy 走 app.pypi_proxy_mode (从 launcher config 读)."""
    from core.cli import cmd_webui
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        webui_path = tmp / "Comfyui-Workbench-Mie"
        (webui_path / "app").mkdir(parents=True)
        (webui_path / "app" / "flask_app.py").write_text("# stub")
        (webui_path / "requirements.txt").write_text("flask\n")

        app = _make_app(config={
            "environments": [{"id": "env_a", "comfyui_root": str(tmp), "python_path": sys.executable}],
            "active_env_id": "env_a",
        })
        app._cwd = str(tmp)
        with patch("core.webui_dependencies.install_webui_requirements",
                   return_value={"ok": True, "deps_ok": True, "deps_installed": [], "deps_satisfied": ["flask"]}) as mock_install:
            args = _Args(env=None)
            res = cmd_webui._do_setup(app, args)
        assert res["ok"] is True
        # install_webui_requirements 被调, py / req 透传
        call = mock_install.call_args
        assert call.args[0] is not None  # py
        assert call.args[1] is not None  # req


# === _do_update ===

def test_do_update_when_not_git_repo(tmp_path):
    """webui 目录不是 git 仓库 -> ok=False."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    (webui_path / "app").mkdir(parents=True)
    (webui_path / "app" / "flask_app.py").write_text("# stub")
    # 没有 .git/
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    args = _Args(env=None)
    res = cmd_webui._do_update(app, args)
    assert res["ok"] is False
    assert "git" in res["error"].lower()


def test_do_update_success(tmp_path):
    """webui 是 git 仓库 + pull 成功 -> ok=True."""
    from core.cli import cmd_webui
    webui_path = tmp_path / "Comfyui-Workbench-Mie"
    webui_path.mkdir()
    (webui_path / ".git").mkdir()
    app = _make_app(config={
        "environments": [{"id": "env_a", "comfyui_root": str(tmp_path), "python_path": sys.executable}],
        "active_env_id": "env_a",
    })
    with patch("core.webui_installer.pull_webui",
               return_value={"ok": True, "updated": True, "log": "Already up to date."}):
        args = _Args(env=None)
        res = cmd_webui._do_update(app, args)
    assert res["ok"] is True
    assert res["updated"] is True


# === run() 入口 (dispatch + 异常处理) ===

def test_run_dispatches_to_correct_handler():
    """cmd_webui.run() 根据 args.webui_action 派发到对应 _do_*."""
    from core.cli import cmd_webui
    app = _make_app()
    for action in ("start", "stop", "status", "info", "restart", "install", "setup", "update"):
        args = _Args(webui_action=action, json=True, env=None,
                     no_wait=False, timeout=60, with_comfyui=False, force=False, url=None)
        with patch.object(cmd_webui, "_DISPATCH") as mock_dispatch:
            handler = MagicMock()
            handler.return_value = {"ok": True, "action": action, "exit_code": 0}
            mock_dispatch.__contains__ = lambda self, k: True
            mock_dispatch.__getitem__ = lambda self, k: handler
            try:
                rc = cmd_webui.run(args, app)
            except SystemExit as e:
                rc = e.code
        assert handler.called, f"{action} handler not called"


def test_run_unknown_action():
    """args.webui_action 不在 WEBUI_ACTIONS 时, run() 返 EXIT_ERROR."""
    from core.cli import cmd_webui
    app = _make_app()
    args = _Args(webui_action="bogus", json=True, env=None,
                 no_wait=False, timeout=60, with_comfyui=False, force=False, url=None)
    try:
        rc = cmd_webui.run(args, app)
    except SystemExit as e:
        rc = e.code
    from core.cli.exitcodes import EXIT_ERROR
    assert rc == EXIT_ERROR


def test_run_handler_exception_returns_exit_error():
    """handler raise Exception 时, run() 兜底返 EXIT_ERROR."""
    from core.cli import cmd_webui
    from core.cli.exitcodes import EXIT_ERROR
    app = _make_app()
    args = _Args(webui_action="info", json=True, env=None,
                 no_wait=False, timeout=60, with_comfyui=False, force=False, url=None)
    with patch.object(cmd_webui, "_DISPATCH") as mock_dispatch:
        mock_dispatch.__contains__ = lambda self, k: True
        mock_dispatch.__getitem__ = lambda s, k: MagicMock(side_effect=Exception("boom"))
        try:
            rc = cmd_webui.run(args, app)
        except SystemExit as e:
            rc = e.code
    assert rc == EXIT_ERROR
