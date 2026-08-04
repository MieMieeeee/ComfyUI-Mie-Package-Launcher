"""Unit tests for core.ui_scaling (pure DPI math, no Qt).

Pattern follows tests/unit/test_app_state.py: plain unittest.TestCase, lazy
imports, no QApplication needed.
"""

import math
import unittest


class TestComputeScaleFromDpi(unittest.TestCase):
    def _import(self):
        from core.ui_scaling import compute_scale_from_dpi

        return compute_scale_from_dpi

    def test_module_importable(self):
        from core import ui_scaling  # noqa: F401

    def test_default_base_dpi_is_one(self):
        compute = self._import()
        self.assertAlmostEqual(compute(96.0), 1.0, places=6)

    def test_120_dpi_caps_at_max(self):
        # 120/96 = 1.25 exactly — boundary, should be 1.25 (not snapped away).
        compute = self._import()
        self.assertAlmostEqual(compute(120.0), 1.25, places=6)

    def test_144_dpi_clamps_to_max(self):
        # 144/96 = 1.5 → clamp to 1.25.
        compute = self._import()
        self.assertAlmostEqual(compute(144.0), 1.25, places=6)

    def test_200_dpi_clamps_to_max(self):
        compute = self._import()
        self.assertAlmostEqual(compute(200.0), 1.25, places=6)

    def test_72_dpi_floors_at_min(self):
        # 72/96 = 0.75 exactly — boundary.
        compute = self._import()
        self.assertAlmostEqual(compute(72.0), 0.75, places=6)

    def test_60_dpi_clamps_to_min(self):
        # 60/96 = 0.625 → clamp to 0.75.
        compute = self._import()
        self.assertAlmostEqual(compute(60.0), 0.75, places=6)

    def test_user_override_wins(self):
        compute = self._import()
        # Even at 200 DPI, an explicit override of 1.0 should win.
        self.assertAlmostEqual(compute(200.0, user_override=1.0), 1.0, places=6)

    def test_user_override_is_clamped(self):
        compute = self._import()
        # Override out of range still clamped.
        self.assertAlmostEqual(compute(96.0, user_override=2.0), 1.25, places=6)
        self.assertAlmostEqual(compute(96.0, user_override=0.5), 0.75, places=6)

    def test_user_override_is_snapped(self):
        # Override 1.03 → snap to 0.05 step → 1.05.
        compute = self._import()
        self.assertAlmostEqual(compute(96.0, user_override=1.03), 1.05, places=6)

    def test_invalid_dpi_falls_back_to_default(self):
        compute = self._import()
        self.assertAlmostEqual(compute("not a number"), 1.0, places=6)

    def test_invalid_override_falls_back_to_dpi(self):
        compute = self._import()
        # Invalid override → ignored → use DPI ratio (120/96=1.25).
        self.assertAlmostEqual(compute(120.0, user_override="bad"), 1.25, places=6)

    def test_invalid_base_dpi_falls_back_to_default(self):
        compute = self._import()
        self.assertAlmostEqual(compute(96.0, base_dpi=0), 1.0, places=6)
        self.assertAlmostEqual(compute(96.0, base_dpi=-1), 1.0, places=6)

    def test_snap_disabled(self):
        compute = self._import()
        # 110/96 ≈ 1.1458 → with snap it'd round to 1.15; without snap it stays raw then clamps.
        raw = 110.0 / 96.0
        self.assertAlmostEqual(compute(110.0, snap=False), min(max(raw, 0.75), 1.25), places=6)

    def test_custom_min_max(self):
        compute = self._import()
        self.assertAlmostEqual(
            compute(144.0, min_scale=0.5, max_scale=2.0, snap=False), 1.5, places=6
        )


class TestSnapScale(unittest.TestCase):
    def _import(self):
        from core.ui_scaling import snap_scale

        return snap_scale

    def test_exact_step_unchanged(self):
        snap = self._import()
        self.assertAlmostEqual(snap(1.0), 1.0, places=6)
        self.assertAlmostEqual(snap(1.25), 1.25, places=6)

    def test_rounds_up(self):
        snap = self._import()
        # 1.13 → nearest 0.05 is 1.15? 1.13/0.05=22.6 → round=23 → 1.15.
        self.assertAlmostEqual(snap(1.13), 1.15, places=6)

    def test_rounds_down(self):
        snap = self._import()
        # 1.12 → 22.4 → round=22 → 1.10.
        self.assertAlmostEqual(snap(1.12), 1.10, places=6)

    def test_no_floating_point_tail(self):
        snap = self._import()
        # The classic 0.8500000000001 regression.
        result = snap(0.852)
        self.assertEqual(str(result), "0.85")

    def test_zero_step_returns_raw(self):
        snap = self._import()
        self.assertAlmostEqual(snap(1.123, step=0), 1.123, places=6)


class TestResolveUiScale(unittest.TestCase):
    """Integration between config dict + DPI math."""

    def _import(self):
        from core.ui_scaling import resolve_ui_scale

        return resolve_ui_scale

    def test_none_config_uses_dpi(self):
        resolve = self._import()
        self.assertAlmostEqual(resolve(None, 96.0), 1.0, places=6)
        self.assertAlmostEqual(resolve(None, 120.0), 1.25, places=6)

    def test_missing_ui_scale_uses_dpi(self):
        resolve = self._import()
        config = {"ui_settings": {}}
        self.assertAlmostEqual(resolve(config, 96.0), 1.0, places=6)

    def test_explicit_ui_scale_overrides_dpi(self):
        resolve = self._import()
        config = {"ui_settings": {"ui_scale": 1.1}}
        self.assertAlmostEqual(resolve(config, 200.0), 1.1, places=6)

    def test_null_ui_scale_means_auto(self):
        resolve = self._import()
        config = {"ui_settings": {"ui_scale": None}}
        self.assertAlmostEqual(resolve(config, 120.0), 1.25, places=6)

    def test_empty_string_ui_scale_means_auto(self):
        resolve = self._import()
        config = {"ui_settings": {"ui_scale": "  "}}
        self.assertAlmostEqual(resolve(config, 96.0), 1.0, places=6)

    def test_numeric_string_ui_scale_parsed(self):
        resolve = self._import()
        config = {"ui_settings": {"ui_scale": "1.1"}}
        self.assertAlmostEqual(resolve(config, 96.0), 1.1, places=6)

    def test_garbage_string_ui_scale_means_auto(self):
        resolve = self._import()
        config = {"ui_settings": {"ui_scale": "garbage"}}
        self.assertAlmostEqual(resolve(config, 120.0), 1.25, places=6)

    def test_clamps_extreme_config_value(self):
        resolve = self._import()
        config = {"ui_settings": {"ui_scale": 5.0}}
        self.assertAlmostEqual(resolve(config, 96.0), 1.25, places=6)


if __name__ == "__main__":
    unittest.main()
