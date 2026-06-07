"""Smoke tests for CustomConfirmDialog: confirm it inherits drag from base."""

import pytest
from PyQt5 import QtCore
from unittest.mock import patch

from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog


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


def test_custom_confirm_dialog_is_draggable(qtbot):
    """CustomConfirmDialog must inherit drag from FramelessDraggableDialog."""
    dlg = CustomConfirmDialog(title="t", content="c")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    move_calls = []
    with patch.object(dlg, "move", side_effect=lambda p: move_calls.append(p)):
        dlg.mousePressEvent(_make_event(QtCore.QEvent.MouseButtonPress, (50, 50)))
        dlg.mouseMoveEvent(_make_event(QtCore.QEvent.MouseMove, (200, 150)))
    assert len(move_calls) == 1


def test_custom_confirm_dialog_is_modal_by_default(qtbot):
    dlg = CustomConfirmDialog(title="t", content="c")
    qtbot.addWidget(dlg)
    assert dlg.isModal() is True
