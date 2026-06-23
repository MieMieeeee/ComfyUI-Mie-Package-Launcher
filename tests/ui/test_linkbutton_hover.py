# -*- coding: utf-8 -*-
"""Tests for LinkButton hover effect performance.

背景:
- 旧实现里 LinkButton.enterEvent / leaveEvent 每次都 new 一个
  QGraphicsDropShadowEffect 并 setGraphicsEffect(), 鼠标移开又
  setGraphicsEffect(None) 把旧 effect 干掉. 这相当于每次 hover 都
  触发一次完整重绘 + 内存分配 + 释放, 是界面卡顿的最大单一原因.
- 新实现应该在 __init__ 阶段创建一个 effect, 通过 setEnabled(True/False)
  复用同一份 effect 实例.

这里的测试不依赖 QApplication 实际渲染, 只验证 effect 实例的复用语义.
"""
from unittest.mock import MagicMock, patch
import pytest

# Skip the whole module if PyQt5 can't even import (no GUI on Linux CI etc.)
pytest.importorskip("PyQt5")


@pytest.fixture
def theme_styles():
    """A bare ThemeStyles stub.  We only need .c.dark for the effect's alpha."""
    from ui_qt.theme_styles import ThemeStyles, ThemeColors
    return ThemeStyles(ThemeColors(dark=True))


def _make_linkbutton(theme_styles, qtbot):
    from ui_qt.widgets.buttons import LinkButton
    btn = LinkButton("hi", theme_styles)
    qtbot.addWidget(btn)
    return btn


class TestLinkButtonHoverEffectIsCached:
    """The hover effect must be created once and reused, not rebuilt per hover."""

    def test_init_creates_hover_effect(self, theme_styles, qtbot):
        """__init__ 阶段就应该有一个 _hover_effect 实例挂上, 不在 enterEvent 里临时建."""
        btn = _make_linkbutton(theme_styles, qtbot)
        assert btn.graphicsEffect() is not None, (
            "LinkButton.__init__ 应当立刻挂上 hover effect, 避免 enterEvent 临时构造"
        )
        # effect 默认应当是禁用状态 (鼠标还没进去)
        assert btn.graphicsEffect().isEnabled() is False

    def test_hover_does_not_recreate_effect(self, theme_styles, qtbot):
        """反复 enter / leave 不应产生新的 QGraphicsDropShadowEffect 实例."""
        from PyQt5 import QtCore, QtGui
        btn = _make_linkbutton(theme_styles, qtbot)
        before = btn.graphicsEffect()
        assert before is not None, (
            "hover 之前就该有一个 effect 实例, 否则下面的 before/after 比对无意义"
        )
        # 5 次 enter / leave
        for _ in range(5):
            btn.enterEvent(QtGui.QEnterEvent(QtCore.QPointF(0, 0), QtCore.QPointF(0, 0), QtCore.QPointF(0, 0)))
            btn.leaveEvent(QtCore.QEvent(QtCore.QEvent.Leave))
        after = btn.graphicsEffect()
        assert before is after, (
            "enter/leave 不应替换 effect 实例; 之前的实现每次都 new 一个,"
            "setGraphicsEffect(None) 再 setGraphicsEffect(new), 触发全量重绘."
        )

    def test_enter_enables_and_leave_disables(self, theme_styles, qtbot):
        """mouse enter -> effect enabled, leave -> effect disabled."""
        from PyQt5 import QtCore, QtGui
        btn = _make_linkbutton(theme_styles, qtbot)
        effect = btn.graphicsEffect()
        assert effect.isEnabled() is False
        btn.enterEvent(QtGui.QEnterEvent(QtCore.QPointF(0, 0), QtCore.QPointF(0, 0), QtCore.QPointF(0, 0)))
        assert effect.isEnabled() is True
        btn.leaveEvent(QtCore.QEvent(QtCore.QEvent.Leave))
        assert effect.isEnabled() is False

    def test_constructor_does_not_call_setGraphicsEffect_none(self, theme_styles, qtbot):
        """__init__ 不应在最后一步 setGraphicsEffect(None) 把刚建好的 effect 又拆掉."""
        from PyQt5 import QtWidgets
        from ui_qt.widgets.buttons import LinkButton
        with patch.object(QtWidgets.QWidget, "setGraphicsEffect") as mocked:
            btn = LinkButton("hi", theme_styles)
            # 找出所有传入 None 的调用
            none_calls = [c for c in mocked.call_args_list if c.args and c.args[0] is None]
            assert not none_calls, (
                f"__init__ 不应再 setGraphicsEffect(None); 找了 {len(none_calls)} 次"
            )
            qtbot.addWidget(btn)
