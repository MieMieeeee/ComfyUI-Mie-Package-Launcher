"""Tests for the persistent hint about external-library folder changes.

The models page must show a hint that informs the user: adding or removing
folders inside the external library directory requires clicking "Apply
Changes" to refresh the mapping table and rewrite extra_model_paths.yaml.

The hint and the global yaml-management actions (应用更改, 打开 yaml,
仅使用内置, 恢复配置) belong in a single card at the top of the page —
same pattern as the kernel version management page's "当前版本信息" card.

Run with the project canonical interpreter (see pyproject.toml
[project.optional-dependencies].test): .venv/Scripts/python.exe -m pytest ...
"""
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtCore, QtWidgets  # noqa: E402  (after importorskip)


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


class TestGlobalActionsCard:
    """The hint + global yaml-management actions live together in one card at the top."""

    def _card(self, page):
        """The page must expose the global actions card."""
        assert hasattr(page, "_global_actions_card"), \
            "ModelsPage must expose _global_actions_card"
        return page._global_actions_card

    def test_card_exists_and_uses_info_card(self, qapp, tmp_path):
        page = _make_page(qapp, tmp_path)
        card = self._card(page)
        # InfoCard sets objectName so other widgets can find it.
        assert card.objectName() == "InfoCard", \
            f"global actions card must be an InfoCard, got objectName={card.objectName()!r}"

    def test_card_sits_above_main_split(self, qapp, tmp_path):
        page = _make_page(qapp, tmp_path)
        card = self._card(page)
        # The card should be a child of the page (page-level), and appear in the
        # page main layout before the QSplitter.
        layout = page.layout()
        card_idx = layout.indexOf(card)
        assert card_idx >= 0, "card must be in the page main layout"
        # Walk past the card to find the QSplitter; card must precede it.
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if isinstance(w, QtWidgets.QSplitter):
                splitter_idx = i
                break
        else:
            pytest.fail("page must contain a QSplitter for the library list / editor split")
        assert card_idx < splitter_idx, \
            f"global actions card (idx {card_idx}) must appear above the main split (idx {splitter_idx})"

    def test_hint_is_in_global_actions_card(self, qapp, tmp_path):
        page = _make_page(qapp, tmp_path)
        card = self._card(page)
        hint = page.mapping_hint_label
        # hint's parent chain must lead to the global card.
        walker = hint.parentWidget()
        while walker is not None and walker is not page:
            if walker is card:
                return  # found the card in the chain
            walker = walker.parentWidget()
        pytest.fail("mapping_hint_label must be a descendant of _global_actions_card")

    def test_apply_button_is_in_global_actions_card(self, qapp, tmp_path):
        page = _make_page(qapp, tmp_path)
        apply_btn = next(
            (w for w in page.findChildren(QtWidgets.QPushButton) if w.text() == "应用更改"),
            None,
        )
        assert apply_btn is not None, "page must have an 应用更改 button"
        # The apply button must NOT be inside the per-library editor card.
        editor_card = page.editor_panel["card"]
        walker = apply_btn.parentWidget()
        while walker is not None and walker is not page:
            if walker is editor_card:
                pytest.fail("应用更改 must not live inside the per-library editor card")
            walker = walker.parentWidget()
        # And it SHOULD be inside the global actions card.
        walker = apply_btn.parentWidget()
        while walker is not None and walker is not page:
            if walker is page._global_actions_card:
                return
            walker = walker.parentWidget()
        pytest.fail("应用更改 must live inside _global_actions_card")

    def test_open_yaml_button_is_in_global_actions_card(self, qapp, tmp_path):
        page = _make_page(qapp, tmp_path)
        yaml_btn = next(
            (w for w in page.findChildren(QtWidgets.QPushButton) if w.text() == "打开 yaml"),
            None,
        )
        assert yaml_btn is not None, "page must have a 打开 yaml button"
        editor_card = page.editor_panel["card"]
        walker = yaml_btn.parentWidget()
        while walker is not None and walker is not page:
            if walker is editor_card:
                pytest.fail("打开 yaml must not live inside the per-library editor card")
            walker = walker.parentWidget()
        walker = yaml_btn.parentWidget()
        while walker is not None and walker is not page:
            if walker is page._global_actions_card:
                return
            walker = walker.parentWidget()
        pytest.fail("打开 yaml must live inside _global_actions_card")

    def test_editor_panel_drops_global_buttons(self, qapp, tmp_path):
        """The per-library editor card should no longer carry 应用更改 / 打开 yaml —
        they belong to the global actions card now."""
        page = _make_page(qapp, tmp_path)
        editor = page.editor_panel
        assert "save_btn" not in editor, \
            "editor_panel should no longer expose save_btn (moved to global actions card)"
        assert "open_yaml_btn" not in editor, \
            "editor_panel should no longer expose open_yaml_btn (moved to global actions card)"
        # And the editor card should only contain the per-library actions.
        editor_card = editor["card"]
        editor_buttons = [
            w for w in editor_card.findChildren(QtWidgets.QPushButton)
            if w.text() in ("添加库", "移除所选", "打开目录")
        ]
        assert len(editor_buttons) == 3, \
            f"editor card should have 3 per-library action buttons (添加库/移除所选/打开目录), found: {[b.text() for b in editor_buttons]}"


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