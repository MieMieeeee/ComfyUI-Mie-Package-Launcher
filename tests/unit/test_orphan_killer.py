"""core.orphan_killer: 退出 launcher 时清理孤儿 WebUI 工作台.

本测试覆盖 4 个核心场景:
- ComfyUI 未跑 + WebUI 跑 -> 关 (True)
- ComfyUI 跑 + WebUI 跑 -> 不关 (False)
- ComfyUI 未跑 + WebUI 未跑 -> 不关 (False)
- 探测 / 停止抛异常 -> 不冒泡, 返回 False (不阻断退出)

orphan_killer 是纯函数模块, 不依赖 PyQt5, 也不 import qt_app, 单测能离线跑.
"""
from unittest.mock import MagicMock

from core.orphan_killer import should_stop_orphan_webui, stop_orphan_webui


def _make_app(comfyui_running=False, comfyui_raises=False, has_pm=True, has_stop=True):
    """构造最小 app 替身, 注入 comfyui / stop 行为."""
    app = MagicMock()
    if has_pm:
        if comfyui_raises:
            app.process_manager.is_running_fast.side_effect = RuntimeError("comfyui probe fail")
        else:
            app.process_manager.is_running_fast.return_value = comfyui_running
    else:
        # 无 process_manager: 用一个没有 is_running_fast 属性的对象
        app.process_manager = MagicMock(spec=[])
    if not has_stop:
        # 让 _stop_webui_sync 不可用
        del app._stop_webui_sync
    return app


def test_orphan_should_stop_when_comfyui_down_webui_up():
    """ComfyUI 未跑 + WebUI 跑 -> should_stop=True."""
    app = _make_app(comfyui_running=False)
    webui_probe = lambda _a: True
    assert should_stop_orphan_webui(app, is_webui_running_fn=webui_probe) is True


def test_orphan_should_not_stop_when_comfyui_up():
    """ComfyUI 跑 + WebUI 跑 -> should_stop=False (用户场景 1a/3 仅退出)."""
    app = _make_app(comfyui_running=True)
    webui_probe = lambda _a: True
    assert should_stop_orphan_webui(app, is_webui_running_fn=webui_probe) is False


def test_orphan_should_not_stop_when_webui_down():
    """ComfyUI 未跑 + WebUI 未跑 -> should_stop=False (无对象可关)."""
    app = _make_app(comfyui_running=False)
    webui_probe = lambda _a: False
    assert should_stop_orphan_webui(app, is_webui_running_fn=webui_probe) is False


def test_orphan_should_false_on_comfyui_probe_exception():
    """ComfyUI 探测抛 -> should_stop=False, 不贸然关."""
    app = _make_app(comfyui_raises=True)
    webui_probe = lambda _a: True
    assert should_stop_orphan_webui(app, is_webui_running_fn=webui_probe) is False


def test_orphan_should_false_when_no_process_manager():
    """app.process_manager 缺失 -> should_stop=False, 不抛."""
    app = _make_app(has_pm=False)
    webui_probe = lambda _a: True
    assert should_stop_orphan_webui(app, is_webui_running_fn=webui_probe) is False


def test_stop_orphan_calls_stop_webui_and_logs():
    """stop_orphan_webui: ComfyUI 未跑 + WebUI 跑 -> 调 stop_webui_fn, logger.info 一行, 返回 True."""
    app = _make_app(comfyui_running=False)
    called = []
    stop_fn = lambda: called.append(True) or True
    log = MagicMock()
    result = stop_orphan_webui(
        app,
        stop_webui_fn=stop_fn,
        is_webui_running_fn=lambda _a: True,
        logger=log,
    )
    assert result is True
    assert called == [True]
    log.info.assert_called_once()
    log_msg = log.info.call_args[0][0]
    assert "ComfyUI" in log_msg and ("未运行" in log_msg or "WebUI" in log_msg)


def test_stop_orphan_no_op_when_comfyui_running():
    """ComfyUI 跑 -> stop_orphan_webui 不调 stop_fn, 返回 False, 不记日志."""
    app = _make_app(comfyui_running=True)
    called = []
    stop_fn = lambda: called.append(True) or True
    log = MagicMock()
    result = stop_orphan_webui(
        app,
        stop_webui_fn=stop_fn,
        is_webui_running_fn=lambda _a: True,
        logger=log,
    )
    assert result is False
    assert called == []
    log.info.assert_not_called()


def test_stop_orphan_no_op_when_webui_not_running():
    """WebUI 未在跑 -> stop_orphan_webui 不调 stop_fn, 返回 False."""
    app = _make_app(comfyui_running=False)
    called = []
    stop_fn = lambda: called.append(True) or True
    log = MagicMock()
    result = stop_orphan_webui(
        app,
        stop_webui_fn=stop_fn,
        is_webui_running_fn=lambda _a: False,
        logger=log,
    )
    assert result is False
    assert called == []


def test_stop_orphan_swallows_stop_exception():
    """stop_webui_fn 内部抛 -> 兜住, 返回 False, 不冒泡."""
    app = _make_app(comfyui_running=False)
    def _boom():
        raise RuntimeError("taskkill fail")
    log = MagicMock()
    result = stop_orphan_webui(
        app,
        stop_webui_fn=_boom,
        is_webui_running_fn=lambda _a: True,
        logger=log,
    )
    assert result is False
    # 抛了, 就不记成功日志 (catch 块内只 return False)
    log.info.assert_not_called()


def test_stop_orphan_swallows_probe_exception():
    """ComfyUI 探测抛 -> stop_orphan_webui 兜住, 返回 False, 不调 stop_fn."""
    app = _make_app(comfyui_raises=True)
    called = []
    stop_fn = lambda: called.append(True) or True
    result = stop_orphan_webui(
        app,
        stop_webui_fn=stop_fn,
        is_webui_running_fn=lambda _a: True,
    )
    assert result is False
    assert called == [], "探测失败时不应贸然调 stop"


def test_stop_orphan_default_uses_app_stop_webui_sync():
    """不传 stop_webui_fn -> 用 app._stop_webui_sync (qt_app 那边就是这么挂的)."""
    app = _make_app(comfyui_running=False)
    app._stop_webui_sync = MagicMock(return_value=True)
    result = stop_orphan_webui(
        app,
        is_webui_running_fn=lambda _a: True,
    )
    assert result is True
    app._stop_webui_sync.assert_called_once()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
