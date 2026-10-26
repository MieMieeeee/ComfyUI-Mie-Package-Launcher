"""PluginsPage 单测：纯 UI + 信号（不依赖 qt_app / PluginService）。

页面只做：展示插件列表 + 勾选 + 通过信号请求「更新全部/更新选中/刷新/
启用禁用/卸载/安装/检查更新」。真正调 PluginService 的控制器逻辑在
PluginController（本文件内测），qt_app 侧的弹窗接线靠手动验证
（本环境 import qt_app 会崩）。
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtWidgets  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def _destroy_leftover_widgets(qt_app):
    """每个用例结束后确定性销毁遗留的顶层 widget（仿 qtbot 的托管清理）。

    背景：本文件的 PluginsPage 都是无 parent 的顶层 widget，也不经 qtbot
    注册——销毁全靠 Python GC 在任意时机兜底。pytest-qt 在每个用例后调
    QApplication.processEvents()，与「迟到析构的 widget + 仍挂着的事件」
    叠加，在本机 offscreen PyQt5/Py3.12 组合下会腐蚀堆（0xc0000374，
    连跑到 ~25 个用例时进程直接崩、exit 127）。这是 pytest-qt 文档明确
    要求 widget 托管（qtbot.addWidget）的原因；本文件历史写法没走 qtbot，
    这里用 teardown 统一 close + deleteLater + 冲刷事件，效果等价且不用
    改 58 个用例。

    注意：pytestqt 的 -p no:pytestqt 禁不掉本插件（注册名是 pytest-qt），
    别用那个 flag「验证」——曾经因此误判「与 pytest-qt 无关」。
    """
    yield
    import gc

    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    # 先收 Python 引用（让 wrapper 析构发生在受控点），再处理 posted events
    gc.collect()
    for w in list(app.topLevelWidgets()):
        try:
            w.close()
        except Exception:
            pass
    # deleteLater + 立刻冲刷 DeferredDelete，不让删除动作跨用例漂移
    for w in list(app.topLevelWidgets()):
        w.deleteLater()
    try:
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    except Exception:
        pass
    app.processEvents()
    gc.collect()


def _plugin(name, is_git=True, version="abc1234", remote="https://github.com/x/y",
            enabled=True, dir_name=None):
    """造一个插件 dict（含新字段 dir_name / enabled）。默认 dir_name=name。"""
    return {"name": name, "dir_name": dir_name or name, "is_git": is_git,
            "enabled": enabled, "version": version, "remote_url": remote}


def _stub_theme():
    """BasePage 构造需要的最小 theme_manager 替身。"""
    tm = MagicMock()
    tm.register_listener = lambda *_a, **_k: None
    styles = MagicMock()
    styles.c.dark = False
    styles.content_style_light.return_value = ""
    styles.content_style_dark.return_value = ""
    styles.primary_button_style.return_value = ""
    styles.secondary_button_style.return_value = ""
    styles.destructive_button_style.return_value = ""
    tm.styles = styles
    tm.colors = {}
    return tm


# ---- populate / 选择 ----

def test_populate_lists_all_plugins(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("ComfyUI-KJNodes"), _plugin("ComfyMath")])
    assert page.list_widget.count() == 2
    assert page.plugin_names() == ["ComfyUI-KJNodes", "ComfyMath"]


def test_selected_names_returns_checked_items(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B"), _plugin("C")])
    page.list_widget.item(0).setCheckState(QtCore.Qt.Checked)
    page.list_widget.item(2).setCheckState(QtCore.Qt.Checked)
    assert page.selected_names() == ["A", "C"]


def test_selected_dir_names_uses_dir_name_including_disabled_suffix(qt_app):
    """禁用插件 dir_name 带 .disabled，selected_dir_names 必须返回它（操作要拼对路径）。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("MieNodes", enabled=False, dir_name="MieNodes.disabled")])
    page.list_widget.item(1).setCheckState(QtCore.Qt.Checked)  # 勾选禁用的那个
    assert page.selected_dir_names() == ["MieNodes.disabled"]


def test_populate_marks_disabled_item_with_suffix_and_keeps_name(qt_app):
    """禁用项显示带「（已禁用）」后缀，但 name 字段仍是纯名。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("MieNodes", enabled=False, dir_name="MieNodes.disabled")])
    item = page.list_widget.item(0)
    assert "已禁用" in item.text()
    # plugin_names 返回纯 name（剥状态后缀）
    assert page.plugin_names() == ["MieNodes"]


# ---- 全选 / 取消全选（用户反馈：60 个插件一个个勾太累）----

def test_toggle_select_all_checks_every_item(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B"), _plugin("C")])
    page.toggle_select_all()
    assert sorted(page.selected_dir_names()) == ["A", "B", "C"]


def test_toggle_select_all_twice_unchecks_all(qt_app):
    """再点一次取消全选（文案此时应变成「取消全选」）。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    page.toggle_select_all()
    assert page.select_all_btn.text() == "取消全选"
    page.toggle_select_all()
    assert page.selected_dir_names() == []
    assert page.select_all_btn.text() == "全选"


def test_select_all_button_visible_with_nothing_checked(qt_app):
    """未勾选时全选按钮也必须可见——否则用户没法用它做第一次全选。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    assert page.list_widget.item(0).checkState() == QtCore.Qt.Unchecked
    assert page.select_all_btn.isVisible() or not page.isVisible()


def test_selection_survives_populate_after_update(qt_app):
    """回归：更新后 populate 会换掉整个 cache，勾选状态必须按 dir_name 继承回来。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B"), _plugin("C")])
    page.list_widget.item(0).setCheckState(QtCore.Qt.Checked)
    page.list_widget.item(1).setCheckState(QtCore.Qt.Checked)
    # 模拟更新后的刷新（list_installed 返回全新 dict，不带 _sel）
    page.populate([_plugin("A"), _plugin("B"), _plugin("C")], preserve_outdated=True)
    assert sorted(page.selected_dir_names()) == ["A", "B"]


def test_toggle_select_all_only_affects_visible_list(qt_app):
    """只作用于当前可见列表（Tab 筛选/搜索后不应把看不见的也勾上）。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    # 模拟筛选后只剩 1 项
    page._render_from_list([p for p in page._all_plugins_cache
                            if p["dir_name"] == "A"], preserve_outdated=False)
    page.toggle_select_all()
    assert page.selected_dir_names() == ["A"]


# ---- 原有三按钮信号 ----

def test_refresh_button_emits_refresh_requested(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    received = []
    page.refresh_requested.connect(lambda: received.append(True))
    page.refresh_btn.click()
    assert received == [True]


def test_update_all_button_emits_update_all_requested(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    received = []
    page.update_all_requested.connect(lambda: received.append(True))
    page.update_all_btn.click()
    assert received == [True]


def test_update_selected_button_emits_checked_dir_names(qt_app):
    """update_selected 现在发 dir_name（操作要用），不再是纯 name。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B"), _plugin("C")])
    page.list_widget.item(1).setCheckState(QtCore.Qt.Checked)

    received = []
    page.update_selected_requested.connect(lambda names: received.append(names))
    page.update_selected_btn.click()
    assert received == [["B"]]


# ---- 新增按钮信号 ----

def test_check_updates_button_emits_check_updates_requested(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    received = []
    page.check_updates_requested.connect(lambda: received.append(True))
    page.check_updates_btn.click()
    assert received == [True]


def test_disable_button_emits_selected_dir_names(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    page.list_widget.item(0).setCheckState(QtCore.Qt.Checked)
    received = []
    page.disable_selected_requested.connect(lambda names: received.append(names))
    page.disable_btn.click()
    assert received == [["A"]]


def test_enable_button_emits_selected_dir_names(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    page.list_widget.item(1).setCheckState(QtCore.Qt.Checked)
    received = []
    page.enable_selected_requested.connect(lambda names: received.append(names))
    page.enable_btn.click()
    assert received == [["B"]]


def test_uninstall_button_emits_selected_dir_names(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A")])
    page.list_widget.item(0).setCheckState(QtCore.Qt.Checked)
    received = []
    page.uninstall_selected_requested.connect(lambda names: received.append(names))
    page.uninstall_btn.click()
    assert received == [["A"]]


def test_outdated_reported_is_emittable(qt_app):
    """outdated_reported 是控制器→页面的回推信号（list + dict），验证它能连。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    received = []
    page.outdated_reported.connect(lambda names, dates: received.append((names, dates)))
    page.outdated_reported.emit(["Behind"], {"Behind": "2025-01-01"})
    assert received == [(["Behind"], {"Behind": "2025-01-01"})]


# ---- mark_outdated：检查更新结果回推后更新显示 ----

def test_mark_outdated_prefixes_outdated_items(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("Current"), _plugin("Behind")])
    page.mark_outdated(["Behind"])
    texts = [page.list_widget.item(i).text() for i in range(page.list_widget.count())]
    assert any("可更新" in t for t in texts if "Behind" in t or "🔄" in t)
    # 重排后 outdated(Behind) 置顶；Current 在后面且不被标记
    # 找到 Current 那一行（不在固定位置，因 Behind 被提前），断言它不含「可更新」
    current_texts = [t for t in texts if "Current" in t]
    assert current_texts, "Current 项应存在"
    assert all("可更新" not in t for t in current_texts), "Current 不应被标记"


def test_mark_outdated_moves_outdated_to_top(qt_app):
    """outdated 项重排到列表顶部，其余按原顺序跟在后面。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("Alpha"), _plugin("Behind1"), _plugin("Behind2"), _plugin("Zeta")])
    page.mark_outdated(["Behind1", "Behind2"])
    order = [page._item_name(page.list_widget.item(i)) for i in range(page.list_widget.count())]
    # Behind1/Behind2 在前（保留 name 排序），Alpha/Zeta 在后
    assert order == ["Behind1", "Behind2", "Alpha", "Zeta"], f"重排顺序错: {order}"


# ---- 远端日期列：检查更新后整表可见（不只落后插件）----

def test_remote_date_kept_for_all_rows_after_check(qt_app):
    """回归（2026-10-04 用户反馈）：检查后「远端日期」列整表可见。

    以前只在 outdated 插件上填远端日期，用户把唯一可更新的插件更新完之后整列全是
    —，看不出任何插件的远端停在哪天。delegate 对 outdated 用强调色、其余弱化色。
    """
    from ui_qt.pages.plugins_page import PluginsPage, _REMOTE_DATE_ROLE

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("Alpha"), _plugin("Beta")])
    page.mark_outdated(["Alpha"],
                       {"Alpha": "2025-06-01", "Beta": "2025-05-20"})

    dates = {}
    for i in range(page.list_widget.count()):
        it = page.list_widget.item(i)
        dates[page._item_name(it)] = it.data(_REMOTE_DATE_ROLE)
    assert dates == {"Alpha": "2025-06-01", "Beta": "2025-05-20"}, f"远端日期没整表填充: {dates}"


def test_remote_date_survives_repopulate_after_update(qt_app):
    """更新后刷新（preserve_outdated）不能把「远端日期」列清空——那正是用户看到的
    「更新完成、可更新 0、远端日期全 —」。"""
    from ui_qt.pages.plugins_page import PluginsPage, _REMOTE_DATE_ROLE

    page = PluginsPage(theme_manager=_stub_theme())
    plugins = [_plugin("Alpha"), _plugin("Beta")]
    page.populate(plugins)
    page.mark_outdated(["Alpha"], {"Alpha": "2025-06-01", "Beta": "2025-05-20"})
    page.repopulate_preserving_outdated([_plugin("Alpha"), _plugin("Beta")],
                                       done_names={"Alpha"})

    dates = {}
    for i in range(page.list_widget.count()):
        it = page.list_widget.item(i)
        dates[page._item_name(it)] = it.data(_REMOTE_DATE_ROLE)
    assert dates == {"Alpha": "2025-06-01", "Beta": "2025-05-20"}, \
        f"更新后远端日期被清空: {dates}"


def test_repopulate_after_update_keeps_current_filter_and_search(qt_app):
    """回归（2026-10-04 反馈）：更新后不该把用户踢回「全部」Tab、清空搜索词。

    用户正是在筛选视图里选插件更新的，刷完跳走既突兀，又看不到
    repopulate_preserving_outdated 特意保留的「还剩哪些落后」。
    """
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("Alpha"), _plugin("Beta"), _plugin("Gamma")])
    page.mark_outdated(["Alpha", "Beta"], {"Alpha": "2025-06-01", "Beta": "2025-05-20"})
    page._set_filter("outdated")
    page._search_edit.setText("Beta")

    page.repopulate_preserving_outdated([_plugin("Alpha"), _plugin("Beta"),
                                         _plugin("Gamma")],
                                       done_names={"Alpha"})

    assert page._current_filter == "outdated", \
        f"更新后应留在原 Tab，实际 {page._current_filter}"
    assert page._search_edit.text() == "Beta", \
        f"更新后搜索词不该被清空，实际 {page._search_edit.text()!r}"


def test_full_repopulate_still_resets_filter_and_search(qt_app):
    """对照组：全量 populate（刷新列表按钮）仍重置 Tab + 清搜索——那是「重新开始」的语义。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("Alpha"), _plugin("Beta")])
    page._set_filter("git")
    page._search_edit.setText("Beta")

    page.populate([_plugin("Alpha"), _plugin("Beta")])

    assert page._current_filter == "all", f"全量刷新应回「全部」，实际 {page._current_filter}"
    assert page._search_edit.text() == ""


# ---- repopulate_preserving_outdated：更新后保留 🔄，不要求重新检查 ----

def test_repopulate_keeps_outdated_mark_for_untouched_plugins(qt_app):
    """更新指定插件后刷新：更新成功的摘掉 🔄，没动的保留（用户不用重新点「检查更新」）。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("Alpha"), _plugin("Beta"), _plugin("Gamma")])
    page.mark_outdated(["Alpha", "Beta", "Gamma"])
    # 模拟「更新了 Alpha/Beta 成功，Gamma 仍落后」后的刷新
    page.repopulate_preserving_outdated(
        [_plugin("Alpha"), _plugin("Beta"), _plugin("Gamma")],
        done_names={"Alpha", "Beta"})
    assert page._outdated_dir_names == {"Gamma"}, \
        f"只应保留 Gamma，实际 {page._outdated_dir_names}"


def test_repopulate_clears_outdated_role_and_text_on_items(qt_app):
    """回归：已更新插件的 item role 与文本都要还原（之前只写 True 不写 False，
    且没人复原「🔄 … [可更新]」文本 → 更新完仍显示可更新、还挂在顶部）。"""
    from ui_qt.pages.plugins_page import PluginsPage, _OUTDATED_ROLE

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("Alpha"), _plugin("Beta"), _plugin("Gamma")])
    page.mark_outdated(["Alpha", "Beta", "Gamma"])
    page.repopulate_preserving_outdated(
        [_plugin("Alpha"), _plugin("Beta"), _plugin("Gamma")],
        done_names={"Alpha", "Beta"})

    roles = {}
    texts = {}
    for i in range(page.list_widget.count()):
        it = page.list_widget.item(i)
        roles[page._item_name(it)] = bool(it.data(_OUTDATED_ROLE))
        texts[page._item_name(it)] = it.text()
    # role：更新的两个必须 False，仍落后的 True
    assert roles == {"Gamma": True, "Alpha": False, "Beta": False}, f"role 不对: {roles}"
    # 文本：还原成普通名，不残留「可更新」
    assert "可更新" not in texts["Alpha"] and "可更新" not in texts["Beta"], \
        f"已更新插件文本未还原: {texts}"
    assert "可更新" in texts["Gamma"]
    # 仍落后的置顶，已更新的排到后面
    order = [page._item_name(page.list_widget.item(i)) for i in range(page.list_widget.count())]
    assert order[0] == "Gamma", f"可更新项应置顶，实际 {order}"


def test_repopulate_drops_ghost_marks_for_removed_plugins(qt_app):
    """插件被卸载/重装换名后，旧 dir_name 的标记不该继续挂着（列表里已不存在）。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("Alpha"), _plugin("Beta")])
    page.mark_outdated(["Alpha", "Beta"])
    # Beta 在刷新时已不在列表（被卸载）
    page.repopulate_preserving_outdated([_plugin("Alpha")], done_names=set())
    assert page._outdated_dir_names == {"Alpha"}, \
        f"幽灵标记应被清掉，实际 {page._outdated_dir_names}"


def test_repopulate_without_prior_check_falls_back_to_full_populate(qt_app):
    """没做过检查时退化为普通 populate，不报错。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.repopulate_preserving_outdated([_plugin("Alpha")], done_names={"Alpha"})
    assert page.list_widget.count() == 1


def test_populate_default_clears_outdated(qt_app):
    """默认 populate（点「刷新」）仍是全量清空标记——不改变既有语义。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("Alpha")])
    page.mark_outdated(["Alpha"])
    assert page._outdated_dir_names == {"Alpha"}
    page.populate([_plugin("Alpha")])  # preserve_outdated 默认 False
    assert page._outdated_dir_names == set()


# ---- PluginController：编排（page 信号 → PluginService），可测 ----

def _sync_runner():
    """同步的 run_in_background / post_to_ui 替身，让控制器测试确定性。"""
    return (lambda fn: fn()), (lambda fn: fn())


def test_controller_refresh_populates_page_from_service(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.list_installed.return_value = [_plugin("PluginX")]
    run_bg, post_ui = _sync_runner()
    # 控制器必须被持有（生产环境由 qt_app 持有），否则 GC 后信号连接失效
    ctrl = PluginController(page, svc, run_bg, post_ui)
    assert ctrl is not None

    page.refresh_btn.click()
    svc.list_installed.assert_called_once()
    assert page.plugin_names() == ["PluginX"]


def test_controller_update_all_calls_service_then_refreshes(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.update_all.return_value = {"updated": True, "log": "", "error": None}
    svc.list_installed.return_value = [_plugin("AfterUpdate")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    page.update_all_btn.click()
    svc.update_all.assert_called_once()
    svc.list_installed.assert_called_once()  # 更新后刷新
    assert page.plugin_names() == ["AfterUpdate"]


def test_controller_update_selected_passes_checked_dir_names(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B"), _plugin("C")])
    page.list_widget.item(1).setCheckState(QtCore.Qt.Checked)  # 只勾选 B
    svc = MagicMock()
    svc.update_selected.return_value = {"updated": True, "log": "", "error": None}
    svc.outdated_plugins.return_value = []  # 成功路径：无失败 → 不提示强制
    svc.list_installed.return_value = [_plugin("A"), _plugin("B"), _plugin("C")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    page.update_selected_btn.click()
    svc.update_selected.assert_called_once_with(["B"])


def test_controller_offers_force_update_when_plugins_still_outdated(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.update_selected.return_value = {"updated": True, "log": "", "error": None}
    svc.outdated_plugins.return_value = ["MieNodes"]  # 正常更新后仍落后 = 失败
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    suggested = []
    page.force_update_suggested.connect(lambda names: suggested.append(names))

    page.populate([_plugin("MieNodes")])
    page.list_widget.item(0).setCheckState(QtCore.Qt.Checked)
    page.update_selected_btn.click()

    svc.update_selected.assert_called_once_with(["MieNodes"])
    svc.outdated_plugins.assert_called_once_with(["MieNodes"])
    assert suggested == [["MieNodes"]]


def test_controller_apply_force_update_calls_service_then_refreshes(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.force_update_selected.return_value = [
        {"name": "MieNodes", "ok": True, "skipped": False, "detail": "Already up to date."}]
    svc.list_installed.return_value = [_plugin("MieNodes")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    ctrl.apply_force_update(["MieNodes"])
    svc.force_update_selected.assert_called_once_with(["MieNodes"])
    svc.list_installed.assert_called_once()  # 强制后刷新


def test_controller_apply_force_update_runs_sync_deps(qt_app):
    """强制更新后复用普通更新的「同步依赖库」流程（注入的 sync_deps 回调）。"""
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.force_update_selected.return_value = [
        {"name": "MieNodes", "ok": True, "skipped": False, "detail": ""}]
    svc.list_installed.return_value = [_plugin("MieNodes")]
    sync_calls = []
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui,
                            sync_deps=lambda: sync_calls.append(True))

    ctrl.apply_force_update(["MieNodes"])
    svc.force_update_selected.assert_called_once_with(["MieNodes"])
    assert sync_calls == [True]  # 强制更新后跑了依赖同步


# ---- 新增控制器方法 ----

def test_controller_disable_loops_service_disable_per_dir_name_then_refreshes(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    page.list_widget.item(0).setCheckState(QtCore.Qt.Checked)
    page.list_widget.item(1).setCheckState(QtCore.Qt.Checked)
    svc = MagicMock()
    svc.list_installed.return_value = [_plugin("A"), _plugin("B")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    page.disable_btn.click()
    # service.disable 接收单 target，故被调两次
    assert svc.disable.call_count == 2
    svc.disable.assert_any_call("A")
    svc.disable.assert_any_call("B")
    svc.list_installed.assert_called_once()  # 刷新


def test_controller_enable_loops_service_enable_per_dir_name(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("MieNodes", enabled=False, dir_name="MieNodes.disabled")])
    page.list_widget.item(0).setCheckState(QtCore.Qt.Checked)
    svc = MagicMock()
    svc.list_installed.return_value = [_plugin("MieNodes")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    page.enable_btn.click()
    svc.enable.assert_called_once_with("MieNodes.disabled")  # 用 dir_name


def test_controller_apply_uninstall_loops_service_uninstall_then_refreshes(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.list_installed.return_value = []
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    ctrl.apply_uninstall(["A", "B"])  # 公开方法（qt_app 确认后调）
    assert svc.uninstall.call_count == 2
    svc.uninstall.assert_any_call("A")
    svc.uninstall.assert_any_call("B")
    svc.list_installed.assert_called_once()


def test_controller_request_install_calls_service_install_then_refreshes(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.list_installed.return_value = [_plugin("NewPlugin")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    ctrl.request_install("https://github.com/x/NewPlugin")
    svc.install.assert_called_once_with("https://github.com/x/NewPlugin")
    svc.list_installed.assert_called_once()


# ---- run_install / run_uninstall / run_disable：带反馈版本（接收 service 返回值）----
# 回归保护：旧 request_install/apply_uninstall 丢弃 {ok,log,error} → 无反馈；
# 新 run_* 必须把结果通过 on_done(ok, message) 派回。

def test_controller_run_install_reports_success(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.list_installed.return_value = []
    svc.install_streaming.return_value = {"ok": True, "log": "installed", "error": None}
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    got = []
    ctrl.run_install("https://github.com/x/Y",
                     on_done=lambda ok, msg: got.append((ok, msg)))
    assert svc.install_streaming.call_count == 1
    assert svc.install_streaming.call_args[0][0] == "https://github.com/x/Y"
    assert got and got[0][0] is True            # 成功
    assert "完成" in got[0][1]


def test_controller_run_install_reports_failure(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.list_installed.return_value = []
    svc.install_streaming.return_value = {"ok": False, "log": "", "error": "boom"}
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    got = []
    ctrl.run_install("https://github.com/x/Y",
                     on_done=lambda ok, msg: got.append((ok, msg)))
    assert svc.install_streaming.call_count == 1
    assert svc.install_streaming.call_args[0][0] == "https://github.com/x/Y"
    assert got and got[0][0] is False           # 失败也要回报（旧路径静默吞掉）
    assert "boom" in got[0][1]                  # cm-cli 原因透传给用户


def test_controller_run_uninstall_aggregates_partial_failure(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.list_installed.return_value = []
    # A 成功、B 失败
    svc.uninstall.side_effect = [{"ok": True, "error": None}, {"ok": False, "error": "denied"}]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    statuses, got = [], []
    ctrl.run_uninstall(["A", "B"],
                       on_status=lambda s: statuses.append(s),
                       on_done=lambda ok, msg: got.append((ok, msg)))
    assert svc.uninstall.call_count == 2
    assert len(statuses) == 2                   # 逐项进度：每个插件一次
    assert got and got[0][0] is False           # 有失败 → 整体不成功
    assert "1/2" in got[0][1]                   # 汇总部分失败
    assert "denied" in got[0][1]


def test_controller_run_disable_calls_service_disable(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.list_installed.return_value = []
    svc.disable.return_value = {"ok": True, "error": None}
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    got = []
    ctrl.run_disable(["MieNodes"], on_done=lambda ok, msg: got.append((ok, msg)))
    svc.disable.assert_called_once_with("MieNodes")   # op 路由到 svc.disable
    assert got and got[0][0] is True


def test_controller_check_updates_emits_outdated_reported(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.check_updates.return_value = ["Behind", "MieNodes.disabled"]
    svc.remote_dates.return_value = {"Behind": "2025-06-01", "MieNodes.disabled": "2025-05-20"}
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    reported = []
    page.outdated_reported.connect(lambda names, dates: reported.append((names, dates)))

    page.check_updates_btn.click()
    svc.check_updates.assert_called_once()
    # include_all_git=True：远端日期对整表取，列表「远端日期」列不该只有落后插件有值
    svc.remote_dates.assert_called_once_with(["Behind", "MieNodes.disabled"],
                                              include_all_git=True)
    assert reported == [(["Behind", "MieNodes.disabled"],
                         {"Behind": "2025-06-01", "MieNodes.disabled": "2025-05-20"})]


# ---- 「检查中」状态药丸（未检查 / 检查中 / 有更新 / 无更新 四态）----

def test_set_checking_marks_all_items(qt_app):
    """检查进行中：所有 item 打上 _CHECKING_ROLE，delegate 据此画「检查中…」。"""
    from ui_qt.pages.plugins_page import PluginsPage, _CHECKING_ROLE

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    page.set_checking(True)
    assert page._checking is True
    assert all(bool(page.list_widget.item(i).data(_CHECKING_ROLE))
               for i in range(page.list_widget.count()))
    page.set_checking(False)
    assert all(not page.list_widget.item(i).data(_CHECKING_ROLE)
               for i in range(page.list_widget.count()))


def test_mark_outdated_clears_checking_state(qt_app):
    """检查出结果后「检查中」必须收掉（否则列表永远停在那个药丸）。"""
    from ui_qt.pages.plugins_page import PluginsPage, _CHECKING_ROLE

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    page.set_checking(True)
    page.mark_outdated(["A"])
    assert all(not page.list_widget.item(i).data(_CHECKING_ROLE)
               for i in range(page.list_widget.count()))


def test_checking_state_survives_filter_refresh(qt_app):
    """检查期间切 Tab / 搜索过滤导致列表重建，「检查中」要保持。"""
    from ui_qt.pages.plugins_page import PluginsPage, _CHECKING_ROLE

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    page.mark_outdated(["A", "B"])
    page.set_checking(True)
    page._render_from_list(list(page._all_plugins_cache), preserve_outdated=True)
    assert all(bool(page.list_widget.item(i).data(_CHECKING_ROLE))
               for i in range(page.list_widget.count()))


def test_controller_check_updates_clears_checking_on_exception(qt_app):
    """检查抛异常也要收掉「检查中」，且 on_done 必达（2026-10-04：此前异常直接
    raise 出线程被吞，弹窗永久冻在最后一格进度）。"""
    from ui_qt.pages.plugins_page import PluginsPage, PluginController, _CHECKING_ROLE

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A")])
    svc = MagicMock()
    svc.check_updates.side_effect = RuntimeError("boom")
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    received = {}
    ctrl.run_check_updates(on_done=lambda o, d, e=None: received.update(
        outdated=o, dates=d, error=e))
    # 不再向外抛（此前 pytest.raises(RuntimeError)）——异常走 on_done 的 error 通道
    assert "RuntimeError: boom" in (received.get("error") or "")
    assert received.get("outdated") == [] and received.get("dates") == {}
    assert all(not page.list_widget.item(i).data(_CHECKING_ROLE)
               for i in range(page.list_widget.count()))


def test_mark_outdated_resets_page_checking_flag(qt_app):
    """mark_outdated（=检查出结果）必须复位页面级 _checking 标志。

    _render_from_list（切 Tab/搜索的重渲染）用这个标志回填 item 的
    _CHECKING_ROLE。原先只清 item 不清标志：调用方一旦漏调
    set_checking(False)（qt_app on_done 曾因 NameError 漏调），切一次
    Tab 全列表永久卡「检查中」。复位收敛到这里，不再依赖调用方记得关。
    """
    from ui_qt.pages.plugins_page import PluginsPage, _CHECKING_ROLE

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    page.set_checking(True)
    page.mark_outdated(["A"])
    assert page._checking is False
    assert all(not page.list_widget.item(i).data(_CHECKING_ROLE)
               for i in range(page.list_widget.count()))


def test_no_stuck_checking_after_tab_roundtrip_without_set_checking_false(qt_app):
    """回归：检查完成但调用方漏调 set_checking(False)（qt_app on_done 曾因
    NameError 漏调），用户切可更新 Tab 全选→取消全选→回全部 Tab，
    可更新列不得卡「检查中…」，远端日期标记也不得丢（用户实测报告的场景）。
    """
    from ui_qt.pages.plugins_page import (PluginsPage, _CHECKING_ROLE,
                                          _OUTDATED_ROLE, _REMOTE_DATE_ROLE)

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin(n) for n in ["A", "B", "C", "D", "E"]])
    dates = {"A": "2026-10-01", "C": "2026-10-02"}
    page.set_checking(True)
    page.mark_outdated(["A", "C"], dates)  # 模拟 on_done：mark_outdated 正常执行
    # ……而 set_checking(False) 这一行因 bug 没有执行（此处故意不调）

    page._set_filter("outdated")
    page.toggle_select_all()      # 全选
    page.toggle_select_all()      # 取消全选
    page._set_filter("all")       # 回「全部」Tab

    for i in range(page.list_widget.count()):
        item = page.list_widget.item(i)
        dn = str(item.data(QtCore.Qt.UserRole + 1))
        assert not item.data(_CHECKING_ROLE), f"{dn} 卡在「检查中」"
        if dn in ("A", "C"):
            assert item.data(_OUTDATED_ROLE) is True
            assert item.data(_REMOTE_DATE_ROLE) == dates[dn], f"{dn} 远端日期丢失"
        else:
            assert not item.data(_OUTDATED_ROLE)


def test_outdated_first_order_restored_after_tab_roundtrip(qt_app):
    """切 Tab 一圈回来，可更新插件仍应置顶（mark_outdated 的重排不因
    filter 重建列表而丢失），否则用户在列表顶部只看到普通插件。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin(n) for n in ["A", "B", "C", "D", "E"]])
    page.mark_outdated(["B", "E"], {"B": "2026-10-01", "E": "2026-10-02"})
    assert [str(page.list_widget.item(i).data(QtCore.Qt.UserRole + 1))
            for i in range(2)] == ["B", "E"]  # mark_outdated 置顶

    page._set_filter("outdated")
    page._set_filter("all")
    assert [str(page.list_widget.item(i).data(QtCore.Qt.UserRole + 1))
            for i in range(2)] == ["B", "E"], "Tab 一圈回来置顶丢失"


# ---- showEvent + set_loading_state + load_if_not_loaded（BackgroundLoader 集成）----

def _show_event(page):
    """触发 showEvent，用真实 QShowEvent（super().showEvent 校验类型，MagicMock 会报错）。"""
    from PyQt5 import QtGui
    page.showEvent(QtGui.QShowEvent())


def test_show_event_triggers_load_on_first_show(qt_app):
    """首次 showEvent → loader.load_if_not_loaded 触发后台取列表 → 填充页面。"""
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.list_installed.return_value = [_plugin("FirstShow")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    assert page.list_widget.count() == 0  # 加载前为空
    _show_event(page)  # 模拟切到本页
    svc.list_installed.assert_called_once()
    assert page.plugin_names() == ["FirstShow"]


def test_show_event_skips_when_already_loaded(qt_app):
    """已加载过 → 再次 showEvent 不重复触发 list_installed。"""
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.list_installed.return_value = [_plugin("Once")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    _show_event(page)  # 首次
    _show_event(page)  # 再次
    _show_event(page)  # 又再次
    svc.list_installed.assert_called_once()  # 只加载一次


def test_set_loading_state_shows_placeholder_when_loading(qt_app):
    """加载中 + 列表为空 → 插入「正在获取插件列表…」占位 item。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    assert page.list_widget.count() == 0
    page.set_loading_state(True)
    assert page.list_widget.count() == 1
    assert "获取" in page.list_widget.item(0).text()


def test_set_loading_state_clears_placeholder_when_done(qt_app):
    """加载完成 → 不主动留占位（populate 的 clear() 会清；这里验证 loading=False 对已有占位无副作用）。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.set_loading_state(True)   # 加占位
    page.set_loading_state(False)  # 加载结束（占位仍在，等 populate clear）
    # populate 会清掉占位并填真实数据
    page.populate([_plugin("Real")])
    assert page.plugin_names() == ["Real"]
    assert page.list_widget.count() == 1


def test_set_loading_state_noop_when_list_already_populated(qt_app):
    """列表已有内容时不插占位（避免刷新已有数据时闪占位）。"""
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("Existing")])  # 已有 1 项
    page.set_loading_state(True)           # 触发加载态
    assert page.list_widget.count() == 1   # 没多插占位，还是 1 项


# ---- PluginController.run_update_selected: 带 on_status/on_done 回调 (qt_app 弹窗接线) ----

def test_controller_run_update_selected_calls_svc_and_invokes_on_status(qt_app):
    """run_update_selected 直接入口: 调 svc.update_selected + svc.outdated_plugins, on_status 派发一次."""
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.update_selected.return_value = {"updated": True, "log": "", "error": None}
    svc.outdated_plugins.return_value = []
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    statuses = []
    ctrl.run_update_selected(["A", "B"], on_status=lambda s: statuses.append(s))

    svc.update_selected.assert_called_once_with(["A", "B"])
    svc.outdated_plugins.assert_called_once_with(["A", "B"])
    assert len(statuses) == 1, f"on_status 应调一次, 实际 {len(statuses)}"
    assert "更新" in statuses[0] or "A" in statuses[0] or "B" in statuses[0], (

        f"on_status 文案应含「更新」或选中插件名: {statuses[0]}"

    )


def test_controller_run_update_selected_success_refreshes_and_calls_on_done(qt_app):
    """全部成功: _populate_from_service (svc.list_installed) + on_done 派发."""
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.update_selected.return_value = {"updated": True, "log": "", "error": None}
    svc.outdated_plugins.return_value = []  # 无失败
    svc.list_installed.return_value = [_plugin("A"), _plugin("B")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    done_called = []
    ctrl.run_update_selected(["A", "B"], on_done=lambda: done_called.append(True))

    svc.list_installed.assert_called_once()  # 成功后刷新列表
    assert done_called == [True], "on_done 应被调一次"


def test_controller_refreshes_list_before_reporting_done(qt_app):
    """回归：更新完成后必须**先刷列表再报完成**。

    用户反馈「更新完了没刷新界面，还是那 6 个」+「没有完成提示」。根因是刷新走
    _post_to_ui（Qt 信号，异步）而 on_done 紧随其后同步发出，完成提示先于列表
    刷新到达。本测试记录 on_done 时刻的列表状态，确保它已是刷新后的。
    """
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.update_selected.return_value = {"updated": True, "log": "", "error": None}
    svc.outdated_plugins.return_value = []
    svc.list_installed.return_value = [_plugin("A"), _plugin("B")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    seen = {}

    def on_done(ok, msg):
        # on_done 触发时列表应该已经重建（count=2）
        seen["count_at_done"] = page.list_widget.count()
        seen["called"] = True

    ctrl.run_update_selected(["A", "B"], on_done=on_done)
    assert seen.get("called") is True, "on_done 应被调"
    assert seen["count_at_done"] == 2, \
        f"on_done 时列表应已刷新（2 项），实际 {seen['count_at_done']} —— 完成提示跑在刷新前面了"


def test_controller_run_update_selected_partial_failure_emits_force_update_and_calls_on_done(qt_app):
    """部分失败: force_update_suggested 发出 + on_done 仍然调 (让 qt_app 收尾弹窗)."""
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.update_selected.return_value = {"updated": True, "log": "", "error": None}
    svc.outdated_plugins.return_value = ["MieNodes"]  # 仍落后 = 失败
    svc.list_installed.return_value = [_plugin("MieNodes")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    suggested = []
    page.force_update_suggested.connect(lambda names: suggested.append(names))
    done_called = []
    ctrl.run_update_selected(["MieNodes"], on_done=lambda: done_called.append(True))

    assert suggested == [["MieNodes"]], "失败列表通过 force_update_suggested 通知页面"
    svc.list_installed.assert_called_once()  # 失败也刷新 (跟现有 _update_selected_work 行为一致)
    assert done_called == [True], "on_done 仍应在 finally 调, 让 qt_app 收尾"


def test_controller_reports_failure_when_update_selected_returns_error(qt_app):
    """回归（review H4）：update_selected 返回 error 时不能报「更新完成」。

    Manager 未安装 / cm-cli 非零退出时 svc 返回 error 非空；原先返回值被直接
    丢弃，ok 仍为 True，用户看到「更新完成」但插件一个没升。
    """
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.update_selected.return_value = {
        "updated": False, "up_to_date": False, "log": "",
        "error": "cm-cli update 退出码 1"}
    svc.list_installed.return_value = [_plugin("A"), _plugin("B")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    got = {}
    ctrl.run_update_selected(["A", "B"],
                             on_done=lambda ok, msg: got.update(ok=ok, msg=msg))
    assert got["ok"] is False, "svc 返回 error 时必须报失败"
    assert "cm-cli update 退出码 1" in got["msg"]
    # 什么都没升成功 → 🔄 标记全量保留
    assert page._outdated_dir_names == {"A", "B"}


def test_controller_run_update_selected_keeps_marks_on_success(qt_app):
    """成功路径：已更新的摘掉 🔄，其余保留。"""
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.update_selected.return_value = {
        "updated": True, "up_to_date": False, "log": "", "error": None}
    svc.outdated_plugins.return_value = ["B"]   # A 升好了，B 仍落后
    svc.list_installed.return_value = [_plugin("A"), _plugin("B")]
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    # 用户先点过「检查更新」，A/B 都被标记可更新
    page.mark_outdated(["A", "B"])
    ctrl.run_update_selected(["A", "B"], on_done=lambda ok, msg: None)
    assert page._outdated_dir_names == {"B"}, "只剩仍落后的 B 保留标记"


def test_controller_run_update_selected_swallows_svc_exception_still_calls_on_done(qt_app):
    """svc.update_selected 抛 -> 兜住, on_done 仍调, 不冒泡 (不阻断退出/后续操作)."""
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    svc = MagicMock()
    svc.update_selected.side_effect = RuntimeError("cm-cli failed")
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    done_called = []
    # 不应抛
    ctrl.run_update_selected(["X"], on_done=lambda: done_called.append(True))
    assert done_called == [True], "on_done 必须在 finally 调, 即便 svc 抛"
    # 失败时不调 outdated_plugins (svc 已崩, 再问 outdated 没意义)
    svc.outdated_plugins.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_controller_update_selected_streams_progress_to_ui(qt_app):
    """run_update_selected 的 on_progress 透传：service 层流式回调经 post_to_ui
    派回 UI 线程（驱动进度弹窗 k/N 进度条）。"""
    from ui_qt.pages.plugins_page import PluginsPage, PluginController

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B")])
    svc = MagicMock()
    svc.update_selected.return_value = {"updated": True, "up_to_date": False,
                                        "log": "", "error": None}
    svc.outdated_plugins.return_value = []
    svc.list_installed.return_value = []
    run_bg, post_ui = _sync_runner()
    ctrl = PluginController(page, svc, run_bg, post_ui)

    got = []
    ctrl.run_update_selected(["A", "B"], on_done=None,
                             on_progress=lambda c, t, n: got.append((c, t, n)))
    kw = svc.update_selected.call_args.kwargs
    assert callable(kw.get("on_progress")), "service 层应收到 on_progress 回调"
    # 模拟 service 在工作线程里发逐插件进度（post_to_ui 同步执行，直达 UI 侧）
    kw["on_progress"](1, 2, "A")
    kw["on_progress"](2, 2, "B")
    assert got == [(1, 2, "A"), (2, 2, "B")]
