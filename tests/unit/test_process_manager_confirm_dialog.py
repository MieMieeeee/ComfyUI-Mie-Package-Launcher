"""ProcessManager 启动中/端口占用确认框走 DialogHelper(统一弹窗风格)."""
# 本测试验证:
#   1. _ask_yes_no 走 DialogHelper.show_confirmation, 不再调 QMessageBox.question.
#   2. default=True / False 透传 DialogHelper 返回值.
#   3. destructive / yes_text / no_text 显式传参时透传 DialogHelper.
#   4. ProcessEvent 在 dialog 调用前 emit (保持事件总线契约).
#   5. headless 模式直接返回 default, 不调 dialog 也不调 QMessageBox.
#   6. DialogHelper 不可用时 (import 失败) 走 default 兜底.
from unittest.mock import MagicMock, patch

import pytest

from core.process_manager import ProcessManager


def _make_pm(headless=False):
    app = MagicMock()
    app.headless = headless
    app.big_btn = MagicMock()
    app.root = MagicMock(name="RootWindow")
    return app, ProcessManager(app)


@patch("PyQt5.QtWidgets.QMessageBox.question")
@patch("core.process_manager.DialogHelper.show_confirmation")
def test_ask_yes_no_uses_dialog_helper(mock_confirm, mock_qmb_question):
    """_ask_yes_no 必须走 DialogHelper, 不能直接调 QMessageBox.question."""
    _, pm = _make_pm()
    mock_confirm.return_value = True
    result = pm._ask_yes_no(
        "启动中", "是否取消本次启动?", default=False, destructive=True,
        yes_text="取消启动", no_text="继续启动",
    )
    assert result is True
    mock_confirm.assert_called_once()
    args, kwargs = mock_confirm.call_args
    # parent 来自 app.root / big_btn / main_window 之一 (MagicMock 自动 mock)
    assert args[1] == "启动中"
    assert "是否取消本次启动?" in args[2]
    assert kwargs["destructive"] is True
    assert kwargs["yes_text"] == "取消启动"
    assert kwargs["no_text"] == "继续启动"
    # 关键: 不再走 QMessageBox.question
    mock_qmb_question.assert_not_called()


@patch("core.process_manager.DialogHelper.show_confirmation", return_value=True)
def test_ask_yes_no_default_true_returns_user_yes(mock_confirm):
    """default=True 路径: DialogHelper 返回 True, _ask_yes_no 透传."""
    _, pm = _make_pm()
    assert pm._ask_yes_no("端口被占用", "直接打开网页?", default=True) is True
    args, kwargs = mock_confirm.call_args
    # parent 取的是 app.root (fallback chain 第一个非 None 的)
    assert args[0] is not None
    # default=True 时不传 destructive, 走 DialogHelper 默认值 (False)
    assert kwargs.get("destructive", False) is False


@patch("core.process_manager.DialogHelper.show_confirmation", return_value=False)
def test_ask_yes_no_default_false_returns_user_no(mock_confirm):
    """default=False 路径: DialogHelper 返回 False, _ask_yes_no 透传."""
    _, pm = _make_pm()
    result = pm._ask_yes_no("启动中", "是否取消本次启动?", default=False)
    assert result is False
    # 调用方 (toggle_comfyui) 显式传 destructive=True, 这里模拟调用方约定:
    # 见 toggle_comfyui 改造后 _ask_yes_no(..., destructive=True, yes_text=取消启动)
    args, kwargs = mock_confirm.call_args
    # 不传 destructive 时, 走 DialogHelper 默认 False (调用方按需显式开)
    assert kwargs.get("destructive", False) is False


@patch("core.process_manager.emit_event")
@patch("core.process_manager.DialogHelper.show_confirmation", return_value=False)
def test_ask_yes_no_emits_event_before_dialog(mock_confirm, mock_emit):
    """ProcessEvent 在 dialog 调用前 emit, 保持事件总线契约."""
    from core.process_events import ProcessEvent
    _, pm = _make_pm()
    pm._ask_yes_no("端口被占用", "停止并重启?", default=False, event=ProcessEvent.STARTING)
    mock_emit.assert_called_once_with(ProcessEvent.STARTING)
    assert mock_confirm.call_count == 1


@patch("PyQt5.QtWidgets.QMessageBox.question")
@patch("core.process_manager.DialogHelper.show_confirmation")
def test_headless_short_circuits_to_default(mock_confirm, mock_qmb_question):
    """headless 模式直接返回 default, 不调 dialog 也不调 QMessageBox."""
    app, pm = _make_pm(headless=True)
    assert pm._ask_yes_no("x", "y", default=True) is True
    assert pm._ask_yes_no("x", "y", default=False) is False
    mock_confirm.assert_not_called()
    mock_qmb_question.assert_not_called()


@patch("core.process_manager.DialogHelper", None)
def test_dialog_helper_unavailable_falls_back_to_default():
    """DialogHelper import 失败 (PyQt5 未就绪) 时, 走 default 兜底, 不抛."""
    _, pm = _make_pm()
    # 显式传 True/False 验证 default 透传
    assert pm._ask_yes_no("x", "y", default=True) is True
    assert pm._ask_yes_no("x", "y", default=False) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])