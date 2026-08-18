"""PR #4-RED webui_page 尺寸跟随失败测试。

目标 DPI 相关尺寸：
- port_edit setFixedWidth(60) → 1.25x → 75
- cpath_btn setFixedWidth(32) → 1.25x → 40
- btn_container setFixedWidth(180) → 1.25x → 225
- btn_primary setMinimumHeight(60) → 1.25x → 75
- btn_open setMinimumHeight(40) → 1.25x → 50
- btn_update setMinimumHeight(36) → 1.25x → 45
- btn_remove setMinimumHeight(36) → 1.25x → 45
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5 import QtWidgets

from ui_qt.theme_manager import ThemeManager
from ui_qt.theme_styles import ThemeStyles


class FakeServices:
    class _process:
        @staticmethod
        def probe(*a, **kw):
            return {}
    process = _process()

    class _plugin:
        pass
    plugin = _plugin()


class FakeApp:
    """最小 fake app。"""
    def __init__(self, tm: ThemeManager):
        self.tm = tm
        self.webui_options = {"port": 8199, "autorun": False, "extra_args": ""}
        self.config = {
            "environments": [{"id": "env_default", "name": "默认", "comfyui_root": ".", "python_path": "python"}],
            "active_env_id": "env_default",
            "webui": {"install_path": "."},
            "paths": {"comfyui_root": ".", "python_path": "python"},
        }
        self.services = FakeServices()

    def get_active_paths(self):
        return {"comfyui_root": ".", "python_path": "python", "comfyui_path": "./ComfyUI"}


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    yield app


def _px(styles: ThemeStyles, base: int) -> int:
    return styles._px(base)


def test_webui_page_port_edit_fixed_width_follows_scale(qapp):
    tm = ThemeManager(dark=True, scale=1.0)
    app = FakeApp(tm)
    from ui_qt.pages.webui_page import WebuiPage as WebUIPage
    page = WebUIPage(app, tm)
    tm.register_listener(page.update_theme)
    assert page._port_edit.width() == _px(tm.styles, 60)

    tm.set_scale(1.25)
    assert page._port_edit.width() == _px(tm.styles, 60), \
        f"WebUIPage port_edit 1.25x 宽应为 {_px(tm.styles,60)}，实 {page._port_edit.width()}"


def test_webui_page_primary_min_height_follows_scale(qapp):
    tm = ThemeManager(dark=True, scale=1.0)
    app = FakeApp(tm)
    from ui_qt.pages.webui_page import WebuiPage as WebUIPage
    page = WebUIPage(app, tm)
    tm.register_listener(page.update_theme)
    assert page._btn_primary.minimumHeight() == _px(tm.styles, 60)

    tm.set_scale(1.25)
    target = _px(tm.styles, 60)  # 75
    assert page._btn_primary.minimumHeight() == target, \
        f"WebUIPage _btn_primary 1.25x minHeight 应为 {target}，实 {page._btn_primary.minimumHeight()}"


def test_webui_page_btn_container_width_follows_scale(qapp):
    tm = ThemeManager(dark=True, scale=1.0)
    app = FakeApp(tm)
    from ui_qt.pages.webui_page import WebuiPage as WebUIPage
    page = WebUIPage(app, tm)
    tm.register_listener(page.update_theme)
    # btn_container 是按钮包装容器，固定宽
    container = page._btn_container
    assert container.width() == _px(tm.styles, 180)

    tm.set_scale(1.25)
    target = _px(tm.styles, 180)  # 225
    assert container.width() == target, \
        f"WebUIPage btn_container 1.25x 宽应为 {target}，实 {container.width()}"

