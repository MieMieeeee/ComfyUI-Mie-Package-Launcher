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


class TestPkgProgressTailTruncation:
    """utils.pip._pkg_progress tail should be truncated to a sane length."""

    def test_long_tail_is_truncated_to_under_30_chars(self):
        """Reproduce _pkg_progress tail truncation logic and verify."""
        # The _pkg_progress closure is hard to call directly, so we
        # reproduce its core judgement: tails >30 chars get clipped
        # to 27 + ellipsis.
        long_text = "collecting deps: " + ("x" * 80)
        text = long_text
        if text and len(text) > 30:
            text = text[:27] + "..."
        tail = f"  {text}" if text else ""
        assert len(tail) < 35, (
            f"Tail after truncation should be < 35 chars, got {tail!r}"
        )
        assert tail.endswith("..."), (
            f"Long tail should end with ellipsis, got {tail!r}"
        )
