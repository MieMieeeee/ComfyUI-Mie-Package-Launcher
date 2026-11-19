"""伴生服务页的状态轮询**不能在 UI 线程**做端口探测。

2026-11-19（issue: 连续切页十多次会卡一下才响应）：stall_probe 抓到主线程
栈顶是

    h3_page._poll_status → _detect_state → manager.is_running → _try_adopt
      → h3_runtime.owned_listener → probe.find_pids_by_port_safe
        → subprocess.run(netstat)          ← 同步子进程，几百 ms

即：三个伴生服务页（h3 / openjutsu / webui）的 5 秒轮询定时器在 **UI 主线程**
做端口探测 → 每 5 秒把主线程堵一次 → 用户点切换时点击事件排在队列后面。

修法：探测放后台线程，算好状态后 invokeMethod 回主线程应用。这里锁住
「_detect_state 不在 UI 线程跑」+「结果回到 UI 线程应用」两个行为。
"""
import os
import sys
import threading
import time
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PyQt5 import QtWidgets  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


def _pump(seconds=1.5):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def _stub_theme():
    tm = MagicMock()
    tm.register_listener = lambda *_a, **_k: None
    styles = MagicMock()
    styles.c.dark = False
    styles._px = lambda b: b
    styles._pt = lambda b: b
    styles.content_style_light.return_value = ""
    styles.content_style_dark.return_value = ""
    for name in ("primary_button_style", "secondary_button_style",
                 "destructive_button_style", "destructive_outline_button_style",
                 "link_button_style", "input_style"):
        getattr(styles, name).return_value = ""
    tm.styles = styles
    tm.colors = {}
    return tm


def _build_page(cls, qt_app):
    """真构造页面（invokeMethod 需要有效的 QObject），把探测换成记录线程的替身。"""
    page = cls(app=None, theme_manager=_stub_theme())
    main_thread = threading.get_ident()
    seen = {}

    def _fake_detect_state():
        seen["thread"] = threading.get_ident()
        return "ready"

    page._detect_state = _fake_detect_state
    page._is_busy = lambda: False
    page._poll_inflight = False
    page._state = "init"
    return page, main_thread, seen


@pytest.mark.parametrize("module_name,cls_name", [
    ("ui_qt.pages.h3_page", "H3Page"),
    ("ui_qt.pages.openjutsu_page", "OpenjutsuPage"),
    ("ui_qt.pages.webui_page", "WebuiPage"),
])
def test_poll_status_runs_detection_off_ui_thread(qt_app, module_name, cls_name):
    import importlib
    mod = importlib.import_module(module_name)
    cls = getattr(mod, cls_name)
    page, main_thread, seen = _build_page(cls, qt_app)

    with patch.object(cls, "_start_log_tail", lambda self: None):
        page._poll_status()
    _pump(1.5)

    assert "thread" in seen, "探测没跑起来"
    assert seen["thread"] != main_thread, \
        "状态探测跑在 UI 主线程上了（会阻塞界面：切页卡一下才响应）"


@pytest.mark.parametrize("module_name,cls_name", [
    ("ui_qt.pages.h3_page", "H3Page"),
    ("ui_qt.pages.openjutsu_page", "OpenjutsuPage"),
    ("ui_qt.pages.webui_page", "WebuiPage"),
])
def test_poll_status_applies_state_on_ui_thread(qt_app, module_name, cls_name):
    """后台算出的状态要回到 UI 线程应用（invokeMethod 投递）。"""
    import importlib
    mod = importlib.import_module(module_name)
    cls = getattr(mod, cls_name)
    page, main_thread, seen = _build_page(cls, qt_app)

    with patch.object(cls, "_start_log_tail", lambda self: None):
        page._poll_status()
    _pump(1.5)

    assert getattr(page, "_state", None) == "ready", "探测结果没被应用"
