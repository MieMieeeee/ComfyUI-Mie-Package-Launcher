"""一键启动按钮必须「立即」切到启动中。

用户报告：点首页「一键启动」后要等一会儿按钮才变化。根因：toggle_comfyui
在 idle 分支里先做可达性探测（is_http_reachable 最多 ~2s）+ 端口占用扫描
（psutil 逐进程 connections 可能数秒），全部跑在 UI 线程，之后才把按钮切到
「启动中…」。修复：进入启动前检测就先切按钮，探测后放弃启动的分支恢复 idle。
"""
from unittest.mock import MagicMock, patch

import pytest

from core.process_manager import ProcessManager


def _make_pm():
    app = MagicMock()
    app.headless = False
    # toggle_comfyui 按钮状态机读 _state 字符串，MagicMock 自动属性必须钉成 "idle"
    app.big_btn = MagicMock()
    app.big_btn._state = "idle"
    app.custom_port.get.return_value = "8188"
    # MagicMock 自动属性为真，会让 toggle 误判「启动中再次点击」提前 return
    app._launching = False
    return app, ProcessManager(app)


def _starting_displayed(app):
    return any(
        c.args and c.args[0] == "启动中…"
        for c in app.big_btn.set_display.call_args_list
    )


def test_toggle_sets_starting_before_probes():
    """探测（慢操作）执行时按钮必须已经切到「启动中…」。"""
    app, pm = _make_pm()
    seen = []

    def slow_http(_app, _log=False):
        seen.append(_starting_displayed(app))
        return False

    with patch("core.process_manager.is_http_reachable", slow_http), \
         patch("core.process_manager.find_pids_by_port_safe", return_value=[]), \
         patch.object(pm, "start_comfyui") as start:
        pm.toggle_comfyui()

    assert seen == [True], "is_http_reachable 执行时按钮必须已显示「启动中…」"
    start.assert_called_once()


def test_toggle_port_occupied_open_web_restores_idle():
    """端口占用 + 用户选「打开网页」：不启动，按钮恢复「一键启动」。"""
    app, pm = _make_pm()
    with patch("core.process_manager.is_http_reachable", return_value=False), \
         patch("core.process_manager.find_pids_by_port_safe", return_value=[123]), \
         patch.object(pm, "_ask_yes_no", return_value=True):
        pm.toggle_comfyui()

    assert any(
        c.args and c.args[0] == "🚀 一键启动"
        for c in app.big_btn.set_display.call_args_list
    ), "放弃启动后按钮必须恢复 idle 显示"
    app.open_comfyui_web.assert_called_once()


def test_toggle_port_occupied_user_cancel_restores_idle():
    """端口占用 + 用户取消：按钮恢复 idle，且不触发启动。"""
    app, pm = _make_pm()
    with patch("core.process_manager.is_http_reachable", return_value=False), \
         patch("core.process_manager.find_pids_by_port_safe", return_value=[123]), \
         patch.object(pm, "_ask_yes_no", return_value=False), \
         patch.object(pm, "start_comfyui") as start, \
         patch.object(pm, "stop_all_comfyui_instances") as stop_all:
        pm.toggle_comfyui()

    assert any(
        c.args and c.args[0] == "🚀 一键启动"
        for c in app.big_btn.set_display.call_args_list
    ), "用户取消后按钮必须恢复 idle 显示"
    start.assert_not_called()
    stop_all.assert_not_called()


def test_toggle_detects_running_keeps_running_display():
    """探测发现其实已在跑：状态先修成 running 再走停止，不能停在「启动中…」。"""
    app, pm = _make_pm()
    with patch("core.process_manager.is_http_reachable", return_value=True), \
         patch.object(pm, "stop_comfyui") as stop:
        pm.toggle_comfyui()

    displays = [c.args for c in app.big_btn.set_display.call_args_list]
    assert ("正常运行", "点击停止") in displays, (
        "探测发现已在跑时应显示「正常运行」，而不是停在「启动中…」；实际: %s" % displays
    )
    stop.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
