# -*- coding: utf-8 -*-
"""Tests for HiDPI scaling helpers in ui/assets_helper.py.

These helpers exist so callers can pass logical pixel sizes and let the helper
perform the devicePixelRatio dance (scale to physical pixels, then
setDevicePixelRatio so QLabel still measures in logical pixels). The
contract we lock down here is:
  - input dimensions are LOGICAL pixels (what the QLabel shows as)
  - output QPixmap has physical size = logical * dpr
  - output QPixmap.devicePixelRatio() == dpr
  - dpr is sourced from QApplication.instance().devicePixelRatio()
  - when no QApplication exists, dpr falls back to 1.0

To keep assertions independent of aspect-ratio logic, the source pixmap is
square (1:1). With ``IgnoreAspectRatio`` mode the scaled buffer matches the
target rectangle exactly, so physical = target_w * dpr.
"""
import sys
import unittest
from unittest.mock import patch, MagicMock

import pytest

from PyQt5 import QtCore


# ---------------------------------------------------------------------------
# _device_pixel_ratio fallback tests -- no Qt GUI needed, run as plain unittest
# ---------------------------------------------------------------------------

class TestDevicePixelRatioFallback(unittest.TestCase):
    """_device_pixel_ratio() falls back to 1.0 with no QApplication."""

    def _reload_module(self):
        for mod in list(sys.modules):
            if mod == "ui.assets_helper" or mod == "ui":
                del sys.modules[mod]

    def test_no_qapplication_returns_1(self):
        fake_qtwidgets = MagicMock()
        fake_qtwidgets.QApplication.instance.return_value = None
        with patch.dict(sys.modules, {"PyQt5.QtWidgets": fake_qtwidgets}):
            self._reload_module()
            from ui import assets_helper
            self.assertEqual(assets_helper._device_pixel_ratio(), 1.0)

    def test_uses_qapplication_device_pixel_ratio(self):
        fake_app = MagicMock()
        fake_app.devicePixelRatio.return_value = 2.0
        fake_qtwidgets = MagicMock()
        fake_qtwidgets.QApplication.instance.return_value = fake_app
        with patch.dict(sys.modules, {"PyQt5.QtWidgets": fake_qtwidgets}):
            self._reload_module()
            from ui import assets_helper
            self.assertEqual(assets_helper._device_pixel_ratio(), 2.0)

    def test_qapplication_instance_raises_returns_1(self):
        """QApplication.instance() raising must still fall back to 1.0."""
        fake_qtwidgets = MagicMock()
        fake_qtwidgets.QApplication.instance.side_effect = RuntimeError("boom")
        with patch.dict(sys.modules, {"PyQt5.QtWidgets": fake_qtwidgets}):
            self._reload_module()
            from ui import assets_helper
            self.assertEqual(assets_helper._device_pixel_ratio(), 1.0)


# ---------------------------------------------------------------------------
# scaled_pixmap / scaled_to_height -- need a real QApplication for QPixmap
# ---------------------------------------------------------------------------

def _patch_dpr(dpr):
    fake_app = MagicMock()
    fake_app.devicePixelRatio.return_value = dpr
    return patch(
        "PyQt5.QtWidgets.QApplication.instance",
        return_value=fake_app,
    )


class TestScaledPixmap:
    """scaled_pixmap: logical pixels -> physical pixels + setDevicePixelRatio."""

    def test_dpr_1_keeps_size_and_dpr(self, qtbot):
        from PyQt5 import QtGui
        from ui import assets_helper
        pix = QtGui.QPixmap(100, 100)  # 1:1
        with _patch_dpr(1.0):
            out = assets_helper.scaled_pixmap(
                pix, 48, 48, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation,
            )
        assert out.width() == 48
        assert out.height() == 48
        assert out.devicePixelRatio() == 1.0

    def test_dpr_2_doubles_physical_size_and_records_dpr(self, qtbot):
        from PyQt5 import QtGui
        from ui import assets_helper
        pix = QtGui.QPixmap(100, 100)
        with _patch_dpr(2.0):
            out = assets_helper.scaled_pixmap(
                pix, 48, 48, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation,
            )
        # Physical pixels should be logical * dpr.
        assert out.width() == 96
        assert out.height() == 96
        assert out.devicePixelRatio() == 2.0
        # QLabel calculates display size as physical / dpr == 48.
        assert out.width() / out.devicePixelRatio() == 48.0

    def test_dpr_fractional_rounds(self, qtbot):
        from PyQt5 import QtGui
        from ui import assets_helper
        pix = QtGui.QPixmap(100, 100)
        with _patch_dpr(1.5):
            out = assets_helper.scaled_pixmap(
                pix, 48, 48, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation,
            )
        # round(48 * 1.5) = 72
        assert out.width() == 72
        assert out.height() == 72
        assert out.devicePixelRatio() == 1.5

    def test_minimum_one_pixel(self, qtbot):
        """Logical 0 still produces at least 1 physical pixel."""
        from PyQt5 import QtGui
        from ui import assets_helper
        pix = QtGui.QPixmap(100, 100)
        with _patch_dpr(1.0):
            out = assets_helper.scaled_pixmap(
                pix, 0, 0, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation,
            )
        assert out.width() >= 1
        assert out.height() >= 1


class TestScaledToHeight:
    """scaled_to_height: height only, width keeps aspect ratio."""

    def test_dpr_1_keeps_height(self, qtbot):
        from PyQt5 import QtGui
        from ui import assets_helper
        pix = QtGui.QPixmap(100, 100)  # 1:1
        with _patch_dpr(1.0):
            out = assets_helper.scaled_to_height(pix, 48, QtCore.Qt.SmoothTransformation)
        assert out.height() == 48
        assert out.width() == 48  # 1:1 -> height 48 -> width 48
        assert out.devicePixelRatio() == 1.0

    def test_dpr_2_scales_height_to_physical(self, qtbot):
        from PyQt5 import QtGui
        from ui import assets_helper
        pix = QtGui.QPixmap(100, 100)
        with _patch_dpr(2.0):
            out = assets_helper.scaled_to_height(pix, 48, QtCore.Qt.SmoothTransformation)
        # Physical height = round(48 * 2) = 96
        assert out.height() == 96
        assert out.width() == 96
        assert out.devicePixelRatio() == 2.0
        # QLabel display height = physical / dpr == 48
        assert out.height() / out.devicePixelRatio() == 48.0


if __name__ == "__main__":
    unittest.main(verbosity=2)
