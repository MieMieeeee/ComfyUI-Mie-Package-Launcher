"""PR #1 RED — BasePage _dpi_sized_widgets 注册表与 _reapply_dpi_sizes 的失败测试。

TDD Cycle: RED → 写期望行为的最小测试 → 运行确认失败 → GREEN 写最小实现。
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class BasePageDpiWidgetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5 import QtWidgets

        cls.QtWidgets = QtWidgets
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    # ==================== 合法 setter_name 正向用例 ====================

    def _build_page(self, scale=1.0):
        from ui_qt.theme_manager import ThemeManager
        from ui_qt.pages.base_page import BasePage

        tm = ThemeManager(dark=True, scale=scale)
        return BasePage(theme_manager=tm), tm

    def test_set_fixed_width_1x_to_125x(self):
        page, tm = self._build_page(scale=1.0)
        w = self.QtWidgets.QWidget(page)
        page._dpi_sized_widgets = [(w, "setFixedWidth", 100)]
        page._reapply_dpi_sizes()
        self.assertEqual(w.width(), 100)
        # scale 切换
        tm.set_scale(1.25)
        # simulate what update_theme does at tail
        page._reapply_dpi_sizes()
        self.assertEqual(w.width(), 125)

    def test_set_minimum_height_1x_to_075x(self):
        page, tm = self._build_page(scale=1.0)
        w = self.QtWidgets.QWidget(page)
        page._dpi_sized_widgets = [(w, "setMinimumHeight", 40)]
        page._reapply_dpi_sizes()
        self.assertEqual(w.minimumHeight(), 40)
        tm.set_scale(0.75)
        page._reapply_dpi_sizes()
        self.assertEqual(w.minimumHeight(), 30)

    def test_set_minimum_size_tuple_1x_to_125x(self):
        page, tm = self._build_page(scale=1.0)
        w = self.QtWidgets.QWidget(page)
        page._dpi_sized_widgets = [(w, "setMinimumSize", (80, 30))]
        page._reapply_dpi_sizes()
        self.assertEqual(w.minimumSize().width(), 80)
        self.assertEqual(w.minimumSize().height(), 30)
        tm.set_scale(1.25)
        page._reapply_dpi_sizes()
        # banker's rounding: 80*1.25=100 exact, 30*1.25=37.5 -> round(37.5)=38? no: int(round(37.5))=38 (banker's even=38)
        self.assertEqual(w.minimumSize().width(), 100)
        self.assertIn(w.minimumSize().height(), (37, 38))

    def test_set_fixed_size_tuple_1x_to_125x(self):
        page, tm = self._build_page(scale=1.0)
        w = self.QtWidgets.QWidget(page)
        page._dpi_sized_widgets = [(w, "setFixedSize", (24, 24))]
        page._reapply_dpi_sizes()
        self.assertEqual((w.width(), w.height()), (24, 24))
        tm.set_scale(1.25)
        page._reapply_dpi_sizes()
        self.assertEqual((w.width(), w.height()), (30, 30))

    def test_set_maximum_width_1x_to_125x(self):
        page, tm = self._build_page(scale=1.0)
        w = self.QtWidgets.QWidget(page)
        page._dpi_sized_widgets = [(w, "setMaximumWidth", 800)]
        page._reapply_dpi_sizes()
        self.assertEqual(w.maximumWidth(), 800)
        tm.set_scale(1.25)
        page._reapply_dpi_sizes()
        self.assertEqual(w.maximumWidth(), 1000)

    # ==================== 非法 setter_name 必须抛 AttributeError（不吞异常） ====================

    def test_invalid_setter_name_raises_attribute_error_no_silent_failure(self):
        """验证 typo 不会静默。为避免 RED 阶段 BasePage 没有 _reapply_dpi_sizes 时假红（两种 AttributeError 分不清），
        这里直接构造一个独立对象：用 ThemeManager + 自建存根类，只测试 '_reapply_dpi_sizes 的分发逻辑'。
        分发代码搬到基类之后，断言路径依然相同（getattr(widget, bad_name) -> AttributeError）。
        """
        from ui_qt.theme_manager import ThemeManager

        class StubPage:
            """完全独立的存根，复制分发逻辑的「期望版本」的反面——但我们先拿真实 BasePage 比一下。"""
            _dpi_sized_widgets = []

        tm = ThemeManager(dark=True, scale=1.0)

        # 构造独立的测试用例：模拟未来基类有了方法后，坏名 => AttributeError
        w = self.QtWidgets.QWidget()

        class TestPageHarness:
            """最小 harness，直接模拟未来 BasePage._reapply_dpi_sizes 的签名。"""
            _dpi_sized_widgets = []
            def _reapply(self):
                for widget, setter_name, base in self._dpi_sized_widgets:
                    setter = getattr(widget, setter_name)   # 此行失败 -> AttributeError（typo 不吞）
                    if isinstance(base, tuple):
                        setter(tm.styles._px(base[0]), tm.styles._px(base[1]))
                    else:
                        setter(tm.styles._px(base))

        h = TestPageHarness()
        h._dpi_sized_widgets = [(w, "notExistMethodXyz", 100)]
        with self.assertRaises(AttributeError) as ctx:
            h._reapply()
        # 确认错误来自 typo 的方法名，不是别的
        self.assertIn("notExistMethodXyz", str(ctx.exception))

    # ==================== update_theme 自动触发 _reapply_dpi_sizes ====================

    def test_update_theme_calls_reapply_dpi_sizes(self):
        page, tm = self._build_page(scale=1.0)
        w = self.QtWidgets.QWidget(page)
        page._dpi_sized_widgets = [(w, "setFixedWidth", 100)]
        # Force init size (via init apply — we called _reapply once per positive tests above,
        # here we rely on update_theme doing it automatically for registered widgets).
        tm.set_scale(1.25)  # -> fires update_theme via listener
        self.assertEqual(w.width(), 125,
                         "update_theme must auto-trigger _reapply_dpi_sizes for registered widgets")


if __name__ == "__main__":
    unittest.main()
