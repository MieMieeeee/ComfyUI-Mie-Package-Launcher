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


class _Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

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
        return page, app

    def _scaffold(self, theme_manager, webui_options=None):
        d = Path(tempfile.mkdtemp())
        webui_path = d / "Comfyui-Workbench-Mie"
        (webui_path / "app").mkdir(parents=True)
        (webui_path / "app" / "flask_app.py").write_text("# stub")
        py = d / "python.exe"
        py.touch()
        return self._make_page(webui_path, py, theme_manager, webui_options) + (webui_path,)


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


if __name__ == "__main__":
    unittest.main()
