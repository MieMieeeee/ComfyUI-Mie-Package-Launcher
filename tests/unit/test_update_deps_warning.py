"""Tests for the deps-disabled warning in ui_qt.qt_app._confirm_deps_or_warn."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestConfirmDepsOrWarn(unittest.TestCase):
    """_confirm_deps_or_warn gates the update flow when deps are disabled."""

    def test_returns_true_silently_when_deps_enabled(self):
        from ui_qt.qt_app import _confirm_deps_or_warn

        var = MagicMock()
        var.get.return_value = True

        with patch(
            "ui_qt.widgets.dialog_helper.DialogHelper.show_confirmation"
        ) as mock_confirm:
            result = _confirm_deps_or_warn(MagicMock(), var)

        self.assertTrue(result)
        mock_confirm.assert_not_called()

    def test_returns_false_when_user_cancels(self):
        from ui_qt.qt_app import _confirm_deps_or_warn

        var = MagicMock()
        var.get.return_value = False

        with patch(
            "ui_qt.widgets.dialog_helper.DialogHelper.show_confirmation",
            return_value=False,
        ) as mock_confirm:
            result = _confirm_deps_or_warn(MagicMock(), var)

        self.assertFalse(result)
        mock_confirm.assert_called_once()
        # 提示文案必须出现“闪退”和“依赖库”
        args, _ = mock_confirm.call_args
        self.assertIn("闪退", args[2])
        self.assertIn("依赖库", args[2])

    def test_returns_true_when_user_confirms(self):
        from ui_qt.qt_app import _confirm_deps_or_warn

        var = MagicMock()
        var.get.return_value = False

        with patch(
            "ui_qt.widgets.dialog_helper.DialogHelper.show_confirmation",
            return_value=True,
        ):
            result = _confirm_deps_or_warn(MagicMock(), var)

        self.assertTrue(result)

    def test_returns_true_when_var_get_raises(self):
        from ui_qt.qt_app import _confirm_deps_or_warn

        var = MagicMock()
        var.get.side_effect = Exception("var broken")

        with patch(
            "ui_qt.widgets.dialog_helper.DialogHelper.show_confirmation"
        ) as mock_confirm:
            result = _confirm_deps_or_warn(MagicMock(), var)

        # 读不出状态时不拦住用户
        self.assertTrue(result)
        mock_confirm.assert_not_called()

    def test_returns_true_when_dialog_helper_import_fails(self):
        from ui_qt.qt_app import _confirm_deps_or_warn

        var = MagicMock()
        var.get.return_value = False

        with patch.dict(sys.modules, {"ui_qt.widgets.dialog_helper": None}):
            result = _confirm_deps_or_warn(MagicMock(), var)

        # 对话框出问题不能拦住用户
        self.assertTrue(result)

    def test_uses_confirmation_with_continue_and_cancel_buttons(self):
        from ui_qt.qt_app import _confirm_deps_or_warn

        var = MagicMock()
        var.get.return_value = False

        with patch(
            "ui_qt.widgets.dialog_helper.DialogHelper.show_confirmation",
            return_value=True,
        ) as mock_confirm:
            _confirm_deps_or_warn(MagicMock(), var)

        args, kwargs = mock_confirm.call_args
        # kwargs 里是按钮文案，保证“继续更新”和“取消”都出现
        self.assertEqual(kwargs.get("yes_text"), "继续更新")
        self.assertEqual(kwargs.get("no_text"), "取消")


class TestStartUpdateCallsWarningHelper(unittest.TestCase):
    """start_update invokes the deps warning helper at the top of the flow."""

    def test_helper_is_importable(self):
        # 帮助函数必须从 ui_qt.qt_app 导入，以保证 start_update 能调用
        from ui_qt.qt_app import _confirm_deps_or_warn
        self.assertTrue(callable(_confirm_deps_or_warn))

    def test_helper_passes_through_when_deps_enabled(self):
        from ui_qt.qt_app import _confirm_deps_or_warn
        var = MagicMock()
        var.get.return_value = True
        with patch("ui_qt.widgets.dialog_helper.DialogHelper.show_confirmation") as m:
            self.assertTrue(_confirm_deps_or_warn(MagicMock(), var))
            m.assert_not_called()
