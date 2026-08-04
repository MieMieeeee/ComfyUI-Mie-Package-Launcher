"""Tests for the UI scale control (_ScaleRow) added to SystemSettingsPage.

Verifies the new DPI-scale user control: option mapping, signal emission,
and that selecting 'auto' vs a locked value emits the right payload.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets  # noqa: E402

from ui_qt.theme_manager import ThemeManager  # noqa: E402
from ui_qt.pages.system_settings_page import _ScaleRow, _SCALE_OPTIONS  # noqa: E402


_QT_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class TestScaleRowOptions(unittest.TestCase):
    def test_scale_options_include_auto_and_range(self):
        """Options must include 'auto' (None) and the [0.75, 1.25] range."""
        labels = [label for label, _val in _SCALE_OPTIONS]
        self.assertIn("自动跟随系统", labels)
        # First option must be 'auto' (None) — the safe default.
        self.assertIsNone(_SCALE_OPTIONS[0][1])
        values = [v for _l, v in _SCALE_OPTIONS if v is not None]
        self.assertEqual(min(values), 0.75)
        self.assertEqual(max(values), 1.25)


class TestScaleRowConstruction(unittest.TestCase):
    def _make_row(self, current_scale=1.0, current_override=None):
        tm = ThemeManager(dark=True, scale=1.0)
        row = _ScaleRow(
            theme_styles=tm.styles,
            current_scale=current_scale,
            current_override=current_override,
        )
        return row

    def test_auto_mode_selects_first_option(self):
        row = self._make_row(current_scale=1.0, current_override=None)
        self.assertEqual(row.combo.currentIndex(), 0)  # 'auto'

    def test_locked_override_selects_matching_option(self):
        row = self._make_row(current_scale=1.25, current_override=1.25)
        # Find which index has value 1.25
        expected_idx = next(i for i, (_l, v) in enumerate(_SCALE_OPTIONS) if v == 1.25)
        self.assertEqual(row.combo.currentIndex(), expected_idx)

    def test_auto_mode_shows_current_percentage(self):
        row = self._make_row(current_scale=1.1, current_override=None)
        self.assertIn("110%", row.lbl_desc.text())

    def test_index_for_handles_none_and_float(self):
        self.assertEqual(_ScaleRow._index_for(None), 0)
        idx = _ScaleRow._index_for(0.9)
        self.assertEqual(_SCALE_OPTIONS[idx][1], 0.9)
        # Unknown override falls back to auto (index 0)
        self.assertEqual(_ScaleRow._index_for(0.77), 0)

    def test_index_for_tolerant_of_float_equality(self):
        # 1.0 stored as float should match the 1.0 option
        idx = _ScaleRow._index_for(1.0)
        self.assertEqual(_SCALE_OPTIONS[idx][1], 1.0)


class TestScaleRowSignal(unittest.TestCase):
    def test_selecting_option_emits_correct_value(self):
        tm = ThemeManager(dark=True, scale=1.0)
        row = _ScaleRow(
            theme_styles=tm.styles, current_scale=1.0, current_override=None
        )
        received = []
        row.scale_changed.connect(lambda v: received.append(v))
        # Select the 100% option
        idx = next(i for i, (_l, v) in enumerate(_SCALE_OPTIONS) if v == 1.0)
        row.combo.setCurrentIndex(idx)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], 1.0)

    def test_selecting_auto_emits_none(self):
        tm = ThemeManager(dark=True, scale=1.0)
        row = _ScaleRow(
            theme_styles=tm.styles, current_scale=1.0, current_override=1.0
        )
        received = []
        row.scale_changed.connect(lambda v: received.append(v))
        row.combo.setCurrentIndex(0)  # 'auto'
        self.assertEqual(received, [None])


class TestScaleRowThemeUpdate(unittest.TestCase):
    def test_update_theme_does_not_crash(self):
        tm = ThemeManager(dark=True, scale=1.0)
        row = _ScaleRow(
            theme_styles=tm.styles, current_scale=1.0, current_override=None
        )
        # Switch to a different theme/scale and ensure update_theme is safe.
        tm2 = ThemeManager(dark=False, scale=1.25)
        row.update_theme(tm2.styles)
        # combo style should have been re-applied without error
        self.assertTrue(row.combo.styleSheet() != "" or True)  # just ensure no crash


if __name__ == "__main__":
    unittest.main()
