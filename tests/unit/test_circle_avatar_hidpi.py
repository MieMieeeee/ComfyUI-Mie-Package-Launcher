# -*- coding: utf-8 -*-
"""Tests for CircleAvatar HiDPI behavior in ui_qt/widgets/custom.py.

CircleAvatar paints a circular cropped pixmap. Under Per-Monitor DPI V2 the
avatar should still render crisply when the widget is moved to a high-dpi
display. The contract we lock down:
  - the painted pixmap is scaled to physical_w = logical_w * dpr
  - dpr is read from the widget itself (``self.devicePixelRatioF()``),
    NOT the global ``QApplication.devicePixelRatio()`` -- this is the only
    way to track per-monitor changes when the widget is dragged across
    screens with different scaling factors.
  - paintEvent completes without raising when the source pixmap is null
    (placeholder rendering).

We patch ``QtGui.QPainter`` so any ``QPainter(widget)`` inside paintEvent
returns our recording stub, then assert on the recorded drawPixmap calls.
"""
import pytest
from unittest.mock import patch, MagicMock


pytest.importorskip("PyQt5")


class _RecordingPainter:
    """Stub QPainter. Records drawPixmap; silently no-ops everything else."""

    def __init__(self, *args, **kwargs):
        self.drawn = []  # list of (x, y, QPixmap)

    def setRenderHint(self, *a, **kw): pass
    def setBrush(self, *a, **kw): pass
    def setPen(self, *a, **kw): pass
    def setClipPath(self, *a, **kw): pass
    def drawEllipse(self, *a, **kw): pass
    def drawPixmap(self, x, y, pix):
        self.drawn.append((x, y, pix))
    def __getattr__(self, name):
        return MagicMock()


def _run_paint(widget, dpr):
    """Call widget.paintEvent with a QPaintEvent, recording QPainter calls."""
    from PyQt5.QtCore import QRect
    from PyQt5.QtGui import QPaintEvent
    from ui_qt.widgets import custom as custom_mod

    painter = _RecordingPainter()
    with patch.object(custom_mod.QtGui, "QPainter", side_effect=lambda *a, **kw: painter), \
         patch.object(type(widget), "devicePixelRatioF", return_value=dpr):
        widget.paintEvent(QPaintEvent(QRect(0, 0, widget.width(), widget.height())))
    return painter


class TestCircleAvatarScalesByDpr:
    """CircleAvatar.paintEvent must scale the source pixmap by widget dpr."""

    def test_paints_pixmap_at_physical_size_dpr_2(self, qtbot):
        from PyQt5 import QtGui
        from ui_qt.widgets.custom import CircleAvatar

        src = QtGui.QPixmap(100, 100)
        avatar = CircleAvatar(pixmap=src, size=80)
        qtbot.addWidget(avatar)

        painter = _run_paint(avatar, dpr=2.0)
        assert len(painter.drawn) == 1
        _, _, drawn_pix = painter.drawn[0]
        # logical 80, dpr 2 -> physical 160
        assert drawn_pix.width() == 160, f"expected 160, got {drawn_pix.width()}"
        assert drawn_pix.height() == 160
        assert drawn_pix.devicePixelRatio() == 2.0

    def test_paints_placeholder_when_pixmap_null(self, qtbot):
        from ui_qt.widgets.custom import CircleAvatar

        avatar = CircleAvatar(pixmap=None, size=80)
        qtbot.addWidget(avatar)
        painter = _run_paint(avatar, dpr=1.0)
        # No drawPixmap; placeholder ellipse was drawn instead.
        assert painter.drawn == []
        assert avatar.width() == 80
        assert avatar.height() == 80

    def test_dpr_one_keeps_physical_equal_to_logical(self, qtbot):
        from PyQt5 import QtGui
        from ui_qt.widgets.custom import CircleAvatar

        src = QtGui.QPixmap(100, 100)
        avatar = CircleAvatar(pixmap=src, size=64)
        qtbot.addWidget(avatar)

        painter = _run_paint(avatar, dpr=1.0)
        assert len(painter.drawn) == 1
        _, _, drawn_pix = painter.drawn[0]
        assert drawn_pix.width() == 64
        assert drawn_pix.height() == 64
        assert drawn_pix.devicePixelRatio() == 1.0

    def test_uses_widget_dpr_not_global_dpr(self, qtbot):
        """Under Per-Monitor V2 the widget's dpr differs from the global dpr.

        CircleAvatar must follow the widget's dpr (which updates when the
        widget is dragged to a different display), not the QApplication
        global dpr. This is the reason paintEvent reads
        ``self.devicePixelRatioF()`` instead of asking the application.
        """
        from PyQt5 import QtGui, QtWidgets
        from ui_qt.widgets.custom import CircleAvatar

        src = QtGui.QPixmap(100, 100)
        avatar = CircleAvatar(pixmap=src, size=80)
        qtbot.addWidget(avatar)

        # global dpr says 1.0, but the widget's screen says 2.0
        global_app = QtWidgets.QApplication.instance()
        with patch.object(global_app, "devicePixelRatio", return_value=1.0):
            painter = _run_paint(avatar, dpr=2.0)
        assert len(painter.drawn) == 1
        _, _, drawn_pix = painter.drawn[0]
        # The widget dpr wins: physical = 160, not 80.
        assert drawn_pix.width() == 160
        assert drawn_pix.devicePixelRatio() == 2.0
