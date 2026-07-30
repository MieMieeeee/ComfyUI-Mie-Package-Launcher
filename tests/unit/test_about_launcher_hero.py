"""Tests for 关于启动器页面 HeroCard 布局 (回归: 兔子图标与描述文字重叠).

原 bug: HeroCard 里标题(40px) + 兔子图标(180×180 Fixed) + 描述文字垂直排列,
窗口较小时 QVBoxLayout 无法缩小 Fixed 控件, 兔子和描述被挤得重叠.

修复: 兔子图标保持 Fixed 完整 180×180 (不变形不截断), 靠 HeroCard.setMinimumHeight
撑出足够空间, 让标题/兔子/描述都能正常排列不重叠.

(中间曾用 Preferred + setMaximumSize, 但那样会让 QLabel 缩小裁剪 pixmap 截断兔子,
 已弃用 — 兔子必须完整.)
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets, QtCore

from ui_qt.theme_manager import ThemeManager
from ui_qt.pages.about_launcher_page import AboutLauncherPage
from ui_qt.widgets.cards import HeroCard


class _FakeApp:
    """最小 app, 仅供 AboutLauncherPage 构造 (不触发版本检查)."""
    config = {}
    base_root = None


class TestHeroCardNoOverlap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _make_page(self, dark=True):
        return AboutLauncherPage(app=_FakeApp(), theme_manager=ThemeManager(dark=dark))

    def _find_hero(self, page):
        for w in page.findChildren(QtWidgets.QWidget):
            if isinstance(w, HeroCard):
                return w
        return None

    def _find_logo(self, hero):
        for lbl in hero.findChildren(QtWidgets.QLabel):
            if lbl.pixmap() is not None and not lbl.pixmap().isNull():
                return lbl
        return None

    def test_hero_card_has_minimum_height(self):
        """HeroCard 设了足够大的 minimumHeight, 保证内容留足余量不挤 (不重叠).

        原 bug: minimumHeight 刚好塞下, offscreen 算 gap 仅 3px, 实际 Windows +
        DPI 缩放下字体度量略大, 3px 变负 -> 兔子和描述重叠. 这里要求留足余量 (>=400).
        """
        page = self._make_page()
        hero = self._find_hero(page)
        self.assertIsNotNone(hero)
        self.assertGreaterEqual(hero.minimumHeight(), 400,
                                "HeroCard 应设足够大的最小高度留足余量 (>=400) 避免重叠")

    def test_title_font_size_is_tuned_down(self):
        """标题字号调小 (默认 40 太大占太多视觉权重, "ComfyUI 启动器" 用 26)."""
        import re
        qt_app_path = Path(__file__).resolve().parents[2] / "ui_qt" / "pages" / "about_launcher_page.py"
        src = qt_app_path.read_text(encoding="utf-8")
        # HeroCard 构造传了 title_font_size, 且值 < 40
        m = re.search(r"HeroCard\([^)]*title_font_size=(\d+)", src)
        self.assertIsNotNone(m, "about_launcher 的 HeroCard 应传 title_font_size")
        size = int(m.group(1))
        self.assertLessEqual(size, 30, "标题字号应调小 (<=30), 40 太大")

    def test_description_margins_are_symmetric(self):
        """描述容器 margins 对称, 不再收窄行宽 (原 40/30 非对称把文字挤窄)."""
        qt_app_path = Path(__file__).resolve().parents[2] / "ui_qt" / "pages" / "about_launcher_page.py"
        src = qt_app_path.read_text(encoding="utf-8")
        # content_layout.setContentsMargins 应为对称小值 (左右相等)
        import re
        m = re.search(r"content_layout\.setContentsMargins\((\d+),\s*0,\s*(\d+),\s*0\)", src)
        self.assertIsNotNone(m, "应找到 content_layout.setContentsMargins")
        left, right = int(m.group(1)), int(m.group(2))
        self.assertEqual(left, right, "描述 margins 左右应对称 (不再 40/30 非对称)")
        self.assertLessEqual(left, 20, "描述 margins 应是小值, 不收窄行宽")

    def test_logo_keeps_fixed_full_size(self):
        """兔子图标保持 Fixed size policy + 完整 180×180 (不缩小不截断).

        原修复曾把 sizePolicy 改 Preferred + setMaximumSize, 导致 QLabel 缩小时 pixmap
        被裁剪截断. 正确做法: 兔子 Fixed 完整不变形, 靠 HeroCard.minimumHeight 撑出空间
        避免重叠.
        """
        page = self._make_page()
        hero = self._find_hero(page)
        logo = self._find_logo(hero)
        self.assertIsNotNone(logo, "应加载到兔子图标")
        self.assertEqual(logo.sizePolicy().verticalPolicy(), QtWidgets.QSizePolicy.Fixed,
                         "兔子图标应是 Fixed sizePolicy (完整不变形, 不被压缩截断)")
        # Fixed 完整尺寸 180×180 (不被截断)
        self.assertEqual(logo.width(), 180)
        self.assertEqual(logo.height(), 180)

    def test_logo_and_description_do_not_overlap_at_small_height(self):
        """窗口/卡片高度较小时, 兔子图标和描述文字不应重叠 (核心回归).

        用全局坐标 (mapToGlobal) 比较 logo 底边和描述顶边, 避免内层 widget 相对坐标误导.
        """
        page = self._make_page()
        hero = self._find_hero(page)
        logo = self._find_logo(hero)
        # 描述: HeroCard 内带文字且非标题的 QLabel, 取全局坐标最低的那个 (描述在标题下方)
        desc_candidates = [
            lbl for lbl in hero.findChildren(QtWidgets.QLabel)
            if lbl.pixmap() is None and lbl.text() and "启动器" not in lbl.text()
        ]
        self.assertIsNotNone(logo)
        self.assertTrue(desc_candidates, "应找到描述文字 label")
        desc = desc_candidates[-1]
        for h in (300, 340):
            hero.resize(400, h)
            hero.show()
            self.app_qt.processEvents()
            logo_bottom = logo.mapTo(hero, QtCore.QPoint(0, logo.height())).y()
            desc_top = desc.mapTo(hero, QtCore.QPoint(0, 0)).y()
            self.assertLess(
                logo_bottom, desc_top,
                "h=%d 时兔子底边(%d) 应在描述顶边(%d) 之上, 不重叠" % (h, logo_bottom, desc_top),
            )
            hero.hide()


if __name__ == "__main__":
    unittest.main()
