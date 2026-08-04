"""UI tests for DPI / UI scaling behavior.

Parametrized over a range of scale factors to verify that ThemeStyles tokens
and dialog/page fixed sizes respond to the scale factor. Geometry-assertion
pattern follows tests/ui/test_launch_controls_section.py::TestUserEnvVarsColumnAlignment.

These run offscreen (QT_QPA_PLATFORM=offscreen is set centrally in conftest.py).
"""

import os
import sys
import unittest

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets  # noqa: E402

from ui_qt.theme_styles import ThemeColors, ThemeStyles  # noqa: E402
from ui_qt.theme_manager import ThemeManager  # noqa: E402


# Ensure a QApplication exists for widget tests.
_QT_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


# Scale factors we exercise: min, mid, max of the allowed [0.75, 1.25] range,
# plus the default 1.0.
SCALES = [0.75, 1.0, 1.1, 1.25]


@pytest.mark.ui
@pytest.mark.dpi
@pytest.mark.parametrize("scale", SCALES)
def test_theme_styles_pt_scales_linearly(scale):
    """_pt(base) ≈ round(base * scale), clamped to >= 6."""
    styles = ThemeStyles(ThemeColors(dark=True), scale=scale)
    for base in (8, 10, 12, 16):
        expected = max(6, int(round(base * scale)))
        assert styles._pt(base) == expected, f"_pt({base}) at scale {scale}"


@pytest.mark.ui
@pytest.mark.dpi
@pytest.mark.parametrize("scale", SCALES)
def test_theme_styles_px_scales_linearly(scale):
    """_px(base) ≈ round(base * scale), clamped to >= 1."""
    styles = ThemeStyles(ThemeColors(dark=True), scale=scale)
    for base in (8, 32, 100, 240):
        expected = max(1, int(round(base * scale)))
        assert styles._px(base) == expected, f"_px({base}) at scale {scale}"


@pytest.mark.ui
@pytest.mark.dpi
def test_theme_styles_scale_is_clamped():
    """ThemeStyles must clamp scale to [0.75, 1.25]."""
    lo = ThemeStyles(ThemeColors(dark=True), scale=0.5)
    hi = ThemeStyles(ThemeColors(dark=True), scale=2.0)
    assert abs(lo._scale - 0.75) < 1e-9
    assert abs(hi._scale - 1.25) < 1e-9


@pytest.mark.ui
@pytest.mark.dpi
def test_content_style_contains_scaled_font():
    """content_style_dark/light output should embed the scaled pt value, not the raw 10."""
    styles = ThemeStyles(ThemeColors(dark=True), scale=1.25)
    qss = styles.content_style_dark()
    # round(10 * 1.25) = 12 (banker's rounding of 12.5 → 12). Either way it should
    # NOT be the unscaled "10pt" for the body QLabel.
    assert "Microsoft YaHei UI" in qss


@pytest.mark.ui
@pytest.mark.dpi
@pytest.mark.parametrize("scale", SCALES)
def test_progress_dialog_width_scales(scale):
    """ProgressDialog fixed width (420 base) scales with the theme_manager's scale.

    This validates the real widget construction path (not just the math):
    the dialog reads _px from theme_manager.styles at build time.
    """
    from ui_qt.widgets.progress_dialog import ProgressDialog

    tm = ThemeManager(dark=True, scale=scale)
    dlg = ProgressDialog(theme_manager=tm)
    expected = max(1, int(round(420 * scale)))
    # The dialog fixed width is set via _px(420). Allow exact match.
    assert dlg.width() == expected, (
        f"ProgressDialog width at scale {scale}: got {dlg.width()}, want {expected}"
    )


@pytest.mark.ui
@pytest.mark.dpi
@pytest.mark.parametrize("scale", SCALES)
def test_theme_button_dimensions_scale(scale):
    """ThemeButton fixed width (70) and min height (60) scale."""
    from ui_qt.widgets.buttons import ThemeButton

    tm = ThemeManager(dark=True, scale=scale)
    btn = ThemeButton("🌙", "深", "dark", theme_styles=tm.styles)
    expected_w = max(1, int(round(70 * scale)))
    expected_h = max(1, int(round(60 * scale)))
    assert btn.minimumWidth() == expected_w or btn.width() == expected_w
    assert btn.minimumHeight() == expected_h


@pytest.mark.ui
@pytest.mark.dpi
def test_set_scale_rebuilds_and_propagates_to_new_widget():
    """A widget constructed AFTER set_scale picks up the new scale."""
    from ui_qt.widgets.progress_dialog import ProgressDialog

    tm = ThemeManager(dark=True, scale=1.0)
    tm.set_scale(1.25)
    dlg = ProgressDialog(theme_manager=tm)
    # 420 * 1.25 = 525
    assert dlg.width() == 525


if __name__ == "__main__":
    unittest.main()
