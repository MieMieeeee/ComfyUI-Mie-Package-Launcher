"""Tests for the persistent hint about external-library folder changes.

The models page must show a hint that informs the user: adding or removing
folders inside the external library directory requires clicking "Apply
Changes" to refresh the mapping table and rewrite extra_model_paths.yaml.

These tests construct their own QApplication because pytest-qt is not
installed in this environment; the project'"'"'s conftest.py qtbot fixture
is broken (recursive self-dependency) so we sidestep both.
"""
import sys
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt5")


# --- QApplication bootstrap --------------------------------------------------

@pytest.fixture(scope="session")
def _qapp_session():
    from PyQt5 import QtWidgets
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


@pytest.fixture
def qapp(_qapp_session):
    """Session-scoped QApplication, exposed as a per-test fixture."""
    return _qapp_session


# --- helpers ---------------------------------------------------------------

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


def _make_page(qapp, tmp_path):
    from ui_qt.theme_manager import ThemeManager
    from ui_qt.pages.models_page import ModelsPage
    theme = ThemeManager(dark=True)
    app = _make_app(tmp_path)
    page = ModelsPage(app=app, theme_manager=theme)
    page.show()
    qapp.processEvents()
    return page


# --- tests -----------------------------------------------------------------

class TestMappingHintLabel:
    """The models page exposes a persistent hint about re-applying after folder changes."""

    def test_hint_label_attribute_exists(self, qapp, tmp_path):
        page = _make_page(qapp, tmp_path)
        assert hasattr(page, "mapping_hint_label"), \
            "ModelsPage must expose mapping_hint_label"

    def test_hint_label_text_mentions_apply(self, qapp, tmp_path):
        page = _make_page(qapp, tmp_path)
        text = page.mapping_hint_label.text()
        assert "应用更改" in text, f"hint must mention 应用更改: {text!r}"

    def test_hint_label_text_mentions_folder_change(self, qapp, tmp_path):
        page = _make_page(qapp, tmp_path)
        text = page.mapping_hint_label.text()
        assert ("新建" in text) or ("子文件夹" in text), \
            f"hint must mention folder-change trigger: {text!r}"

    def test_hint_label_uses_muted_color(self, qapp, tmp_path):
        from ui_qt.theme_styles import ThemeColors
        page = _make_page(qapp, tmp_path)
        muted = ThemeColors(dark=True).get("label_muted")
        css = page.mapping_hint_label.styleSheet() or ""
        assert muted in css, \
            f"hint must use label_muted color so it stays muted in any theme: {css!r}"

    def test_hint_label_is_sibling_of_mapping_table(self, qapp, tmp_path):
        page = _make_page(qapp, tmp_path)
        parent = page.mapping_hint_label.parentWidget()
        assert parent is not None
        layout = parent.layout()
        assert layout is not None
        items = [layout.itemAt(i).widget() for i in range(layout.count())]
        assert page.mapping_table in items, "table must be in same parent as hint"
        assert page.mapping_hint_label in items, "hint must be in mapping card layout"


class TestAddLibraryDialogMentionsFolderRefresh:
    """The success dialog after adding a library must remind the user about folder refresh."""

    def test_source_message_mentions_apply(self):
        import inspect
        from ui_qt.pages.models_page import ModelsPage
        src = inspect.getsource(ModelsPage._on_add_library)
        assert "应用更改" in src, \
            "_on_add_library must mention 应用更改 so users know the cadence"
        assert ("新建" in src) or ("子文件夹" in src), \
            "_on_add_library must mention the folder-change trigger"