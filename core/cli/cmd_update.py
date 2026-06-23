"""update 子命令：当前仅支持 comfyui。

走 services.update_service.UpdateService 的 update 路径。等价于
GUI 的"更新内核"按钮。
"""
from core.cli.exitcodes import EXIT_OK, EXIT_UP_TO_DATE, EXIT_ERROR
from core.cli.output import format_human, format_json

__all__ = ["run", "UPDATE_TARGETS"]

# 锁住的 target 列表，与 parser.UPDATE_TARGETS 一致
UPDATE_TARGETS = ["comfyui"]


def _do_update(app, target: str) -> dict:
    """实际触发更新。返回 dict with keys:
      updated (bool), up_to_date (bool), version (str|None), log (str), error (str|None)
    """
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
        return {
            "updated": updated,
            "up_to_date": not updated and bool(items),
            "version": None,
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
            from core.cli.output import format_json
            print(format_json({"component": target, "updated": False, "log": "", "error": msg}))
        else:
            print(f"update: {msg}")
        return EXIT_ERROR

    if dry_run:
        # 只打印会做什么，不实际执行
        data = {
            "component": target,
            "updated": False,
            "from_version": None,
            "to_version": None,
            "log": "dry-run: would invoke UpdateService.perform_batch_update()",
        }
        if as_json:
            print(format_json(data))
        else:
            print(format_human(data))
        return EXIT_OK

    result = _do_update(app, target)

    if result.get("error"):
        data = {
            "component": target,
            "updated": False,
            "from_version": None,
            "to_version": None,
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
            "from_version": None,
            "to_version": None,
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
        "from_version": None,
        "to_version": result.get("version"),
        "log": result.get("log") or "",
    }
    if as_json:
        print(format_json(data))
    else:
        print(format_human(data))
    return EXIT_OK
