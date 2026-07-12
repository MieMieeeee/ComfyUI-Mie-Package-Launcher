"""Tests for the persistent hint about external-library folder changes.

The models page must show a hint that informs the user: adding or removing
folders inside the external library directory requires clicking "Apply
Changes" to refresh the mapping table and rewrite extra_model_paths.yaml.

Run with the project'"'"'s canonical interpreter (see pyproject.toml
[project.optional-dependencies].test): .venv/Scripts/python.exe -m pytest ...
"""
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


def _make_page(qapp, tmp_path):
    from ui_qt.theme_manager import ThemeManager
    from ui_qt.pages.models_page import ModelsPage
    theme = ThemeManager(dark=True)
    app = _make_app(tmp_path)
    page = ModelsPage(app=app, theme_manager=theme)
    page.show()
    qapp.processEvents()
    return page


class TestRefreshHintLabel:
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

    def test_hint_label_is_in_page_main_layout(self, qapp, tmp_path):
        """The hint must be in the page'"'"'s own main layout, not tucked under the
        mapping card at the bottom. We check by walking the page'"'"'s children
        and asserting the hint is a direct child of the page (not nested in a card)."""
        page = _make_page(qapp, tmp_path)
        hint = page.mapping_hint_label
        # parentWidget chain: hint -> ... -> page. Assert no InfoCard in between.
        walker = hint.parentWidget()
        found_card = False
        while walker is not None and walker is not page:
            if walker.objectName() == "InfoCard":
                found_card = True
                break
            walker = walker.parentWidget()
        assert not found_card, \
            "hint should sit at the page level, not nested inside the 映射列表 InfoCard"

    def test_hint_label_sits_above_legacy_buttons(self, qapp, tmp_path):
        """The hint should appear visually above the legacy button row
        (仅使用内置 / 恢复配置), so users see it before they reach the editor."""
        page = _make_page(qapp, tmp_path)
        layout = page.layout()

        # Walk both widget items and sub-layouts so we can locate the hint
        # (a direct widget child) and btn_row (a sub-layout containing the
        # 仅使用内置 button) by their positions in the page main VBoxLayout.
        hint_idx = -1
        btn_row_idx = -1
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is None:
                continue
            if item.widget() is page.mapping_hint_label:
                hint_idx = i
                continue
            sub = item.layout()
            if sub is not None:
                for j in range(sub.count()):
                    child = sub.itemAt(j).widget()
                    if child is not None and getattr(child, "text", lambda: "")() == "仅使用内置":
                        btn_row_idx = i
                        break

        assert hint_idx >= 0, "hint must be a direct child of the page main layout"
        assert btn_row_idx >= 0, "legacy button row must still be present"
        assert hint_idx < btn_row_idx, \
            f"hint (idx {hint_idx}) must appear above the legacy button row (idx {btn_row_idx})"


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