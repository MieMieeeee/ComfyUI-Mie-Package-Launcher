"""plugins 子命令：管理 custom_nodes 插件。

复用 services.plugin_service.PluginService 的全部能力（与 GUI 同一套）：
    list / install / uninstall / disable / enable / check-updates / force-update

调用形态与 cmd_update 的 plugins target 一致：
    PluginService(app).<method>()

各 action 的 Output schema 见 _PLUGINS_EPILOG（parser.py），docs/cli.md 同步。
"""
from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli.output import format_human, format_json

__all__ = ["run", "PLUGINS_ACTIONS"]

# 锁住的 action 列表，与 parser.PLUGINS_ACTIONS 一致
PLUGINS_ACTIONS = ["list", "install", "uninstall", "disable", "enable",
                   "check-updates", "force-update"]


def _svc(app):
    """懒构造 PluginService（CLI 的 HeadlessAppContext 上没有 .services）。"""
    from services.plugin_service import PluginService
    return PluginService(app)


def _emit(as_json, data):
    if as_json:
        print(format_json(data))
    else:
        print(format_human(data))


def _do_list(app) -> dict:
    plugins = _svc(app).list_installed()
    return {"plugins": plugins, "count": len(plugins), "error": None}


def _do_lifecycle(app, op, target) -> dict:
    """install/uninstall/disable/enable 共用：跑 cm-cli <op> <target>。"""
    if not target:
        return {"ok": False, "log": "", "error": f"{op} 需要一个参数（插件 dir_name / git URL / CNR id）"}
    svc = _svc(app)
    fn = {"install": svc.install, "uninstall": svc.uninstall,
          "disable": svc.disable, "enable": svc.enable}[op]
    res = fn(target)
    return {"ok": bool(res.get("ok")), "log": res.get("log") or "",
            "error": res.get("error")}


def _do_check_updates(app) -> dict:
    outdated = _svc(app).check_updates()
    return {"outdated": outdated, "count": len(outdated), "error": None}


def _do_force_update(app, names) -> dict:
    """force-update：无 names 则全部，有则指定。返回每插件结果。"""
    svc = _svc(app)
    if not names:
        names = [p["dir_name"] for p in svc.list_installed()]
    if not names:
        return {"results": [], "error": None}
    results = svc.force_update_selected(names)
    return {"results": results, "error": None}


def run(args, app) -> int:
    action = getattr(args, "plugins_action", None)
    target = getattr(args, "plugins_name", None)  # install/uninstall/disable/enable 用
    as_json = bool(getattr(args, "json", False))

    if action not in PLUGINS_ACTIONS:
        msg = f"unsupported plugins action: {action!r} (supported: {PLUGINS_ACTIONS})"
        if as_json:
            print(format_json({"action": action, "error": msg}))
        else:
            print(f"plugins: {msg}")
        return EXIT_ERROR

    try:
        if action == "list":
            r = _do_list(app)
            _emit(as_json, r)
            return EXIT_OK

        if action in ("install", "uninstall", "disable", "enable"):
            r = _do_lifecycle(app, action, target)
            if r.get("error") or not r.get("ok"):
                _emit(as_json, {"action": action, "target": target,
                                "ok": False, "log": r.get("log") or "",
                                "error": r.get("error")})
                return EXIT_ERROR
            _emit(as_json, {"action": action, "target": target,
                            "ok": True, "log": r.get("log") or "", "error": None})
            return EXIT_OK

        if action == "check-updates":
            r = _do_check_updates(app)
            _emit(as_json, r)
            return EXIT_OK  # 信息查询，有无 outdated 都不算错误

        if action == "force-update":
            # plugins_name 是 nargs="?" 单值；CLI 不支持一次传多个（要多个走 GUI）
            # 这里接受单个，或为空则全部。多插件用空格分隔在 nargs="*" 才行，
            # 但 install/uninstall 等只要一个，故统一 nargs="?"。
            names = [target] if target else []
            r = _do_force_update(app, names)
            results = r.get("results") or []
            # 空结果（没插件可更新）视为成功；有结果则要求全部 ok
            all_ok = (not results) or all(x.get("ok") for x in results)
            _emit(as_json, {"action": "force-update", "results": results,
                            "all_ok": all_ok, "error": None})
            return EXIT_OK if all_ok else EXIT_ERROR
    except Exception as e:
        _emit(as_json, {"action": action, "error": str(e)})
        return EXIT_ERROR

    return EXIT_ERROR  # 理论不可达
