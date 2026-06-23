# -*- coding: utf-8 -*-
"""Tests for setup_qt_high_dpi() in ui/assets_helper.py.

The helper sets the two Qt application attributes that turn on Qt's
high-DPI scaling. They MUST be set before QApplication is constructed, so
the function is just a thin wrapper around setAttribute calls. The contract
we lock down:
  - sets AA_EnableHighDpiScaling when the attribute exists
  - sets AA_UseHighDpiPixmaps when the attribute exists
  - never raises (Qt not present, missing attributes, etc.)
  - is idempotent (calling twice is fine)
"""
import sys
import unittest
from unittest.mock import patch, MagicMock

import pytest


class TestSetupQtHighDpi:
    """setup_qt_high_dpi() should set the two Qt AA_ attributes safely."""

    def test_sets_both_aa_attributes(self, qtbot):
        from PyQt5 import QtCore, QtWidgets
        from ui import assets_helper

        # Reset any previous state.
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, False)
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, False)

        assets_helper.setup_qt_high_dpi()

        assert QtWidgets.QApplication.testAttribute(QtCore.Qt.AA_EnableHighDpiScaling) is True
        assert QtWidgets.QApplication.testAttribute(QtCore.Qt.AA_UseHighDpiPixmaps) is True

    def test_is_idempotent(self, qtbot):
        from PyQt5 import QtCore, QtWidgets
        from ui import assets_helper

        assets_helper.setup_qt_high_dpi()
        assets_helper.setup_qt_high_dpi()  # calling again must not raise

        assert QtWidgets.QApplication.testAttribute(QtCore.Qt.AA_EnableHighDpiScaling) is True
        assert QtWidgets.QApplication.testAttribute(QtCore.Qt.AA_UseHighDpiPixmaps) is True


class TestSetupQtHighDpiMissingQt:
    """If PyQt5 QtWidgets cannot be imported, the function must not raise."""

    def test_returns_silently_when_qtwidgets_import_fails(self):
        from ui import assets_helper

        # Force the import inside setup_qt_high_dpi to fail. We do not need
        # to mock the whole PyQt5 module; we patch the symbol lookup.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "PyQt5.QtWidgets" or name.startswith("PyQt5.QtWidgets"):
                raise ImportError("simulated missing PyQt5.QtWidgets")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            # Must not raise.
            assets_helper.setup_qt_high_dpi()


if __name__ == "__main__":
    unittest.main(verbosity=2)
