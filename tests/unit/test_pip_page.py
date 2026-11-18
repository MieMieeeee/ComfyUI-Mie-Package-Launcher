"""PipPage / PipController 单测：纯 UI + 信号 + 注入式控制器（不依赖 qt_app）。

骨架整体照抄 test_plugins_page.py：offscreen 平台 + session QApplication +
autouse 销毁清理 teardown（防堆损坏，勿引 pytest-qt）。控制器测试用同步
run_in_background / post_to_ui 替身 + Fake service；DialogHelper / ProgressDialog
统一 patch 掉（弹窗 exec_ 会阻塞测试）。
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def _destroy_leftover_widgets(qt_app):
    """每个用例结束后确定性销毁遗留的顶层 widget（仿 qtbot 的托管清理）。

    背景见 test_plugins_page.py 同名 fixture：offscreen PyQt5/Py3.12 组合下
    迟到析构的 widget + 仍挂着的事件会腐蚀堆（0xc0000374）。
    """
    yield
    import gc

    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    gc.collect()
    for w in list(app.topLevelWidgets()):
        try:
            w.close()
        except Exception:
            pass
    for w in list(app.topLevelWidgets()):
        w.deleteLater()
    try:
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    except Exception:
        pass
    app.processEvents()
    gc.collect()


def _stub_theme():
    """BasePage / PipPage 构造需要的最小 theme_manager 替身（同 plugins 页测试）。

    _px/_pt 用真 lambda：delegate 命中测试 / 布局要做整数算术，
    MagicMock 返回值进比较会 TypeError。
    """
    tm = MagicMock()
    tm.register_listener = lambda *_a, **_k: None
    styles = MagicMock()
    styles.c.dark = False
    styles._px = lambda b: b
    styles._pt = lambda b: b
    styles.content_style_light.return_value = ""
    styles.content_style_dark.return_value = ""
    styles.primary_button_style.return_value = ""
    styles.secondary_button_style.return_value = ""
    styles.destructive_button_style.return_value = ""
    styles.destructive_outline_button_style.return_value = ""
    styles.link_button_style.return_value = ""
    tm.styles = styles
    tm.colors = {}
    return tm


def _pkg(name, version="1.0.0"):
    return {"name": name, "version": version}


# ---------------------------------------------------------------------------
# PipPage：列表 / 过滤 / 信号 / busy / 主题
# ---------------------------------------------------------------------------

def test_populate_lists_all_packages(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.populate([_pkg("numpy"), _pkg("requests"), _pkg("torch")])
    assert page.list_widget.count() == 3


def test_populate_keeps_search_filter(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.populate([_pkg("numpy"), _pkg("requests")])
    page._search_edit.setText("num")
    page._apply_filters()
    assert page.list_widget.count() == 1
    page.populate([_pkg("numpy"), _pkg("requests"), _pkg("torch")])
    # 全量刷新后保留过滤关键字
    assert page.list_widget.count() == 1


def test_count_label_updates(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.populate([_pkg("a"), _pkg("b")])
    assert "2" in page._count_label.text()
    page._search_edit.setText("a")
    page._apply_filters()
    assert "1" in page._count_label.text()


def test_install_input_signal(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    got = []
    page.install_input_requested.connect(got.append)
    page._install_edit.setText("nvidia-vfx")
    page._install_edit.returnPressed.emit()
    assert got == ["nvidia-vfx"]
    page._install_btn.click()
    assert got == ["nvidia-vfx", "nvidia-vfx"]


def test_install_empty_input_not_emitted(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    got = []
    page.install_input_requested.connect(got.append)
    page._install_edit.setText("   ")
    page._emit_install()
    assert got == []


def test_install_signal_suppressed_when_busy(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    got = []
    page.install_input_requested.connect(got.append)
    page.set_busy(True)
    assert not page._install_btn.isEnabled()
    assert not page._install_edit.isEnabled()
    assert not page.refresh_btn.isEnabled()
    page._install_edit.setText("pkg")
    page._emit_install()
    page._install_btn.click()
    assert got == []
    page.set_busy(False)
    assert page._install_btn.isEnabled()


def test_set_loading_state_placeholder(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.set_loading_state(True)
    assert page.list_widget.count() == 1  # 占位行
    page.set_loading_state(True)
    assert page.list_widget.count() == 1  # 不重复插
    page.populate([_pkg("a")])
    assert page.list_widget.count() == 1  # populate 清掉占位


def test_set_env_info(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.set_env_info("3.11.8", "24.0")
    assert "3.11.8" in page._stat_python._lbl_value.text()
    assert "24.0" in page._stat_pip._lbl_value.text()
    page.set_env_info(None, None)
    assert page._stat_python._lbl_value.text() == "—"


def test_subtitle(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.set_subtitle("当前环境 Python：C:/py/python.exe")
    assert "C:/py/python.exe" in page._subtitle_label.text()


def test_update_theme_runs(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.populate([_pkg("a")])
    page.update_theme()  # 不抛异常即通过


# ---------------------------------------------------------------------------
# delegate 行内按钮：hit-test → 信号
# ---------------------------------------------------------------------------

def _editor_index(page):
    lw = page.list_widget
    return lw.model().index(0, 0)


def _make_opt(page, width=800, height=52):
    opt = QtWidgets.QStyleOptionViewItem()
    opt.rect = QtCore.QRect(0, 0, width, height)
    return opt


def _action_events(page, which):
    """构造命中「升级/卸载」按钮的 Press/Release 鼠标事件。"""
    from ui_qt.pages.pip_page import _column_geometry, _action_rects
    rect = _make_opt(page).rect
    g = _column_geometry(rect.width(), lambda v: v)
    upg, unl = _action_rects(g, rect, lambda v: v)
    target = upg if which == "upgrade" else unl
    press = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, target.center(),
                              QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                              QtCore.Qt.NoModifier)
    release = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease, target.center(),
                                QtCore.Qt.LeftButton, QtCore.Qt.NoButton,
                                QtCore.Qt.NoModifier)
    return press, release


def test_delegate_upgrade_click_emits(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.populate([_pkg("numpy", "1.26")])
    got = []
    page.upgrade_requested.connect(got.append)
    press, release = _action_events(page, "upgrade")
    opt = _make_opt(page)
    index = _editor_index(page)
    assert page._delegate.editorEvent(press, page.list_widget.model(), opt, index) is True
    page._delegate.editorEvent(release, page.list_widget.model(), opt, index)
    assert got == ["numpy"]


def test_delegate_uninstall_click_emits(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.populate([_pkg("numpy", "1.26")])
    got = []
    page.uninstall_requested.connect(got.append)
    press, release = _action_events(page, "uninstall")
    opt = _make_opt(page)
    index = _editor_index(page)
    page._delegate.editorEvent(press, page.list_widget.model(), opt, index)
    page._delegate.editorEvent(release, page.list_widget.model(), opt, index)
    assert got == ["numpy"]


def test_delegate_busy_suppresses_actions(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.populate([_pkg("numpy", "1.26")])
    got = []
    page.upgrade_requested.connect(got.append)
    page.set_busy(True)
    press, release = _action_events(page, "upgrade")
    opt = _make_opt(page)
    index = _editor_index(page)
    page._delegate.editorEvent(press, page.list_widget.model(), opt, index)
    page._delegate.editorEvent(release, page.list_widget.model(), opt, index)
    assert got == []
    page.set_busy(False)
    page._delegate.editorEvent(press, page.list_widget.model(), opt, index)
    page._delegate.editorEvent(release, page.list_widget.model(), opt, index)
    assert got == ["numpy"]


def test_delegate_click_outside_button_falls_through(qt_app):
    """点按钮之外的区域不触发操作信号（交回基类处理行选中）。"""
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    page.populate([_pkg("numpy", "1.26")])
    got = []
    page.upgrade_requested.connect(got.append)
    opt = _make_opt(page)
    index = _editor_index(page)
    pos = QtCore.QPoint(200, 26)  # 名称区
    press = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, pos,
                              QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                              QtCore.Qt.NoModifier)
    release = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease, pos,
                                QtCore.Qt.LeftButton, QtCore.Qt.NoButton,
                                QtCore.Qt.NoModifier)
    page._delegate.editorEvent(press, page.list_widget.model(), opt, index)
    page._delegate.editorEvent(release, page.list_widget.model(), opt, index)
    assert got == []


# ---------------------------------------------------------------------------
# PipController：确认 → 执行 → 收尾（Fake service + 同步线程替身）
# ---------------------------------------------------------------------------

class _FakeSvc:
    def __init__(self):
        self.packages = [_pkg("numpy", "1.26"), _pkg("requests", "2.31")]
        self.last_args = None
        self.last_uninstall = None
        self.last_install = None
        self.run_result = {"success": True, "returncode": 0, "stdout": "ok",
                           "stderr": "", "error": None, "cancelled": False}
        self.uninstall_result = {"success": True, "error": None, "error_code": None,
                                 "uninstalled": ["numpy"], "cancelled": False}
        self.install_result = {"success": True, "error": None, "error_code": None,
                               "updated": True, "up_to_date": False, "version": "2.0",
                               "cancelled": False}

    def list_installed(self):
        return list(self.packages)

    def python_version(self):
        return "3.11.8"

    def pip_version(self):
        return "24.0"

    def python_exec(self):
        return "C:/py/python.exe"

    def preview_command(self, args):
        return " ".join(["C:/py/python.exe", "-m", "pip", *[str(a) for a in args]])

    def run_args(self, args, on_progress=None, cancel_event=None):
        self.last_args = list(args)
        if on_progress:
            on_progress("正在下载")
        return dict(self.run_result)

    def uninstall(self, names, on_progress=None, cancel_event=None):
        self.last_uninstall = list(names)
        return dict(self.uninstall_result)

    def install(self, spec, **kwargs):
        self.last_install = spec
        return dict(self.install_result)


def _make_controller(page, svc, **kwargs):
    from ui_qt.pages.pip_page import PipController
    defaults = dict(
        run_in_background=lambda fn: fn(),   # 同步执行
        post_to_ui=lambda fn: fn(),          # 同步执行
        registry=None,
        is_comfyui_running=lambda: False,
        resolve_index_url=lambda: "https://idx/simple",
    )
    defaults.update(kwargs)
    return PipController(page, svc, **defaults)


def test_controller_full_command_no_mirror_injected(qt_app):
    """完整命令：参数原样透传，不注入镜像（命令自带 --index-url）。"""
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        dh.show_confirmation.return_value = True
        ctrl = _make_controller(page, svc)
        ctrl.run_install_input(
            "python -m pip install -U --no-build-isolation nvidia-vfx "
            "--index-url https://pypi.nvidia.com")
    assert svc.last_args == ["install", "-U", "--no-build-isolation",
                             "nvidia-vfx", "--index-url", "https://pypi.nvidia.com"]
    # 确认框预览里显示替换 python 前缀后的完整 argv
    content = dh.show_confirmation.call_args[0][2]
    assert "C:/py/python.exe -m pip install -U" in content


def test_controller_bare_name_uses_mirror(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        dh.show_confirmation.return_value = True
        ctrl = _make_controller(page, svc)
        ctrl.run_install_input("nvidia-vfx")
    assert svc.last_args == ["install", "-U", "nvidia-vfx", "-i", "https://idx/simple"]


def test_controller_declined_confirm_no_op(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        dh.show_confirmation.return_value = False
        ctrl = _make_controller(page, svc)
        ctrl.run_install_input("nvidia-vfx")
    assert svc.last_args is None


def test_controller_rejects_other_subcommands(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        ctrl = _make_controller(page, svc)
        ctrl.run_install_input("pip list")
    assert svc.last_args is None
    dh.show_error.assert_called_once()


def test_controller_uninstall_command_filters_flags(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        dh.show_confirmation.return_value = True
        ctrl = _make_controller(page, svc)
        ctrl.run_install_input("python -m pip uninstall -y torch numpy")
    assert svc.last_uninstall == ["torch", "numpy"]


def test_controller_row_uninstall(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        dh.show_confirmation.return_value = True
        ctrl = _make_controller(page, svc)
        ctrl.run_uninstall("numpy")
    assert svc.last_uninstall == ["numpy"]


def test_controller_upgrade_frozen_warning(qt_app):
    """升级 torch：确认框内容带 CUDA 警告（真实 is_frozen）。"""
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        dh.show_confirmation.return_value = True
        ctrl = _make_controller(page, svc)
        ctrl.run_upgrade("torch")
        content = dh.show_confirmation.call_args[0][2]
        assert "CUDA" in content
        assert svc.last_args == ["install", "-U", "torch", "-i", "https://idx/simple"]
        # 普通包没有警告行
        ctrl.run_upgrade("requests")
        content2 = dh.show_confirmation.call_args[0][2]
        assert "CUDA" not in content2
        assert svc.last_args == ["install", "-U", "requests", "-i", "https://idx/simple"]


def test_controller_failure_shows_error(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    svc.run_result = {"success": False, "returncode": 1, "stdout": "",
                      "stderr": "detail line", "error": "pip 命令执行失败",
                      "cancelled": False}
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        dh.show_confirmation.return_value = True
        ctrl = _make_controller(page, svc)
        ctrl.run_install_input("nvidia-vfx")
    dh.show_error.assert_called_once()
    assert "detail line" in dh.show_error.call_args[0][2]


def test_controller_cancelled_no_error_dialog(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    svc.run_result = {"success": False, "returncode": -1, "stdout": "",
                      "stderr": "", "error": "已取消", "cancelled": True}
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        dh.show_confirmation.return_value = True
        ctrl = _make_controller(page, svc)
        ctrl.run_install_input("nvidia-vfx")
    dh.show_error.assert_not_called()
    dh.show_info.assert_called_once()


def test_controller_second_op_rejected_while_busy(qt_app):
    """任务进行中（lock 未释放）第二个操作被拒。"""
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    deferred = []
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        dh.show_confirmation.return_value = True
        ctrl = _make_controller(page, svc,
                                run_in_background=deferred.append)
        ctrl.run_upgrade("numpy")
        assert page._busy is True
        assert len(deferred) == 1
        ctrl.run_upgrade("requests")  # 第二个 → 提示已有任务
        dh.show_info.assert_called_once()
        assert len(deferred) == 1
        assert svc.last_args is None  # 第二个操作没执行


def test_controller_op_finishes_refreshes_list(qt_app):
    """操作完成 → set_busy(False) + 列表刷新。"""
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        dh.show_confirmation.return_value = True
        ctrl = _make_controller(page, svc)
        ctrl.run_install_input("nvidia-vfx")
    assert page._busy is False
    assert page.list_widget.count() == len(svc.packages) + 0  # fake 列表不变


def test_controller_load_error_dialog(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    with patch("ui_qt.pages.pip_page.DialogHelper") as dh, \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        ctrl = _make_controller(page, svc)
        ctrl._on_load_error(ValueError("python 不存在"))
    dh.show_error.assert_called_once()
    assert "python 不存在" in dh.show_error.call_args[0][2]


def test_controller_loader_loads_list_and_env_info(qt_app):
    from ui_qt.pages.pip_page import PipPage

    page = PipPage(theme_manager=_stub_theme())
    svc = _FakeSvc()
    with patch("ui_qt.pages.pip_page.DialogHelper"), \
         patch("ui_qt.widgets.progress_dialog.ProgressDialog"):
        ctrl = _make_controller(page, svc)
        ctrl._on_refresh()
    assert page.list_widget.count() == 2
    assert "3.11.8" in page._stat_python._lbl_value.text()
    assert "24.0" in page._stat_pip._lbl_value.text()


if __name__ == "__main__":
    pytest.main([__file__])
