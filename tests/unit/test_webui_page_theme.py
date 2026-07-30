"""WebuiPage 主题一致性测试.

锁死 webui_page 走 theme_manager (而非硬编码 hex), 跟 launch_page / models_page 一致.
验证:
1. 关键按钮控件 stylesheet 含 primary_button_style 的品牌色 (#7F56D9), 不含旧硬编码 (#4a90e2 等).
2. 日志视图走 token (input_readonly_*), 不含旧硬编码 (#1e1e1e).
3. update_theme() 不抛异常, 切深/浅主题后状态点颜色随之变 (#10B981 深色 / #059669 浅色).
4. WebuiConfigDialog 能构造 (继承 FramelessDraggableDialog), get_values() 结构正确.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

from ui_qt.pages import webui_page as wp_module
from ui_qt.pages.webui_page import WebuiPage, WebuiConfigDialog
from ui_qt.theme_manager import ThemeManager


def _make_app(cwd, webui_path, py_path):
    """构造最小 app (跟 test_webui_page_deps_cache 一致)."""
    app = type("A", (), {})()
    app._cwd = str(cwd)
    app.config = {
        "environments": [
            {"id": "env_a", "comfyui_root": str(cwd), "python_path": str(py_path)},
        ],
        "active_env_id": "env_a",
        "webui_options": {"port": 8199, "display_host": "127.0.0.1"},
    }
    app.logger = MagicMock()
    app.pypi_proxy_mode = MagicMock()
    app.pypi_proxy_mode.get = lambda: "none"
    app.pypi_proxy_url = MagicMock()
    app.pypi_proxy_url.get = lambda: ""
    app.custom_port = MagicMock()
    app.custom_port.get = lambda: "8188"
    return app


class _Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _make_page(self, webui_path, py_path, theme_manager):
        cwd = webui_path.parent
        app = _make_app(cwd, webui_path, py_path)
        _ok_dep = {"ok": True, "missing": [], "available": ["flask", "requests", "websockets"]}
        with patch("core.webui_process_manager.WebuiProcessManager.is_running", return_value=False), \
             patch("ui_qt.pages.webui_page.check_webui_dependencies", return_value=_ok_dep):
            page = WebuiPage(app=app, theme_manager=theme_manager)
        try:
            page._state_check_timer.stop()
        except Exception:
            pass
        return page


class TestThemeNoHardcodedHex(_Fixture):

    def test_primary_button_uses_brand_color(self):
        """主按钮 stylesheet 含品牌紫 #7F56D9 (primary_button_style), 不含旧蓝 #4a90e2."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            webui_path = d / "Comfyui-Workbench-Mie"
            (webui_path / "app").mkdir(parents=True)
            (webui_path / "app" / "flask_app.py").write_text("# stub")
            py = d / "python.exe"
            py.touch()
            page = self._make_page(webui_path, py, ThemeManager(dark=True))
            ss = page._btn_primary.styleSheet()
            self.assertIn("#7F56D9", ss, "主按钮应走 primary_button_style 品牌色")
            self.assertNotIn("#4a90e2", ss, "主按钮不应残留旧硬编码蓝")
            self.assertNotIn("#5cb85c", ss)

    def test_secondary_and_config_buttons_not_hardcoded(self):
        """二级/配置按钮走 secondary_button_style, 不含旧硬编码绿/灰."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            webui_path = d / "Comfyui-Workbench-Mie"
            (webui_path / "app").mkdir(parents=True)
            (webui_path / "app" / "flask_app.py").write_text("# stub")
            py = d / "python.exe"
            py.touch()
            page = self._make_page(webui_path, py, ThemeManager(dark=True))
            for btn in (page._btn_secondary, page._btn_config):
                ss = btn.styleSheet()
                self.assertNotIn("#5cb85c", ss, "二级按钮不应是旧硬编码绿")
                self.assertNotIn("#777", ss.replace("#777777", ""), "配置按钮不应是旧硬编码灰")

    def test_log_view_uses_token_not_vscode_colors(self):
        """日志视图走 input_readonly_* token, 不含旧 VS Code 色 #1e1e1e/#d4d4d4."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            webui_path = d / "Comfyui-Workbench-Mie"
            (webui_path / "app").mkdir(parents=True)
            (webui_path / "app" / "flask_app.py").write_text("# stub")
            py = d / "python.exe"
            py.touch()
            page = self._make_page(webui_path, py, ThemeManager(dark=True))
            ss = page._log_view.styleSheet()
            self.assertNotIn("#1e1e1e", ss, "日志视图不应是旧 VS Code 暗色")
            self.assertNotIn("#d4d4d4", ss)
            # 深色主题: input_readonly_bg = #1F2937 (来自 theme_styles token)
            self.assertIn("#1F2937", ss)


class TestUpdateTheme(_Fixture):

    def test_update_theme_no_exception(self):
        """update_theme() 不抛异常 (BasePage.update_theme + 页内控件重应用)."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            webui_path = d / "Comfyui-Workbench-Mie"
            (webui_path / "app").mkdir(parents=True)
            (webui_path / "app" / "flask_app.py").write_text("# stub")
            py = d / "python.exe"
            py.touch()
            tm = ThemeManager(dark=True)
            page = self._make_page(webui_path, py, tm)
            # 不抛即可
            page.update_theme()
            page.update_theme(tm.styles)

    def test_status_dot_color_changes_with_theme(self):
        """状态圆点颜色随深/浅主题切换 (绿: 深色 #10B981 / 浅色 #059669)."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            webui_path = d / "Comfyui-Workbench-Mie"
            (webui_path / "app").mkdir(parents=True)
            (webui_path / "app" / "flask_app.py").write_text("# stub")
            py = d / "python.exe"
            py.touch()
            tm_dark = ThemeManager(dark=True)
            page = self._make_page(webui_path, py, tm_dark)
            page._state = wp_module.STATE_READY
            page._update_ui_for_state()
            self.assertIn("#10B981", page._status_dot.styleSheet(), "深色主题绿点")
            # 切浅色
            tm_light = ThemeManager(dark=False)
            page.theme_manager = tm_light
            page.update_theme(tm_light.styles)
            self.assertIn("#059669", page._status_dot.styleSheet(), "浅色主题绿点")


class TestWebuiConfigDialog(_Fixture):

    def test_construct_and_get_values(self):
        """WebuiConfigDialog 能构造, get_values() 返回完整结构 (端口/host/url/extra/auto)."""
        initial = {
            "port": 8300,
            "display_host": "0.0.0.0",
            "auto_open": True,
            "download_url": "https://example.com/x.git",
            "extra_args": "--debug",
        }
        dlg = WebuiConfigDialog(parent=None, initial=initial, theme_manager=ThemeManager(dark=True))
        vals = dlg.get_values()
        self.assertEqual(vals["port"], 8300)
        self.assertEqual(vals["display_host"], "0.0.0.0")
        self.assertTrue(vals["auto_open_browser"])
        self.assertEqual(vals["download_url"], "https://example.com/x.git")
        self.assertEqual(vals["extra_args"], "--debug")

    def test_dialog_not_hardcoded_grey(self):
        """配置对话框容器 stylesheet 不含旧硬编码灰 #888."""
        dlg = WebuiConfigDialog(
            parent=None,
            initial={"port": 8199},
            theme_manager=ThemeManager(dark=True),
        )
        ss = dlg.container.styleSheet()
        self.assertNotIn("#888", ss)


if __name__ == "__main__":
    unittest.main()
