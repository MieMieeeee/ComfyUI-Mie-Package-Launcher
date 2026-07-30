"""webui 子命令: start / stop / status / info / restart / install / setup / update.

跟 ComfyUI 平级的第二个服务 (Comfyui-Workbench-Mie):
- start [--env] [--no-wait] [--timeout] [--with-comfyui]
- stop [--force]
- status --json
- info --json
- restart [--env] [--with-comfyui]
- install [--url]                  # 仅未安装时
- setup                            # 仅缺依赖时
- update                           # 已安装时 git pull

返 Exit codes (跟 comfyui start/stop/status 体系对齐):
  0  success
  1  general error (path missing / IO / timeout)
  2  start 拒绝重复 (已在跑)
  3  status 未在跑
  6  comfyui 未运行 (--with-comfyui 未传且 comfyui 没在跑)
  7  webui 路径未安装
  8  webui 依赖缺失

--json 始终返单行 JSON (字段 schema 在 parser.py 的 epilog 里写).
"""
from __future__ import annotations

from typing import Any

from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli.output import format_human, format_json

__all__ = ["run", "WEBUI_ACTIONS"]


WEBUI_ACTIONS = [
    "start", "stop", "status", "info", "restart",
    "install", "setup", "update",
]


def _resolve_webui_status(app) -> dict:
    """读 webui pidfile + http 探活, 统一 status."""
    from core.webui_process_manager import WebuiProcessManager
    pm = WebuiProcessManager(app)
    return pm.status()


def _resolve_webui_path(app, env_id=None) -> str | None:
    """webui 期望路径 (env-aware)."""
    from utils.paths import webui_path_from_config
    cfg = getattr(app, "config", None)
    p = webui_path_from_config(cfg if isinstance(cfg, dict) else {}, env_id=env_id)
    return str(p) if p else None


def _resolve_webui_installed(app, env_id=None) -> bool:
    """webui 是否真安装 (路径 + 入口 flask_app.py 都在)."""
    from pathlib import Path
    p = _resolve_webui_path(app, env_id=env_id)
    if not p:
        return False
    target = Path(p)
    return target.exists() and (target / "app" / "flask_app.py").exists()


def _resolve_webui_python(app, env_id=None) -> str | None:
    """激活 env 的 python 路径."""
    from config.migrations import resolve_active_paths_for_webui
    cfg = getattr(app, "config", None)
    pw = resolve_active_paths_for_webui(cfg if isinstance(cfg, dict) else {}, env_id=env_id)
    return pw.get("python_path")


def _do_start(app, args) -> dict:
    """start 子动作."""
    from core.webui_process_manager import WebuiProcessManager
    from core.webui_launcher_cmd import build_webui_launch_params

    env_id = getattr(args, "env", None)
    no_wait = bool(getattr(args, "no_wait", False))
    timeout = int(getattr(args, "timeout", 60) or 60)
    with_comfyui = bool(getattr(args, "with_comfyui", False))

    # 1. 路径 / 入口检查
    if not _resolve_webui_installed(app, env_id=env_id):
        return {
            "ok": False, "pid": None, "port": None, "url": None,
            "elapsed_sec": 0.0, "error": "WebUI 路径未安装; 请先 webui install",
            "exit_code": 7,
        }

    # 2. 依赖检查
    py = _resolve_webui_python(app, env_id=env_id)
    if py:
        from core.webui_dependencies import check_webui_dependencies
        from pathlib import Path
        dep = check_webui_dependencies(Path(py))
        if not dep["ok"]:
            return {
                "ok": False, "pid": None, "port": None, "url": None,
                "elapsed_sec": 0.0,
                "error": "依赖缺失: " + ", ".join(dep["missing"]) + "; 请先 webui setup",
                "missing": dep["missing"],
                "exit_code": 8,
            }

    # 3. --with-comfyui: 先确认 ComfyUI 在跑 (不强启动)
    if with_comfyui:
        comfyui_status = _resolve_comfyui_status(app)
        if not comfyui_status.get("running"):
            return {
                "ok": False, "pid": None, "port": None, "url": None,
                "elapsed_sec": 0.0,
                "error": "ComfyUI 未运行; --with-comfyui 要求先启 ComfyUI",
                "exit_code": 6,
            }

    # 4. 启
    pm = WebuiProcessManager(app)
    # WebuiProcessManager.start_webui 是阻塞到 http 就绪 (或 timeout).
    # --no-wait 模式: 短超时, 接受 slow-start 风险
    eff_timeout = 10 if no_wait else timeout
    res = pm.start_webui(timeout=eff_timeout)
    # pidfile 中 env_id 一致化 (build_webui_launch_params 已经在 pm.start_webui 里走完了)
    # 把 pm.start_webui 的所有字段透传 (含 already_running / log_path 等)
    return {
        "ok": res.get("ok") is True,
        "pid": res.get("pid"),
        "port": res.get("port"),
        "url": res.get("url"),
        "elapsed_sec": res.get("elapsed_sec", 0.0),
        "error": res.get("error"),
        "env_id": res.get("env_id"),
        "log_path": res.get("log_path"),
        "already_running": res.get("already_running", False),
        "exit_code": 0 if res.get("ok") else 1,
    }


def _do_stop(app, args) -> dict:
    """stop 子动作."""
    from core.webui_process_manager import WebuiProcessManager
    pm = WebuiProcessManager(app)
    res = pm.stop_webui(force=bool(getattr(args, "force", False)))
    return {
        "ok": res.get("ok") is True,
        "pid": res.get("pid"),
        "elapsed_sec": res.get("elapsed_sec", 0.0),
        "killed": res.get("killed"),
        "error": res.get("error"),
        "exit_code": 0,
    }


def _do_status(app, args) -> dict:
    """status 子动作."""
    res = _resolve_webui_status(app)
    res["exit_code"] = 0 if res["running"] else 3
    return res


def _do_info(app, args) -> dict:
    """info 子动作: 当前生效配置 (路径 / python / port / 安装状态 / 依赖)."""
    from core.webui_dependencies import check_webui_dependencies
    from pathlib import Path

    env_id = getattr(args, "env", None)
    pw_cfg = getattr(app, "config", {}) or {}
    webui_options = dict(pw_cfg.get("webui_options") or {})

    py = _resolve_webui_python(app, env_id=env_id)
    installed = _resolve_webui_installed(app, env_id=env_id)
    deps = {"ok": False, "missing": [], "available": []}
    if py and Path(py).exists():
        deps = check_webui_dependencies(Path(py))

    # 解析过的端口
    port = int(webui_options.get("port") or 8199)
    display_host = webui_options.get("display_host") or "127.0.0.1"

    return {
        "installed": installed,
        "available": installed and deps["ok"],
        "webui_path": _resolve_webui_path(app, env_id=env_id),
        "python_path": py,
        "port": port,
        "display_host": display_host,
        "deps_ok": deps["ok"],
        "deps_missing": deps["missing"],
        "deps_available": deps["available"],
        "env_id": env_id,
        "exit_code": 0,
    }


def _do_restart(app, args) -> dict:
    """restart 子动作: stop + start."""
    stop_res = _do_stop(app, args)
    start_res = _do_start(app, args)
    return {
        "ok": start_res.get("ok") is True,
        "stopped": stop_res.get("ok") is True,
        "started": start_res.get("ok") is True,  # start 返 ok
        "pid": start_res.get("pid"),
        "port": start_res.get("port"),
        "url": start_res.get("url"),
        "elapsed_sec": (stop_res.get("elapsed_sec") or 0)
                       + (start_res.get("elapsed_sec") or 0),
        "error": start_res.get("error") or stop_res.get("error"),
        "exit_code": start_res.get("exit_code", 1),
    }


def _do_install(app, args) -> dict:
    """install 子动作: git clone + 装 deps (无 webui 时)."""
    from core.webui_installer import clone_webui
    from core.webui_dependencies import install_webui_requirements
    from pathlib import Path

    env_id = getattr(args, "env", None)
    webui_path = _resolve_webui_path(app, env_id=env_id)
    if not webui_path:
        return {
            "ok": False, "error": "无法解析 webui_path", "exit_code": 1,
        }
    target = Path(webui_path)

    # 1. clone
    custom_url = getattr(args, "url", None)
    clone_res = clone_webui(app, target, repo_url=custom_url)
    if not clone_res.get("ok"):
        return {
            "ok": False,
            "error": "clone 失败: " + (clone_res.get("error") or ""),
            "log": clone_res.get("log"),
            "exit_code": 1,
        }

    # 2. 装 deps
    py = _resolve_webui_python(app, env_id=env_id)
    if not py or not Path(py).exists():
        return {
            "ok": True, "already_exists": clone_res.get("already_exists"),
            "cloned": True, "deps_ok": False,
            "error": "python 不可用, 跳过 pip install: " + str(py),
            "exit_code": 0,
        }

    req = target / "requirements.txt"
    if not req.exists():
        return {
            "ok": True, "cloned": True,
            "error": "requirements.txt 不存在, 跳过 pip install",
            "exit_code": 0,
        }

    # 走 pypi proxy
    from utils.net import get_pypi_index_url_for_mode
    pypi_mode = (getattr(app, "pypi_proxy_mode", None) or type("V", (), {"get": lambda self: "none"})()).get()
    idx_url = get_pypi_index_url_for_mode(pypi_mode)
    if pypi_mode == "custom":
        try:
            u = (getattr(app, "pypi_proxy_url", None) or type("V", (), {"get": lambda self: ""})()).get()
            if u:
                idx_url = u
        except Exception:
            pass

    dep_res = install_webui_requirements(Path(py), req, index_url=idx_url)
    return {
        "ok": dep_res.get("ok") is True,
        "cloned": True,
        "deps_ok": dep_res.get("ok") is True,
        "deps_installed": dep_res.get("installed"),
        "deps_satisfied": dep_res.get("satisfied"),
        "deps_missing": dep_res.get("missing"),
        "deps_failed": dep_res.get("failed"),
        "deps_error": dep_res.get("error"),
        "exit_code": 0 if dep_res.get("ok") else 1,
    }


def _do_setup(app, args) -> dict:
    """setup 子动作: 装 deps (假定 webui 已 clone)."""
    from core.webui_dependencies import install_webui_requirements
    from pathlib import Path

    env_id = getattr(args, "env", None)
    webui_path = _resolve_webui_path(app, env_id=env_id)
    if not webui_path:
        return {"ok": False, "error": "webui_path 解析失败", "exit_code": 1}
    target = Path(webui_path)
    if not target.exists():
        return {"ok": False, "error": "WebUI 目录不存在: " + str(target), "exit_code": 7}

    req = target / "requirements.txt"
    if not req.exists():
        return {"ok": False, "error": "requirements.txt 不存在: " + str(req), "exit_code": 1}

    py = _resolve_webui_python(app, env_id=env_id)
    if not py or not Path(py).exists():
        return {"ok": False, "error": "python 不可用: " + str(py), "exit_code": 1}

    from utils.net import get_pypi_index_url_for_mode
    pypi_mode = "none"
    try:
        v = getattr(app, "pypi_proxy_mode", None)
        if v:
            pypi_mode = v.get() or "none"
    except Exception:
        pypi_mode = "none"
    idx_url = get_pypi_index_url_for_mode(pypi_mode)
    if pypi_mode == "custom":
        try:
            u = getattr(app, "pypi_proxy_url", None)
            if u:
                idx_url = u.get() or idx_url
        except Exception:
            pass

    dep_res = install_webui_requirements(Path(py), req, index_url=idx_url)
    return {
        "ok": dep_res.get("ok") is True,
        "deps_ok": dep_res.get("ok") is True,
        "deps_installed": dep_res.get("installed"),
        "deps_satisfied": dep_res.get("satisfied"),
        "deps_missing": dep_res.get("missing"),
        "deps_failed": dep_res.get("failed"),
        "deps_error": dep_res.get("error"),
        "exit_code": 0 if dep_res.get("ok") else 1,
    }


def _do_update(app, args) -> dict:
    """update 子动作: git pull (假定 webui 已 clone)."""
    from core.webui_installer import pull_webui
    from pathlib import Path

    env_id = getattr(args, "env", None)
    webui_path = _resolve_webui_path(app, env_id=env_id)
    if not webui_path:
        return {"ok": False, "error": "webui_path 解析失败", "exit_code": 1}
    target = Path(webui_path)
    if not (target / ".git").exists():
        return {"ok": False, "error": "WebUI 不是 git 仓库: " + str(target), "exit_code": 1}

    pull_res = pull_webui(app, target)
    return {
        "ok": pull_res.get("ok") is True,
        "updated": pull_res.get("updated"),
        "log": pull_res.get("log"),
        "error": pull_res.get("error"),
        "exit_code": 0 if pull_res.get("ok") else 1,
    }


def _resolve_comfyui_status(app) -> dict:
    """ComfyUI 当前状态 (复用 cli runner 的 service_status)."""
    try:
        from core.cli.runner import service_status
        return service_status(app) or {}
    except Exception:
        return {"running": False}


_DISPATCH = {
    "start": _do_start,
    "stop": _do_stop,
    "status": _do_status,
    "info": _do_info,
    "restart": _do_restart,
    "install": _do_install,
    "setup": _do_setup,
    "update": _do_update,
}


def run(args, app) -> int:
    """webui 子命令入口. args.webui_action ∈ WEBUI_ACTIONS."""
    action = getattr(args, "webui_action", None)
    as_json = bool(getattr(args, "json", False))

    if action not in WEBUI_ACTIONS:
        msg = f"unsupported webui action: {action!r} (supported: {WEBUI_ACTIONS})"
        if as_json:
            print(format_json({"action": action, "ok": False, "error": msg}))
        else:
            print(f"webui: {msg}")
        return EXIT_ERROR

    fn = _DISPATCH[action]
    try:
        result = fn(app, args)
    except Exception as e:
        if as_json:
            print(format_json({"action": action, "ok": False, "error": str(e)}))
        else:
            print(f"webui {action}: {e}")
        return EXIT_ERROR

    # 规范化: schema 一致
    payload = {"action": action, **result}
    if as_json:
        print(format_json(payload))
    else:
        print(format_human(payload))

    return int(result.get("exit_code", EXIT_OK))
