"""Tests for ui_qt.qt_app._shutdown_log_handles.

aboutToQuit 阶段释放日志资源的回归锁。验证四件事:

1. logging.shutdown() 被调用 (flush + close + remove 所有 handler)
2. launcher logger 上的 handler 被 close + remove (双保险)
3. 所有 LogViewerPage 子对象 stop_tailing() 被调用 (避免 daemon LogTailer
   线程被强杀泄漏 ComfyUI 日志 fd)
4. 任何 step 抛异常都被 swallow,不影响 launcher 退出

直接 import ui_qt.qt_app 在当前 Windows + PyQt5 环境会触发 QMainWindow
元类的 access violation (跟 test_start_update_threads 同根因)。
这里复用同样的 exec-stub 模式:把 PyQtLauncher 的 Qt 基类换成 object 后 exec,
再绑 _shutdown_log_handles 到 stub 上跑行为断言。
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _load_qt_app_with_stub():
    """读 ui_qt/qt_app.py 源码,把 PyQtLauncher 的 Qt 基类替换为 object 后 exec。

    直接 import 会触发 QMainWindow 元类 access violation (test_start_update_threads
    注释里有详细说明)。把基类换成 object 拿到 unbound method 用于绑定 stub。
    """
    src_path = Path(ROOT) / "ui_qt" / "qt_app.py"
    src = src_path.read_text(encoding="utf-8")
    patched = src.replace(
        "class PyQtLauncher(QtWidgets.QMainWindow, process_events.ProcessCallback):",
        "class PyQtLauncher(object):",
    )
    assert patched != src, "\u672a\u627e\u5230 PyQtLauncher \u7c7b\u5b9a\u4e49"
    ns = {"__name__": "ui_qt.qt_app", "__file__": str(src_path)}
    exec(compile(patched, "qt_app", "exec"), ns)
    return ns


_NAMESPACES = {}


def _get_module():
    if "ns" not in _NAMESPACES:
        _NAMESPACES["ns"] = _load_qt_app_with_stub()
    return _NAMESPACES["ns"]


def _shutdown_bound(stub):
    """把 PyQtLauncher._shutdown_log_handles 绑到 stub 实例,返回 bound method。"""
    ns = _get_module()
    return ns["PyQtLauncher"].__dict__["_shutdown_log_handles"].__get__(stub)


def _install_fake_handler():
    """在 launcher logger 上挂 tracked handler,返回 (logger, handler)。

    handler.close 是 MagicMock,可断言被调用。
    """
    logger = logging.getLogger("comfyui_launcher")
    handler = MagicMock(spec=logging.Handler)
    handler.close = MagicMock()
    logger.addHandler(handler)
    return logger, handler


def _remove_fake_handler(logger, handler):
    try:
        logger.removeHandler(handler)
    except Exception:
        pass


class TestShutdownLogHandles(unittest.TestCase):
    def test_calls_logging_shutdown(self):
        """logging.shutdown() 必须被调一次(标准 flush + close + remove 入口)。"""
        stub = MagicMock()
        with patch("logging.shutdown") as mock_shutdown:
            _shutdown_bound(stub)()
        mock_shutdown.assert_called_once()

    def test_closes_and_removes_launcher_handlers(self):
        """launcher logger 上挂的 handler 必须被 close + remove(双保险)。"""
        stub = MagicMock()
        logger, handler = _install_fake_handler()
        try:
            _shutdown_bound(stub)()
            handler.close.assert_called_once()
            self.assertNotIn(
                handler, logger.handlers,
                "handler should be removed from launcher logger after shutdown",
            )
        finally:
            _remove_fake_handler(logger, handler)

    def test_stops_all_log_viewer_pages(self):
        """所有 LogViewerPage 子对象的 stop_tailing 必须被调。

        全 MagicMock 路径:patch QApplication.instance 让 topLevelWidgets
        返回 [stub_w];stub_w.findChildren 返回 [fake_page1, fake_page2]。
        验证每个 fake_page.stop_tailing 都被调用一次。
        """
        from PyQt5 import QtWidgets  # noqa: F401
        from ui_qt.log_viewer import LogViewerPage  # noqa: F401

        stub_w = MagicMock(name="top_level_widget")
        fake_page1 = MagicMock(spec=LogViewerPage, name="fake_page1")
        fake_page2 = MagicMock(spec=LogViewerPage, name="fake_page2")
        stub_w.findChildren.return_value = [fake_page1, fake_page2]

        with patch(
            "PyQt5.QtWidgets.QApplication.instance"
        ) as mock_instance:
            mock_instance.return_value.topLevelWidgets.return_value = [stub_w]
            # 直接调 unbound method,stub_w 仅作为 first arg 传进去
            ns = _get_module()
            method = ns["PyQtLauncher"].__dict__["_shutdown_log_handles"]
            method(stub_w)

        fake_page1.stop_tailing.assert_called_once()
        fake_page2.stop_tailing.assert_called_once()
        # 传给 findChildren 的类型必须是 LogViewerPage(类型过滤)
        args, _ = stub_w.findChildren.call_args
        self.assertIs(args[0], LogViewerPage)

    def test_swallows_exceptions_in_each_step(self):
        """任何 step 抛异常都必须被 swallow,aboutToQuit 阶段不能影响退出。

        同时让 logging.shutdown 和 findChildren 都炸,确认方法不抛。
        """
        stub = MagicMock()
        stub.findChildren.side_effect = Exception("boom2")
        with patch("logging.shutdown", side_effect=Exception("boom1")):
            # 不应抛
            _shutdown_bound(stub)()

    def test_idempotent_when_no_pages_and_no_handlers(self):
        """无 page + 无 handler 时也不能挂:生产路径已被外部清理过的状态。"""
        stub = MagicMock()
        stub_w = MagicMock(name="top_level_widget")
        stub_w.findChildren.return_value = []
        logger = logging.getLogger("comfyui_launcher")
        saved = list(logger.handlers)
        for h in saved:
            try:
                logger.removeHandler(h)
            except Exception:
                pass
        try:
            with patch(
                "PyQt5.QtWidgets.QApplication.instance"
            ) as mock_instance:
                mock_instance.return_value.topLevelWidgets.return_value = [stub_w]
                ns = _get_module()
                method = ns["PyQtLauncher"].__dict__["_shutdown_log_handles"]
                method(stub_w)  # 不应抛
        finally:
            for h in saved:
                try:
                    logger.addHandler(h)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()