"""
Tests for the unified FramelessDraggableDialog base class.

Extracted from ProgressDialog so UpdateDialog and CustomConfirmDialog
can also be draggable without duplicating mouse-event handlers.
"""

import pytest
from PyQt5 import QtCore, QtGui, QtWidgets
from unittest.mock import patch

from ui_qt.widgets.frameless_draggable_dialog import FramelessDraggableDialog


class _MinimalDialog(FramelessDraggableDialog):
    """A minimal subclass for testing the base class in isolation.

    Real dialogs add UI on top; for the base class we just need
    something concrete to instantiate.
    """

    def __init__(self, parent=None, modal=True, window_type=QtCore.Qt.Dialog):
        super().__init__(parent=parent, modal=modal, window_type=window_type)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(QtWidgets.QLabel("hello"))
        self.resize(200, 100)


def _make_mouse_event(event_type, pos, button=QtCore.Qt.LeftButton):
    """Build a QMouseEvent (button / buttons slots ordered correctly)."""
    return QtGui.QMouseEvent(
        event_type,
        QtCore.QPointF(*pos),
        QtCore.QPointF(*pos),
        button,
        button,
        QtCore.Qt.NoModifier,
    )


class TestFramelessDraggableDialogFlags:
    """Base class sets common frameless flags and translucent background."""

    def test_has_frameless_window_hint(self, qtbot):
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        assert bool(dlg.windowFlags() & QtCore.Qt.FramelessWindowHint), (
            f"FramelessWindowHint missing, got {dlg.windowFlags()!r}"
        )

    def test_has_window_stays_on_top(self, qtbot):
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        assert bool(dlg.windowFlags() & QtCore.Qt.WindowStaysOnTopHint), (
            f"WindowStaysOnTopHint missing, got {dlg.windowFlags()!r}"
        )

    def test_has_translucent_background(self, qtbot):
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        assert dlg.testAttribute(QtCore.Qt.WA_TranslucentBackground), (
            "WA_TranslucentBackground should be set for rounded corners"
        )

    def test_default_window_type_is_dialog(self, qtbot):
        """Without window_type override, default is Qt.Dialog (modal feel)."""
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        window_type = dlg.windowFlags() & QtCore.Qt.WindowType_Mask
        assert window_type == QtCore.Qt.Dialog, (
            f"default window type should be Qt.Dialog, got {window_type!r}"
        )

    def test_window_type_can_be_overridden(self, qtbot):
        """window_type=Qt.Tool gives a non-modal tool window."""
        dlg = _MinimalDialog(window_type=QtCore.Qt.Tool)
        qtbot.addWidget(dlg)
        window_type = dlg.windowFlags() & QtCore.Qt.WindowType_Mask
        assert window_type == QtCore.Qt.Tool, (
            f"override window type should be Qt.Tool, got {window_type!r}"
        )

    def test_modal_default_true(self, qtbot):
        """Default modal=True matches most confirmation dialogs."""
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        assert dlg.isModal() is True

    def test_modal_can_be_disabled(self, qtbot):
        """ProgressDialog uses modal=False to keep main window clickable."""
        dlg = _MinimalDialog(modal=False)
        qtbot.addWidget(dlg)
        assert dlg.isModal() is False


class TestFramelessDraggableDialogDrag:
    """Base class implements the mouse-event drag protocol."""

    def test_press_sets_drag_pos(self, qtbot):
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)
        dlg.mousePressEvent(_make_mouse_event(QtCore.QEvent.MouseButtonPress, (100, 100)))
        assert dlg._drag_pos is not None, (
            "_drag_pos should be set after left press"
        )

    def test_release_clears_drag_pos(self, qtbot):
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)
        dlg.mousePressEvent(_make_mouse_event(QtCore.QEvent.MouseButtonPress, (100, 100)))
        dlg.mouseReleaseEvent(_make_mouse_event(QtCore.QEvent.MouseButtonRelease, (100, 100)))
        assert dlg._drag_pos is None

    def test_move_during_drag_calls_widget_move(self, qtbot):
        """Press then move should call self.move() with a new position."""
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)
        move_calls = []
        with patch.object(dlg, "move", side_effect=lambda p: move_calls.append(p)):
            dlg.mousePressEvent(_make_mouse_event(QtCore.QEvent.MouseButtonPress, (200, 200)))
            dlg.mouseMoveEvent(_make_mouse_event(QtCore.QEvent.MouseMove, (350, 300)))
        assert len(move_calls) == 1, (
            f"self.move should be called once during drag, got {len(move_calls)}"
        )

    def test_move_without_drag_is_noop(self, qtbot):
        """A mouseMove with _drag_pos=None should not move the widget."""
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)
        move_calls = []
        with patch.object(dlg, "move", side_effect=lambda p: move_calls.append(p)):
            dlg.mouseMoveEvent(_make_mouse_event(QtCore.QEvent.MouseMove, (500, 500)))
        assert len(move_calls) == 0

    def test_right_button_press_does_not_start_drag(self, qtbot):
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)
        dlg.mousePressEvent(
            _make_mouse_event(
                QtCore.QEvent.MouseButtonPress,
                (50, 50),
                button=QtCore.Qt.RightButton,
            )
        )
        assert dlg._drag_pos is None
