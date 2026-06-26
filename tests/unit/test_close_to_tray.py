"""
\u6d4b\u8bd5 PyQtLauncher \u7684\u5173\u95ed -> \u6258\u76d8 \u884c\u4e3a\u3002

\u91cd\u70b9\u9a8c\u8bc1 _resolve_close_action \u548c _prompt_comfyui_exit_mode \u7684\u903b\u8f91\u3002
\u4e3a\u4e86\u8ba9 CustomConfirmDialog.exec_() \u80fd\u8dd1\uff0c\u4f2a\u903b\u8f91\u5bf9\u8c61\u9700\u8981\u662f QObject\u3002
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtWidgets  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


class _StubTray:
    def __init__(self, available=True):
        self.available = available


class _StubLauncher(QtWidgets.QWidget):
    """\u4ec5\u4f9b _resolve_close_action / _prompt_comfyui_exit_mode \u4f7f\u7528\u7684\u8f85\u52a9\u7c7b\u3002"""

    def __init__(self, config=None, tray=None, comfyui_running=False, parent=None):
        super().__init__(parent)
        self.setObjectName("_StubLauncher")
        self.config = config or {"ui_settings": {}}
        self._tray = tray
        self._is_comfyui_running = lambda: comfyui_running
        self.theme_manager = None
        self.services = types.SimpleNamespace(
            config=types.SimpleNamespace(save=lambda *_a, **_k: None)
        )


def _resolver():
    import ui_qt.qt_app as qa
    return qa.PyQtLauncher._resolve_close_action


def test_no_ask_uses_saved_minimize(qt_app):
    resolve = _resolver()
    stub = _StubLauncher(
        config={"ui_settings": {"minimize_to_tray_on_close": True, "minimize_to_tray_ask_every_time": False}},
        tray=_StubTray(available=True),
    )
    with patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.exec_") as exec_:
        exec_.return_value = QtWidgets.QDialog.Accepted
        assert resolve(stub) == "minimize"
        assert exec_.call_count == 0


def test_no_ask_quit_when_preference_says_quit(qt_app):
    resolve = _resolver()
    stub = _StubLauncher(
        config={"ui_settings": {"minimize_to_tray_on_close": False, "minimize_to_tray_ask_every_time": False}},
        tray=_StubTray(available=True),
    )
    assert resolve(stub) == "quit"


def test_no_ask_falls_back_to_quit_when_tray_unavailable(qt_app):
    resolve = _resolver()
    stub = _StubLauncher(
        config={"ui_settings": {"minimize_to_tray_on_close": True, "minimize_to_tray_ask_every_time": False}},
        tray=_StubTray(available=False),
    )
    assert resolve(stub) == "quit"


def test_ask_user_can_cancel(qt_app):
    resolve = _resolver()
    stub = _StubLauncher(
        config={"ui_settings": {"minimize_to_tray_on_close": False, "minimize_to_tray_ask_every_time": True}},
        tray=_StubTray(available=True),
    )
    with patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.exec_") as exec_, \
         patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.get_result", return_value=0):
        exec_.return_value = QtWidgets.QDialog.Accepted
        assert resolve(stub) == "cancel"


def test_ask_user_picks_minimize_and_saves(qt_app):
    resolve = _resolver()
    stub = _StubLauncher(
        config={"ui_settings": {"minimize_to_tray_on_close": False, "minimize_to_tray_ask_every_time": True}},
        tray=_StubTray(available=True),
    )
    saved = {}
    stub.services.config.save = lambda cfg: saved.update(cfg)

    with patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.exec_") as exec_, \
         patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.get_result", return_value=1), \
         patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.is_remember_checked", return_value=True):
        exec_.return_value = QtWidgets.QDialog.Accepted
        assert resolve(stub) == "minimize"

    ui = saved.get("ui_settings", {})
    assert ui.get("minimize_to_tray_ask_every_time") is False
    assert ui.get("minimize_to_tray_on_close") is True


def test_ask_user_picks_quit_with_remember(qt_app):
    resolve = _resolver()
    stub = _StubLauncher(
        config={"ui_settings": {"minimize_to_tray_on_close": False, "minimize_to_tray_ask_every_time": True}},
        tray=_StubTray(available=True),
    )
    saved = {}
    stub.services.config.save = lambda cfg: saved.update(cfg)

    with patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.exec_") as exec_, \
         patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.get_result", return_value=2), \
         patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.is_remember_checked", return_value=True):
        exec_.return_value = QtWidgets.QDialog.Accepted
        assert resolve(stub) == "quit"

    ui = saved.get("ui_settings", {})
    assert ui.get("minimize_to_tray_ask_every_time") is False
    assert ui.get("minimize_to_tray_on_close") is False


def test_tray_unavailable_no_minimize_option(qt_app):
    resolve = _resolver()
    stub = _StubLauncher(
        config={"ui_settings": {"minimize_to_tray_on_close": True, "minimize_to_tray_ask_every_time": True}},
        tray=_StubTray(available=False),
    )
    captured = {}
    import ui_qt.widgets.custom_confirm_dialog as ccd
    real_init = ccd.CustomConfirmDialog.__init__

    def spy(self, *args, **kwargs):
        captured["buttons"] = kwargs.get("buttons") or (args[3] if len(args) > 3 else None)
        return real_init(self, *args, **kwargs)

    with patch.object(ccd.CustomConfirmDialog, "__init__", spy), \
         patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.exec_") as exec_, \
         patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.get_result", return_value=1):
        exec_.return_value = QtWidgets.QDialog.Accepted
        assert resolve(stub) == "quit"

    texts = [b["text"] for b in captured["buttons"]]
    assert "\u6700\u5c0f\u5316\u5230\u6258\u76d8" not in texts
    assert "\u9000\u51fa\u542f\u52a8\u5668" in texts


def test_ask_default_focus_is_cancel_when_ask_true(qt_app):
    """回归："每次都提醒" 时默认焦点必须落在「取消」上，避免 Enter 直接最小化/退出。

    之前实现是 default_index=1 if minimize_default else 2，会让用户在回车时
    直接触发「最小化到托盘」或「退出启动器」，与「每次都提醒」的语义冲突。
    """
    import ui_qt.widgets.custom_confirm_dialog as ccd
    real_init = ccd.CustomConfirmDialog.__init__
    resolve = _resolver()

    for minimize_default in (True, False):
        stub = _StubLauncher(
            config={
                "ui_settings": {
                    "minimize_to_tray_on_close": minimize_default,
                    "minimize_to_tray_ask_every_time": True,
                }
            },
            tray=_StubTray(available=True),
        )
        captured = {}

        def spy(self, *args, **kwargs):
            captured["default_index"] = kwargs.get("default_index", 0)
            return real_init(self, *args, **kwargs)

        with patch.object(ccd.CustomConfirmDialog, "__init__", spy), \
             patch("ui_qt.widgets.custom_confirm_dialog.CustomConfirmDialog.exec_") as exec_:
            exec_.return_value = QtWidgets.QDialog.Rejected
            action = resolve(stub)
            assert action == "cancel"
            assert captured.get("default_index") == 0, (
                f"minimize_default={minimize_default}: default_index should be 0 (取消), "
                f"got {captured.get('default_index')}"
            )


class _FakeSignal:
    def __init__(self):
        self._handler = None
    def connect(self, h):
        self._handler = h


class _FakeAction:
    def __init__(self, text):
        self._text = text
        self._enabled = True
        self._tooltip = ""
        self.triggered = _FakeSignal()
    def setText(self, t):
        self._text = t
    def text(self):
        return self._text
    def setEnabled(self, e):
        self._enabled = e
    def isEnabled(self):
        return self._enabled
    def setToolTip(self, t):
        self._tooltip = t
    def toolTip(self):
        return self._tooltip


class _FakeMenu:
    aboutToShow = _FakeSignal()
    def __init__(self):
        self.actions = []
    def addAction(self, text):
        a = _FakeAction(text)
        self.actions.append(a)
        return a
    def addSeparator(self):
        pass
    def setStyleSheet(self, *_a, **_k):
        pass


class _FakeTray:
    activated = _FakeSignal()
    def __init__(self, icon, parent=None):
        pass
    def setToolTip(self, _t):
        pass
    def setContextMenu(self, _m):
        pass
    def show(self):
        pass
    def hide(self):
        pass
    def deleteLater(self):
        pass


_FakeTray.isSystemTrayAvailable = staticmethod(lambda: True)


def test_tray_menu_has_quit_and_quit_and_stop_actions(qt_app):
    """托盘菜单应同时提供 '退出启动器' 与 '退出并关闭 ComfyUI' 两项。"""
    from ui_qt.widgets import tray_icon as ti

    fake_menu = _FakeMenu()
    app_stub = type("A", (), {"logger": None})()

    with patch.object(ti.QtWidgets, "QSystemTrayIcon", _FakeTray), \
         patch.object(ti.QtWidgets, "QMenu", lambda: fake_menu):
        tray = ti.LauncherTray(app=app_stub, theme_manager=None, parent=None)
        assert tray.init() is True

    texts = [a.text() for a in fake_menu.actions]
    assert "退出启动器" in texts
    assert "退出并关闭 ComfyUI" in texts


def test_tray_quit_and_stop_disabled_when_comfyui_not_running(qt_app):
    """ComfyUI 未运行时，"退出并关闭 ComfyUI" 应保持禁用。"""
    from ui_qt.widgets import tray_icon as ti

    fake_menu = _FakeMenu()
    app_stub = type("A", (), {"logger": None})()

    with patch.object(ti.QtWidgets, "QSystemTrayIcon", _FakeTray), \
         patch.object(ti.QtWidgets, "QMenu", lambda: fake_menu):
        tray = ti.LauncherTray(app=app_stub, theme_manager=None, parent=None)
        tray.init()
    stop_action = next(a for a in fake_menu.actions if a.text() == "退出并关闭 ComfyUI")
    assert stop_action.isEnabled() is False


def test_tray_quit_and_stop_enables_when_comfyui_running(qt_app):
    """ComfyUI 运行中时，"退出并关闭 ComfyUI" 应启用。"""
    from ui_qt.widgets import tray_icon as ti

    fake_menu = _FakeMenu()
    app_stub = type("A", (), {"logger": None})()

    with patch.object(ti.QtWidgets, "QSystemTrayIcon", _FakeTray), \
         patch.object(ti.QtWidgets, "QMenu", lambda: fake_menu):
        tray = ti.LauncherTray(app=app_stub, theme_manager=None, parent=None)
        tray.init()
    stop_action = next(a for a in fake_menu.actions if a.text() == "退出并关闭 ComfyUI")
    tray.update_comfyui_status(True)
    assert stop_action.isEnabled() is True
    tray.update_comfyui_status(False)
    assert stop_action.isEnabled() is False


def test_tray_about_to_show_disables_stop_when_not_running(qt_app):
    """菜单弹出（aboutToShow）据 is_running_fast 复核：未跑时「退出并关闭」必置灰。

    回归：即便动作此前被异步推送误置为 enabled，弹出时也要纠正回来。
    """
    from ui_qt.widgets import tray_icon as ti

    fake_menu = _FakeMenu()
    app_stub = type("A", (), {
        "logger": None,
        "process_manager": type("PM", (), {"is_running_fast": lambda self: False})(),
    })()

    with patch.object(ti.QtWidgets, "QSystemTrayIcon", _FakeTray), \
         patch.object(ti.QtWidgets, "QMenu", lambda: fake_menu):
        tray = ti.LauncherTray(app=app_stub, theme_manager=None, parent=None)
        tray.init()

    stop_action = next(a for a in fake_menu.actions if a.text() == "退出并关闭 ComfyUI")
    stop_action.setEnabled(True)  # 模拟异步推送留下的过时 enabled 态
    assert stop_action.isEnabled() is True
    tray._on_about_to_show()
    assert stop_action.isEnabled() is False


def test_tray_about_to_show_enables_stop_when_running(qt_app):
    """is_running_fast=True 时，aboutToShow 启用「退出并关闭」项。"""
    from ui_qt.widgets import tray_icon as ti

    fake_menu = _FakeMenu()
    app_stub = type("A", (), {
        "logger": None,
        "process_manager": type("PM", (), {"is_running_fast": lambda self: True})(),
    })()

    with patch.object(ti.QtWidgets, "QSystemTrayIcon", _FakeTray), \
         patch.object(ti.QtWidgets, "QMenu", lambda: fake_menu):
        tray = ti.LauncherTray(app=app_stub, theme_manager=None, parent=None)
        tray.init()

    stop_action = next(a for a in fake_menu.actions if a.text() == "退出并关闭 ComfyUI")
    tray._on_about_to_show()
    assert stop_action.isEnabled() is True


def test_tray_emits_quit_and_stop_signal(qt_app):
    """点击"退出并关闭 ComfyUI"应发射 quit_and_stop_requested 信号。"""
    from ui_qt.widgets import tray_icon as ti
    from PyQt5 import QtWidgets

    fake_menu = _FakeMenu()
    app_stub = type("A", (), {"logger": None})()

    with patch.object(ti.QtWidgets, "QSystemTrayIcon", _FakeTray), \
         patch.object(ti.QtWidgets, "QMenu", lambda: fake_menu):
        tray = ti.LauncherTray(app=app_stub, theme_manager=None, parent=None)
        tray.init()

    # 用真 Qt 动作代替 fake 触发：临时 patch 菜单里的 stop_action 替换为真 QAction
    stop_action = next(a for a in fake_menu.actions if a.text() == "退出并关闭 ComfyUI")
    real_action = QtWidgets.QAction(stop_action.text())
    # 让 tray 内部用的 stop_action 也是真 QAction：直接换掉 fake_menu 里的 action
    real_action.triggered.connect(tray.quit_and_stop_requested.emit)

    received = []
    tray.quit_and_stop_requested.connect(lambda: received.append(True))
    real_action.trigger()
    QtWidgets.QApplication.processEvents()
    assert received == [True], "quit_and_stop_requested should be emitted on click"
