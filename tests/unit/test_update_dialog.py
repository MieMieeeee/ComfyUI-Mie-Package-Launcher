"""Smoke tests for UpdateDialog: confirm it inherits drag from base."""

import pytest
from PyQt5 import QtCore
from unittest.mock import patch

from ui_qt.widgets.update_dialog import UpdateDialog


def _make_event(event_type, pos, button=QtCore.Qt.LeftButton):
    from PyQt5 import QtGui
    return QtGui.QMouseEvent(
        event_type,
        QtCore.QPointF(*pos),
        QtCore.QPointF(*pos),
        button,
        button,
        QtCore.Qt.NoModifier,
    )


def test_update_dialog_is_draggable(qtbot):
    """UpdateDialog must inherit drag from FramelessDraggableDialog.

    用户反馈：\"@\"更新完成的弹出框没有办法拖\"@\"。现在通过基类
    FramelessDraggableDialog 统一提供拖拽支持。
    """
    dlg = UpdateDialog()
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    move_calls = []
    with patch.object(dlg, "move", side_effect=lambda p: move_calls.append(p)):
        dlg.mousePressEvent(_make_event(QtCore.QEvent.MouseButtonPress, (100, 100)))
        dlg.mouseMoveEvent(_make_event(QtCore.QEvent.MouseMove, (250, 200)))
    assert len(move_calls) == 1, (
        f"UpdateDialog.move should be called once during drag, got {len(move_calls)}"
    )


def test_update_dialog_is_modal_by_default(qtbot):
    dlg = UpdateDialog()
    qtbot.addWidget(dlg)
    assert dlg.isModal() is True, "UpdateDialog should be modal by default"


def test_update_dialog_window_type_is_dialog(qtbot):
    dlg = UpdateDialog()
    qtbot.addWidget(dlg)
    window_type = dlg.windowFlags() & QtCore.Qt.WindowType_Mask
    assert window_type == QtCore.Qt.Dialog
"""UpdateDialog 主题切换回归测试（issue 6 / Minor）。

UpdateDialog 继承 FramelessDraggableDialog 但未实现 update_theme()，
构造时一次性取色，切深/浅主题时颜色冻结，违反 AGENTS.md 主题规范。

验证点：
- update_theme() 必须存在并被 theme_changed 信号触发调用
- 调用 update_theme() 后 container / changelog_edit / btn_update 等 setStyleSheet 被重新调用
- 调 update_theme(theme_styles) 不传 theme_manager 时走 fallback（不要崩）
"""
import pytest
from PyQt5 import QtCore
from unittest.mock import MagicMock, patch, call

pytest.importorskip("PyQt5")


class TestUpdateDialogThemeRefresh:
    """UpdateDialog.update_theme 必须重设 QSS。"""

    def test_update_theme_method_exists(self, qtbot):
        from ui_qt.widgets.update_dialog import UpdateDialog
        dlg = UpdateDialog()
        qtbot.addWidget(dlg)
        assert hasattr(dlg, "update_theme"), "UpdateDialog 必须实现 update_theme() 方法"
        assert callable(dlg.update_theme)

    def test_update_theme_reapplies_container_qss(self, qtbot):
        """调 update_theme 时 container.setStyleSheet 至少被调一次（即重新应用 QSS）。"""
        from ui_qt.widgets.update_dialog import UpdateDialog
        from ui_qt.theme_manager import ThemeManager
        tm = ThemeManager(dark=True)
        dlg = UpdateDialog(theme_manager=tm)
        qtbot.addWidget(dlg)
        with patch.object(dlg.container, "setStyleSheet") as mock_set:
            dlg.update_theme()  # 不传 theme_styles，走 fallback 到 self.theme_manager.styles
        # 至少被调一次（重新应用），QSS 字符串应该包含新的 color token
        assert mock_set.call_count >= 1, f"container.setStyleSheet 应该被重新调用，实际 {mock_set.call_count} 次"
        # 取最后一次的 QSS 字符串
        qss = mock_set.call_args.args[0]
        assert "UpdateContainer" in qss or "background-color" in qss, f"QSS 应含 container 样式，实际：{qss[:200]}"

    def test_update_theme_accepts_styles_argument(self, qtbot):
        """update_theme(theme_styles) 显式传 styles 时也走通。"""
        from ui_qt.widgets.update_dialog import UpdateDialog
        from ui_qt.theme_manager import ThemeManager
        tm = ThemeManager(dark=True)
        dlg = UpdateDialog(theme_manager=tm)
        qtbot.addWidget(dlg)
        # 传一个真实的 ThemeStyles（验证不崩 + setStyleSheet 被调）
        with patch.object(dlg.container, "setStyleSheet") as mock_set:
            dlg.update_theme(theme_styles=tm.styles)
        assert mock_set.call_count >= 1

    def test_update_theme_doesnt_crash_without_theme_manager(self, qtbot):
        """theme_manager=None（开发调试场景）时调 update_theme() 不崩。"""
        from ui_qt.widgets.update_dialog import UpdateDialog
        dlg = UpdateDialog(theme_manager=None)
        qtbot.addWidget(dlg)
        # 不应抛异常
        try:
            dlg.update_theme()
        except Exception as e:
            pytest.fail(f"update_theme() 不应抛异常: {e}")

    def test_update_theme_invoked_on_theme_change(self, qtbot):
        """构造时如果有 theme_manager，set_theme 切换时 update_theme 会被调（spy container.setStyleSheet）。"""
        from ui_qt.widgets.update_dialog import UpdateDialog
        from ui_qt.theme_manager import ThemeManager
        tm = ThemeManager(dark=True)
        dlg = UpdateDialog(theme_manager=tm)
        qtbot.addWidget(dlg)
        with patch.object(dlg.container, "setStyleSheet") as mock_set:
            tm.set_theme(False)  # 切到浅色
        assert mock_set.call_count >= 1, f"切主题时 update_theme 应被触发，container.setStyleSheet 至少被调 1 次，实际 {mock_set.call_count}"
class TestBtnLaterAccessibility:
    """btn_later 必须从 QLabel 改为 QPushButton（issue 8 / Minor，无障碍）：

    - Tab 可聚焦
    - Space/Enter 可触发
    - 屏幕阅读器识别为 button role
    - laterRequested 信号 + reject() 正常发出
    """

    def test_btn_later_is_qpushbutton(self, qtbot):
        from PyQt5 import QtWidgets
        from ui_qt.widgets.update_dialog import UpdateDialog
        dlg = UpdateDialog()
        qtbot.addWidget(dlg)
        assert isinstance(dlg.btn_later, QtWidgets.QPushButton), \
            f"btn_later 必须是 QPushButton，实际 {type(dlg.btn_later).__name__}"

    def test_btn_later_is_focusable(self, qtbot):
        from PyQt5 import QtCore
        from ui_qt.widgets.update_dialog import UpdateDialog
        dlg = UpdateDialog()
        qtbot.addWidget(dlg)
        # QPushButton 默认 focusPolicy 应含 StrongFocus 或 WheelFocus
        fp = dlg.btn_later.focusPolicy()
        # 至少应该可 tab focus 或 click focus
        assert fp != QtCore.Qt.NoFocus, f"btn_later 不应是 NoFocus，实际 {fp}"

    def test_btn_later_click_emits_laterRequested(self, qtbot):
        from PyQt5.QtTest import QTest
        from PyQt5 import QtCore
        from ui_qt.widgets.update_dialog import UpdateDialog
        dlg = UpdateDialog()
        qtbot.addWidget(dlg)
        captured = []
        dlg.laterRequested.connect(lambda: captured.append("later"))
        QTest.mouseClick(dlg.btn_later, QtCore.Qt.LeftButton)
        assert "later" in captured, f"点击 btn_later 应发射 laterRequested，实际 {captured}"

    def test_btn_later_space_key_emits_laterRequested(self, qtbot):
        """聚焦后按 Space 也能触发（键盘可达）。"""
        from PyQt5.QtTest import QTest
        from PyQt5 import QtCore
        from ui_qt.widgets.update_dialog import UpdateDialog
        dlg = UpdateDialog()
        qtbot.addWidget(dlg)
        captured = []
        dlg.laterRequested.connect(lambda: captured.append("later"))
        dlg.btn_later.setFocus()
        QTest.keyClick(dlg.btn_later, QtCore.Qt.Key_Space)
        assert "later" in captured, f"Space 键应触发 laterRequested，实际 {captured}"
class TestUpdateDialogThemeCoverage:
    """update_theme 必须刷新 container / changelog_edit / progress_bar / 所有 label（review 遗留 1）。

    计划验收标准 1："主题切换信号发出后，dialog 的 container 背景 / 输入框 / 进度条 / 按钮全部刷新"。
    之前只刷了 container，changelog_edit / progress_bar / lbl_title / current_label / arrow_label /
    latest_label / changelog_label / lbl_status 切深/浅色后颜色冻结。
    """

    def test_update_theme_refreshes_changelog_edit(self, qtbot):
        from PyQt5 import QtWidgets
        from ui_qt.widgets.update_dialog import UpdateDialog
        from ui_qt.theme_manager import ThemeManager
        info = {"current": "1.0", "latest": "2.0", "changelog": "new features"}
        tm = ThemeManager(dark=True)
        dlg = UpdateDialog(update_info=info, theme_manager=tm)
        qtbot.addWidget(dlg)
        # changelog_edit 应存在（changelog 非空）
        assert hasattr(dlg, "changelog_edit"), "构造时 changelog 非空，必须有 changelog_edit 实例属性"
        # 切主题时 changelog_edit.setStyleSheet 必须被调
        with patch.object(dlg.changelog_edit, "setStyleSheet") as mock_set:
            tm.set_theme(False)
        assert mock_set.call_count >= 1, f"changelog_edit QSS 应被刷新，实际 {mock_set.call_count} 次"
        qss = mock_set.call_args.args[0]
        assert "QTextEdit" in qss, f"changelog_edit QSS 应含 QTextEdit selector，实际 {qss[:120]}"

    def test_update_theme_refreshes_progress_bar(self, qtbot):
        from ui_qt.widgets.update_dialog import UpdateDialog
        from ui_qt.theme_manager import ThemeManager
        tm = ThemeManager(dark=True)
        dlg = UpdateDialog(theme_manager=tm)
        qtbot.addWidget(dlg)
        assert hasattr(dlg, "progress_bar"), "UpdateDialog 必须存 progress_bar 为实例属性"
        with patch.object(dlg.progress_bar, "setStyleSheet") as mock_set:
            tm.set_theme(False)
        assert mock_set.call_count >= 1, f"progress_bar QSS 应被刷新，实际 {mock_set.call_count} 次"
        qss = mock_set.call_args.args[0]
        assert "QProgressBar" in qss, f"progress_bar QSS 应含 QProgressBar selector，实际 {qss[:120]}"

    def test_update_theme_refreshes_status_label(self, qtbot):
        from ui_qt.widgets.update_dialog import UpdateDialog
        from ui_qt.theme_manager import ThemeManager
        tm = ThemeManager(dark=True)
        dlg = UpdateDialog(theme_manager=tm)
        qtbot.addWidget(dlg)
        assert hasattr(dlg, "lbl_status"), "UpdateDialog 必须存 lbl_status 为实例属性"
        with patch.object(dlg.lbl_status, "setStyleSheet") as mock_set:
            tm.set_theme(False)
        assert mock_set.call_count >= 1, f"lbl_status QSS 应被刷新，实际 {mock_set.call_count} 次"

    def test_update_theme_refreshes_title_label(self, qtbot):
        from ui_qt.widgets.update_dialog import UpdateDialog
        from ui_qt.theme_manager import ThemeManager
        tm = ThemeManager(dark=True)
        dlg = UpdateDialog(theme_manager=tm)
        qtbot.addWidget(dlg)
        assert hasattr(dlg, "lbl_title"), "UpdateDialog 必须存 lbl_title 为实例属性"
        with patch.object(dlg.lbl_title, "setStyleSheet") as mock_set:
            tm.set_theme(False)
        assert mock_set.call_count >= 1

    def test_update_theme_refreshes_version_labels(self, qtbot):
        """当前 / 箭头 / 最新 / 日期 / changelog_label 都得刷。"""
        from ui_qt.widgets.update_dialog import UpdateDialog
        from ui_qt.theme_manager import ThemeManager
        info = {"current": "1.0", "latest": "2.0", "release_date": "2026-08-19", "changelog": "x"}
        tm = ThemeManager(dark=True)
        dlg = UpdateDialog(update_info=info, theme_manager=tm)
        qtbot.addWidget(dlg)
        # 这些 label 必须提升为实例属性才能 update_theme 重刷
        for attr in ("current_label", "arrow_label", "latest_label", "changelog_label", "date_label"):
            assert hasattr(dlg, attr), f"UpdateDialog 缺实例属性 {attr}，update_theme 无法重刷"
        # 显式调 update_theme() 而非走 set_theme（后者仅在 dark 切换时才触发 listener）
        for attr in ("current_label", "arrow_label", "latest_label", "changelog_label", "date_label"):
            with patch.object(getattr(dlg, attr), "setStyleSheet") as mock_set:
                dlg.update_theme()
            assert mock_set.call_count >= 1, f"{attr} QSS 应被刷新，实际 {mock_set.call_count} 次"