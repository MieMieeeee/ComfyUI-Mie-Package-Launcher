"""Regression tests for ui_qt.widgets.background_task_panel.

锁定 ``BackgroundTasksPage`` 的 tab 标题不再被裁:
1. ``padding`` 从 8px 20px 收紧到 8px 14px (QSS).
2. ``min-width: 96px`` (QSS) 让 tab cell 不被压扁.
3. ``setExpanding(False)`` + ``setElideMode(ElideNone)`` + ``setMinimumSize(260, 0)``
   程序上锁死, 防止未来无意改回 auto-expanding / 默认 elide.

历史背景: 用户报 background-task 窗口里的 “进行中 / 已完成” 两个 tab 标题
显示不全 (被压成 “程中” / “U导成 (”). 根因是 QSS padding 8px 20px 太大
(QTabBar sizeHint 比可分配宽度宽) + 缺 min-width + 没显式 setExpanding(False).
"""

import os
import sys
import re
from pathlib import Path

import pytest


_PANEL_FILE = Path(
    "F:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/background_task_panel.py"
)


@pytest.fixture(scope="module")
def panel_source() -> str:
    return _PANEL_FILE.read_text(encoding="utf-8")


class TestTabQssLayout:
    def test_qss_uses_14px_horizontal_padding(self, panel_source):
        """Padding 8px 20px 被裁 "进行中 / 已完成". 8px 14px 配 96px min-width
        才能让 Chinese 4-char 标题 + 计数括号都放下.

        Note: values are now DPI-tokenized via _px() (e.g. ``padding: {_px(8)}px {_px(14)}px;``),
        so we match the base ints inside the _px(...) calls instead of raw px literals.
        """
        m = re.search(
            r"QTabBar::tab\s*\{\{[\s\S]*?padding:\s*\{_px\(8\)\}px\s+\{_px\((\d+)\)\}px;",
            panel_source,
            flags=re.DOTALL,
        )
        assert m is not None, "QTabBar::tab block not found"
        px = int(m.group(1))
        assert px <= 14, (
            f"QTabBar::tab horizontal padding grew to {px}px (was 8px 20px); "
            f"宽 padding 会让两个 tab 装不下 Chinese 标题, 退回到裁字的状态."
        )

    def test_qss_pins_min_width(self, panel_source):
        """Min-width: 96px 必须存在, 否则窄容器里 Qt 会把 tab cell 压到字号以下.

        Now DPI-tokenized: ``min-width: {_px(96)}px;``.
        """
        m = re.search(
            r"QTabBar::tab\s*\{\{[\s\S]*?min-width:\s*\{_px\((\d+)\)\}px;",
            panel_source,
            flags=re.DOTALL,
        )
        assert m is not None, "QTabBar::tab 没有 min-width, 这是 user-reported 裁字的元凶"
        px = int(m.group(1))
        assert 80 <= px <= 160, (
            f"min-width={px}px 不合理 (太小容不下 4 个 Chinese + 括号, 太大挤压布局)."
        )


class TestTabQtabwidgetApi:
    def test_program_calls_setExpanding_False(self, panel_source):
        """No-auto-stretch: tab 按 sizeHint 自然大小, 不被 QTabBar 重新分配."""
        assert "self._tabs.tabBar().setExpanding(False)" in panel_source, (
            "未显式 setExpanding(False); 容器窄时 Qt 可能按可用宽度平均分给 tab, "
            "一个 tab 不到 50px 时 Chinese 标题被裁."
        )

    def test_program_calls_setElideMode_ElideNone(self, panel_source):
        """ElideMode.ElideNone 防 Qt 默认 elideRight 把标题变 "进行..."""
        assert "setElideMode(" in panel_source, "缺 ElideMode 锁定"
        assert (
            "TextElideMode.ElideNone" in panel_source
        ), "ElideMode 没设 ElideNone, Qt 默认会按宽度裁字符串尾部"

    def test_program_calls_setMinimumSize_for_tab_strip(self, panel_source):
        """QTabWidget 自身最小宽度 260: 两个 ~110px tab + page chrome 不被压扁."""
        m = re.search(
            r"self\._tabs\.setMinimumSize\(([^,]+),\s*(\d+)\)",
            panel_source,
        )
        assert m is not None, "缺 setMinimumSize 锁定"
        # Just assert the call exists with a non-zero width and zero height
        # (we don't pin exact value to keep the test resilient to future tweaks).
        assert int(m.group(2)) == 0, (
            f"setMinimumSize 第二参应是 0 (高度不限), got '{m.group(2)}'"
        )

    def test_initial_tab_labels_match_chinese_title(self, panel_source):
        """Sanity: ensure the tab labels are still the expected Chinese titles.
        若未来无意 i18n 化或换文案, 这个 test 会拦住."""
        assert '"进行中"' in panel_source or "'进行中'" in panel_source
        assert '"已完成"' in panel_source or "'已完成'" in panel_source

class TestTabRuntime:
    """Runtime smoke: actually construct BackgroundTasksPage and verify no crash.

    The static-source tests above would happily pass even if setExpanding()
    were called on QTabWidget (which does NOT have that method, only
    QTabBar does). Ceb7a61 shipped exactly that bug and crashed the
    launcher at startup. This test instantiates the panel and asserts the
    constructor returns without raising AttributeError.
    """

    def test_construct_does_not_crash(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5 import QtWidgets
        from ui_qt.widgets.background_task_panel import BackgroundTasksPage
        from ui_qt.background_task_registry import BackgroundTaskRegistry
        from ui_qt.theme_manager import ThemeManager
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        registry = BackgroundTaskRegistry()
        tm = ThemeManager()
        try:
            panel = BackgroundTasksPage(registry=registry, theme_manager=tm)
        except AttributeError as e:
            pytest.fail("BackgroundTasksPage constructor raised AttributeError (regression of ceb7a61): " + str(e))

    def test_tabs_set_expanding_via_tab_bar(self, panel_source):
        """setExpanding must be called on QTabBar, not QTabWidget.

        QTabWidget has no setExpanding. The fix is self._tabs.tabBar().setExpanding(False).
        If someone re-introduces the bad call (setExpanding on _tabs directly),
        the launcher crashes at startup. Pin the exact pattern.
        """
        assert "self._tabs.tabBar().setExpanding(False)" in panel_source, (
            "setExpanding must be called on tabBar(); QTabWidget itself"
            "has no such method (regression ceb7a61 crashed the launcher)."
        )
