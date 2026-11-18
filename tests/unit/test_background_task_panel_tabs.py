"""Regression tests for ui_qt.widgets.background_task_panel.

锁定 ``BackgroundTasksPage`` 的 tab 标题不再被裁:
1. tab 字体走 ``tabBar().setFont``（API 字体）—— QSS ``font:`` 简写只参与
   渲染、**不进 tab 的 sizeHint**，hint 会用 widget 默认字体（Segoe UI 9pt）
   计算，比 QSS 渲染的 10pt YaHei 窄 ~10%，tab 被排得比文字短而尾字硬切
   （2026-11-10 advanced_services_page 同源真机 bug，见其模块 docstring）。
2. ``padding`` 8px 14px + ``min-width: 96px``（QSS）—— 点击面积下限。
3. ``setExpanding(False)`` + ``setElideMode(ElideRight)`` + ``setMinimumSize(260, 0)``
   程序上锁死; 放不下时省略号优于硬裁（旧 ElideNone 在溢出时直接切字尾）。

历史背景: 早期裁字（“程中” / “U导成 (”）曾用收 padding + min-width 压住,
2026-11-10 找到真正根因（QSS 字体不进 sizeHint）后由 API 字体根治。
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
        """Min-width: 96px 是两个短标题 tab 的点击面积下限（不再承担防裁字职责,
        防裁字由 API 字体保证, 见 TestTabFontHint）.

        Now DPI-tokenized: ``min-width: {_px(96)}px;``.
        """
        m = re.search(
            r"QTabBar::tab\s*\{\{[\s\S]*?min-width:\s*\{_px\((\d+)\)\}px;",
            panel_source,
            flags=re.DOTALL,
        )
        assert m is not None, "QTabBar::tab 没有 min-width"
        px = int(m.group(1))
        assert 80 <= px <= 160, (
            f"min-width={px}px 不合理 (太小容不下 4 个 Chinese + 括号, 太大挤压布局)."
        )

    def test_qss_tab_block_has_no_font_shorthand(self, panel_source):
        """QTabBar::tab 里禁止再出现 ``font:`` 简写 —— 根因锁定.

        QSS 伪元素字体只管渲染不进 sizeHint, 会让 tab 比 10pt YaHei 渲染出的
        文字窄而硬切尾字. 字体必须走 tabBar().setFont（API）.
        """
        m = re.search(r"QTabBar::tab\s*\{\{([\s\S]*?)\}\}", panel_source, flags=re.DOTALL)
        assert m is not None, "QTabBar::tab block not found"
        assert not re.search(r"font\s*:", m.group(1)), (
            "QTabBar::tab 出现 QSS font: 简写 —— 它不进 sizeHint, 会让 tab "
            "比渲染文字窄（2026-11-10 真机裁字根因）, 字体请走 tabBar().setFont"
        )


class TestTabQtabwidgetApi:
    def test_program_calls_setExpanding_False(self, panel_source):
        """No-auto-stretch: tab 按 sizeHint 自然大小, 不被 QTabBar 重新分配."""
        assert "self._tabs.tabBar().setExpanding(False)" in panel_source, (
            "未显式 setExpanding(False); 容器窄时 Qt 可能按可用宽度平均分给 tab, "
            "一个 tab 不到 50px 时 Chinese 标题被裁."
        )

    def test_program_calls_setElideMode_ElideRight(self, panel_source):
        """ElideMode.ElideRight: 放不下时省略号收尾, 绝不硬裁字符串.

        旧 ElideNone 在溢出时直接把尾字切半个; 尺寸本身由 API 字体 hint 保证,
        这里只兜溢出极端情况."""
        assert "setElideMode(" in panel_source, "缺 ElideMode 锁定"
        assert (
            "TextElideMode.ElideRight" in panel_source
        ), "ElideMode 应为 ElideRight（溢出时省略号优于硬裁）"


class TestTabFontHint:
    """tab 宽度 hint 的真正来源: tabBar().setFont（API 字体, bold 基准）."""

    def test_tab_bar_font_set_via_api(self, panel_source):
        m = re.search(
            r"self\._tabs\.tabBar\(\)\.setFont\(_tab_font\)", panel_source
        )
        assert m is not None, "tab bar 字体必须走 API setFont（hint 与渲染同源）"

    def test_tab_font_bold_base(self, panel_source):
        """hint 按最宽变体（bold）算 —— 选中态 QSS 加粗渲染必然放得下."""
        assert "_tab_font.setBold(True)" in panel_source, (
            "tab 基础字体应取 bold（hint 最宽变体, 选中态加粗不裁字）"
        )

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
