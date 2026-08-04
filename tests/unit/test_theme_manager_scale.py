"""Unit tests for ThemeManager.set_scale (DPI scaling mechanism).

Requires a QApplication; sets QT_QPA_PLATFORM=offscreen before importing PyQt5,
following the pattern in tests/unit/test_format_update_summary.py.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestThemeManagerScale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5 import QtWidgets

        cls.QtWidgets = QtWidgets
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def _import(self):
        from ui_qt.theme_manager import ThemeManager

        return ThemeManager

    def test_construct_with_scale_propagates_to_styles(self):
        ThemeManager = self._import()
        tm = ThemeManager(dark=True, scale=1.25)
        self.assertAlmostEqual(tm.styles._scale, 1.25, places=6)
        # _pt/_px should reflect the scale. Note Python uses banker's rounding
        # (round-half-to-even), so round(10 * 1.25) = round(12.5) = 12, not 13.
        self.assertEqual(tm.styles._pt(10), 12)
        self.assertEqual(tm.styles._pt(8), 10)  # round(10.0) = 10
        self.assertEqual(tm.styles._px(100), 125)

    def test_construct_clamps_scale(self):
        ThemeManager = self._import()
        tm_lo = ThemeManager(dark=True, scale=0.5)
        self.assertAlmostEqual(tm_lo._scale, 0.75, places=6)
        tm_hi = ThemeManager(dark=True, scale=2.0)
        self.assertAlmostEqual(tm_hi._scale, 1.25, places=6)

    def test_set_scale_rebuilds_styles(self):
        ThemeManager = self._import()
        tm = ThemeManager(dark=True, scale=1.0)
        old_styles = tm.styles
        tm.set_scale(1.25)
        self.assertIsNot(tm.styles, old_styles)
        self.assertAlmostEqual(tm._scale, 1.25, places=6)
        self.assertEqual(tm.styles._pt(10), 12)  # banker's: round(12.5)=12
        self.assertEqual(tm.styles._px(100), 125)

    def test_set_scale_notifies_listeners(self):
        ThemeManager = self._import()
        tm = ThemeManager(dark=True, scale=1.0)
        received = []
        tm.register_listener(lambda styles: received.append(styles))
        tm.set_scale(1.1)
        self.assertEqual(len(received), 1)
        self.assertIs(received[0], tm.styles)
        self.assertAlmostEqual(received[0]._scale, 1.1, places=6)

    def test_set_scale_no_change_does_not_notify(self):
        """防抖第一道：无变化时不回调监听器。"""
        ThemeManager = self._import()
        tm = ThemeManager(dark=True, scale=1.0)
        received = []
        tm.register_listener(lambda styles: received.append(styles))
        tm.set_scale(1.0)  # identical
        tm.set_scale(1.0001)  # within 1e-3 tolerance
        self.assertEqual(len(received), 0)
        self.assertAlmostEqual(tm._scale, 1.0, places=6)

    def test_set_scale_clamps_and_snaps_within_tolerance(self):
        ThemeManager = self._import()
        tm = ThemeManager(dark=True, scale=1.0)
        # 2.0 → clamped to 1.25 (diff > 1e-3, so should apply)
        received = []
        tm.register_listener(lambda styles: received.append(styles))
        tm.set_scale(2.0)
        self.assertAlmostEqual(tm._scale, 1.25, places=6)
        self.assertEqual(len(received), 1)

    def test_set_scale_invalid_value_noop(self):
        ThemeManager = self._import()
        tm = ThemeManager(dark=True, scale=1.0)
        tm.set_scale("not a number")
        self.assertAlmostEqual(tm._scale, 1.0, places=6)

    def test_set_scale_preserves_dark_state(self):
        """Scale change must not flip the theme."""
        ThemeManager = self._import()
        tm = ThemeManager(dark=True, scale=1.0)
        tm.set_scale(1.1)
        self.assertTrue(tm.is_dark)
        self.assertTrue(tm.colors.dark)
        self.assertTrue(tm.styles.c.dark)


if __name__ == "__main__":
    unittest.main()
