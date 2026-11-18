"""service 子命令: 伴生服务（companion services）统一入口.

  service list [--json]
  service <ACTION> <SERVICE_ID> [flags]

ACTION ∈ start / stop / status / info / restart / update；SERVICE_ID 见
core.companion.spec.BUILTIN_SERVICES（当前: webui / openjutsu / h3-engine）.

webui 在注册表里是名义条目（runtime="webui-legacy"，strangler P1）：
`service ... webui` 内部转发老五件套（cmd_webui._do_*），行为与 `webui ...`
完全一致；openjutsu / h3-engine 走 core/companion 新框架。

--env：start / stop / status / info / update 都接受 `--env <ENV_ID>`，透传到
manager（stop 也不例外 —— 少了它会拿激活环境的身份规则去动别的环境）。

Exit codes（与 webui 子命令同值同义，见 exitcodes.py 的 service 段）:
  0  success（start 已在跑也返 0, already_running=true 幂等）
  1  general error（含端口被占 / spawn 失败 / 超时）
  3  status 未在跑
  6  start 时 requires_comfyui 的服务发现 ComfyUI 未跑（不强启动）
  7  服务未安装 / 当前环境无此服务
  8  依赖缺失
"""
from __future__ import annotations

from typing import Any

from core.cli.exitcodes import (
    EXIT_OK,
    EXIT_ERROR,
)
from core.cli.output import format_human, format_json

__all__ = ["run", "SERVICE_ACTIONS"]

SERVICE_ACTIONS = ["list", "start", "stop", "status", "info", "restart",
                   "install", "setup", "update"]


def _known_services() -> dict:
    from core.companion.spec import BUILTIN_SERVICES
    return BUILTIN_SERVICES


def _is_legacy(service_id: str) -> bool:
    return _known_services()[service_id].runtime == "webui-legacy"


# ---------------- 各 action ----------------

def _do_list(app, args) -> dict:
    """注册表总览: 每服务 available(文件系统) + running(身份校验过的进程)."""
    from core.companion import registry
    services = []
    for spec in registry.all_specs():
        avail = registry.availability(app, spec, env_id=getattr(args, "env", None))
        running = _service_running(app, spec)
        services.append({
            "id": spec.id,
            "name": spec.name,
            "runtime": spec.runtime,
            "requires_comfyui": spec.requires_comfyui,
            "available": avail["available"],
            "running": running,
        })
    return {"ok": True, "services": services, "exit_code": 0}


def _service_running(app, spec) -> bool:
    """便宜的 running 判定 (list 用): 只读 pidstore + 身份门, 不探端口/不收养."""
    try:
        if spec.runtime == "webui-legacy":
            from core.webui_process_manager import WebuiProcessManager
            return bool(WebuiProcessManager(app).is_running())
        from core.companion.manager import CompanionServiceManager
        return bool(CompanionServiceManager(app, spec.id).is_running())
    except Exception:
        return False


def _do_start(app, args) -> dict:
    service_id = args.service_id
    if _is_legacy(service_id):
        from core.cli import cmd_webui
        res = cmd_webui._do_start(app, args)
        res["service"] = service_id
        return res
    from core.companion.manager import CompanionServiceManager
    no_wait = bool(getattr(args, "no_wait", False))
    timeout = int(getattr(args, "timeout", 120) or 120)
    res = CompanionServiceManager(app, service_id,
                                  env_id=getattr(args, "env", None)).start(
        timeout=timeout, no_wait=no_wait)
    return res


def _do_stop(app, args) -> dict:
    service_id = args.service_id
    if _is_legacy(service_id):
        from core.cli import cmd_webui
        res = cmd_webui._do_stop(app, args)
        res["service"] = service_id
        return res
    from core.companion.manager import CompanionServiceManager
    # --env 要透传: 否则 stop 会拿**激活环境**的 root/端口去核对身份, 结果是
    # 「停 A 环境」时去动 B 环境 (多环境同端口的服务尤其危险).
    res = CompanionServiceManager(app, service_id,
                                  env_id=getattr(args, "env", None)).stop(
        force=bool(getattr(args, "force", False)))
    return res


def _do_status(app, args) -> dict:
    service_id = args.service_id
    if _is_legacy(service_id):
        from core.webui_process_manager import WebuiProcessManager
        res = WebuiProcessManager(app).status()
        res["service_id"] = service_id
        res["exit_code"] = 0 if res.get("running") else 3
        return res
    from core.companion.manager import CompanionServiceManager
    res = CompanionServiceManager(app, service_id,
                                  env_id=getattr(args, "env", None)).status()
    res["exit_code"] = 0 if res.get("running") else 3
    return res


def _do_info(app, args) -> dict:
    service_id = args.service_id
    if _is_legacy(service_id):
        from core.cli import cmd_webui
        res = cmd_webui._do_info(app, args)
        res["service"] = service_id
        return res
    from core.companion import registry
    from core.companion.manager import CompanionServiceManager
    env_id = getattr(args, "env", None)
    spec = registry.get(service_id)
    avail = registry.availability(app, spec, env_id=env_id)
    ports = registry.resolved_ports(app, spec)
    res = {
        "ok": True,
        "service_id": spec.id,
        "name": spec.name,
        "installed": avail["available"],
        "available": avail["available"],
        "root": avail["root"],
        "missing_markers": avail["missing_markers"],
        "ports": ports,
        "requires_comfyui": spec.requires_comfyui,
        "runtime": spec.runtime,
        "env_id": env_id,
        "exit_code": 0,
    }
    if avail["available"]:
        try:
            from core.companion.manager import CompanionServiceManager
            m = CompanionServiceManager(app, service_id, env_id=env_id)
            res["running"] = m.is_running()
            res["log_path"] = str(m._log_path())
            try:
                # 依赖检查按**所选服务自己的 runtime** 走 (原先固定调 openjutsu,
                # 换个服务就查错东西).
                deps = m._runtime().check_deps(m._paths())
                res["deps_ok"] = deps["ok"]
                res["deps_missing"] = deps["missing"]
            except Exception:
                pass
        except Exception:
            pass
    return res


def _do_restart(app, args) -> dict:
    stop_res = _do_stop(app, args)
    start_res = _do_start(app, args)
    start_res.setdefault("service", args.service_id)
    return {
        "ok": start_res.get("ok") is True,
        "stopped": stop_res.get("ok") is True,
        "started": start_res.get("ok") is True,
        "pid": start_res.get("pid"),
        "pids": start_res.get("pids"),
        "ports": start_res.get("ports"),
        "url": start_res.get("url"),
        "elapsed_sec": (stop_res.get("elapsed_sec") or 0)
                       + (start_res.get("elapsed_sec") or 0),
        "error": start_res.get("error") or stop_res.get("error"),
        "exit_code": start_res.get("exit_code", 1),
    }


def _do_install(app, args) -> dict:
    """install: 下载服务本体 (runtime 提供 install 钩子时)."""
    service_id = args.service_id
    if _is_legacy(service_id):
        from core.cli import cmd_webui
        res = cmd_webui._do_install(app, args)
        res["service"] = service_id
        return res
    from core.companion.manager import CompanionServiceManager
    m = CompanionServiceManager(app, service_id, env_id=getattr(args, "env", None))
    res = m.install(repo_url=getattr(args, "url", None))
    res["service"] = service_id
    return res


def _do_setup(app, args) -> dict:
    """setup: 装服务运行依赖 (runtime 提供 setup 钩子时)."""
    service_id = args.service_id
    if _is_legacy(service_id):
        from core.cli import cmd_webui
        res = cmd_webui._do_setup(app, args)
        res["service"] = service_id
        return res
    from core.companion.manager import CompanionServiceManager
    m = CompanionServiceManager(app, service_id, env_id=getattr(args, "env", None))
    res = m.setup()
    res["service"] = service_id
    return res


def _do_update(app, args) -> dict:
    service_id = args.service_id
    if _is_legacy(service_id):
        from core.cli import cmd_webui
        res = cmd_webui._do_update(app, args)
        res["service"] = service_id
        return res
    from core.companion.manager import CompanionServiceManager
    res = CompanionServiceManager(app, service_id,
                                  env_id=getattr(args, "env", None)).update()
    return res


_DISPATCH = {
    "list": _do_list,
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
    """service 子命令入口. args.service_action ∈ SERVICE_ACTIONS."""
    action = getattr(args, "service_action", None)
    as_json = bool(getattr(args, "json", False))
    service_id = getattr(args, "service_id", None)

    if action not in SERVICE_ACTIONS:
        msg = f"unsupported service action: {action!r} (supported: {SERVICE_ACTIONS})"
        if as_json:
            print(format_json({"action": action, "ok": False, "error": msg}))
        else:
            print(f"service: {msg}")
        return EXIT_ERROR

    if action != "list":
        known = _known_services()
        if not service_id:
            msg = f"service {action} 需要服务 id (可选: {', '.join(sorted(known))})"
            if as_json:
                print(format_json({"action": action, "ok": False, "error": msg}))
            else:
                print(f"service: {msg}")
            return EXIT_ERROR
        if service_id not in known:
            msg = f"未知服务: {service_id!r} (可选: {', '.join(sorted(known))})"
            if as_json:
                print(format_json({"action": action, "service": service_id,
                                   "ok": False, "error": msg}))
            else:
                print(f"service: {msg}")
            return EXIT_ERROR

    fn = _DISPATCH[action]
    try:
        result = fn(app, args)
    except Exception as e:
        if as_json:
            print(format_json({"action": action, "service": service_id,
                               "ok": False, "error": str(e)}))
        else:
            print(f"service {action} {service_id or ''}: {e}".strip())
        return EXIT_ERROR

    payload = {"action": action, "service": service_id, **result} \
        if service_id else {"action": action, **result}
    if as_json:
        print(format_json(payload))
    else:
        print(format_human(payload))

    return int(result.get("exit_code", EXIT_OK))
