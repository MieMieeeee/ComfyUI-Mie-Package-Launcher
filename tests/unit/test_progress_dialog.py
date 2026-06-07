"""
Test ProgressDialog non-modal and auto-size behaviour.

Reasons for the change:
1. setModal(True) blocked all main-window clicks during update;
   user could not click quick directory or one-click launch.
2. setFixedSize(350, 190) made the dialog a fixed height; long
   status text was truncated when wrapped.
3. utils.pip._pkg_progress tail should be truncated so the dialog
   stays compact.
"""

import pytest
from PyQt5 import QtCore, QtWidgets

from ui_qt.widgets.progress_dialog import ProgressDialog


class TestProgressDialogNonModal:
    """Dialog must not block main-window input."""

    def test_dialog_is_not_modal(self, qtbot):
        """After setModal(False), Qt.isModal() returns False."""
        dlg = ProgressDialog(title="t", show_cancel=True)
        qtbot.addWidget(dlg)
        assert dlg.isModal() is False, (
            "ProgressDialog must be non-modal, otherwise the user "
            "cannot click the main window during update."
        )

    def test_window_flag_uses_tool(self, qtbot):
        """Window flag should be Qt.Tool (floats, no taskbar, no focus grab).

        Note: in Qt5, Qt.Tool is value 0x0a which internally has the
        Qt.Dialog bit (0x02) set. We must use WindowType_Mask to
        compare the actual window-type slot, not a bitwise AND.
        """
        dlg = ProgressDialog(title="t", show_cancel=True)
        qtbot.addWidget(dlg)
        flags = dlg.windowFlags()
        window_type = flags & QtCore.Qt.WindowType_Mask
        assert window_type == QtCore.Qt.Tool, (
            f"ProgressDialog window type should be Qt.Tool, got {window_type!r} "
            f"(raw flags={flags!r})"
        )


class TestProgressDialogAutoSize:
    """Dialog height must grow with wrapped status text."""

    def test_grows_vertically_for_wrapped_status(self, qtbot):
        """Long wrapped status text must grow the dialog height."""
        dlg = ProgressDialog(title="t", show_cancel=True)
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)

        dlg.set_status("short")
        short_h = dlg.height()

        dlg.set_status("long " * 60)
        tall_h = dlg.height()

        assert tall_h > short_h, (
            f"Dialog should grow for long text: short={short_h}, long={tall_h}"
        )

    def test_width_does_not_explode(self, qtbot):
        """Width must not grow unboundedly."""
        dlg = ProgressDialog(title="t", show_cancel=True)
        qtbot.addWidget(dlg)
        dlg.set_status("x" * 500)
        assert dlg.width() <= 600, (
            f"Dialog width should be <= 600, got {dlg.width()}"
        )


class TestProgressDialogDraggable:
    """Frameless dialog must be draggable with left mouse button.

    The popup is frameless (no title bar), so the user has no handle
    to grab. Implement mousePress / mouseMove / mouseRelease so the
    whole dialog body (except the cancel button) becomes a drag
    handle. This lets the user push the dialog out of the way when
    it covers important content behind it.
    """

    def _make_event(self, event_type, global_pos, button=QtCore.Qt.LeftButton):
        """Build a QMouseEvent-like object the dialog handlers can use.

        QMouseEvent(type, localPos, button, buttons, modifiers):
          - button: which mouse button caused the event (event.button())
          - buttons: which buttons are currently held (event.buttons())
        """
        from PyQt5 import QtGui
        local_pos = QtCore.QPointF(global_pos[0], global_pos[1])
        return QtGui.QMouseEvent(
            event_type,
            local_pos,
            button,             # event.button() == the pressed button
            button,             # event.buttons() == held buttons
            QtCore.Qt.NoModifier,
        )

    def test_drag_moves_the_dialog(self, qtbot):
        """Press, move, release should move the dialog by the drag delta.

        We spy on dlg.move() instead of asserting exact screen coords,
        since QMouseEvent.globalPos() in tests may not include window
        offset and dlg.pos() vs frameGeometry() can differ by frame
        margins in some environments.
        """
        from unittest.mock import patch
        dlg = ProgressDialog(title="t", show_cancel=True)
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)

        move_calls = []
        def fake_move(pos):
            # 记录被请求的 move 点
            move_calls.append((pos.x(), pos.y()))
        with patch.object(dlg, "move", side_effect=fake_move):
            # press
            press_event = self._make_event(
                QtCore.QEvent.MouseButtonPress, (300, 300)
            )
            dlg.mousePressEvent(press_event)
            assert dlg._drag_pos is not None, (
                "_drag_pos should be set after press"
            )

            # move
            from PyQt5 import QtGui
            move_event = QtGui.QMouseEvent(
                QtCore.QEvent.MouseMove,
                QtCore.QPointF(450, 380),
                QtCore.QPointF(450, 380),
                QtCore.Qt.LeftButton,
                QtCore.Qt.LeftButton,
                QtCore.Qt.NoModifier,
            )
            dlg.mouseMoveEvent(move_event)
            assert len(move_calls) == 1, (
                f"dlg.move should be called once during drag, got {len(move_calls)}"
            )

            # release
            release_event = self._make_event(
                QtCore.QEvent.MouseButtonRelease, (450, 380)
            )
            dlg.mouseReleaseEvent(release_event)
            assert dlg._drag_pos is None, (
                "_drag_pos should be cleared after release"
            )

        # move 后再 move 应该被忽略（_drag_pos=None）
        extra_event = self._make_event(
            QtCore.QEvent.MouseMove, (500, 500)
        )
        move_calls.clear()
        with patch.object(dlg, "move", side_effect=fake_move):
            dlg.mouseMoveEvent(extra_event)
        assert len(move_calls) == 0, (
            "mouseMoveEvent after release should not call self.move()"
        )

    def test_release_without_drag_is_safe(self, qtbot):
        """Press then release without moving should not crash and should reset state."""
        dlg = ProgressDialog(title="t", show_cancel=True)
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)

        press_event = self._make_event(
            QtCore.QEvent.MouseButtonPress, (50, 50)
        )
        dlg.mousePressEvent(press_event)
        assert dlg._drag_pos is not None

        release_event = self._make_event(
            QtCore.QEvent.MouseButtonRelease, (50, 50)
        )
        dlg.mouseReleaseEvent(release_event)
        assert dlg._drag_pos is None

    def test_right_button_press_does_not_initiate_drag(self, qtbot):
        """Right-click should not start a drag (left button only)."""
        dlg = ProgressDialog(title="t", show_cancel=True)
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)

        right_event = self._make_event(
            QtCore.QEvent.MouseButtonPress,
            (50, 50),
            button=QtCore.Qt.RightButton,
        )
        dlg.mousePressEvent(right_event)
        assert dlg._drag_pos is None, (
            "Right click should not start drag"
        )
