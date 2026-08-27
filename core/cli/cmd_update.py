"""update 子命令：支持 comfyui（内核）/ plugins（custom_nodes 插件）。

- comfyui: 走 services.update_service.UpdateService 的 update 路径，等价于 GUI 的"更新内核"。
- plugins: 走 services.plugin_service.PluginService，调 ComfyUI-Manager 的 cm-cli update all。
"""
from core.cli.exitcodes import EXIT_OK, EXIT_UP_TO_DATE, EXIT_ERROR
from core.cli.output import format_human, format_json

__all__ = ["run", "UPDATE_TARGETS"]

# 锁住的 target 列表，与 parser.UPDATE_TARGETS 一致
UPDATE_TARGETS = ["comfyui", "plugins"]


def _do_update(app, target: str) -> dict:
    """实际触发更新。返回 dict with keys:
      updated (bool), up_to_date (bool), version (str|None), log (str), error (str|None)
    """
    if target == "plugins":
        try:
            from services.plugin_service import PluginService
            res = PluginService(app).update_all()
            return {
                "updated": bool(res.get("updated")),
                "up_to_date": bool(res.get("up_to_date")),
                "version": None,
                "log": res.get("log") or "",
                "error": res.get("error"),
            }
        except Exception as e:
            return {
                "updated": False, "up_to_date": False, "version": None,
                "log": "", "error": str(e),
            }

    if target != "comfyui":
        return {
            "updated": False, "up_to_date": False, "version": None,
            "log": "", "error": f"unknown target: {target}",
        }
    try:
        from services.update_service import UpdateService
        svc = UpdateService(app)
        result = svc.perform_batch_update()
        # perform_batch_update returns (results_list, summary_str)
        items, summary = result
        updated = any(bool(it.get("updated", False)) for it in items) if items else False
        # 从 items 中抽 core 项的 from_version / to_version（issue 9）。
        # _run_batch 已把 pre_core 存进 core_res["before"]，这里读 tag/commit。
        core_item = next((it for it in items if it.get("component") == "core"), None)
        to_version = None
        from_version = None
        if core_item:
            to_version = core_item.get("tag") or core_item.get("commit")
            before = core_item.get("before") or {}
            from_version = before.get("tag") or before.get("commit") or None
        return {
            "updated": updated,
            "up_to_date": not updated and bool(items),
            "version": to_version,
            "from_version": from_version,
            "to_version": to_version,
            "items": items,
            "log": summary,
            "error": None,
        }
    except Exception as e:
        return {
            "updated": False, "up_to_date": False, "version": None,
            "log": "", "error": str(e),
        }


def run(args, app) -> int:
    target = getattr(args, "update_target", "comfyui")
    dry_run = bool(getattr(args, "dry_run", False))
    as_json = bool(getattr(args, "json", False))

    if target not in UPDATE_TARGETS:
        msg = f"unsupported update target: {target!r} (supported: {UPDATE_TARGETS})"
        if as_json:
            print(format_json({"component": target, "updated": False, "log": "", "error": msg}))
        else:
            print(f"update: {msg}")
        return EXIT_ERROR

    if dry_run:
        # 只打印会做什么，不实际执行
        would_do = {
            "comfyui": "would invoke UpdateService.perform_batch_update()",
            "plugins": "would invoke PluginService.update_all() (cm-cli update all)",
        }.get(target, "would invoke update")
        data = {
            "component": target,
            "updated": False,
            "from_version": None,
            "to_version": None,
            "log": f"dry-run: {would_do}",
        }
        if as_json:
            print(format_json(data))
        else:
            print(format_human(data))
        return EXIT_OK

    result = _do_update(app, target)

    # 兜底：如果 _do_update 没填 from_version/to_version，从 items 里抽（issue 9）
    items = result.get("items") or []
    if result.get("from_version") is None and items:
        core_item = next((it for it in items if it.get("component") == "core"), None)
        if core_item:
            before = core_item.get("before") or {}
            result["from_version"] = before.get("tag") or before.get("commit") or None
            result["to_version"] = core_item.get("tag") or core_item.get("commit") or None

    if result.get("error"):
        data = {
            "component": target,
            "updated": False,
            "from_version": result.get("from_version"),
            "to_version": result.get("to_version"),
            "log": result.get("log") or "",
            "error": result["error"],
        }
        if as_json:
            print(format_json(data))
        else:
            print(f"update failed: {result['error']}")
        return EXIT_ERROR

    if result.get("up_to_date"):
        data = {
            "component": target,
            "updated": False,
            "from_version": result.get("from_version"),
            "to_version": result.get("to_version"),
            "log": result.get("log") or "already up to date",
        }
        if as_json:
            print(format_json(data))
        else:
            print(format_human(data))
        return EXIT_UP_TO_DATE

    data = {
        "component": target,
        "updated": bool(result.get("updated")),
        "from_version": result.get("from_version"),
        "to_version": result.get("to_version"),
        "log": result.get("log") or "",
    }
    if as_json:
        print(format_json(data))
    else:
        print(format_human(data))
    return EXIT_OK
