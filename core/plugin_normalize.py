"""PluginService 返回值的归一化（三套契约 → 统一 report item）。

PluginService 有**三套**返回契约（核对 plugin_service.py 后确认）：

+-------------------------------+----------------------------------+-------------------+----------------------------------+
| 调用路径                      | action                           | 返回类型          | 字段集                           |
+===============================+==================================+===================+==================================+
| ``_lifecycle`` (:478-486)     | install/uninstall/enable/disable | ``dict``          | ``{ok, log, error}``             |
+-------------------------------+----------------------------------+-------------------+----------------------------------+
| ``_do_update`` (:513-529)     | update_all/selected (force=false)| ``dict``          | ``{updated, up_to_date, log, error}`` |
+-------------------------------+----------------------------------+-------------------+----------------------------------+
| ``force_update_selected``     | update (force=true)              | ``list[dict]``    | 每项 ``{name, ok, skipped, detail}`` |
| (:488) → ``_force_update_one``|                                  |                   |                                  |
| (:496-511)                    |                                  |                   |                                  |
+-------------------------------+----------------------------------+-------------------+----------------------------------+

PackageUpdateService 拿到的 item 要塞进统一 report schema（status / reason / log / error），
必须把这三套都归一化。本模块就是这层 adapter，纯函数、不依赖 app / PyQt5。

**两个陷阱**（核对代码发现，见 plan §3.2）：

1. ``_do_update`` 的 ``up_to_date`` **恒为 False**、成功路径 ``updated`` **恒为 True**
   （源码注释：cm-cli update 输出是人类文本，无法可靠区分「真更新了」与「本就最新」）。
   → 归一化只看 ``error`` 是否为 None，**不要**读 ``updated`` / ``up_to_date``。

2. ``force_update_selected`` 成功路径的 ``detail`` 是正常文本（如 ``"已是最新"`` 或
   git pull stdout），失败路径才是 ``"pull 失败 (rc=...): ..."``。
   → 成功时 ``detail`` 该进 ``log``（或丢弃），**不能无条件塞进 ``error``**，
   否则 report 看起来全是 error。

**不用 ``set >= set`` 子集判断**（v3.2 之前的脆弱写法）：底层多返一个字段就静默走错分支。
改用 ``action`` + ``force`` 显式分支。
"""
from __future__ import annotations

from typing import Any


def normalize_plugin_result(
    raw: Any,
    action: str,
    force: bool = False,
    spec: str | None = None,
) -> dict[str, Any]:
    """把 PluginService 的三套返回归一化成统一 report item 字段。

    Args:
        raw: PluginService 方法的原始返回值（dict 或 list[dict]，取决于 action+force）
        action: plugin item 的 action（install/uninstall/enable/disable/update）
        force: 是否走了 force_update_selected（仅 action=update 时可能为 True）
        spec: plugin 的 spec（force=true 时用于从 list 里按 name 找对应项）

    Returns:
        dict 含：
        - ``ok``: bool —— 是否成功
        - ``error``: str | None —— 失败详情（成功时为 None）
        - ``log``: str | None —— 正常日志（force 成功路径的 detail）
        - ``not_applicable``: bool —— True 表示「系统不支持」（如 force 对非 git 仓库）
        - ``reason``: str | None —— 结构化跳过原因（仅 not_applicable=True 时有值）

    Raises:
        ValueError: action 非法 / force=true 但 raw 里找不到 spec 对应项（后者不 raise，
            标 ok=False + error）
    """
    if action in ("install", "uninstall", "enable", "disable"):
        # 契约 1：_lifecycle 返 {ok, log, error}
        return {
            "ok": bool(raw.get("ok")) if isinstance(raw, dict) else False,
            "error": raw.get("error") if isinstance(raw, dict) else "PluginService 返回非 dict",
            "log": raw.get("log") if isinstance(raw, dict) else None,
            "not_applicable": False,
            "reason": None,
        }
    if action == "update" and not force:
        # 契约 2：_do_update 返 {updated, up_to_date, log, error}
        # ⚠️ 不读 updated / up_to_date（陷阱 1：恒为 True/False，不可靠），只看 error
        if not isinstance(raw, dict):
            return {"ok": False, "error": "PluginService 返回非 dict", "log": None,
                    "not_applicable": False, "reason": None}
        err = raw.get("error")
        return {
            "ok": not err,
            "error": err,
            "log": raw.get("log"),
            "not_applicable": False,
            "reason": None,
        }
    if action == "update" and force:
        # 契约 3：force_update_selected 返 list[{name, ok, skipped, detail}]
        return _normalize_force(raw, spec)
    raise ValueError(f"unknown plugin action: {action!r}")


def _normalize_force(raw: Any, spec: str | None) -> dict[str, Any]:
    """处理 force_update_selected 的 list[dict] 返回。

    按 spec 从 list 里取对应项（force_update_selected 一次更新多个插件，每个插件一项）。
    """
    if not isinstance(raw, list):
        return {"ok": False, "error": "force_update_selected 返回非 list", "log": None,
                "not_applicable": False, "reason": None}
    if spec is None:
        return {"ok": False, "error": "force=true 需要 spec 从 list 里定位结果", "log": None,
                "not_applicable": False, "reason": None}
    item = next((x for x in raw if isinstance(x, dict) and x.get("name") == spec), None)
    if item is None:
        return {
            "ok": False,
            "error": f"force_update_selected 未返回 {spec} 的结果",
            "log": None,
            "not_applicable": False,
            "reason": None,
        }
    if item.get("skipped"):
        # 非 git 仓库 → not_applicable（force_update_selected 对 CNR id 返 skipped）
        return {
            "ok": False,
            "error": item.get("detail"),
            "log": None,
            "not_applicable": True,
            "reason": "not_git_for_force",
        }
    # ⚠️ detail 语义随 ok 变化（陷阱 2）：
    #   成功路径 detail = pull stdout 或 "已是最新"（正常文本，非错误）
    #   失败路径 detail = "pull 失败 (rc=...): ..."
    # 成功时 error 置 None，detail 进 log；失败时 detail 才进 error
    ok = bool(item.get("ok"))
    detail = item.get("detail")
    return {
        "ok": ok,
        "error": None if ok else detail,
        "log": detail if ok else None,
        "not_applicable": False,
        "reason": None,
    }
