"""_run_with_progress helper 单测.
"""
import os, sys, threading, time
from unittest.mock import MagicMock, patch
import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets
from ui_qt.widgets.progress_dialog import ProgressDialog  # noqa: E402

@pytest.fixture(scope="module")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app

class _FakeApp:
    def __init__(self, registry=None):
        self.config = {"proxy_settings": {}}
        if registry is not None:
            self._bg_task_registry = registry
        self._posted = []
        self.ui_post = lambda fn: (fn(), self._posted.append(fn))[1]

def _make_page(qt_app):
    from ui_qt.pages.webui_page import WebuiPage
    app = _FakeApp()
    page = WebuiPage.__new__(WebuiPage)
    page.app = app
    page.theme_manager = None
    return page, app

def _patch_progress_dialog():
    class _FakePbar:
        def setRange(self, *a, **k): pass
        def setValue(self, *a, **k): pass
        def setTextVisible(self, *a, **k): pass
        def setStyleSheet(self, *a, **k): pass
    captured = {"status": [], "progress": [], "mark_complete": [], "close": []}
    class _FakePD:
        def __init__(self, *a, **k):
            self.pbar = _FakePbar()
        def set_status(self, text):
            captured["status"].append(text)
        def set_progress(self, value, maximum=100):
            captured["progress"].append((value, maximum))
        def show(self): pass
        def set_background_callback(self, cb): pass
        def is_backgrounded(self): return False
        def is_cancelled(self): return False
        def mark_complete(self, msg=""):
            captured["mark_complete"].append(msg)
        def close(self):
            captured["close"].append(1)
    return _FakePD, captured


def test_run_with_progress_registers_task_with_real_registry(qt_app):
    from ui_qt.background_task_registry import BackgroundTaskRegistry
    registry = BackgroundTaskRegistry()
    page, app = _make_page(qt_app)
    app._bg_task_registry = registry
    done = threading.Event()
    def fake_runner(on_progress):
        done.set()
        return {"ok": True}
    def fake_done(result): pass
    page._run_with_progress("X", fake_runner, fake_done)
    assert done.wait(2.0), "runner should be called"
    assert len(registry.get_all()) == 1
    t = list(registry.get_all())[0]
    assert t.title == "X"
    assert t.is_active() is False, "task should be inactive after completion"


def test_run_with_progress_dispatches_on_progress_via_ui_post(qt_app):
    _FakePD, captured = _patch_progress_dialog()
    page, app = _make_page(qt_app)
    app._bg_task_registry = None
    def fake_runner(on_progress):
        on_progress("hello", 50)
        on_progress("world", None)
        return {"ok": True}
    def fake_done(result): pass
    with patch("ui_qt.widgets.progress_dialog.ProgressDialog", _FakePD):
        page._run_with_progress("X", fake_runner, fake_done, parent=page)
    time.sleep(0.1)
    assert any("hello" in s for s in captured["status"]), (
        f"set_status should be called with hello, actual {captured['status']}")
    assert any("world" in s for s in captured["status"]), (
        f"set_status should be called with world, actual {captured['status']}")
    assert (50, 100) in captured["progress"], (
        f"percent=50 should go to determinate, actual {captured['progress']}")
    assert (None, 100) in captured["progress"], (
        f"percent=None should go to pulse, actual {captured['progress']}")


def test_run_with_progress_completes_task_in_registry(qt_app):
    from ui_qt.background_task_registry import BackgroundTaskRegistry
    registry = BackgroundTaskRegistry()
    page, app = _make_page(qt_app)
    app._bg_task_registry = registry
    done = threading.Event()
    def fake_runner(on_progress):
        done.set()
        return {"ok": True}
    def fake_done(result): pass
    page._run_with_progress("X", fake_runner, fake_done)
    assert done.wait(2.0)
    t = list(registry.get_all())[0]
    assert t.done is True
    assert t.error is False


def test_run_with_progress_marks_complete_and_closes_dialog_on_success(qt_app):
    _FakePD, captured = _patch_progress_dialog()
    page, app = _make_page(qt_app)
    app._bg_task_registry = None
    done = threading.Event()
    def fake_runner(on_progress):
        done.set()
        return {"ok": True}
    def fake_done(result): pass
    with patch("ui_qt.widgets.progress_dialog.ProgressDialog", _FakePD):
        page._run_with_progress("X", fake_runner, fake_done, parent=page)
    assert done.wait(2.0)
    time.sleep(0.1)
    assert any("完成" in m for m in captured["mark_complete"]), (
        f"mark_complete should be called, actual {captured['mark_complete']}")
    assert len(captured["close"]) == 1, (
        f"close should be called once, actual {captured['close']}")


def test_run_with_progress_marks_error_on_failure(qt_app):
    _FakePD, captured = _patch_progress_dialog()
    from ui_qt.background_task_registry import BackgroundTaskRegistry
    registry = BackgroundTaskRegistry()
    page, app = _make_page(qt_app)
    app._bg_task_registry = registry
    done = threading.Event()
    def fake_runner(on_progress):
        done.set()
        return {"ok": False, "error": "deps fail"}
    def fake_done(result): pass
    with patch("ui_qt.widgets.progress_dialog.ProgressDialog", _FakePD):
        page._run_with_progress("X", fake_runner, fake_done, parent=page)
    assert done.wait(2.0)
    time.sleep(0.1)
    t = list(registry.get_all())[0]
    assert t.done is False, f"failure should leave t.done False, actual {t.done}"
    assert t.error is True
    assert any("完成(有失败)" in m for m in captured["mark_complete"]), (
        f"mark_complete should mark error, actual {captured['mark_complete']}")


def test_run_with_progress_degrades_without_registry(qt_app):
    _FakePD, captured = _patch_progress_dialog()
    page, app = _make_page(qt_app)
    assert not hasattr(app, "_bg_task_registry")
    done = threading.Event()
    def fake_runner(on_progress):
        done.set()
        return {"ok": True}
    def fake_done(result): pass
    with patch("ui_qt.widgets.progress_dialog.ProgressDialog", _FakePD):
        page._run_with_progress("X", fake_runner, fake_done, parent=page)
    assert done.wait(2.0)
    time.sleep(0.1)
    assert len(captured["close"]) == 1


def test_run_with_progress_skips_dialog_for_non_widget_parent(qt_app):
    page, app = _make_page(qt_app)
    app._bg_task_registry = None
    done = threading.Event()
    def fake_runner(on_progress):
        done.set()
        return {"ok": True}
    def fake_done(result): pass
    non_widget_parent = MagicMock()
    with patch.object(ProgressDialog, "__init__", wraps=ProgressDialog.__init__) as m_init:
        page._run_with_progress("X", fake_runner, fake_done, parent=non_widget_parent)
    assert done.wait(2.0)
    time.sleep(0.1)
    assert m_init.call_count == 0


def test_run_with_progress_runs_runner_in_background_thread(qt_app):
    page, app = _make_page(qt_app)
    app._bg_task_registry = None
    main_thread_id = threading.get_ident()
    runner_thread_id = []
    def fake_runner(on_progress):
        runner_thread_id.append(threading.get_ident())
        return {"ok": True}
    def fake_done(result): pass
    page._run_with_progress("X", fake_runner, fake_done, parent=MagicMock())
    for _ in range(200):
        if runner_thread_id:
            break
        time.sleep(0.01)
    assert runner_thread_id, "runner not called"
    assert runner_thread_id[0] != main_thread_id, (
        f"runner should be in background thread, not main ({main_thread_id} == {runner_thread_id[0]})")


def test_run_with_progress_invokes_on_done_slot(qt_app):
    """worker 返回后, on_done_slot(result) 必须被调一次 (状态机恢复的唯一准入).
    这个是快亮上某位调实现的 _run_with_progress 收 result 但不调 on_done_slot 的型 bug: 状态机卡在 DOWNLOADING,
    按钮文字卡在 "下载中...", 侧边栏任务不出现, 用户看不到进度也退不了状态.
    """
    page, app = _make_page(qt_app)
    app._bg_task_registry = None
    done = threading.Event()
    captured_result = []
    def fake_done_slot(result):
        captured_result.append(result)
        done.set()
    def fake_runner(on_progress):
        return {"ok": True, "extra": "value"}
    page._run_with_progress("X", fake_runner, fake_done_slot)
    assert done.wait(2.0), "on_done_slot should be called after runner finishes"
    assert len(captured_result) == 1, f"on_done_slot should be called once, actual {len(captured_result)}"
    assert captured_result[0] == {"ok": True, "extra": "value"}, (
        f"on_done_slot should receive runner's return value, actual {captured_result[0]}")


def test_run_with_progress_passes_failure_result_to_on_done_slot(qt_app):
    """runner 中抛异常时, on_done_slot 也必须被调 (含 error), 避免状态机卡在 DOWNLOADING.
    """
    page, app = _make_page(qt_app)
    app._bg_task_registry = None
    done = threading.Event()
    captured_result = []
    def fake_done_slot(result):
        captured_result.append(result)
        done.set()
    def fake_runner(on_progress):
        raise RuntimeError("boom")
    page._run_with_progress("X", fake_runner, fake_done_slot)
    assert done.wait(2.0), "on_done_slot should be called even on runner exception"
    assert len(captured_result) == 1
    assert captured_result[0].get("ok") is False
    assert "boom" in captured_result[0].get("error", ""), (
        f"failure result should carry the error message, actual {captured_result[0]}")
