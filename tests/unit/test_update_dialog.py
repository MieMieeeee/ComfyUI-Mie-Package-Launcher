"""Smoke tests for UpdateDialog: confirm it inherits drag from base."""

import pytest
from PyQt5 import QtCore
from unittest.mock import patch

from ui_qt.widgets.update_dialog import UpdateDialog


def _make_event(event_type, pos, button=QtCore.Qt.LeftButton):
    from PyQt5 import QtGui
    return QtGui.QMouseEvent(
        event_type,
        QtCore.QPointF(*pos),
        QtCore.QPointF(*pos),
        button,
        button,
        QtCore.Qt.NoModifier,
    )


def test_update_dialog_is_draggable(qtbot):
    """UpdateDialog must inherit drag from FramelessDraggableDialog.

    用户反馈：\"@\"更新完成的弹出框没有办法拖\"@\"。现在通过基类
    FramelessDraggableDialog 统一提供拖拽支持。
    """
    dlg = UpdateDialog()
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    move_calls = []
    with patch.object(dlg, "move", side_effect=lambda p: move_calls.append(p)):
        dlg.mousePressEvent(_make_event(QtCore.QEvent.MouseButtonPress, (100, 100)))
        dlg.mouseMoveEvent(_make_event(QtCore.QEvent.MouseMove, (250, 200)))
    assert len(move_calls) == 1, (
        f"UpdateDialog.move should be called once during drag, got {len(move_calls)}"
    )


def test_update_dialog_is_modal_by_default(qtbot):
    dlg = UpdateDialog()
    qtbot.addWidget(dlg)
    assert dlg.isModal() is True, "UpdateDialog should be modal by default"


def test_update_dialog_window_type_is_dialog(qtbot):
    dlg = UpdateDialog()
    qtbot.addWidget(dlg)
    window_type = dlg.windowFlags() & QtCore.Qt.WindowType_Mask
    assert window_type == QtCore.Qt.Dialog
