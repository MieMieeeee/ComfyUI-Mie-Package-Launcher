"""plugin_normalize 单测：锁死 PluginService 三套返回契约的归一化。

按 plan §3.2 + reviewer 要求，用 fake ``raw`` 喂 8+ 用例覆盖：
- 契约 1（_lifecycle）：install/uninstall/enable/disable 的 {ok, log, error}
- 契约 2（_do_update）：update (force=false) 的 {updated, up_to_date, log, error}
- 契约 3（force_update_selected）：update (force=true) 的 list[{name, ok, skipped, detail}]

重点锁两个陷阱：
- 契约 2 不读 updated/up_to_date（_do_update 里这俩恒为 True/False，不可靠）
- 契约 3 成功路径 detail 进 log 不进 error（否则 report 看起来全是 error）
"""
import pytest

from core.plugin_normalize import normalize_plugin_result


# ===========================================================================
# 契约 1：_lifecycle（install / uninstall / enable / disable）
# 字段集：{ok, log, error}
# ===========================================================================

def test_install_success():
    raw = {"ok": True, "log": "installed", "error": None}
    r = normalize_plugin_result(raw, action="install")
    assert r["ok"] is True
    assert r["error"] is None
    assert r["not_applicable"] is False
    assert r["reason"] is None
    assert r["log"] == "installed"


def test_install_failure():
    raw = {"ok": False, "log": "", "error": "git clone failed"}
    r = normalize_plugin_result(raw, action="install")
    assert r["ok"] is False
    assert r["error"] == "git clone failed"
    assert r["not_applicable"] is False


def test_uninstall_enable_disable_share_path():
    """uninstall/enable/disable 走同一个 _lifecycle，归一化行为一致。"""
    for action in ("uninstall", "enable", "disable"):
        raw = {"ok": True, "log": "ok", "error": None}
        r = normalize_plugin_result(raw, action=action)
        assert r["ok"] is True


# ===========================================================================
# 契约 2：_do_update（update_all / update_selected，force=false）
# 字段集：{updated, up_to_date, log, error}
# 陷阱：up_to_date 恒 False、updated 成功路径恒 True，不可靠 → 只看 error
# ===========================================================================

def test_update_no_force_success_ignores_updated_uptodate():
    """成功路径：error=None → ok=True。updated=True/up_to_date=False 被忽略（不可靠）。"""
    raw = {"updated": True, "up_to_date": False, "log": "done", "error": None}
    r = normalize_plugin_result(raw, action="update", force=False)
    assert r["ok"] is True
    assert r["error"] is None
    assert r["not_applicable"] is False


def test_update_no_force_failure():
    """失败路径：error 非空 → ok=False。"""
    raw = {"updated": False, "up_to_date": False, "log": "", "error": "cm-cli 退出码 1"}
    r = normalize_plugin_result(raw, action="update", force=False)
    assert r["ok"] is False
    assert r["error"] == "cm-cli 退出码 1"


def test_update_no_force_does_not_read_updated_field():
    """陷阱锁定：即使 updated=False（底层不该返这个组合），只要 error=None 就 ok=True。

    这锁住「不依赖 updated 字段」的设计决策——_do_update 里 updated 成功路径恒 True
    是不可靠的，归一化只看 error。
    """
    raw = {"updated": False, "up_to_date": False, "log": "", "error": None}
    r = normalize_plugin_result(raw, action="update", force=False)
    assert r["ok"] is True  # 只看 error=None


# ===========================================================================
# 契约 3：force_update_selected（update + force=true）
# 字段集：list[{name, ok, skipped, detail}]
# 陷阱：成功路径 detail 是正常文本（"已是最新"/pull stdout），不能进 error
# ===========================================================================

def test_force_update_success_detail_goes_to_log_not_error():
    """成功路径：detail="已是最新" 应进 log，error 必须为 None。

    这是 v3.3 修的核心 bug：旧代码无条件 error=item.get("detail")，
    导致成功项的 error 字段塞进「已是最新」，report 看起来全是 error。
    """
    raw = [{"name": "ComfyUI_MieNodes", "ok": True, "skipped": False, "detail": "已是最新"}]
    r = normalize_plugin_result(raw, action="update", force=True, spec="ComfyUI_MieNodes")
    assert r["ok"] is True
    assert r["error"] is None  # ← 关键：不把「已是最新」塞进 error
    assert r["log"] == "已是最新"  # detail 进 log
    assert r["not_applicable"] is False


def test_force_update_success_with_pull_stdout():
    """成功路径 detail 也可以是 git pull stdout（非空正常文本）。"""
    raw = [{"name": "plugin-x", "ok": True, "skipped": False,
            "detail": "Updating abc..def\nFast-forward"}]
    r = normalize_plugin_result(raw, action="update", force=True, spec="plugin-x")
    assert r["ok"] is True
    assert r["error"] is None
    assert "Fast-forward" in r["log"]


def test_force_update_failure_detail_goes_to_error():
    """失败路径：detail="pull 失败 (rc=...)" 应进 error。"""
    raw = [{"name": "plugin-x", "ok": False, "skipped": False,
            "detail": "pull 失败 (rc=1): merge conflict"}]
    r = normalize_plugin_result(raw, action="update", force=True, spec="plugin-x")
    assert r["ok"] is False
    assert r["error"] == "pull 失败 (rc=1): merge conflict"
    assert r["log"] is None


def test_force_update_skipped_non_git_is_not_applicable():
    """非 git 仓库 → skipped=True → not_applicable=True + reason=not_git_for_force。

    这是 v3.1 加 not_applicable status 的原因：force 对 CNR id 无效，
    但不该污染 summary 的 skipped 计数（那是「用户预期跳过」）。
    """
    raw = [{"name": "some-cnr-plugin", "ok": False, "skipped": True,
            "detail": "非 git 仓库，跳过强制更新"}]
    r = normalize_plugin_result(raw, action="update", force=True, spec="some-cnr-plugin")
    assert r["ok"] is False
    assert r["not_applicable"] is True
    assert r["reason"] == "not_git_for_force"
    assert r["error"] == "非 git 仓库，跳过强制更新"


def test_force_update_picks_correct_item_from_list_by_spec():
    """force_update_selected 一次更新多个插件，按 spec 从 list 取对应项。"""
    raw = [
        {"name": "plugin-a", "ok": True, "skipped": False, "detail": "已是最新"},
        {"name": "plugin-b", "ok": False, "skipped": False, "detail": "pull 失败"},
        {"name": "plugin-c", "ok": False, "skipped": True, "detail": "非 git 仓库"},
    ]
    # 取 plugin-b
    r = normalize_plugin_result(raw, action="update", force=True, spec="plugin-b")
    assert r["ok"] is False
    assert r["error"] == "pull 失败"
    # 取 plugin-c
    r = normalize_plugin_result(raw, action="update", force=True, spec="plugin-c")
    assert r["not_applicable"] is True


def test_force_update_spec_not_in_list():
    """spec 在 list 里找不到 → ok=False + 明确错误（不 crash）。"""
    raw = [{"name": "plugin-a", "ok": True, "skipped": False, "detail": "ok"}]
    r = normalize_plugin_result(raw, action="update", force=True, spec="nonexistent")
    assert r["ok"] is False
    assert "nonexistent" in r["error"]


def test_force_update_missing_spec():
    """force=true 但没传 spec → ok=False（无法从 list 定位）。"""
    raw = [{"name": "plugin-a", "ok": True, "skipped": False, "detail": "ok"}]
    r = normalize_plugin_result(raw, action="update", force=True, spec=None)
    assert r["ok"] is False
    assert "spec" in r["error"]


# ===========================================================================
# 异常 / 防御
# ===========================================================================

def test_unknown_action_raises():
    with pytest.raises(ValueError, match="unknown plugin action"):
        normalize_plugin_result({}, action="reinstall")


def test_non_dict_lifecycle_input_handled():
    """底层若返了非 dict（不该发生但防御），不 crash。"""
    r = normalize_plugin_result("not a dict", action="install")  # type: ignore[arg-type]
    assert r["ok"] is False
    assert "非 dict" in r["error"]


def test_non_list_force_input_handled():
    r = normalize_plugin_result({"not": "a list"}, action="update", force=True, spec="x")  # type: ignore[arg-type]
    assert r["ok"] is False
    assert "非 list" in r["error"]
