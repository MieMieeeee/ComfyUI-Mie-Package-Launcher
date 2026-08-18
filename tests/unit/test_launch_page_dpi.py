"""PR #3-RED launch_page 尺寸跟随失败测试。

目标：
- right_container 固定宽 200 → 1.25x → 250
- quick dir 按钮 minHeight 32 → 1.25x → 40
- 内部级联：launch_controls_section._port_edit(60→75) / _gpu_combo(min 220→275) / _cpath_btn(32→40)
- environment_section 级联 _min/_fixed 跟随
- version_section 级联 timeout_combo(85→106)
- btn_toggle / btn_action 内部 QLabel 字号变更
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5 import QtWidgets

from ui_qt.theme_manager import ThemeManager
from ui_qt.theme_styles import ThemeStyles


class FakeApp:
    """最小化的 fake app，避免启动 LaunchPage 时触发数据库/后台服务等真实依赖。"""
    def __init__(self, tm: ThemeManager):
        self.tm = tm
        self.config = {
            "paths": {"comfyui_root": ".", "python_path": "python"},
            "environments": [
                {"id": "env_default", "name": "默认环境",
                 "comfyui_root": ".", "python_path": "python"}
            ],
            "active_env_id": "env_default",
            "launch_options": {"default_port": 8188},
        }

    def get_active_paths(self):
        from config.migrations import resolve_active_paths
        try:
            return resolve_active_paths(self.config)
        except Exception:
            return {"comfyui_root": ".", "python_path": "python"}

    def save_config(self):
        pass

    @property
    def services(self):
        class _S:
            class _P:
                def toggle(self):
                    pass
                def probe(self, *a, **kw):
                    return {}
            process = _P()

            class _C:
                def save(self, cfg):
                    return cfg
            config = _C()
        return _S()

    class logger:
        @staticmethod
        def info(*a, **kw):
            pass


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    yield app


def _px(styles: ThemeStyles, base: int) -> int:
    return styles._px(base)


def _pt(styles: ThemeStyles, base: int) -> int:
    return styles._pt(base)


def test_launchpage_right_container_fixed_width_follows_scale(qapp):
    tm = ThemeManager(dark=True, scale=1.0)
    app = FakeApp(tm)
    from ui_qt.pages.launch_page import LaunchPage
    page = LaunchPage(app, tm)
    tm.register_listener(page.update_theme)
    assert page.right_container.width() == _px(tm.styles, 200)

    tm.set_scale(1.25)
    assert page.right_container.width() == _px(tm.styles, 200), \
        f"right_container 1.25x 宽应为 {_px(tm.styles,200)}，实 {page.right_container.width()}"


def test_launchpage_quickdir_min_height_follows_scale(qapp):
    tm = ThemeManager(dark=True, scale=1.0)
    app = FakeApp(tm)
    from ui_qt.pages.launch_page import LaunchPage
    page = LaunchPage(app, tm)
    tm.register_listener(page.update_theme)
    buttons = getattr(page, "_quick_dir_buttons", [])
    assert len(buttons) > 0
    assert buttons[0].minimumHeight() == _px(tm.styles, 32)

    tm.set_scale(1.25)
    target = _px(tm.styles, 32)  # 40
    for b in buttons:
        assert b.minimumHeight() == target, \
            f"quick dir 按钮 1.25x 最小高应为 {target}，实 {b.minimumHeight()}"


def test_launchpage_controls_cascade_port_edit(qapp):
    tm = ThemeManager(dark=True, scale=1.0)
    app = FakeApp(tm)
    from ui_qt.pages.launch_page import LaunchPage
    page = LaunchPage(app, tm)
    tm.register_listener(page.update_theme)
    port = page.launch_controls_section._port_edit
    assert port.width() == _px(tm.styles, 60)

    tm.set_scale(1.25)
    assert port.width() == _px(tm.styles, 60), \
        f"port_edit 1.25x 宽应为 {_px(tm.styles,60)}，实 {port.width()}"


def test_launchpage_controls_cascade_gpu_combo_min(qapp):
    tm = ThemeManager(dark=True, scale=1.0)
    app = FakeApp(tm)
    from ui_qt.pages.launch_page import LaunchPage
    page = LaunchPage(app, tm)
    tm.register_listener(page.update_theme)
    combo = page.launch_controls_section._gpu_combo
    assert combo.minimumWidth() == _px(tm.styles, 220)

    tm.set_scale(1.25)
    assert combo.minimumWidth() == _px(tm.styles, 220), \
        f"gpu_combo 1.25x minWidth 应为 {_px(tm.styles,220)}，实 {combo.minimumWidth()}"
