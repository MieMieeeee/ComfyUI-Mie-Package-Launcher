"""PR #2 共享组件尺寸跟随测试（RED 时 8 failed；GREEN 后 8 passed）。

验证：set_scale -> ThemeManager 通知 listener -> 组件 update_theme() -> 几何/字号跟随。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5 import QtWidgets

from ui_qt.theme_styles import ThemeStyles, ThemeColors
from ui_qt.theme_manager import ThemeManager
from ui_qt.widgets.buttons import ThemeButton, IconButton, PrimaryButton
from ui_qt.widgets.cards import InfoCard
from ui_qt.widgets.custom import CircleAvatar
from ui_qt.components.sidebar import Sidebar


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    yield app


def _px(styles: ThemeStyles, base: int) -> int:
    return styles._px(base)


def _pt(styles: ThemeStyles, base: int) -> int:
    return styles._pt(base)


def _make_tm(dark: bool = True, scale: float = 1.0) -> ThemeManager:
    return ThemeManager(dark=dark, scale=scale)


# ---------------------------------------------------------------------------
# 1. ThemeButton
# ---------------------------------------------------------------------------
def test_theme_button_geo_follows_scale(qapp):
    tm = _make_tm(scale=1.0)
    btn = ThemeButton("\U0001f319", "暗黑", "dark", tm.styles)
    tm.register_listener(btn.update_theme)
    assert btn.width() == _px(tm.styles, 70)
    assert btn.minimumHeight() == _px(tm.styles, 60)

    tm.set_scale(1.25)
    assert btn.width() == _px(tm.styles, 70), \
        f"ThemeButton 1.25x 宽应为 {_px(tm.styles,70)}，实 {btn.width()}"
    assert btn.minimumHeight() == _px(tm.styles, 60)


# ---------------------------------------------------------------------------
# 2. IconButton
# ---------------------------------------------------------------------------
def test_icon_button_geo_follows_scale(qapp):
    tm = _make_tm(scale=1.0)
    btn = IconButton("X", tm.styles, size=24)
    tm.register_listener(btn.update_theme)
    assert btn.size().width() == _px(tm.styles, 24)
    assert btn.size().height() == _px(tm.styles, 24)

    tm.set_scale(1.25)
    assert btn.size().width() == _px(tm.styles, 24), \
        f"IconButton 1.25x 宽应为 {_px(tm.styles,24)}，实 {btn.size().width()}"
    assert btn.size().height() == _px(tm.styles, 24)
    assert "border-radius: 10px;" in btn.styleSheet()


def test_icon_button_has_update_theme(qapp):
    tm = _make_tm(scale=1.0)
    btn = IconButton("X", tm.styles, size=24)
    assert callable(getattr(btn, "update_theme", None)), \
        "IconButton 必须实现 update_theme(theme_styles)"


# ---------------------------------------------------------------------------
# 3. PrimaryButton: 字号（_pt 换算）跟随
# ---------------------------------------------------------------------------
def test_primary_button_font_follows_scale(qapp):
    tm = _make_tm(scale=1.0)
    btn = PrimaryButton("确定", tm.styles)
    tm.register_listener(btn.update_theme)
    s1 = btn.styleSheet()

    tm.set_scale(1.25)
    s2 = btn.styleSheet()
    assert s1 != s2, "PrimaryButton 1x / 1.25x QSS 不应完全相同（字号未跟随）"


# ---------------------------------------------------------------------------
# 4. InfoCard: title label 字号跟随
# ---------------------------------------------------------------------------
def test_infocard_title_font_follows_scale(qapp):
    tm = _make_tm(scale=1.0)
    card = InfoCard("标题", tm.styles)
    tm.register_listener(card.update_theme)
    label_1x = card._title_labels[0].styleSheet()
    tm.set_scale(1.25)
    label_125x = card._title_labels[0].styleSheet()
    expected_pt_125 = _pt(tm.styles, 12)  # 15
    assert f"{expected_pt_125}pt" in label_125x, \
        f"InfoCard title 1.25x QSS 未出现 {expected_pt_125}pt，实：{label_125x!r}"
    assert label_1x != label_125x


# ---------------------------------------------------------------------------
# 5. CircleAvatar: size 跟随；新契约：传 base，内部 _px
# ---------------------------------------------------------------------------
def test_circle_avatar_new_contract_size_follows_scale(qapp):
    tm = _make_tm(scale=1.0)
    av = CircleAvatar(size=80, theme_styles=tm.styles)
    assert av.width() == 80 and av.height() == 80

    resizer = getattr(av, "update_theme", None)
    assert callable(resizer), "CircleAvatar 须实现 update_theme(theme_styles)"

    tm.set_scale(1.25)
    av.update_theme(tm.styles)
    assert av.width() == 100 and av.height() == 100, \
        f"CircleAvatar 1.25x 尺寸应为 100x100，实 {av.width()}x{av.height()}"


# ---------------------------------------------------------------------------
# 6. Sidebar: 展开/折叠宽度 + margin/spacing 跟随
# ---------------------------------------------------------------------------
def test_sidebar_expanded_width_follows_scale(qapp):
    tm = _make_tm(scale=1.0)
    sb = Sidebar(tm.styles)
    tm.register_listener(sb.update_theme)
    assert sb.width() == _px(tm.styles, 240)

    tm.set_scale(1.25)
    assert sb.width() == _px(tm.styles, 240), \
        f"Sidebar 1.25x 展开宽应为 {_px(tm.styles,240)}，实 {sb.width()}"

    sb.set_collapsed(True)
    assert sb.width() == _px(tm.styles, 60), \
        f"Sidebar 1.25x 折叠宽应为 {_px(tm.styles,60)}，实 {sb.width()}"


def test_sidebar_layout_margins_follow_scale(qapp):
    tm = _make_tm(scale=1.0)
    sb = Sidebar(tm.styles)
    tm.register_listener(sb.update_theme)
    tm.set_scale(1.5)
    lo = sb.layout()
    m = lo.contentsMargins()
    target = _px(tm.styles, 15)  # 23
    assert m.left() == target and m.top() == target and m.right() == target and m.bottom() == target, \
        f"Sidebar 1.5x layout margin 应为 {target}，实 ({m.left()},{m.top()},{m.right()},{m.bottom()})"
    assert lo.spacing() == target, \
        f"Sidebar 1.5x layout spacing 应为 {target}，实 {lo.spacing()}"
