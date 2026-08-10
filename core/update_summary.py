"""把更新结果格式化成用户可读摘要的**纯函数**模块。

历史上这个函数 ``_format_update_summary`` 住在 ``ui_qt/qt_app.py`` 里，但
``qt_app`` 在某些 PyQt5/sip ABI 组合下 import 时会段错误（``PyQtLauncher``
类定义处），导致任何想测这个纯函数的测试模块（顶层 ``from ui_qt.qt_app
import _format_update_summary``）在 collection 阶段就崩，连带整个
``tests/unit/`` 套件一起挂。

本函数**不依赖任何 Qt / 全局状态**（只接受 dict 返回 str），把它抽到这个
纯模块里后：
  - 测试可以直接 ``from core.update_summary import format_update_summary``，
    不再触达段错误路径。
  - ``ui_qt/qt_app.py`` 仍保留 ``_format_update_summary`` 名字（向后兼容），
    内部改为从本模块 re-import。

行为与原 ``qt_app._format_update_summary`` 完全一致，逐字搬迁，不改逻辑。
"""

from typing import Optional


def format_update_summary(
    core_res: Optional[dict], req_res: Optional[dict]
) -> str:
    """Format the update result into a user-facing summary.

    For dependencies, the first line is always a three-part count
    (satisfied / updated / failed) and any failure details are pushed
    underneath as indented sub-items, so the reason lives in the same
    hierarchy as the package it belongs to.
    """
    lines = []
    if isinstance(core_res, dict):
        if core_res.get("error"):
            err = str(core_res.get("error") or "")
            err = err.strip().replace("\r", " ").replace("\n", " ")
            if len(err) > 180:
                err = err[:180] + "…"
            lines.append(
                f"内核：更新失败（{err}）"
                if err
                else "内核：更新失败"
            )
        else:
            tag = core_res.get("tag") or ""
            br = core_res.get("branch") or ""
            suffix = f"（{tag or br}）" if (tag or br) else ""
            if core_res.get("updated") is True:
                lines.append(f"内核：已更新{suffix}")
            elif core_res.get("updated") is False:
                lines.append(f"内核：已是最新{suffix}")
            else:
                lines.append(f"内核：更新流程完成{suffix}")
    if isinstance(req_res, dict):
        missing = req_res.get("missing") or []
        failed = req_res.get("failed") or []
        installed = req_res.get("installed") or []
        satisfied = req_res.get("satisfied") or []
        frozen = req_res.get("frozen") or []
        # missing = 镜像未同步（VERSION_NOT_FOUND）类
        # failed  = 其他错误（网络、权限、冲突...）类，每条自带 reason
        # frozen  = 黑名单跳过（torch / numpy / frontend / templates）类
        is_mirror_issue = req_res.get("error_code") == "VERSION_NOT_FOUND" and bool(missing)
        generic_err = str(req_res.get("error") or "").strip().replace("\r", " ").replace("\n", " ")
        if len(generic_err) > 200:
            generic_err = generic_err[:200] + "…"
        total_failures = len(missing) + len(failed)

        if installed or satisfied or total_failures or frozen:
            # 一行四项计数：黑名单独立呈现，不加入失败
            counts = (
                f"依赖：已满足 {len(satisfied)} 项，"
                f"已更新 {len(installed)} 项，"
                f"失败 {total_failures} 项，"
                f"跳过 {len(frozen)} 项"
            )
            lines.append(counts)
            # 黑名单明细：单行紧凑呈现。每条一行 "- name (已跳过)" 占太多竖向空间，
            # 改为 "自动跳过（无需操作）：name1, name2, ..."。超过 6 个则折叠为“等 N 项”。
            if frozen:
                names = [
                    item.get("name") if isinstance(item, dict) else str(item)
                    for item in frozen
                ]
                if len(names) <= 6:
                    lines.append(f"  自动跳过（无需操作）：{", ".join(names)}")
                else:
                    head = ", ".join(names[:6])
                    lines.append(f"  自动跳过（无需操作）：{head} 等 {len(names)} 项")
            # 失败明细：作为子项缩进挂在计数行下
            # 镜像未同步在前，其他错误在后，每条都带自己的原因
            detail_lines = []
            for pkg in missing[:5]:
                detail_lines.append(f"  - {pkg}（镜像源未同步）")
            for item in failed[: max(0, 5 - len(missing))]:
                spec = item.get("spec") if isinstance(item, dict) else str(item)
                reason = (item.get("reason") if isinstance(item, dict) else None) or generic_err or "未知原因"
                detail_lines.append(f"  - {spec}（{reason}）")
            lines.extend(detail_lines)
            # 修复原本的“等 N 个”数学 bug：用剩余数而不是总数
            remaining_failures = total_failures - len(detail_lines)
            if remaining_failures > 0:
                lines.append(f"  - ... 等 {remaining_failures} 个")
            # 提示：仅在有失败时出现，且只挑出与失败原因匹配的指引
            if is_mirror_issue:
                lines.append(
                    "提示：未同步的包可能 PyPI 镜像未及时同步，可稍后重试。"
                    "也可在 设置 → PyPI 镜像 中选择“取消”，改用 PyPI 官方源后重试。"
                )
            elif failed and not missing:
                lines.append(
                    "提示：依赖中存在非镜像类错误，可稍后重试，"
                    "或在 设置 → PyPI 镜像 中选择“取消”改用 PyPI 官方源后再试。"
                )
            elif generic_err and not is_mirror_issue:
                lines.append(
                    "提示：可稍后重试，或在 设置 → PyPI 镜像 中选择“取消”改用官方源。"
                )
        elif generic_err:
            # 既没有 installed/satisfied 也没有 missing/failed，但有 error
            lines.append(
                f"依赖：已满足 0 项，已更新 0 项，失败 1 项，跳过 0 项"
            )
            lines.append(f"  - <全部>（{generic_err}）")
        elif req_res.get("summary"):
            lines.append("依赖：已是最新")
    return "\n".join(lines).strip() or "更新流程完成"


def confirm_deps_or_warn(parent, auto_update_deps_var) -> bool:
    """点击更新时检查用户是否勾选了“同时更新依赖库”。

    如果没勾，弹出提醒，让用户选择是否继续。返回 True 代表继续，False 代表取消。

    仅更新内核不更新依赖库可能造成 ComfyUI 启动后闪退或界面问题，所以这里加上一道确认。

    从 ``ui_qt.qt_app._confirm_deps_or_warn`` 抽到本纯模块的原因同
    :func:`format_update_summary`：让测试能在不触达 ``qt_app`` 段错误路径的前提下
    验证。``DialogHelper`` 在函数内部 lazy import，所以本函数本身不需要 Qt 顶层依赖。
    ``qt_app._confirm_deps_or_warn`` 作为向后兼容别名 re-import 本函数。
    """
    try:
        deps_enabled = bool(auto_update_deps_var.get())
    except Exception:
        # 读不出来时默认以“勾选了依赖”看待，不该拦住用户
        return True
    if deps_enabled:
        return True
    try:
        from ui_qt.widgets.dialog_helper import DialogHelper
        return DialogHelper.show_confirmation(
            parent,
            "未勾选“同时更新依赖库”",
            "如果仅更新 ComfyUI 内核，可能会导致闪退或界面问题，"
            "建议勾选“同时更新依赖库”。\n\n是否仍要继续？",
            yes_text="继续更新",
            no_text="取消",
        )
    except Exception:
        # 对话框出问题不能拦住用户，让他们能继续点“更新”
        return True
