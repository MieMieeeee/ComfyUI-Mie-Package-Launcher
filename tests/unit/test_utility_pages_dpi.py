"""PR #5-RED utility 页尺寸跟随测试。

models_page: library_list setMinimumWidth(220)；mapping_table setMinimumHeight(360)；Action按钮 setFixedHeight(28)
version_page: pv_proxy_combo setFixedWidth(140)；timeout_combo setFixedWidth(85)；history_table minHeight 400
plugins_page: StatCard fixedHeight 36；dot 8x8；action_bar height 46；action_bar ab_count_label 34 宽
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5 import QtWidgets

from ui_qt.theme_manager import ThemeManager
from ui_qt.theme_styles import ThemeStyles


def _px(s: ThemeStyles, b: int) -> int:
    return s._px(b)


class FakeServices:
    class _P:
        @staticmethod
        def probe(*a, **kw):
            return {}
        @staticmethod
        def toggle(*a, **kw):
            pass
    process = _P()
    class _Plugin:
        pass
    plugin = _Plugin()
    class _Config:
        def save(self, cfg):
            return cfg
    config = _Config()


class FakeModelService:
    def scan_all(self, *a, **kw):
        return []
    def uninstall(self, *a, **kw):
        return True
    def cancel_scan(self):
        pass


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    yield app


# ---------------------------------------------------------------------------
# 1. ModelsPage
# ---------------------------------------------------------------------------
def test_models_page_library_min_width_follows_scale(qapp):
    tm = ThemeManager(dark=True, scale=1.0)
    config = {
        "environments": [{"id": "env_default", "name": "默认",
                          "comfyui_root": ".", "python_path": "python"}],
        "active_env_id": "env_default",
        "paths": {"comfyui_root": ".", "python_path": "python"},
    }

    class _App:
        services = FakeServices()
        def __init__(self): self.theme_manager = tm
        def get_active_paths(self):
            return {"comfyui_root": ".", "python_path": "python"}
        model_service = FakeModelService()
        config_holder = config

    from ui_qt.pages.models_page import ModelsPage
    page = ModelsPage(_App(), tm)
    tm.register_listener(page.update_theme)
    assert page.library_list.minimumWidth() == _px(tm.styles, 220)

    tm.set_scale(1.25)
    target = _px(tm.styles, 220)  # 275
    assert page.library_list.minimumWidth() == target, \
        f"ModelsPage library_list 1.25x minWidth 应为 {target}，实 {page.library_list.minimumWidth()}"


def test_models_page_mapping_table_min_height_follows_scale(qapp):
    tm = ThemeManager(dark=True, scale=1.0)
    config = {
        "environments": [{"id": "e", "name": "x", "comfyui_root": ".", "python_path": "python"}],
        "active_env_id": "e", "paths": {"comfyui_root": ".", "python_path": "python"},
    }

    class _App:
        services = FakeServices()
        def __init__(self): self.theme_manager = tm
        def get_active_paths(self):
            return {"comfyui_root": ".", "python_path": "python"}
        model_service = FakeModelService()
        config_holder = config

    from ui_qt.pages.models_page import ModelsPage
    page = ModelsPage(_App(), tm)
    tm.register_listener(page.update_theme)
    assert page.mapping_table.minimumHeight() == _px(tm.styles, 360)

    tm.set_scale(1.25)
    target = _px(tm.styles, 360)  # 450
    assert page.mapping_table.minimumHeight() == target, \
        f"ModelsPage mapping_table minHeight 应为 {target}，实 {page.mapping_table.minimumHeight()}"


# ---------------------------------------------------------------------------
# 2. VersionPage
# ---------------------------------------------------------------------------
def test_version_page_pv_proxy_combo_width_follows_scale(qapp):
    tm = ThemeManager(dark=True, scale=1.0)
    config = {
        "environments": [{"id": "e", "name": "x", "comfyui_root": ".", "python_path": "python"}],
        "active_env_id": "e", "paths": {"comfyui_root": ".", "python_path": "python"},
        "update_options": {"connect_timeout_sec": 30, "proxy_port": 10809},
    }

    class _App:
        services = FakeServices()
        def __init__(self): self.theme_manager = tm
        def get_active_paths(self):
            return {"comfyui_root": ".", "python_path": "python"}
        background_task_registry = None

    from ui_qt.pages.version_page import VersionPage
    page = VersionPage(_App(), tm)
    tm.register_listener(page.update_theme)
    assert page.pv_proxy_combo.width() == _px(tm.styles, 140)

    tm.set_scale(1.25)
    target = _px(tm.styles, 140)  # 175
    assert page.pv_proxy_combo.width() == target, \
        f"VersionPage pv_proxy_combo 宽应为 {target}，实 {page.pv_proxy_combo.width()}"
