"""Tests for ui_qt.pages.models_page.ModelsPage multi-library UI."""

from unittest.mock import MagicMock
import pytest

pytest.importorskip("PyQt5")


def _make_app(tmp_path):
    from services.model_path_service import ModelPathService
    comfyui_dir = tmp_path / "ComfyUI"
    comfyui_dir.mkdir(parents=True, exist_ok=True)
    app = MagicMock()
    app.config = {"paths": {"comfyui_root": str(tmp_path)}, "models": {}}
    services = MagicMock()
    services.model_path = ModelPathService(app)
    services.config = MagicMock()
    app.services = services
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
        if hasattr(page, "library_list"):
            assert page.library_list.count() == 0
        if hasattr(page, "status_label"):
            assert "0" in page.status_label.text()


class TestModelsPageMultiLibrary:
    def test_two_libraries_appear_in_list(self, qtbot, tmp_path):
        from ui_qt.theme_manager import ThemeManager
        theme = ThemeManager(dark=True)
        app = _make_app(tmp_path)
        (tmp_path / "Alpha").mkdir()
        (tmp_path / "Beta").mkdir()
        app.services.model_path.add_library(str(tmp_path / "Alpha"))
        app.services.model_path.add_library(str(tmp_path / "Beta"))
        page = _make_page(qtbot, app, theme)
        page.refresh_from_config()
        names = [page.library_list.item(i).text() for i in range(page.library_list.count())]
        joined = "\n".join(names)
        assert "Alpha" in joined
        assert "Beta" in joined

    def test_programmatic_add_library_selects_new_entry(self, qtbot, tmp_path):
        from ui_qt.theme_manager import ThemeManager
        theme = ThemeManager(dark=True)
        app = _make_app(tmp_path)
        (tmp_path / "Gamma").mkdir()
        lib = app.services.model_path.add_library(str(tmp_path / "Gamma"))
        page = _make_page(qtbot, app, theme)
        page.refresh_from_config()
        page.select_library(lib["id"])
        assert str(tmp_path / "Gamma") in page.editor_panel["base_path_edit"].text()


class TestModelsPageLibraryListContrast:
    """Library-list rows must read in the current theme (dark or light)."""

    def test_library_list_item_uses_theme_label_color(self, qtbot, tmp_path):
        from ui_qt.theme_manager import ThemeManager
        from PyQt5 import QtGui
        from services.model_path_service import ModelPathService
        theme = ThemeManager(dark=True)
        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "MyLib").mkdir()
        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}, "models": {}}
        services = MagicMock()
        services.config = MagicMock()
        services.model_path = ModelPathService(app)
        app.services = services
        services.model_path.add_library(str(tmp_path / "MyLib"))
        from ui_qt.pages.models_page import ModelsPage
        page = ModelsPage(app=app, theme_manager=theme)
        qtbot.addWidget(page)
        page.refresh_from_config()
        assert page.library_list.count() >= 1
        item = page.library_list.item(0)
        from ui_qt.theme_styles import ThemeColors
        tc = ThemeColors(dark=True)
        expected = QtGui.QColor(tc.get("label"))
        actual = QtGui.QColor(item.foreground().color())
        assert actual == expected, f"item fg {actual.name()} != label {expected.name()}"

    def test_library_list_widget_has_dark_stylesheet(self, qtbot, tmp_path):
        from ui_qt.theme_manager import ThemeManager
        theme = ThemeManager(dark=True)
        app = _make_app(tmp_path)
        page = _make_page(qtbot, app, theme)
        css = (page.library_list.styleSheet() or "").lower()
        assert ("background" in css) or ("color" in css), f"library_list needs explicit theming, got: {css!r}"

    def test_disabled_library_renders_with_muted_foreground(self, qtbot, tmp_path):
        from ui_qt.theme_manager import ThemeManager
        from PyQt5 import QtGui
        from services.model_path_service import ModelPathService
        theme = ThemeManager(dark=True)
        comfyui_dir = tmp_path / "ComfyUI"
        comfyui_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "Off").mkdir()
        (tmp_path / "On").mkdir()
        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}, "models": {}}
        services = MagicMock()
        services.config = MagicMock()
        services.model_path = ModelPathService(app)
        app.services = services
        off = services.model_path.add_library(str(tmp_path / "Off"))
        services.model_path.add_library(str(tmp_path / "On"))
        services.model_path.enable_library(off["id"], enabled=False)
        from ui_qt.pages.models_page import ModelsPage
        page = ModelsPage(app=app, theme_manager=theme)
        qtbot.addWidget(page)
        page.refresh_from_config()
        items = [page.library_list.item(i) for i in range(page.library_list.count())]
        offs = [it for it in items if "Off" in it.text()]
        ons = [it for it in items if "On" in it.text()]
        assert len(offs) == 1 and len(ons) == 1
        from ui_qt.theme_styles import ThemeColors
        tc = ThemeColors(dark=True)
        muted = QtGui.QColor(tc.get("label_muted"))
        bright = QtGui.QColor(tc.get("label"))
        off_qc = QtGui.QColor(offs[0].foreground().color())
        on_qc = QtGui.QColor(ons[0].foreground().color())
        assert off_qc == muted, f"disabled item fg {off_qc.name()} != muted {muted.name()}"
        assert on_qc == bright, f"enabled item fg {on_qc.name()} != label {bright.name()}"

