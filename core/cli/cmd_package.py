"""package 子命令：加载 manifest，show / diff / apply（plan §4）。

manifest 来源判别：http:// / https:// 前缀走 URL；其它当本地文件路径。
http:// 直接拒绝（exit 11），manifest URL 必须 HTTPS（plan §6.4）。

Exit codes（plan §4.3 唯一定义处）：
  0  全部 ok / skipped / not_applicable（无 failed）
  1  通用错误
  5  部分失败（≥1 项 failed）—— ok_at_alt_path / not_applicable / manual_required 不算
  9  前置不兼容（dirty tree + clean_untracked=false / env 不匹配且未 --auto-yes）
  10 manifest 无效（schema / sha256 / manifest_version 超支持范围）
  11 文件不存在 / URL 不可达 / 解析失败 / manifest URL 非 HTTPS
"""
from __future__ import annotations

import sys

from core.cli.exitcodes import (
    EXIT_OK,
    EXIT_ERROR,
    EXIT_PACKAGE_PARTIAL_FAILURE,
    EXIT_PACKAGE_PRECONDITION,
    EXIT_PACKAGE_MANIFEST_INVALID,
    EXIT_PACKAGE_SOURCE_UNREACHABLE,
)
from core.cli.output import format_human, format_json

__all__ = ["run"]


def _get_service(app):
    """从 app.services 拿 PackageUpdateService（headless 已注入；GUI 在 qt_app 注册）。"""
    return app.services.package


def _load_and_validate(svc, source: str, want_json: bool):
    """加载 + 校验 manifest。返回 (manifest, parsed_ok, error_msg, exit_code)。

    失败时已 print 错误到 stderr（CLI 契约），返回的 exit_code 给 run() 直接 return。
    """
    try:
        manifest, _resolved = svc.load_source(source)
    except ValueError as e:
        msg = str(e)
        # 区分 http:// 拒绝（11）vs 文件不存在/URL 不可达（11）
        print(f"[package] 加载失败: {msg}", file=sys.stderr)
        return None, False, msg, EXIT_PACKAGE_SOURCE_UNREACHABLE
    ok, err = svc.validate(manifest)
    if not ok:
        print(f"[package] manifest 无效: {err}", file=sys.stderr)
        return None, False, err, EXIT_PACKAGE_MANIFEST_INVALID
    return manifest, True, None, EXIT_OK


def _show(svc, app, source: str, want_json: bool) -> int:
    """package show：加载 + 校验 + diff + 打印摘要。"""
    manifest, ok, err, code = _load_and_validate(svc, source, want_json)
    if not ok:
        return code
    diff = svc.diff_against_current(manifest)
    if "error" in diff:
        print(f"[package] diff 失败: {diff['error']}", file=sys.stderr)
        return EXIT_PACKAGE_MANIFEST_INVALID
    # current_versions
    current = {}
    try:
        kv = app.services.version.get_current_kernel_version()
        if kv:
            current["comfyui"] = kv.get("tag") or kv.get("commit") or ""
    except Exception:
        pass
    data = {
        "manifest": manifest,
        "valid": True,
        "validation_error": None,
        "diff": diff,
        "current_versions": current,
    }
    if want_json:
        print(format_json(data))
    else:
        _print_show_human(manifest, diff, current)
    return EXIT_OK


def _diff(svc, source: str, want_json: bool) -> int:
    """package diff：只输出 diff 段。"""
    manifest, ok, err, code = _load_and_validate(svc, source, want_json)
    if not ok:
        return code
    diff = svc.diff_against_current(manifest)
    if "error" in diff:
        print(f"[package] diff 失败: {diff['error']}", file=sys.stderr)
        return EXIT_PACKAGE_MANIFEST_INVALID
    if want_json:
        print(format_json(diff))
    else:
        print(format_human(diff))
    return EXIT_OK


def _apply(svc, app, args, want_json: bool) -> int:
    """package apply：应用 manifest，返回退出码。"""
    source = getattr(args, "source", None)
    manifest, ok, err, code = _load_and_validate(svc, source, want_json)
    if not ok:
        return code
    # flags
    item_ids = None
    if getattr(args, "items", None):
        item_ids = [s.strip() for s in str(args.items).split(",") if s.strip()]
    manual_decisions = {}
    if getattr(args, "manual_yes", False):
        # 所有 model 项视作用户已下载
        try:
            from core.package_manifest import parse_manifest
            parsed = parse_manifest(manifest)
            for it in parsed.items:
                if it.kind == "model":
                    manual_decisions[it.id] = "yes"
        except Exception:
            pass
    if getattr(args, "manual_skip", False):
        try:
            from core.package_manifest import parse_manifest
            parsed = parse_manifest(manifest)
            for it in parsed.items:
                if it.kind == "model":
                    manual_decisions[it.id] = "skip"
        except Exception:
            pass
    auto_yes = bool(getattr(args, "auto_yes", False))
    # CLI 非交互：env 不匹配时 confirm_env_mismatch=None，未 --auto-yes 即拒绝
    report = svc.apply(
        manifest,
        item_ids=item_ids,
        manual_decisions=manual_decisions,
        auto_yes=auto_yes,
        confirm_env_mismatch=None,  # CLI 不弹窗
    )
    exit_hint = report.get("exit_hint", EXIT_OK)
    # 持久化 report（issue 10）：与 GUI 行为一致，CLI 也要写 runs/<run_id>.json。
    # save_report 内部 catch IO 异常并只写 logger.warning，不影响 exit code（与 GUI 一致）。
    try:
        svc.save_report(report)
    except Exception:
        pass
    if want_json:
        print(format_json(report))
    else:
        _print_apply_human(report)
    return int(exit_hint)


def _print_show_human(manifest: dict, diff: dict, current: dict) -> None:
    """package show 的人读输出。"""
    name = manifest.get("name") or manifest.get("id") or "(unnamed)"
    mid = manifest.get("id", "?")
    items = manifest.get("items", [])
    print(f"manifest: {name} ({mid})")
    print(f"items: {len(items)}")
    if current:
        print(f"current: {', '.join(f'{k}={v}' for k, v in current.items())}")
    sat = diff.get("items_already_satisfied", [])
    to_apply = diff.get("items_to_apply", [])
    manual = diff.get("items_manual_required", [])
    print(f"already satisfied: {len(sat)} {sat if sat else ''}")
    print(f"to apply: {len(to_apply)} {to_apply if to_apply else ''}")
    if manual:
        print(f"manual required: {len(manual)} {manual}")


def _print_apply_human(report: dict) -> None:
    """package apply 的人读输出。"""
    items = report.get("items", [])
    summary = report.get("summary", {})
    mid = report.get("manifest_id", "?")
    print(f"manifest: {mid}")
    if report.get("error"):
        print(f"error: {report['error']}")
    for it in items:
        status = it.get("status", "?")
        title = it.get("title") or it.get("id", "?")
        suffix = ""
        if it.get("reason"):
            suffix = f" ({it['reason']})"
        elif it.get("error"):
            suffix = f" — {it['error'][:80]}"
        marker = {"ok": "✓", "ok_at_alt_path": "≈", "skipped": "⏭", "not_applicable": "○",
                  "failed": "✗", "manual_required": "⏸", "pending": "·",
                  "in_progress": "…"}.get(status, "?")
        print(f"  {marker} {it.get('id', '?')}: {status}{suffix}")
    print(f"summary: ok={summary.get('ok', 0)} "
          f"skipped={summary.get('skipped', 0)} "
          f"not_applicable={summary.get('not_applicable', 0)} "
          f"failed={summary.get('failed', 0)} "
          f"manual_required={summary.get('manual_required', 0)}")


def run(args, app) -> int:
    """package 子命令入口。args.package_action ∈ show / diff / apply。"""
    want_json = bool(getattr(args, "json", False))
    source = getattr(args, "source", None)
    action = getattr(args, "package_action", None)
    svc = _get_service(app)

    if action == "show":
        return _show(svc, app, source, want_json)
    if action == "diff":
        return _diff(svc, source, want_json)
    if action == "apply":
        return _apply(svc, app, args, want_json)
    print(f"[package] 未知 action: {action!r}", file=sys.stderr)
    return EXIT_ERROR
