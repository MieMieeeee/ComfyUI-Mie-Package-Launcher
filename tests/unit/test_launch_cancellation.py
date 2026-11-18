import os
import subprocess
import sys
import threading
from unittest.mock import MagicMock, patch
import pytest
from core.process_manager import ProcessManager


def _qt_app_module_importable() -> bool:
    """子进程探针: ui_qt.qt_app 能不能 import.

    本机 PyQt5 5.15.7 + PyQt5-sip 12.17 的 ABI 不兼容, `import ui_qt.qt_app`
    在 PyQtLauncher 类定义那一步直接 access violation —— **连带整个 pytest
    进程一起死** (不是普通失败). 所以凡是要 import qt_app 的用例都必须先
    用子进程探一遍, 探不通就 skip (同 test_close_to_tray.py 的做法).
    """
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent.parent
    try:
        probe = subprocess.run(
            [sys.executable, "-c",
             "import ui_qt.qt_app as qa; print('OK', qa.BigBtnProxy)"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            errors="ignore",
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            timeout=30,
        )
    except Exception:
        return False
    return probe.returncode == 0 and "OK" in probe.stdout


_QT_APP_IMPORTABLE = _qt_app_module_importable()
_qt_app_required = pytest.mark.skipif(
    not _QT_APP_IMPORTABLE,
    reason=(
        "ui_qt.qt_app import crashes in this env (pre-existing PyQt5/sip ABI "
        "access violation at PyQtLauncher class definition). Run on a machine "
        "where the GUI launches normally."
    ),
)


def make_pm():
    app = MagicMock()
    app.headless = False
    app._launching = False
    app.big_btn._state = "idle"
    app.custom_port.get.return_value = "8188"
    app.ui_post.side_effect = lambda fn: fn()
    return app, ProcessManager(app)

def test_toggle_returns_while_probe_is_blocked():
    app, pm = make_pm()
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    def probe(*args, **kwargs):
        entered.set()
        release.wait(2)
        return False
    with patch("core.process_manager.is_http_reachable", side_effect=probe), patch("core.process_manager.find_pids_by_port_safe", return_value=[]), patch.object(pm, "start_comfyui"):
        caller = threading.Thread(target=lambda: (pm.toggle_comfyui(), returned.set()))
        caller.start()
        try:
            assert entered.wait(1)
            assert returned.wait(.2), "UI handler must return before probe completes"
            assert app._launching is True
        finally:
            release.set()
            caller.join(2)
            worker = getattr(pm, "_preflight_thread", None)
            if worker:
                worker.join(2)

def test_cancel_during_probe_never_starts_or_kills_external_process():
    app, pm = make_pm()
    entered, release = threading.Event(), threading.Event()
    def probe(*args, **kwargs):
        entered.set()
        release.wait(2)
        return False
    with patch("core.process_manager.is_http_reachable", side_effect=probe), patch("core.process_manager.find_pids_by_port_safe", return_value=[]), patch.object(pm, "start_comfyui") as start, patch.object(pm, "_ask_yes_no", return_value=True), patch("core.runner_stop.stop") as stop:
        caller = threading.Thread(target=pm.toggle_comfyui)
        caller.start()
        try:
            assert entered.wait(1)
            pm.toggle_comfyui()
        finally:
            release.set()
            caller.join(2)
        worker = getattr(pm, "_preflight_thread", None)
        if worker:
            worker.join(2)
        stop_worker = getattr(pm, "_stop_thread", None)
        if stop_worker:
            stop_worker.join(2)
        assert app._launching is False
        start.assert_not_called()
        stop.assert_not_called()
        app.stop_all_comfyui_instances.assert_not_called()

def test_cancelled_runner_drops_queued_success():
    from core.runner_start import start
    app, pm = make_pm()
    pm._launch_cancel = threading.Event()
    pm._launch_spawn_lock = threading.Lock()
    queued = []
    app.ui_post.side_effect = queued.append
    proc = MagicMock()
    proc.poll.return_value = None
    def spawn(*args, **kwargs):
        pm.comfyui_process = proc
    with patch("core.runner_start.threading.Thread") as thread, patch("core.runner_start._spawn_process", side_effect=spawn), patch("core.runner_start.time.sleep"), patch("core.runner_start._check_system_stats", return_value=True), patch("core.runner_start._verify_listener_is_spawned", return_value=None), patch.object(pm, "on_start_success") as success:
        start(app, pm, [], {}, ".")
        pm._launch_cancel.wait = MagicMock(return_value=False)
        thread.call_args.kwargs["target"]()
        assert queued
        pm._launch_cancel.set()
        for fn in queued:
            fn()
        success.assert_not_called()

def test_cancel_before_worker_prevents_spawn():
    from core.runner_start import start
    app, pm = make_pm()
    with patch("core.runner_start.threading.Thread") as thread, patch("core.runner_start._spawn_process") as spawn:
        start(app, pm, [], {}, ".")
        pm._launch_cancel.set()
        thread.call_args.kwargs["target"]()
        spawn.assert_not_called()

def test_cancel_during_spawn_waits_then_stops_tracked_process():
    from core.runner_start import start
    app, pm = make_pm()
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    proc = MagicMock()
    proc.poll.return_value = None
    def spawn(*args, **kwargs):
        entered.set()
        release.wait(2)
        pm.comfyui_process = proc
    def stop(*args):
        assert pm.comfyui_process is proc
        proc.poll.return_value = 0
        stopped.set()
        return True
    with patch("core.runner_start._spawn_process", side_effect=spawn), patch("core.runner_stop.stop", side_effect=stop), patch.object(pm, "on_process_ended"), patch.object(pm, "on_start_success") as success:
        start(app, pm, [], {}, ".")
        try:
            assert entered.wait(1)
            pm.stop_comfyui()
            assert not stopped.wait(.05)
        finally:
            release.set()
        assert stopped.wait(2)
        pm._stop_thread.join(2)
        pm._start_thread.join(2)
        success.assert_not_called()
        app.stop_all_comfyui_instances.assert_not_called()

def test_cancel_during_preparation_discards_queued_spawn():
    app, pm = make_pm()
    path = MagicMock()
    path.exists.return_value = True
    queued = []
    app.ui_post.side_effect = queued.append
    with patch("core.launcher_cmd.build_launch_params", return_value=([], {}, ".", path, path)), patch("core.process_manager.run_hidden") as run, patch("core.runner_start.start") as spawn:
        run.return_value.returncode = 0
        pm.start_comfyui()
        pm._prepare_thread.join(2)
        assert queued
        pm._launch_cancel.set()
        for fn in queued:
            fn()
        spawn.assert_not_called()

@_qt_app_required
def test_qt_button_paints_and_accepts_cancel_while_probe_is_blocked(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt5 import QtCore, QtWidgets, QtTest
    from ui_qt.qt_app import BigBtnProxy
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    class Relay(QtCore.QObject):
        call = QtCore.pyqtSignal(object)
    class Button(QtWidgets.QPushButton):
        paints = 0
        def paintEvent(self, event):
            self.paints += 1
            super().paintEvent(event)
    relay = Relay()
    relay.call.connect(lambda fn: fn(), QtCore.Qt.QueuedConnection)
    app, pm = make_pm()
    app.ui_post.side_effect = relay.call.emit
    btn = Button()
    app.big_btn = BigBtnProxy()
    app.big_btn.attach(btn)
    btn.clicked.connect(pm.toggle_comfyui)
    entered, release = threading.Event(), threading.Event()
    def probe(*args, **kwargs):
        entered.set()
        release.wait(3)
        return False
    with patch("core.process_manager.is_http_reachable", side_effect=probe), patch("core.process_manager.find_pids_by_port_safe", return_value=[]), patch.object(pm, "_ask_yes_no", return_value=True) as confirm, patch.object(pm, "start_comfyui") as start:
        btn.show()
        QtTest.QTest.qWait(20)
        paints = btn.paints
        try:
            btn.click()
            assert entered.wait(1)
            QtTest.QTest.qWait(30)
            assert btn.text().startswith("启动中")
            assert btn.paints > paints
            btn.click()
            confirm.assert_called_once()
            for _ in range(50):
                QtTest.QTest.qWait(10)
                if not app._launching:
                    break
            assert app._launching is False
            assert "一键启动" in btn.text()
        finally:
            release.set()
            pm._preflight_thread.join(2)
            btn.close()
        start.assert_not_called()
