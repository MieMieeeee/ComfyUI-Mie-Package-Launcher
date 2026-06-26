"""PluginsPage 单测：纯 UI + 信号（不依赖 qt_app / PluginService）。

页面只做：展示插件列表 + 勾选 + 通过信号请求「更新全部/更新选中/刷新」。
真正调 PluginService 的控制器逻辑在 qt_app 侧（手动验证，本环境 import qt_app 会崩）。
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


def _plugin(name, is_git=True, version="abc1234", remote="https://github.com/x/y"):
    return {"name": name, "is_git": is_git, "version": version, "remote_url": remote}


def _stub_theme():
    """BasePage 构造需要的最小 theme_manager 替身。"""
    tm = MagicMock()
    tm.register_listener = lambda *_a, **_k: None
    styles = MagicMock()
    styles.c.dark = False
    styles.content_style_light.return_value = ""
    styles.content_style_dark.return_value = ""
    tm.styles = styles
    tm.colors = {}
    return tm


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


def test_update_selected_button_emits_checked_names(qt_app):
    from ui_qt.pages.plugins_page import PluginsPage

    page = PluginsPage(theme_manager=_stub_theme())
    page.populate([_plugin("A"), _plugin("B"), _plugin("C")])
    page.list_widget.item(1).setCheckState(QtCore.Qt.Checked)

    received = []
    page.update_selected_requested.connect(lambda names: received.append(names))
    page.update_selected_btn.click()
    assert received == [["B"]]


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


def test_controller_update_selected_passes_checked_names(qt_app):
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

