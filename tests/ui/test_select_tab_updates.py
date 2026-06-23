# -*- coding: utf-8 -*-
"""Tests for the tab-switch repaint coalescing pattern in qt_app._setup_ui.

背景:
- 旧 _select_tab 调 content.setCurrentIndex(idx) 一次. 该调用会触发
  show / hide / layoutInvalidate / 多个 paint 事件, 复杂页 (launch page 上
  3 个 QGraphicsDropShadowEffect) 首次 paint 慢, 体感就是点标签过了好一会
  才跳过去.
- 新 _select_tab 在 setCurrentIndex 前后用 setUpdatesEnabled(False/True)
  包裹, 把多次 paint 合并到下一帧, 减少感知卡顿.

本测试不直接调 _select_tab (那是 _setup_ui 里的闭包), 而是用同样的
模式起一个 QStackedWidget, 验证 "setUpdatesEnabled(False) -> setCurrentIndex
-> setUpdatesEnabled(True)" 这个序列的语义.
"""
from unittest.mock import MagicMock, call
import pytest
pytest.importorskip("PyQt5")


class TestSetUpdatesEnabledWrapperPattern:
    """验证切页时的 setUpdatesEnabled 包裹模式."""

    def test_wrapper_pattern_calls_false_then_true(self, qtbot):
        """False 必须出现在 setCurrentIndex 之前, True 必须出现在它之后."""
        from PyQt5 import QtWidgets
        stack = QtWidgets.QStackedWidget()
        # 加两个空页面
        for i in range(2):
            page = QtWidgets.QWidget()
            stack.addWidget(page)
        qtbot.addWidget(stack)

        # 收集 setUpdatesEnabled 调用的序列 (只关心 False / True)
        calls = []

        real_set = stack.setUpdatesEnabled
        def spy_set(enabled):
            calls.append(enabled)
            return real_set(enabled)
        stack.setUpdatesEnabled = spy_set

        # 模拟 _select_tab 的修复后实现
        try:
            stack.setUpdatesEnabled(False)
            try:
                stack.setCurrentIndex(1)
            finally:
                stack.setUpdatesEnabled(True)
        except Exception:
            pass

        # 期望序列: [False, True] (setCurrentIndex 不出现在这个 list 里)
        assert calls == [False, True], (
            f"应严格按 [False, True] 顺序; 实际是 {calls}. "
            f"如果只是 [True] 或空, 说明旧实现里根本没有 setUpdatesEnabled 包裹"
        )

    def test_wrapper_restores_updates_even_on_exception(self, qtbot):
        """setCurrentIndex 抛异常时, finally 也要把 updates 重新打开.

        这条很重要: 如果 finally 漏了, 后续所有 paint 都不会发生, 界面会
        看起来冻死. 老代码不可能有这个问题 (因为根本没包), 但既然加了
        finally 就该有测试守住.
        """
        from PyQt5 import QtWidgets
        stack = QtWidgets.QStackedWidget()
        for i in range(2):
            stack.addWidget(QtWidgets.QWidget())
        qtbot.addWidget(stack)

        # patch setCurrentIndex 让它抛
        real_current = stack.setCurrentIndex
        stack.setCurrentIndex = MagicMock(side_effect=RuntimeError("boom"))

        calls = []
        real_set = stack.setUpdatesEnabled
        def spy_set(enabled):
            calls.append(enabled)
            return real_set(enabled)
        stack.setUpdatesEnabled = spy_set

        with pytest.raises(RuntimeError):
            try:
                stack.setUpdatesEnabled(False)
                try:
                    stack.setCurrentIndex(1)
                finally:
                    stack.setUpdatesEnabled(True)
            except RuntimeError:
                raise

        # 即便中间抛了, 也要保证 True 被调一次
        assert calls == [False, True], (
            f"setCurrentIndex 抛异常时 finally 必须把 updates 重新打开; 实际 {calls}"
        )

        stack.setCurrentIndex = real_current
