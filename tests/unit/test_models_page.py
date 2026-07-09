"""Tests for ui_qt.pages.models_page.ModelsPage multi-library UI."""

import os
import yaml
from pathlib import Path
from unittest.mock import MagicMock
import pytest

pytest.importorskip("PyQt5")


def _make_app(tmp_path, libs=None, yaml_text=None):
    from services.model_path_service import ModelPathService
    comfyui_dir = tmp_path / "ComfyUI"
    comfyui_dir.mkdir(parents=True, exist_ok=True)
    if yaml_text is not None:
        (comfyui_dir / "extra_model_paths.yaml").write_text(yaml_text, encoding="utf-8")
    app = MagicMock()
    app.config = {"paths": {"comfyui_root": str(tmp_path)}, "models": {}}
    if libs:
        app.config["models"]["external_libraries"] = libs
    services = MagicMock()
    services.model_path = ModelPathService(app)
    app.services = services
    app.services.config = MagicMock()
    return app


def _make_page(qtbot, app, theme_styles):
    from ui_qt.pages.models_page import ModelsPage
    page = ModelsPage(app=app, theme_manager=theme_styles)
    qtbot.addWidget(page)
    return page


class TestModelsPageEmptyState:
    def test_no_libraries_renders_empty_list(self, qtbot, tmp_path):
        from ui_qt.theme_manager import ThemeManager
        theme = ThemeManager(dark=True)
        app = _make_app(tmp_path)
        page = _make_page(qtbot, app, theme)
        page.refresh_from_config()
        # library list shows the empty message
        if hasattr(page, "library_list"):
            assert page.library_list.count() == 0
        # status row shows zero
        if hasattr(page, "status_label"):
            assert "0" in page.status_label.text()


class TestModelsPageMultiLibrary:
    def test_two_libraries_appear_in_list(self, qtbot, tmp_path):
        from ui_qt.theme_manager import ThemeManager
        theme = ThemeManager(dark=True)
        # Pre-populate libs through the service so the page reads them on refresh.
        app = _make_app(tmp_path)
        app.services.model_path.add_library(str(tmp_path / "Alpha"))
        app.services.model_path.add_library(str(tmp_path / "Beta"))
        page = _make_page(qtbot, app, theme)
        page.refresh_from_config()
        # Both entries show up.
        names = [page.library_list.item(i).text()
                 for i in range(page.library_list.count())]
        joined = "\n".join(names)
        assert "Alpha" in joined
        assert "Beta" in joined

    def test_programmatic_add_library_selects_new_entry(self, qtbot, tmp_path):
        from ui_qt.theme_manager import ThemeManager
        theme = ThemeManager(dark=True)
        app = _make_app(tmp_path)
        page = _make_page(qtbot, app, theme)
        # Add directly through service
        (tmp_path / "Gamma").mkdir()
        lib = app.services.model_path.add_library(str(tmp_path / "Gamma"))
        page.refresh_from_config()
        page.select_library(lib["id"])
        # Right panel reflects the selected lib's base_path
        assert str(tmp_path / "Gamma") in page.editor_panel["base_path_edit"].text()
