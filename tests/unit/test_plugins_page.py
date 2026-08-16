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
    svc.remote_dates.assert_called_once_with(["Behind", "MieNodes.disabled"])
    assert reported == [(["Behind", "MieNodes.disabled"],
                         {"Behind": "2025-06-01", "MieNodes.disabled": "2025-05-20"})]


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
