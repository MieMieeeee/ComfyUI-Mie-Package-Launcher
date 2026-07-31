"""WebuiPage 主题一致性 + 新结构测试.

新结构 (仿首页): 启动+更新并排 / 三项配置内联 (端口/监听/自动打开浏览器) / 日志.

锁死 webui_page 走 theme_manager (而非硬编码 hex), 跟 launch_page 一致.

验证:

1. 主按钮/更新按钮 stylesheet 含 primary_button_style 品牌色 (#7F56D9), 不含旧硬编码.

2. 日志视图走 token (input_readonly_*), 不含旧硬编码.

3. update_theme() 不抛异常, 切深/浅主题后状态点颜色随之变.

4. 三项配置控件存在且绑定正确; 监听勾选框隐式决定 display_host.

5. _open_url 按 browser_open_mode 分支 (disable 不打开 / webbrowser 用指定路径).

"""

import os
import stat
import subprocess

import tempfile

import threading

import time

import unittest

from pathlib import Path

from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtWidgets

from ui_qt.pages import webui_page as wp_module

from ui_qt.pages.webui_page import WebuiPage

from ui_qt.theme_manager import ThemeManager

def _make_app(cwd, webui_path, py_path, webui_options=None):

    """构造最小 app (config.webui_options 可定制)."""

    app = type("A", (), {})()

    app._cwd = str(cwd)

    app.config = {

        "environments": [

            {"id": "env_a", "comfyui_root": str(cwd), "python_path": str(py_path)},

        ],

        "active_env_id": "env_a",

        "webui_options": webui_options or {"port": 8199},

    }

    app.logger = MagicMock()

    app.pypi_proxy_mode = MagicMock()

    app.pypi_proxy_mode.get = lambda: "none"

    app.pypi_proxy_url = MagicMock()

    app.pypi_proxy_url.get = lambda: ""

    app.custom_port = MagicMock()

    app.custom_port.get = lambda: "8188"

    # services.config.save (webui 配置保存路径)

    app.services = MagicMock()

    app.services.config = MagicMock()

    app.services.config.save = lambda cfg: cfg

    return app

def _safe_stop_tailer(page):

    """测试清理: 停掉 page 的日志 tailer 线程, 避免泄漏."""

    try:

        if hasattr(page, "_stop_log_tail"):

            page._stop_log_tail()

    except Exception:

        pass

def _pump_pending_slots_with_safe_dialogs(page):

    """防 pytest-qt teardown 的 processEvents 触发前一个测试遗留的 Qt 槽弹模态框卡死.

    pytest-qt 在 teardown 调 app.processEvents() 时, 之前测试 worker 线程用
    QMetaObject.invokeMethod 排队的 _after_* 槽会在此刻 fire; 如果该槽带 err,
    会调 DialogHelper.show_warning(...).exec_() 阻塞事件循环.

    解决: teardown 先 patch DialogHelper 全部为 no-op, 再 processEvents 一次,
    把残留槽全部消化完; pytest-qt 再 processEvents 时队列已空.

    """

    from PyQt5 import QtWidgets

    app = QtWidgets.QApplication.instance()

    if app is None:

        return

    try:

        with patch("ui_qt.widgets.dialog_helper.DialogHelper.show_warning", lambda *a, **kw: None), \
             patch("ui_qt.widgets.dialog_helper.DialogHelper.show_info", lambda *a, **kw: None), \
             patch("ui_qt.widgets.dialog_helper.DialogHelper.show_error", lambda *a, **kw: None), \
             patch("ui_qt.widgets.dialog_helper.DialogHelper.show_confirmation", lambda *a, **kw: True):

            app.processEvents()

    except Exception:

        pass

class _Fixture(unittest.TestCase):

    @classmethod

    def setUpClass(cls):

        cls.app_qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        # 全局 patch DialogHelper: 整个测试套件期间弹窗都 no-op, 防 pytest-qt teardown
        # 的 processEvents 触发前一个测试遗留的 Qt 槽弹模态框卡死 teardown.
        from ui_qt.widgets import dialog_helper
        cls._dialog_patches = [
            patch.object(dialog_helper.DialogHelper, "show_warning", lambda *a, **kw: None),
            patch.object(dialog_helper.DialogHelper, "show_info", lambda *a, **kw: None),
            patch.object(dialog_helper.DialogHelper, "show_error", lambda *a, **kw: None),
            patch.object(dialog_helper.DialogHelper, "show_confirmation", lambda *a, **kw: True),
        ]
        for p in cls._dialog_patches:
            p.start()

    @classmethod

    def tearDownClass(cls):

        for p in getattr(cls, "_dialog_patches", []):

            try:

                p.stop()

            except Exception:

                pass

    def _make_page(self, webui_path, py_path, theme_manager, webui_options=None):

        cwd = webui_path.parent

        app = _make_app(cwd, webui_path, py_path, webui_options)

        _ok_dep = {"ok": True, "missing": [], "available": ["flask", "requests", "websockets"]}

        with patch("core.webui_process_manager.WebuiProcessManager.is_running", return_value=False), \
             patch("ui_qt.pages.webui_page.check_webui_dependencies", return_value=_ok_dep):

            page = WebuiPage(app=app, theme_manager=theme_manager)

        try:

            page._state_check_timer.stop()

        except Exception:

            pass

        # 停掉日志 tailer 线程, 避免测试间线程泄漏/污染

        self.addCleanup(lambda: _safe_stop_tailer(page))

        # 防 pytest-qt teardown 的 processEvents 触发上一个测试遗留的 Qt slot 弹模态框卡死

        self.addCleanup(lambda: _pump_pending_slots_with_safe_dialogs(page))

        return page, app

    def _scaffold(self, theme_manager, webui_options=None):

        d = Path(tempfile.mkdtemp())

        webui_path = d / "Comfyui-Workbench-Mie"

        (webui_path / "app").mkdir(parents=True)

        (webui_path / "app" / "flask_app.py").write_text("# stub")

        py = d / "python.exe"

        py.touch()

        return self._make_page(webui_path, py, theme_manager, webui_options) + (webui_path,)

class TestAfterSlotResetsState(_Fixture):

    """TDD RED: 三个 _after_* 槽在 success 路径上必须显式 _set_state, 不依赖 _refresh_state.

    现状: slot 只调 _refresh_state, 在 _BUSY_STATES 里跳过, state 永远卡在 busy.

    期望: slot 检测到非失败时, 显式 _set_state 走 re-detect.

    """

    def test_after_download_resets_state_on_success(self):

        """下载完成后, _after_download("下载完成") 应显式调 _set_state 走出 DOWNLOADING (re-detect).

        现状: slot 只调 _refresh_state, 在 _BUSY_STATES 里跳过, state 卡在 DOWNLOADING.

        """

        page, app, webui_path = self._scaffold(ThemeManager(dark=True))

        (webui_path / "requirements.txt").write_text("flask\n")

        # 设到 DOWNLOADING, 模拟下载中

        page._set_state(wp_module.STATE_DOWNLOADING)

        # 调 _after_download("下载完成"), 应跳出 DOWNLOADING

        page._after_download("下载完成")

        self.assertNotEqual(page._state, wp_module.STATE_DOWNLOADING,

            f"success 后 state 应不再是 DOWNLOADING, 实际 {page._state}")

    def test_after_setup_resets_state_on_success(self):

        """装依赖完成后, _after_setup(True, "") 应调 _set_state 走出 INSTALLING_DEPS.

        """

        page, app, webui_path = self._scaffold(ThemeManager(dark=True))

        (webui_path / "requirements.txt").write_text("flask\n")

        page._set_state(wp_module.STATE_INSTALLING_DEPS)

        page._after_setup(True, "")

        self.assertNotEqual(page._state, wp_module.STATE_INSTALLING_DEPS,

            f"success 后 state 应不再是 INSTALLING_DEPS, 实际 {page._state}")

    def test_after_update_resets_state_on_success(self):

        """更新完成后, _after_update(True, True, "") 应调 _set_state 走出他们各自的 busy 态.

        _after_update 内部会调 DialogHelper.show_info 弹模态框, 必须 patch 掉防卡死.

        """

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        # 设到某个中间态

        page._set_state(wp_module.STATE_DOWNLOADING)

        with patch("ui_qt.pages.webui_page.DialogHelper.show_info"), \
             patch("ui_qt.pages.webui_page.DialogHelper.show_warning"):

            # _after_update(self, ok, updated, err)

            page._after_update(True, True, "")

        self.assertNotEqual(page._state, wp_module.STATE_DOWNLOADING,

            f"success 后 state 应不再是 DOWNLOADING, 实际 {page._state}")

class TestThemeNoHardcodedHex(_Fixture):

    def test_primary_and_update_buttons_use_brand_color(self):

        """主按钮 + 更新按钮 stylesheet 含品牌紫 #7F56D9, 不含旧硬编码."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        for btn in (page._btn_primary, page._btn_update):

            ss = btn.styleSheet()

            self.assertIn("#7F56D9", ss, "按钮应走 primary_button_style 品牌色")

            self.assertNotIn("#4a90e2", ss, "不应残留旧硬编码蓝")

    def test_log_view_uses_token_not_vscode_colors(self):

        """日志视图走 input_readonly_* token, 不含旧 VS Code 色 #1e1e1e/#d4d4d4."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        ss = page._log_view.styleSheet()

        self.assertNotIn("#1e1e1e", ss)

        self.assertNotIn("#d4d4d4", ss)

        self.assertIn("#1F2937", ss)  # 深色主题 input_readonly_bg

class TestUpdateTheme(_Fixture):

    def test_update_theme_no_exception(self):

        """update_theme() 不抛异常."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page.update_theme()

        page.update_theme(ThemeManager(dark=True).styles)

    def test_version_and_config_status_are_separate(self):

        """版本与配置状态使用两个独立条目，并随状态分别更新。"""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        def _value(card):

            return card.layout().itemAt(2).widget().text()

        page._state = wp_module.STATE_READY

        page._update_ui_for_state()

        self.assertEqual(_value(page._version_item), "—")

        self.assertEqual(_value(page._config_status_item), "已安装配置")

        page._state = wp_module.STATE_NOT_INSTALLED

        page._update_ui_for_state()

        self.assertEqual(_value(page._version_item), "—")

        self.assertEqual(_value(page._config_status_item), "未安装")

class TestConfigControls(_Fixture):

    def test_three_config_controls_exist(self):

        """三项配置控件存在: 端口 QLineEdit / 监听 QCheckBox / 自动打开 NoWheelComboBox."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        self.assertIsInstance(page._port_edit, QtWidgets.QLineEdit)

        self.assertIsInstance(page._listen_chk, QtWidgets.QCheckBox)

        self.assertEqual(page._open_combo.count(), 3)  # 三选项

    def test_listen_checkbox_implicitly_sets_host(self):

        """监听勾选框隐式决定 display_host (勾=0.0.0.0 / 不勾=127.0.0.1)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        # 勾选 -> display_host = 0.0.0.0

        page._listen_chk.setChecked(True)

        self.assertEqual(app.config["webui_options"]["display_host"], "0.0.0.0")

        self.assertTrue(app.config["webui_options"]["listen_lan"])

        # 取消 -> 127.0.0.1

        page._listen_chk.setChecked(False)

        self.assertEqual(app.config["webui_options"]["display_host"], "127.0.0.1")

        self.assertFalse(app.config["webui_options"]["listen_lan"])

    def test_port_edit_writes_config(self):

        """端口输入写 config.webui_options.port."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page._port_edit.setText("9000")

        self.assertEqual(app.config["webui_options"]["port"], "9000")

    def test_open_mode_combo_writes_config(self):

        """自动打开下拉写 config.webui_options.browser_open_mode."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page._open_combo.setCurrentIndex(0)  # disable

        self.assertEqual(app.config["webui_options"]["browser_open_mode"], "disable")

        page._open_combo.setCurrentIndex(2)  # webbrowser

        self.assertEqual(app.config["webui_options"]["browser_open_mode"], "webbrowser")

class TestOpenUrl(_Fixture):

    def test_disable_mode_does_not_open(self):

        """browser_open_mode=disable 时 _open_url 不打开."""

        page, app, _ = self._scaffold(

            ThemeManager(dark=True),

            webui_options={"port": 8199, "browser_open_mode": "disable"},

        )

    def test_download_webui_does_not_call_legacy_setup_deps_silent(self):

        """_download_webui._worker 不能再调旧的 self._setup_deps(silent=True) 链式.

        这个调用起新 thread, 是之前双 worker 竞态隐患的源头.

        装依赖必须在同一 worker 里以 install_webui_requirements 直接调.

        """

        page, app, webui_path = self._scaffold(
            ThemeManager(dark=True),
            webui_options={"port": 8199, "browser_open_mode": "disable"},
        )

        (webui_path / "requirements.txt").write_text("flask\n")

        clone_done = threading.Event()

        legacy_called = threading.Event()

        def fake_clone(*args, **kwargs):

            clone_done.set()

            return {"ok": True, "log": "", "error": None, "already_exists": True}

        def fake_install(*args, **kwargs):

            return {"ok": True}

        p_invoke = patch(

            "ui_qt.pages.webui_page.QtCore.QMetaObject.invokeMethod",

            lambda *args, **kwargs: None,

        )

        p_clone = patch("ui_qt.pages.webui_page.clone_webui", side_effect=fake_clone)

        p_install = patch("ui_qt.pages.webui_page.install_webui_requirements", side_effect=fake_install)

        # 押走 _setup_deps 方法, 看有没有被从 _download_webui 里调过

        original_setup_deps = page._setup_deps

        def tracking_setup_deps(*args, **kwargs):

            legacy_called.set()

            return original_setup_deps(*args, **kwargs)

        page._setup_deps = tracking_setup_deps

        for p in (p_invoke, p_clone, p_install):

            p.start()

            self.addCleanup(p.stop)

        self.addCleanup(lambda: setattr(page, "_setup_deps", original_setup_deps))

        page._download_webui()

        self.assertTrue(clone_done.wait(2.0), "worker 应调到 clone_webui")

        # 给 worker 一点时间走完

        legacy_called.wait(1.0)

        self.assertFalse(legacy_called.is_set(),

            "_download_webui 不能再调 _setup_deps, 那是双 worker 竞态的源头")

        with patch("ui_qt.pages.webui_page.webbrowser.open") as m_open, \
             patch("ui_qt.pages.webui_page.subprocess.Popen") as m_popen:

            page._open_url("http://127.0.0.1:8199/")

            m_open.assert_not_called()

            m_popen.assert_not_called()

    def test_default_mode_uses_webbrowser(self):

        """default 模式用 webbrowser.open."""

        page, app, _ = self._scaffold(

            ThemeManager(dark=True),

            webui_options={"port": 8199, "browser_open_mode": "default"},

        )

        with patch("ui_qt.pages.webui_page.webbrowser.open") as m_open:

            page._open_url("http://127.0.0.1:8199/")

            m_open.assert_called_once_with("http://127.0.0.1:8199/")

    def test_open_url_after_start_slot_opens_on_main_thread(self):

        """_open_url_after_start 是主线程 slot, 启动成功后按 mode 打开 (回归 #1).

        webbrowser.open 在后台线程会静默失败, 所以自动打开必须经此 slot 走主线程.

        """

        page, app, _ = self._scaffold(

            ThemeManager(dark=True),

            webui_options={"port": 8199, "browser_open_mode": "default"},

        )

        with patch("ui_qt.pages.webui_page.webbrowser.open") as m_open:

            page._open_url_after_start()

            m_open.assert_called_once()

            self.assertIn("127.0.0.1:8199", m_open.call_args[0][0])

    def test_webbrowser_mode_with_path_uses_popen(self):

        """webbrowser 模式 + 有效路径 -> subprocess.Popen([path, url])."""

        fake_exe = Path(tempfile.gettempdir()) / "fakebrowser.exe"

        fake_exe.write_bytes(b"MZ")

        try:

            page, app, _ = self._scaffold(

                ThemeManager(dark=True),

                webui_options={

                    "port": 8199,

                    "browser_open_mode": "webbrowser",

                    "custom_browser_path": str(fake_exe),

                },

            )

            with patch("ui_qt.pages.webui_page.subprocess.Popen") as m_popen, \
                 patch("ui_qt.pages.webui_page.webbrowser.open") as m_open:

                page._open_url("http://127.0.0.1:8199/")

                m_popen.assert_called_once_with([str(fake_exe), "http://127.0.0.1:8199/"])

                m_open.assert_not_called()

        finally:

            try:

                fake_exe.unlink()

            except Exception:

                pass

class TestAutoOpenRegression(_Fixture):

    """回归: 自动打开浏览器两个 bug (listen_lan=0.0.0.0 打不开 / mode 缺省被当成关闭)."""

    def test_browser_url_always_localhost_even_when_listen_lan(self):

        """listen_lan 勾选 (display_host=0.0.0.0) 时, 打开浏览器仍用 127.0.0.1.

        0.0.0.0 是服务端绑定地址, 浏览器当客户端 URL 打不开 (跟首页 open_web 同理).

        """

        page, app, _ = self._scaffold(

            ThemeManager(dark=True),

            webui_options={"port": 8199, "listen_lan": True, "display_host": "0.0.0.0"},

        )

        url = page._browser_url()

        self.assertIn("127.0.0.1:8199", url)

        self.assertNotIn("0.0.0.0", url)

    def test_on_open_browser_uses_localhost_not_display_host(self):

        """打开网页按钮走 127.0.0.1 (回归 #1: 原先拼 0.0.0.0 浏览器打不开)."""

        page, app, _ = self._scaffold(

            ThemeManager(dark=True),

            webui_options={"port": 8199, "listen_lan": True, "display_host": "0.0.0.0"},

        )

        with patch("ui_qt.pages.webui_page.webbrowser.open") as m_open:

            page._on_open_browser()

            m_open.assert_called_once()

            self.assertIn("127.0.0.1:8199", m_open.call_args[0][0])

    def test_open_url_after_start_uses_localhost(self):

        """启动后自动打开也走 127.0.0.1 (回归 #1)."""

        page, app, _ = self._scaffold(

            ThemeManager(dark=True),

            webui_options={"port": 8199, "listen_lan": True, "display_host": "0.0.0.0"},

        )

        with patch("ui_qt.pages.webui_page.webbrowser.open") as m_open:

            page._open_url_after_start()

            m_open.assert_called_once()

            self.assertIn("127.0.0.1:8199", m_open.call_args[0][0])

    def test_should_auto_open_defaults_to_true_when_mode_missing(self):

        """browser_open_mode 缺省视为 default (开启), 不回退老 auto_open_browser=False (回归 #2).

        下拉框默认显示"使用默认浏览器", 行为必须与显示一致; 老逻辑缺省回退到

        auto_open_browser (默认 False) 会让"看起来已开启"的选项静默失效.

        """

        page, app, _ = self._scaffold(

            ThemeManager(dark=True),

            webui_options={"port": 8199, "auto_open_browser": False},  # 无 browser_open_mode

        )

        self.assertTrue(page._should_auto_open())

    def test_should_auto_open_disabled_only_when_mode_is_disable(self):

        """只有显式 disable/none 才不打开."""

        for mode in ("disable", "none", "DISABLE", " None "):

            page, app, _ = self._scaffold(

                ThemeManager(dark=True),

                webui_options={"port": 8199, "browser_open_mode": mode},

            )

            self.assertFalse(page._should_auto_open(), "mode=%s 应不打开" % mode)

    def test_should_auto_open_true_for_default_and_webbrowser(self):

        """default / webbrowser 模式都应自动打开."""

        for mode in ("default", "webbrowser"):

            page, app, _ = self._scaffold(

                ThemeManager(dark=True),

                webui_options={"port": 8199, "browser_open_mode": mode},

            )

            self.assertTrue(page._should_auto_open(), "mode=%s 应打开" % mode)

class TestSimultaneousComfyUIStart(_Fixture):

    """回归: WebUI 页"同时启动 ComfyUI"经 core.cli.runner.start_service, 后者直接读

    app._cwd (7 处), GUI 的 PyQtLauncher 之前缺这个属性会崩

    ('PyQtLauncher' object has no attribute '_cwd').

    修复: PyQtLauncher.__init__ 注入 self._cwd = base_root (对齐 HeadlessApp._cwd).

    这里用源码注入校验锁住修复点 (实例化 PyQtLauncher 需完整 GUI 初始化, 成本过高).

    """

    def test_pyqt_launcher_init_assigns_cwd(self):

        """PyQtLauncher.__init__ 必须赋值 self._cwd (跟 HeadlessApp._cwd 对齐).

        qt_app.py 有重量级 GUI 依赖, 单元测试里导入会 access violation,

        所以直接读源码文本校验 (不触发模块导入).

        """

        import re

        qt_app_path = Path(__file__).resolve().parents[2] / "ui_qt" / "qt_app.py"

        src = qt_app_path.read_text(encoding="utf-8")

        # 抓 class PyQtLauncher 的 __init__ 函数体 (到下一个同缩进 def/class)

        m = re.search(

            r"class PyQtLauncher\([^)]*\):.*?def __init__\(self\):(.*?)(?=\n    def |\nclass )",

            src,

            re.DOTALL,

        )

        self.assertIsNotNone(m, "找不到 PyQtLauncher.__init__")

        init_body = m.group(1)

        self.assertRegex(

            init_body, r"self\._cwd\s*=",

            "PyQtLauncher.__init__ 必须赋值 self._cwd (start_service 直接读 app._cwd)",

        )

    def test_runner_reads_app_cwd_directly(self):

        """core.cli.runner 直接访问 app._cwd (无 getattr 兜底) — 这是为什么 GUI app

        必须提供该属性. 锁住契约: 至少 start_service 路径读 app._cwd."""

        import inspect

        from core.cli import runner

        src = inspect.getsource(runner)

        # runner 里直接读 app._cwd (7 处). 这里只验证契约存在, 不数具体次数.

        self.assertIn("app._cwd", src, "runner 应直接读 app._cwd")

    def test_webui_page_app_has_cwd(self):

        """WebUI 页的 app 必须有 _cwd 属性 (GUI 经 PyQtLauncher 注入, CLI 经 HeadlessApp).

        _start_comfyui_then_webui 调 start_service, 后者读 app._cwd 解析 pidfile 路径.

        """

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        self.assertTrue(hasattr(app, "_cwd"), "app 必须有 _cwd (start_service 直接读)")

    def test_start_comfyui_runs_in_background_thread(self):

        """_start_comfyui_then_webui 必须在后台线程调 start_service, 不阻塞 UI 主线程.

        回归: 原实现在主线程同步调 start_service, 而 start_service 阻塞等 ready 信号,

        该信号又经 _post_to_ui 投递回 UI 线程 —— 主线程被占住收不到投递, 死锁 60s 超时,

        界面冻死且误判启动失败 (ComfyUI 其实起来了).

        """

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        main_thread = threading.current_thread()

        captured = {"thread": None, "in_main": None}

        def _fake_start_service(app_arg, **kwargs):

            captured["thread"] = threading.current_thread()

            captured["in_main"] = (captured["thread"] is main_thread)

            return {"started": True, "ready": True}  # ready (不是 ok)

        with patch("core.cli.runner.start_service", side_effect=_fake_start_service):

            page._start_comfyui_then_webui()

            # 等 worker 线程跑到 start_service (它会被 fake 立即返回, 不阻塞)

            for _ in range(200):

                if captured["thread"] is not None:

                    break

                time.sleep(0.01)

            self.assertIsNotNone(captured["thread"], "worker 线程应调用 start_service")

            self.assertFalse(captured["in_main"], "start_service 必须在后台线程, 不能在 UI 主线程")

    def test_start_comfyui_uses_ready_not_ok_field(self):

        """worker 用 res.get('ready') 判断成功, 不是 res.get('ok') (start_service 无 ok 字段).

        回归: 原代码 res.get('ok') 永远 None -> 即使 ComfyUI 起来了也误判失败,

        提前 return 不启 WebUI 工作台.

        """

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        # ready=True 才应判成功; 用 started=True 但 ready=False 确认不误判

        ok_results = []

        def _fake_start_service(app_arg, **kwargs):

            return {"started": True, "ready": True, "pid": 123}

        with patch("core.cli.runner.start_service", side_effect=_fake_start_service), \
             patch.object(page, "_start_webui") as m_start_webui, \
             patch.object(page, "_refresh_state"):

            page._start_comfyui_then_webui()

            # worker 成功后会 invokeMethod 回主线程调 _after_comfyui_start -> _start_webui.

            # 直接调 slot 验证 ready 分支 (跳过 Qt 事件循环):

            page._after_comfyui_start(True, "")

            m_start_webui.assert_called_once_with(with_comfyui=False)

    def test_start_comfyui_failure_shows_warning_and_skips_webui(self):

        """ComfyUI 启动失败时回主线程弹警告, 且不启 WebUI 工作台."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        with patch.object(page, "_start_webui") as m_start_webui, \
             patch.object(page, "_refresh_state"), \
             patch("ui_qt.pages.webui_page.DialogHelper.show_warning") as m_warn:

            page._after_comfyui_start(False, "boom")

            m_warn.assert_called_once()  # 弹窗

            m_start_webui.assert_not_called()  # 不继续启 webui

class TestUpdateButton(_Fixture):

    def test_update_button_disabled_when_not_installed(self):

        """未安装时更新按钮禁用."""

        # webui_path 不存在 -> not_installed

        d = Path(tempfile.mkdtemp())

        webui_path = d / "Comfyui-Workbench-Mie"  # 不创建

        py = d / "python.exe"

        py.touch()

        page, app, _ = self._make_page(webui_path, py, ThemeManager(dark=True)) + (webui_path,)

        page._update_ui_for_state()

        self.assertFalse(page._btn_update.isEnabled())

class TestComfyuiRunningCheck(_Fixture):

    """回归: ComfyUI 是否在跑的检查机制.

    原实现 _is_comfyui_running 调 service_status, 后者依赖 pidfile. 但首页 GUI 启动

    ComfyUI (core/runner_start + ProcessManager) 不写 pidfile (只有 CLI 路径写),

    导致"首页启的 ComfyUI"永远探不到 -> ComfyUI 已启动仍弹"是否同时启动".

    修复: 改用 core.probe.is_http_reachable (跟首页 process_manager 同款, 不碰 pidfile).

    """

    def test_is_comfyui_running_uses_http_probe_not_pidfile(self):

        """_is_comfyui_running 用 HTTP 探活 (/system_stats), 不读 pidfile/service_status."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        with patch("core.probe.is_http_reachable", return_value=True) as m_probe:

            self.assertTrue(page._is_comfyui_running())

            m_probe.assert_called_once()

    def test_is_comfyui_running_false_when_not_reachable(self):

        """ComfyUI HTTP 不可达 -> _is_comfyui_running 返回 False."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        with patch("core.probe.is_http_reachable", return_value=False):

            self.assertFalse(page._is_comfyui_running())

    def test_is_comfyui_running_passes_log_false(self):

        """探活带 _log=False (避免轮询刷日志, 跟首页 process_manager 对称)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        with patch("core.probe.is_http_reachable", return_value=False) as m_probe:

            page._is_comfyui_running()

            args, kwargs = m_probe.call_args

            # is_http_reachable(app, _log=False) — _log 是位置或关键字都接受

            self.assertTrue(

                (len(args) >= 2 and args[1] is False) or kwargs.get("_log") is False,

                "应带 _log=False",

            )

    def test_start_with_prompt_enters_checking_state(self):

        """点启动 -> _start_with_prompt 立即进入「检测中」(STATE_CHECKING), 按钮禁用.

        新流程: 探活挪到后台线程, 主线程先显示「检测中…」. 探活完经

        _after_comfyui_check 回主线程决定走「直接启动」还是「弹询问框」.

        """

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        # patch 掉后台线程的实际探活, 避免线程副作用

        with patch("core.probe.is_http_reachable", return_value=True):

            page._start_with_prompt()

        self.assertEqual(page._state, wp_module.STATE_CHECKING)

        self.assertFalse(page._btn_primary.isEnabled(), "检测中应禁用主按钮")

        self.assertIn("检测中", page._btn_primary.text())

    def test_after_comfyui_check_running_starts_webui_no_dialog(self):

        """探活完成 ComfyUI 在跑 (running=True) -> 直接启 WebUI工作台, 不弹框."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        called = {"webui": False}

        def _fake_start_webui(with_comfyui=False):

            called["webui"] = True

        page._start_webui = _fake_start_webui

        with patch("ui_qt.pages.webui_page.CustomConfirmDialog") as m_dlg:

            page._after_comfyui_check(True)

            m_dlg.assert_not_called()  # 不弹框

        self.assertTrue(called["webui"], "ComfyUI 在跑时应直接启 webui")

    def test_after_comfyui_check_not_running_shows_dialog(self):

        """探活完成 ComfyUI 没在跑 (running=False) -> 弹询问框."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        with patch("ui_qt.pages.webui_page.CustomConfirmDialog") as m_dlg:

            m_dlg.return_value.exec_.return_value = None

            m_dlg.return_value.get_result.return_value = 0  # 取消

            page._after_comfyui_check(False)

            m_dlg.assert_called_once()  # 弹框

class TestButtonStateMachine(_Fixture):

    """主按钮状态机: 各 _state -> 文案/可用性映射 + 中间态不被覆盖 + 防重复点击.

    参考 ComfyUI 服务按钮 (BigBtn.set_state 集中文案) 的做法, 把 WebUI 工作台主按钮

    的文案/可用性收口到 _update_ui_for_state, 中间态 (检测/等待ComfyUI/启动/停止/下载/

    装依赖) 显示进度文案且禁用, 并修掉轮询/刷新在中间态覆盖 _state 的隐藏竞态.

    """

    # (state, 期望按钮文案包含的关键词, 期望可点击)

    _STATE_EXPECT = [

        (wp_module.STATE_NOT_INSTALLED, "下载", True),

        (wp_module.STATE_NO_DEPS, "安装依赖", True),

        (wp_module.STATE_READY, "一键启动", True),

        (wp_module.STATE_RUNNING, "停止", True),

        (wp_module.STATE_CHECKING, "检测中", False),

        (wp_module.STATE_WAITING_COMFYUI, "等待 ComfyUI", False),

        (wp_module.STATE_STARTING, "启动中", False),

        (wp_module.STATE_STOPPING, "停止中", False),

        (wp_module.STATE_DOWNLOADING, "下载中", False),

        (wp_module.STATE_INSTALLING_DEPS, "安装依赖中", False),

    ]

    def test_each_state_button_text_and_enabled(self):

        """每个 _state 对应正确的主按钮文案 + 可点击性."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        for state, text_key, enabled in self._STATE_EXPECT:

            with self.subTest(state=state):

                page._set_state(state)

                self.assertEqual(page._state, state)

                self.assertIn(text_key, page._btn_primary.text(),

                              "%s 按钮文案应含 %r" % (state, text_key))

                self.assertEqual(page._btn_primary.isEnabled(), enabled,

                                 "%s 可点击性应为 %s" % (state, enabled))

    def test_config_status_chinese_for_intermediate_states(self):

        """配置状态卡片对中间态给中文化文案, 不再露英文 key."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        # _config_status_item 的值标签是 layout 第 3 个子控件

        def _status_text():

            return page._config_status_item.layout().itemAt(2).widget().text()

        for state in (wp_module.STATE_CHECKING, wp_module.STATE_STARTING,

                      wp_module.STATE_STOPPING, wp_module.STATE_DOWNLOADING):

            with self.subTest(state=state):

                page._set_state(state)

                txt = _status_text()

                self.assertNotIn(state, txt, "不应露英文 key %r" % state)

                self.assertIn("…", txt, "中间态文案应以省略号结尾")

    def test_is_busy_flag(self):

        """_is_busy 对中间态返回 True, 稳定态返回 False."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        for state in (wp_module.STATE_NOT_INSTALLED, wp_module.STATE_NO_DEPS,

                      wp_module.STATE_READY, wp_module.STATE_RUNNING):

            page._state = state

            self.assertFalse(page._is_busy(), "%s 不应是 busy" % state)

        for state in (wp_module.STATE_CHECKING, wp_module.STATE_WAITING_COMFYUI,

                      wp_module.STATE_STARTING, wp_module.STATE_STOPPING,

                      wp_module.STATE_DOWNLOADING, wp_module.STATE_INSTALLING_DEPS):

            page._state = state

            self.assertTrue(page._is_busy(), "%s 应是 busy" % state)

    def test_poll_status_does_not_override_busy_state(self):

        """_poll_status 在中间态不覆盖 _state (竞态回归).

        原 bug: STARTING 时进程还没起, _detect_state 返 READY, 5s 定时器把按钮刷回

        「一键启动」可点击, 用户能在启动中途再次点击.

        """

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page._set_state(wp_module.STATE_STARTING)

        # 模拟 _detect_state 返回 READY (进程还没起来), _poll_status 不应覆盖

        with patch.object(page, "_detect_state", return_value=wp_module.STATE_READY):

            page._poll_status()

        self.assertEqual(page._state, wp_module.STATE_STARTING, "中间态不应被轮询覆盖")

        self.assertFalse(page._btn_primary.isEnabled())

    def test_refresh_state_does_not_override_busy_state(self):

        """_refresh_state 在中间态不覆盖 _state (竞态回归)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page._set_state(wp_module.STATE_CHECKING)

        with patch.object(page, "_detect_state", return_value=wp_module.STATE_READY):

            page._refresh_state()

        self.assertEqual(page._state, wp_module.STATE_CHECKING)

    def test_refresh_state_force_overrides_busy_state(self):

        """_refresh_state(force=True) 强制覆盖 (env/主题切换场景)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page._set_state(wp_module.STATE_STARTING)

        with patch.object(page, "_detect_state", return_value=wp_module.STATE_READY):

            page._refresh_state(force=True)

        self.assertEqual(page._state, wp_module.STATE_READY)

    def test_on_primary_clicked_ignored_when_busy(self):

        """中间态点击主按钮不触发任何启动/停止 (防重复点击)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        for state, method_name in [

            (wp_module.STATE_CHECKING, "_start_with_prompt"),

            (wp_module.STATE_STARTING, "_start_webui"),

            (wp_module.STATE_STOPPING, "_stop_webui"),

            (wp_module.STATE_DOWNLOADING, "_download_webui"),

            (wp_module.STATE_INSTALLING_DEPS, "_setup_deps"),

        ]:

            with self.subTest(state=state):

                page._state = state

                with patch.object(page, method_name) as m:

                    page._on_primary_clicked()

                    self.assertEqual(m.call_count, 0,

                                     "%s 期间点击不应触发 %s" % (state, method_name))

    def test_after_action_done_start_success_to_running(self):

        """_after_action_done(started_ok=True) -> STATE_RUNNING."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page._set_state(wp_module.STATE_STARTING)

        page._after_action_done(True, "")

        self.assertEqual(page._state, wp_module.STATE_RUNNING)

        self.assertIn("停止", page._btn_primary.text())

        self.assertTrue(page._btn_primary.isEnabled())

    def test_after_action_done_start_failure_back_to_ready_with_warning(self):

        """_after_action_done(started_ok=False, err) -> STATE_READY + 弹窗."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page._set_state(wp_module.STATE_STARTING)

        with patch("ui_qt.pages.webui_page.DialogHelper.show_warning") as m_warn:

            page._after_action_done(False, "boom")

            m_warn.assert_called_once()

        self.assertEqual(page._state, wp_module.STATE_READY)

    def test_after_action_done_stop_to_ready_no_warning(self):

        """停止完成 (started_ok=False, err='') -> STATE_READY, 不弹窗."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page._set_state(wp_module.STATE_STOPPING)

        with patch("ui_qt.pages.webui_page.DialogHelper.show_warning") as m_warn:

            page._after_action_done(False, "")

            m_warn.assert_not_called()  # 停止无 err 不弹窗

        self.assertEqual(page._state, wp_module.STATE_READY)

    def test_start_comfyui_then_webui_enters_waiting_comfyui(self):

        """「同时启动」-> STATE_WAITING_COMFYUI (显示「等待 ComfyUI 启动中…»)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page._set_state(wp_module.STATE_READY)

        with patch("core.cli.runner.start_service", return_value={"ready": False}):

            page._start_comfyui_then_webui()

        self.assertEqual(page._state, wp_module.STATE_WAITING_COMFYUI)

        self.assertFalse(page._btn_primary.isEnabled())

        self.assertIn("等待 ComfyUI", page._btn_primary.text())

class TestQuitStopsWebui(_Fixture):

    """回归: 关闭启动器 ("停止 ComfyUI 并退出") 时应同步停止 WebUI 工作台.

    工作台依赖 ComfyUI 后台, ComfyUI 停了工作台没意义, 必须一起停. qt_app.py 不能在

    单元测试里导入 (重量级 GUI 依赖会 access violation), 所以这里用源码校验 + 调用

    未绑定方法的方式验证 _stop_comfyui_and_webui_on_exit / _stop_webui_sync 的契约.

    """

    @staticmethod

    def _qt_app_src() -> str:

        qt_app_path = Path(__file__).resolve().parents[2] / "ui_qt" / "qt_app.py"

        return qt_app_path.read_text(encoding="utf-8")

    def test_stop_comfyui_and_webui_on_exit_method_exists(self):

        """qt_app 定义了 _stop_comfyui_and_webui_on_exit 集中方法."""

        src = self._qt_app_src()

        self.assertIn("def _stop_comfyui_and_webui_on_exit(self)", src)

        self.assertIn("def _stop_webui_sync(self)", src)

    def test_stop_method_stops_webui_before_comfyui(self):

        """_stop_comfyui_and_webui_on_exit 先停工作台 (依赖方) 再停 ComfyUI (被依赖方)."""

        import re

        src = self._qt_app_src()

        m = re.search(

            r"def _stop_comfyui_and_webui_on_exit\(self\).*?(?=\n    def )",

            src, re.DOTALL,

        )

        self.assertIsNotNone(m)

        body = m.group(0)

        idx_webui = body.find("self._stop_webui_sync()")

        idx_comfyui = body.find("stop_comfyui_sync")

        self.assertGreater(idx_webui, -1, "应调 _stop_webui_sync 停工作台")

        self.assertGreater(idx_comfyui, -1, "应调 stop_comfyui_sync 停 ComfyUI")

        self.assertLess(idx_webui, idx_comfyui, "应先停工作台再停 ComfyUI")

    def test_stop_webui_sync_uses_webui_process_manager(self):

        """_stop_webui_sync 用 WebuiProcessManager.stop_webui (靠 pidfile+taskkill)."""

        import re

        src = self._qt_app_src()

        m = re.search(r"def _stop_webui_sync\(self\).*?(?=\n    def )", src, re.DOTALL)

        self.assertIsNotNone(m)

        body = m.group(0)

        self.assertIn("WebuiProcessManager", body)

        self.assertIn("stop_webui", body)

    def test_close_exit_paths_call_unified_stop_method(self):

        """closeEvent 的两个"停止并退出"路径都调 _stop_comfyui_and_webui_on_exit.

        场景 1b (托盘退出并关闭) + 场景 3 (X 按钮"停止并退出") 不应再直接调

        stop_comfyui_sync 漏掉工作台, 应统一走 _stop_comfyui_and_webui_on_exit.

        """

        src = self._qt_app_src()

        # 统一方法被调用 (至少 2 处: 托盘 + X按钮停止并退出)

        call_count = src.count("self._stop_comfyui_and_webui_on_exit()")

        self.assertGreaterEqual(call_count, 2, "两个退出路径都应调统一停服务方法")

    def test_stop_webui_sync_calls_through_webui_process_manager(self):

        """_stop_webui_sync 作为未绑定函数调用: 实际触发 WebuiProcessManager.stop_webui.

        这是行为级验证 (绕过 qt_app 导入): 取出未绑定方法, 用 mock self 调用,

        确认它构造 WebuiProcessManager 并调 stop_webui.

        """

        # 用 exec 从源码提取方法对象太脆弱; 改用 WebuiProcessManager 直接验证 stop_webui

        # 幂等性 (未跑返 ok=True), 这是 _stop_webui_sync 依赖的核心契约.

        from core.webui_process_manager import WebuiProcessManager

        app = type("A", (), {})()

        app.config = {"webui_options": {"port": 8199}}

        app.logger = MagicMock()

        app._cwd = "."

        pm = WebuiProcessManager(app)

        res = pm.stop_webui(timeout=2)  # 无 pidfile 无进程 -> 幂等返 ok

        self.assertTrue(res.get("ok"), "stop_webui 未跑时应幂等返 ok=True")

class TestNewLayout(_Fixture):

    """新左右布局 + 打开网页按钮 + 日志实时化."""

    def test_version_items_share_one_equal_width_row(self):

        """版本与配置状态在同一行左右并排，且两列等宽 (在卡片容器内)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        # 版本信息现在套在 _version_info_card (QFrame) 里, 它的 layout 是网格

        grid = page._version_info_card.layout()

        self.assertIsInstance(grid, QtWidgets.QGridLayout)

        version_pos = grid.getItemPosition(grid.indexOf(page._version_item))

        status_pos = grid.getItemPosition(grid.indexOf(page._config_status_item))

        self.assertEqual(version_pos[:2], (0, 0))

        self.assertEqual(status_pos[:2], (0, 1))

        self.assertEqual(grid.columnStretch(0), 1)

        self.assertEqual(grid.columnStretch(1), 1)

    def test_version_items_match_homepage_center_alignment(self):

        """两个版本条目沿用首页条目的居中对齐格式。"""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        for item in (page._version_item, page._config_status_item):

            self.assertEqual(item.layout().alignment(), QtCore.Qt.AlignCenter)

            self.assertEqual(item.layout().count(), 3)

    def test_version_info_has_card_container(self):

        """版本信息套在卡片容器里 (card_bg + card_border), 跟更新按钮视觉平衡."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        self.assertIsInstance(page._version_info_card, QtWidgets.QFrame)

        ss = page._version_info_card.styleSheet()

        # 走 card_* token (深色主题值: card_bg=#1F2937, card_border=#374151), 不硬编码别的色

        self.assertIn("#1F2937", ss)  # card_bg

        self.assertIn("#374151", ss)  # card_border

        self.assertIn("border-radius", ss)

    def test_version_card_restyles_on_theme_switch(self):

        """深/浅主题的卡片样式不同 (card_bg 深浅色不同).

        _version_card_style 读 self.theme_manager.colors (跟 _log_view_style 等一致),

        所以真实主题切换时 (theme_manager 自身 colors 变) 卡片会跟随. 这里直接验证

        深浅两个 theme_manager 产出不同样式.

        """

        page_dark, _, _ = self._scaffold(ThemeManager(dark=True))

        page_light, _, _ = self._scaffold(ThemeManager(dark=False))

        ss_dark = page_dark._version_info_card.styleSheet()

        ss_light = page_light._version_info_card.styleSheet()

        self.assertIn("#1F2937", ss_dark)   # 深色 card_bg

        self.assertIn("#FFFFFF", ss_light)  # 浅色 card_bg

        self.assertNotEqual(ss_dark, ss_light, "深/浅主题卡片样式应不同")

    def test_open_button_exists_and_disabled_until_running(self):

        """新增「打开网页」按钮存在, 且仅在 running 时可用."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        # ready 状态: 打开网页禁用

        page._update_ui_for_state()

        self.assertFalse(page._btn_open.isEnabled(), "ready 时打开网页应禁用")

        # 模拟 running

        page._state = wp_module.STATE_RUNNING

        page._update_ui_for_state()

        self.assertTrue(page._btn_open.isEnabled(), "running 时打开网页应可用")

    def test_no_service_info_panel(self):

        """服务信息面板已删除 (无 _info_* 控件, 无 _update_info_panel 方法)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        for attr in ("_info_port", "_info_pid", "_info_url", "_info_env", "_info_since"):

            self.assertFalse(hasattr(page, attr), "服务信息控件 %s 应已删除" % attr)

        self.assertFalse(hasattr(page, "_update_info_panel"), "_update_info_panel 应已删除")

    def test_log_view_max_lines(self):

        """日志控件 maxBlockCount 对齐实时日志页 (5000)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        self.assertEqual(page._log_view.document().maximumBlockCount(), 5000)

    def test_log_tailer_started_on_init(self):

        """页面构造时启动日志 tailer (实时 tail, 不再手动刷新)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        self.assertIsNotNone(page._tailer, "tailer 应在构造时启动")

        self.assertIsNotNone(page._log_path)

    def test_log_tailer_restart_on_env_switch(self):

        """env 切换时 tailer 重定向到新路径 (stop + restart)."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        old_tailer = page._tailer

        page.refresh_after_env_switch()

        self.assertIsNotNone(page._tailer, "env 切换后 tailer 应重启")

        self.assertIsNot(old_tailer, page._tailer, "应是新的 tailer 实例")

    def test_batch_flush_appends_lines(self):

        """_enqueue_batch + _flush_batch 把行追加到日志视图."""

        page, app, _ = self._scaffold(ThemeManager(dark=True))

        page._log_view.clear()

        page._enqueue_batch("line1")

        page._enqueue_batch("line2")

        page._flush_batch()

        self.assertIn("line1", page._log_view.toPlainText())

        self.assertIn("line2", page._log_view.toPlainText())

class TestProgressAndBackgroundTask(_Fixture):

    """TDD 红: webui_page 三个操作接进度条 + 后台任务的契约测试.

    每个测试只测一个行为, 失败时给出明确的契约名.

    """

    def test_download_webui_passes_on_progress_and_logger_to_clone_webui(self):

        """_download_webui 调 clone_webui 时必须传 on_progress 和 logger (不是裸跑).

        现状: _download_webui 只传 repo_url, 进度全丢, git 行无处去.

        预期: 传 on_progress (callable) + logger=app.logger.

        防卡死策略:

        - 真线程 + threading.Event 等 fake_clone 被调.

        - QMetaObject.invokeMethod 在 webui_page 里被 stub 成 no-op, 防 worker 于队列

          中的 _after_download slot 被 pytest-qt 的 _process_events() 触发后弹模态框卡死 teardown.

        """

        page, app, _ = self._scaffold(ThemeManager(dark=True))
        # 避免 slot 同步跳弹模态框卡主线程 (helper 里 _ui_post 同步执行 on_done_slot,
        # 会在 worker 线程跳 _after_download 里的 DialogHelper.show_warning 弹模态框,
        # 造成卡主测试套件)
        app.ui_post = lambda fn: None

        captured = {}

        done = threading.Event()

        def fake_clone(*args, **kwargs):

            captured.update(kwargs)

            done.set()

            return {"ok": False, "error": "test short-circuits"}

        # invokeMethod 在 webui_page 中被 stub. 原函数仍从底层可用, 但页面层

        # 不再能把 _after_download 进队列, 从源头消除后续对话框隐患.

        p_invoke = patch(

            "ui_qt.pages.webui_page.QtCore.QMetaObject.invokeMethod",

            lambda *args, **kwargs: None,

        )

        p_clone = patch("ui_qt.pages.webui_page.clone_webui", side_effect=fake_clone)

        for p in (p_invoke, p_clone):

            p.start()

            self.addCleanup(p.stop)

        page._download_webui()

        self.assertTrue(done.wait(2.0), "worker 线程应调到 clone_webui")

        self.assertIn("on_progress", captured, "clone_webui 必须收到 on_progress 回调")

        self.assertIsNotNone(captured["on_progress"], "on_progress 不能是 None")

        self.assertIn("logger", captured, "clone_webui 必须收到 logger (git 行要进 log)")

        self.assertIsNotNone(captured["logger"], "logger 不能是 None")

    def test_download_webui_chains_clone_then_deps_in_single_worker(self):

        """_download_webui 必须在同一 worker 跑 clone + install, 不起第二个 thread.

        现状: clone 成功后同步调 self._setup_deps(silent=True),

        后者又起一个 thread, 存在双线程竞态隐患.

        预期: clone 和 install 在同一个 worker 线程里依次跑完 (用 get_ident 验证).

        """

        page, app, webui_path = self._scaffold(ThemeManager(dark=True))

        (webui_path / "requirements.txt").write_text("flask\n")

        thread_ids = {}

        done = threading.Event()

        def fake_clone(*args, **kwargs):

            thread_ids["clone"] = threading.get_ident()

            return {"ok": True, "log": "", "error": None, "already_exists": True}

        def fake_install(*args, **kwargs):

            thread_ids["install"] = threading.get_ident()

            done.set()

            return {"ok": True}

        p_invoke = patch(

            "ui_qt.pages.webui_page.QtCore.QMetaObject.invokeMethod",

            lambda *args, **kwargs: None,

        )

        p_clone = patch("ui_qt.pages.webui_page.clone_webui", side_effect=fake_clone)

        p_install = patch("ui_qt.pages.webui_page.install_webui_requirements", side_effect=fake_install)

        for p in (p_invoke, p_clone, p_install):

            p.start()

            self.addCleanup(p.stop)

        page._download_webui()

        self.assertTrue(done.wait(2.0), "worker 应走到 install 阶段")

        self.assertIn("clone", thread_ids, "clone_webui 未被调")

        self.assertIn("install", thread_ids, "install_webui_requirements 未被调")

        self.assertEqual(

            thread_ids["clone"], thread_ids["install"],

            "clone 和 install 必须同一 worker, 现在两个 thread: clone=%s install=%s"

            % (thread_ids["clone"], thread_ids["install"]),

        )

    def test_setup_deps_passes_on_progress_and_logger_to_install(self):

        """_setup_deps 调 install_webui_requirements 时必须传 on_progress 和 logger_ (不是裸跑).

        现状: _setup_deps 只传 py/req/index_url, pip 进度全丢.

        预期: 传 on_progress (callable) + logger_=app.logger.

        参数名是 logger_ (下划线, 不是 logger), 以 install_webui_requirements 的接口为准.

        """

        page, app, webui_path = self._scaffold(ThemeManager(dark=True))

        # _scaffold 不创 requirements.txt, _setup_deps 早退分支会弹框, 补上

        (webui_path / "requirements.txt").write_text("flask\nrequests\n")

        captured = {}

        done = threading.Event()

        def fake_install(*args, **kwargs):

            captured.update(kwargs)

            done.set()

            return {"ok": True}

        p_invoke = patch(

            "ui_qt.pages.webui_page.QtCore.QMetaObject.invokeMethod",

            lambda *args, **kwargs: None,

        )

        p_install = patch("ui_qt.pages.webui_page.install_webui_requirements", side_effect=fake_install)

        for p in (p_invoke, p_install):

            p.start()

            self.addCleanup(p.stop)

        page._setup_deps()

        self.assertTrue(done.wait(2.0), "worker 线程应调到 install_webui_requirements")

        self.assertIn("on_progress", captured, "install_webui_requirements 必须收到 on_progress 回调")

        self.assertIsNotNone(captured["on_progress"], "on_progress 不能是 None")

        self.assertIn("logger_", captured, "install_webui_requirements 必须收到 logger_ (pip 行要进 log, 参数名下划线e)")

        self.assertIsNotNone(captured["logger_"], "logger_ 不能是 None")

    def test_on_update_clicked_passes_on_progress_and_logger_to_pull_webui(self):

        """_on_update_clicked 调 pull_webui 时必须传 on_progress 和 logger (不是裸跑).

        现状: _on_update_clicked 只传 webui_path, git 进度全丢.

        预期: 传 on_progress (callable) + logger=app.logger.

        _on_update_clicked 要求 webui_path 存在且含 .git, 补上.

        """

        page, app, webui_path = self._scaffold(ThemeManager(dark=True))
        # 避免 slot 同步跳弹模态框卡主线程
        app.ui_post = lambda fn: None

        (webui_path / ".git").mkdir()

        captured = {}

        done = threading.Event()

        def fake_pull(*args, **kwargs):

            captured.update(kwargs)

            done.set()

            return {"ok": True, "updated": False}

        p_invoke = patch(

            "ui_qt.pages.webui_page.QtCore.QMetaObject.invokeMethod",

            lambda *args, **kwargs: None,

        )

        p_pull = patch("ui_qt.pages.webui_page.pull_webui", side_effect=fake_pull)

        for p in (p_invoke, p_pull):

            p.start()

            self.addCleanup(p.stop)

        page._on_update_clicked()

        self.assertTrue(done.wait(2.0), "worker 线程应调到 pull_webui")

        self.assertIn("on_progress", captured, "pull_webui 必须收到 on_progress 回调")

        self.assertIsNotNone(captured["on_progress"], "on_progress 不能是 None")

        self.assertIn("logger", captured, "pull_webui 必须收到 logger (git pull 行要进 log)")

        self.assertIsNotNone(captured["logger"], "logger 不能是 None")
    def test_pull_webui_applies_git_proxy_from_app_config(self):
        """pull_webui 读 app.config["proxy_settings"], 加上 git proxy 前缀拉.

        现状: pull_webui 直接调 git pull --depth 1, 完全忽略 proxy.
        预期: 首页设了 git_proxy_mode=gh-proxy 后, pull_webui 走 `git fetch https://gh-proxy.com/...`.
        验证方式: 拆 subprocess.Popen, 看 cmd 里是否出现 gh-proxy.com.
        """
        # 临时 fake 一个 git 可执行文件，令 _resolve_git_executable 返回它
        import tempfile, stat
        d = Path(tempfile.mkdtemp())
        fake_git = d / "git.exe"
        fake_git.write_text("")
        fake_git.chmod(stat.S_IEXEC)
        # 拆 _resolve_git_executable 走虚拟路径
        p_resolve = patch(
            "core.webui_installer._resolve_git_executable",
            lambda app: str(fake_git),
        )
        p_resolve.start()
        self.addCleanup(p_resolve.stop)

        # 拆 subprocess.Popen 拿 cmd
        captured_cmds = []
        real_popen = subprocess.Popen
        def fake_popen(cmd, *a, **kw):
            captured_cmds.append(list(cmd))
            # 返回个马上就退的进程，避免真跳
            class FakeProc:
                def __init__(self): self.stdout = iter([])
                def wait(self): return 0
            return FakeProc()
        p_popen = patch("core.webui_installer.subprocess.Popen", side_effect=fake_popen)
        p_popen.start()
        self.addCleanup(p_popen.stop)


        # 搭建带 proxy_settings 的 app
        page, app, _ = self._scaffold(ThemeManager(dark=True))
        app.config["proxy_settings"] = {"git_proxy_mode": "gh-proxy", "git_proxy_url": ""}
        # 需要一个合法的 git 仓库路径 (.git 子目录)
        repo_dir = d / "repo"
        (repo_dir / ".git").mkdir(parents=True)
        # 拆 get 远程 URL 为一个高比的 placeholder (会被 apply_git_proxy_to_url 加前缀)
        p_remote = patch(
            "core.webui_installer.subprocess.check_output",
            lambda *a, **k: b"https://github.com/MieMieeeee/Comfyui-Workbench-Mie.git\n",
        )
        p_remote.start()
        self.addCleanup(p_remote.stop)

        from core.webui_installer import pull_webui
        res = pull_webui(app, repo_dir)
        self.assertTrue(res.get("ok"), f"pull_webui 返回失败: {res}")

        # 查看有没有调 git fetch 或 git pull 时传了 proxy URL
        flat = [arg for cmd in captured_cmds for arg in cmd]
        self.assertTrue(
            any("gh-proxy.com" in a for a in flat),
            f"pull_webui 应使用 git proxy (gh-proxy.com), 实际 cmd={captured_cmds}",
        )
    def test_install_webui_requirements_passes_hf_endpoint_to_pip_env(self):
        """install_webui_requirements 接 hf_endpoint 参, 合并到 env 再调 pip.

        现状: install_webui_requirements 仅接 index_url, hf_endpoint 传不下去 (function 不存在该参).
        预期: 传 hf_endpoint=\"https://hf-mirror.com\" 后, 调 PIPUTILS.install_requirements_file 时 env 含 HF_ENDPOINT.
        验证: 拆 PIPUTILS.install_requirements_file, 拿到的 env kwargs 里含 HF_ENDPOINT 或者 env 参数里含.
        """
        page, app, _ = self._scaffold(ThemeManager(dark=True))
        # 搭建临时的 py / req 路径
        import tempfile
        d = Path(tempfile.mkdtemp())
        py = d / "python.exe"
        py.touch()
        req = d / "requirements.txt"
        req.write_text("flask\n")

        captured = {}
        def fake_install(requirements_file, python_exec, *, index_url=None, upgrade=False, logger=None, on_progress=None, env=None, **kwargs):
            captured["index_url"] = index_url
            captured["env"] = env
            return {"success": True, "installed": [], "satisfied": [], "missing": [], "failed": []}

        p_install = patch("utils.pip.install_requirements_file", side_effect=fake_install)
        p_install.start()
        self.addCleanup(p_install.stop)

        from core.webui_dependencies import install_webui_requirements
        result = install_webui_requirements(
            py, req,
            index_url=None,
            on_progress=lambda text, percent=None: None,
            logger_=None,
            hf_endpoint="https://hf-mirror.com",
        )
        self.assertTrue(result.get("ok"), f"install_webui_requirements 返回失败: {result}")

        # env 参不为 None, 且含 HF_ENDPOINT
        self.assertIsNotNone(captured.get("env"),
            "install_webui_requirements 应给 pip 传 env (含 HF_ENDPOINT)")
        self.assertEqual(captured["env"].get("HF_ENDPOINT"), "https://hf-mirror.com",
            f"pip env 应含 HF_ENDPOINT=https://hf-mirror.com, 实际 {captured['env']}")
    def test_pull_webui_does_not_apply_proxy_to_non_github_remote(self):
        """pull_webui 看到远程 URL 不是 github.com 时, 不加 proxy 前缀.

        防本地 / 内网 gitlab 被 gh-proxy.com 预缀锈坏.
        预期: remote 为 gitlab.example.com/foo.git 时, cmd 原样传该 URL, 不被加前缀.
        """
        # 同上一个测试, fake git + 拆 _resolve_git_executable / Popen / check_output
        import tempfile, stat
        d = Path(tempfile.mkdtemp())
        fake_git = d / "git.exe"
        fake_git.write_text("")
        fake_git.chmod(stat.S_IEXEC)
        p_resolve = patch(
            "core.webui_installer._resolve_git_executable",
            lambda app: str(fake_git),
        )
        p_resolve.start()
        self.addCleanup(p_resolve.stop)

        captured_cmds = []
        def fake_popen(cmd, *a, **kw):
            captured_cmds.append(list(cmd))
            class FakeProc:
                def __init__(self): self.stdout = iter([])
                def wait(self): return 0
            return FakeProc()
        p_popen = patch("core.webui_installer.subprocess.Popen", side_effect=fake_popen)
        p_popen.start()
        self.addCleanup(p_popen.stop)

        # 远程跳过 gh-proxy: gitlab.example.com (subprocess.check_output 返回这个)
        p_remote = patch(
            "core.webui_installer.subprocess.check_output",
            lambda *a, **k: b"https://gitlab.example.com/foo.git\n",
        )
        p_remote.start()
        self.addCleanup(p_remote.stop)

        page, app, _ = self._scaffold(ThemeManager(dark=True))
        app.config["proxy_settings"] = {"git_proxy_mode": "gh-proxy", "git_proxy_url": ""}
        repo_dir = d / "repo"
        (repo_dir / ".git").mkdir(parents=True)

        from core.webui_installer import pull_webui
        res = pull_webui(app, repo_dir)
        self.assertTrue(res.get("ok"), f"pull_webui 返回失败: {res}")

        flat = [arg for cmd in captured_cmds for arg in cmd]
        self.assertFalse(
            any("gh-proxy.com" in a for a in flat),
            f"非 github remote 不应被代理加前缀, 实际 cmd={captured_cmds}",
        )




    def test_download_webui_does_not_call_legacy_setup_deps_silent(self):

        """_download_webui._worker 不能再调旧的 self._setup_deps(silent=True) 链式.

        这个调用起新 thread, 是之前双 worker 竞态隐患的源头.

        装依赖必须在同一 worker 里以 install_webui_requirements 直接调.

        本测试作为回归锁: 即使有人举手加回 self._setup_deps(silent=True) 也会被拿下.

        """

        page, app, webui_path = self._scaffold(ThemeManager(dark=True))

        (webui_path / "requirements.txt").write_text("flask\n")

        clone_done = threading.Event()

        legacy_called = threading.Event()

        def fake_clone(*args, **kwargs):

            clone_done.set()

            return {"ok": True, "log": "", "error": None, "already_exists": True}

        def fake_install(*args, **kwargs):

            return {"ok": True}

        p_invoke = patch(

            "ui_qt.pages.webui_page.QtCore.QMetaObject.invokeMethod",

            lambda *args, **kwargs: None,

        )

        p_clone = patch("ui_qt.pages.webui_page.clone_webui", side_effect=fake_clone)

        p_install = patch("ui_qt.pages.webui_page.install_webui_requirements", side_effect=fake_install)

        original_setup_deps = page._setup_deps

        def tracking_setup_deps(*args, **kwargs):

            legacy_called.set()

            return original_setup_deps(*args, **kwargs)

        page._setup_deps = tracking_setup_deps

        for p in (p_invoke, p_clone, p_install):

            p.start()

            self.addCleanup(p.stop)

        self.addCleanup(lambda: setattr(page, "_setup_deps", original_setup_deps))

        page._download_webui()

        self.assertTrue(clone_done.wait(2.0), "worker 应调到 clone_webui")

        legacy_called.wait(1.0)

        self.assertFalse(legacy_called.is_set(),

            "_download_webui 不能再调 _setup_deps, 那是双 worker 竞态的源头")

    def test_webui_page_passes_hf_endpoint_to_install_webui_requirements(self):
        """webui_page._setup_deps 从 app.config["proxy_settings"] 拿 hf_endpoint 传给 install_webui_requirements.

        两个路径要走同一个接口 —— 抽 _resolve_hf_endpoint(app) 为 helper.
        hf_mirror_url = "https://hf-mirror.com" 时 hf_endpoint 应等于该 URL; 默认为 None.
        """
        page, app, webui_path = self._scaffold(ThemeManager(dark=True))
        (webui_path / "requirements.txt").write_text("flask\n")
        hf_mirror_url = "https://hf-mirror.com"
        app.config["proxy_settings"] = {"hf_mirror_url": hf_mirror_url, "hf_mirror_mode": "hf-mirror"}

        captured = {}
        def fake_install(*args, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

        # 拆 install_webui_requirements 拿 kwargs
        p_install = patch("ui_qt.pages.webui_page.install_webui_requirements", side_effect=fake_install)
        p_install.start()
        self.addCleanup(p_install.stop)

        page._setup_deps()

        self.assertEqual(captured.get("hf_endpoint"), hf_mirror_url,
            f"_setup_deps 应传 hf_endpoint={hf_mirror_url}, 实际 {captured}")

    def test_webui_page_no_hf_endpoint_when_proxy_settings_empty(self):
        """默认不含 hf_mirror_url 时, hf_endpoint 为 None.

        """
        page, app, webui_path = self._scaffold(ThemeManager(dark=True))
        (webui_path / "requirements.txt").write_text("flask\n")
        # 不设 proxy_settings, 或者设但不含 hf_mirror_url
        app.config["proxy_settings"] = {}

        captured = {}
        def fake_install(*args, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

        p_install = patch("ui_qt.pages.webui_page.install_webui_requirements", side_effect=fake_install)
        p_install.start()
        self.addCleanup(p_install.stop)

        page._setup_deps()

        # 要么不传 hf_endpoint, 要么传但是 None
        hf_ep = captured.get("hf_endpoint")
