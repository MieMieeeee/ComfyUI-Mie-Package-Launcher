"""失败弹窗「原始输出详情」组件单测（issue #111）。

- 日志控件必须是 QPlainTextEdit（共享 QSS 选择器只认它；写成 QTextEdit 会让
  整套日志区样式静默失效 —— openjutsu 页踩过这个坑）。
- 「复制详情」只复制、不关闭（用户还要继续看输出）。
- detail 为空时 DialogHelper.show_error_with_detail 退化成普通 show_error。
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
    """确定性销毁顶层 widget（仿 tests/unit/test_plugins_page.py 的同款夹具）。

    本机 offscreen PyQt5/Py3.12 下，迟到的 widget 析构会腐蚀堆（0xc0000374），
    连跑 ~25 个用例时进程直接崩。统一 close + deleteLater + 冲刷事件。
    """
    yield
    import gc

    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    gc.collect()
    for w in list(app.topLevelWidgets()):
        try:
            w.close()
        except Exception:
            pass
    for w in list(app.topLevelWidgets()):
        w.deleteLater()
    try:
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    except Exception:
        pass
    app.processEvents()
    gc.collect()


def _stub_theme():
    """最小 theme_manager 替身（styles._px/_pt 要返回数字，MagicMock 会污染 QSS）。"""
    tm = MagicMock()
    tm.register_listener = lambda *_a, **_k: None
    styles = MagicMock()
    styles._px = lambda v: v
    styles._pt = lambda v: v
    styles.content_style_light.return_value = ""
    styles.content_style_dark.return_value = ""
    styles.primary_button_style.return_value = ""
    styles.secondary_button_style.return_value = ""
    styles.destructive_button_style.return_value = ""
    tm.styles = styles
    tm.colors = {}
    return tm


def test_dialog_shows_detail_in_plain_text_edit(qt_app):
    from ui_qt.widgets.cmcli_error_dialog import CmCliErrorDialog

    detail = "Traceback (most recent call last):\nTypeError: boom"
    dlg = CmCliErrorDialog(title="更新选中", content="更新选中失败：cm-cli update 退出码 1",
                           detail=detail, theme_manager=_stub_theme())
    views = dlg.findChildren(QtWidgets.QPlainTextEdit)
    assert len(views) == 1, "详情区必须是 QPlainTextEdit（QSS 选择器只认它）"
    assert detail in views[0].toPlainText()
    assert dlg.detail_text() == detail


def test_dialog_without_detail_has_no_log_box(qt_app):
    from ui_qt.widgets.cmcli_error_dialog import CmCliErrorDialog

    dlg = CmCliErrorDialog(title="更新选中", content="失败", detail="",
                           theme_manager=_stub_theme())
    assert dlg.findChildren(QtWidgets.QPlainTextEdit) == []


def test_copy_button_copies_and_keeps_dialog_open(qt_app):
    from ui_qt.widgets.cmcli_error_dialog import CmCliErrorDialog

    detail = "ERROR-MARKER-XYZ"
    dlg = CmCliErrorDialog(title="t", content="c", detail=detail,
                           theme_manager=_stub_theme())
    dlg._on_btn_clicked(CmCliErrorDialog.COPY_BUTTON_INDEX)
    assert QtWidgets.QApplication.clipboard().text() == detail
    assert dlg.isVisible() is False or dlg.result() is None, "复制不应关闭弹窗"


def test_show_error_with_detail_falls_back_when_empty(qt_app):
    from ui_qt.widgets.dialog_helper import DialogHelper

    with patch("ui_qt.widgets.dialog_helper.DialogHelper.show_error") as spy:
        DialogHelper.show_error_with_detail(None, "t", "c", "")
    assert spy.called, "detail 为空时应退化成普通 show_error"
