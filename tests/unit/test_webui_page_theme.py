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
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

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

    def test_status_dot_color_changes_with_theme(self):
        """状态圆点颜色随深/浅主题切换 (绿: 深色 #10B981 / 浅色 #059669)."""
        page, app, _ = self._scaffold(ThemeManager(dark=True))
        page._state = wp_module.STATE_READY
        page._update_ui_for_state()
        self.assertIn("#10B981", page._status_dot.styleSheet())
        # 切浅色
        tm_light = ThemeManager(dark=False)
        page.theme_manager = tm_light
        page.update_theme(tm_light.styles)
        self.assertIn("#059669", page._status_dot.styleSheet())


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


if __name__ == "__main__":
    unittest.main()
