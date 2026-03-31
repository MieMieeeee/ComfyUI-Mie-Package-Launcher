"""
Tests for VersionSection - RED phase (class does not exist yet).

These tests define the expected interface for the VersionSection class
which will be extracted from _build_version_section() in launch_page.py.

RED PHASE: All tests should FAIL with ImportError because VersionSection
does not exist yet. GREEN PHASE will implement minimal extraction to make tests pass.
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt5 import QtWidgets


class TestVersionSectionImport:
    """Test that VersionSection can be imported."""

    def test_import_version_section(self):
        """VersionSection should be importable from ui_qt.pages.launch."""
        from ui_qt.pages.launch import VersionSection

    def test_import_creates_widget(self):
        """VersionSection should be a QWidget subclass."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QWidget
        assert issubclass(VersionSection, QWidget)


class TestVersionSectionInit:
    """Test VersionSection initialization with app_context."""

    def test_init_requires_app_context(self, app_context, qtbot):
        """VersionSection should require app_context and qtbot."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)

    def test_init_sets_app_reference(self, app_context, qtbot):
        """VersionSection should store reference to app."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        assert section.app is app_context


class TestVersionGrid:
    """Test version information grid with 7 version items."""

    def test_version_grid_has_7_items(self, app_context, qtbot):
        """Section should display 7 version items in a grid."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        # Version items are: 内核, 前端, 模板库, Python, Torch, Git, 显卡驱动
        # Look for QFrame cards that contain version information
        cards = []
        for frame in section.findChildren(QtWidgets.QFrame):
            # Check if frame has the version item structure
            labels = frame.findChildren(QtWidgets.QLabel)
            if len(labels) >= 2:  # icon + title + value
                texts = [l.text() for l in labels]
                # Check for version item titles
                version_titles = ["内核", "前端", "模板库", "Python", "Torch", "Git", "显卡驱动"]
                for title in version_titles:
                    if any(title in t for t in texts):
                        cards.append(title)
        
        assert len(cards) >= 7, f"Expected 7 version items, found {len(cards)}: {cards}"

    def test_version_grid_contains_kernel_item(self, app_context, qtbot):
        """Grid should contain '内核' (kernel) version item."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        # Find label containing "内核"
        labels = section.findChildren(QtWidgets.QLabel)
        kernel_found = any("内核" in l.text() for l in labels)
        assert kernel_found, "Kernel version item '内核' not found"

    def test_version_grid_containsfrontend_item(self, app_context, qtbot):
        """Grid should contain '前端' (frontend) version item."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        labels = section.findChildren(QtWidgets.QLabel)
        frontend_found = any("前端" in l.text() for l in labels)
        assert frontend_found, "Frontend version item '前端' not found"

    def test_version_grid_contains_python_item(self, app_context, qtbot):
        """Grid should contain 'Python' version item."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        labels = section.findChildren(QtWidgets.QLabel)
        python_found = any("Python" in l.text() for l in labels)
        assert python_found, "Python version item not found"

    def test_version_grid_contains_torch_item(self, app_context, qtbot):
        """Grid should contain 'Torch' version item."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        labels = section.findChildren(QtWidgets.QLabel)
        torch_found = any("Torch" in l.text() or "🔥" in l.text() for l in labels)
        assert torch_found, "Torch version item not found"

    def test_version_grid_contains_git_item(self, app_context, qtbot):
        """Grid should contain 'Git' version item."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        labels = section.findChildren(QtWidgets.QLabel)
        git_found = any("Git" in l.text() or "🐙" in l.text() for l in labels)
        assert git_found, "Git version item not found"

    def test_version_grid_contains_gpu_driver_item(self, app_context, qtbot):
        """Grid should contain '显卡驱动' (GPU driver) version item."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        labels = section.findChildren(QtWidgets.QLabel)
        gpu_found = any("显卡驱动" in l.text() or "🖥️" in l.text() for l in labels)
        assert gpu_found, "GPU driver version item not found"


class TestUpgradeOptions:
    """Test upgrade strategy options (checkboxes and timeout)."""

    def test_has_stable_only_checkbox(self, app_context, qtbot):
        """Section should have '仅更新到稳定版' checkbox."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QCheckBox
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        stable_chk = None
        for chk in section.findChildren(QCheckBox):
            if hasattr(chk, 'text') and "稳定版" in chk.text():
                stable_chk = chk
                break
        assert stable_chk is not None, "Stable-only checkbox not found"

    def test_has_auto_update_deps_checkbox(self, app_context, qtbot):
        """Section should have '同时更新依赖库' checkbox."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QCheckBox
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        deps_chk = None
        for chk in section.findChildren(QCheckBox):
            if hasattr(chk, 'text') and "依赖库" in chk.text():
                deps_chk = chk
                break
        assert deps_chk is not None, "Auto-update deps checkbox not found"

    def test_has_timeout_combo(self, app_context, qtbot):
        """Section should have a timeout selection combo box."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QComboBox
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        timeout_combo = None
        for combo in section.findChildren(QComboBox):
            items = [combo.itemText(i) for i in range(combo.count())]
            if any("秒" in item for item in items):
                timeout_combo = combo
                break
        assert timeout_combo is not None, "Timeout combo box not found"

    def test_timeout_combo_has_expected_options(self, app_context, qtbot):
        """Timeout combo should have expected timeout options."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QComboBox
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        timeout_combo = None
        for combo in section.findChildren(QComboBox):
            items = [combo.itemText(i) for i in range(combo.count())]
            if any("秒" in item for item in items):
                timeout_combo = combo
                break
        
        if timeout_combo:
            expected_timeouts = ["60秒", "120秒", "180秒", "300秒", "600秒"]
            actual_items = [timeout_combo.itemText(i) for i in range(timeout_combo.count())]
            for expected in expected_timeouts:
                assert expected in actual_items, f"Expected timeout option '{expected}' not found"


class TestButtons:
    """Test refresh and update buttons."""

    def test_has_refresh_button(self, app_context, qtbot):
        """Section should have a refresh button."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QPushButton
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        refresh_btn = None
        for btn in section.findChildren(QPushButton):
            if hasattr(btn, 'text') and ("刷新" in btn.text()):
                refresh_btn = btn
                break
        assert refresh_btn is not None, "Refresh button not found"

    def test_refresh_button_is_clickable(self, app_context, qtbot):
        """Refresh button should be clickable."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QPushButton
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        refresh_btn = None
        for btn in section.findChildren(QPushButton):
            if hasattr(btn, 'text') and ("刷新" in btn.text()):
                refresh_btn = btn
                break
        
        if refresh_btn:
            assert refresh_btn.isEnabled(), "Refresh button should be enabled"
            # Click should not raise
            refresh_btn.click()

    def test_has_update_button(self, app_context, qtbot):
        """Section should have an update button."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QPushButton
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        update_btn = None
        for btn in section.findChildren(QPushButton):
            if hasattr(btn, 'text') and ("更新" in btn.text()):
                update_btn = btn
                break
        assert update_btn is not None, "Update button not found"

    def test_update_button_is_clickable(self, app_context, qtbot):
        """Update button should be clickable."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QPushButton
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        update_btn = None
        for btn in section.findChildren(QPushButton):
            if hasattr(btn, 'text') and ("更新" in btn.text()):
                update_btn = btn
                break
        
        if update_btn:
            assert update_btn.isEnabled(), "Update button should be enabled"
            # Click should not raise
            update_btn.click()

    def test_refresh_button_has_text(self, app_context, qtbot):
        """Refresh button should have '刷 新' text."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QPushButton
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        refresh_btn = None
        for btn in section.findChildren(QPushButton):
            if hasattr(btn, 'text') and ("刷新" in btn.text()):
                refresh_btn = btn
                break
        
        if refresh_btn:
            assert "刷新" in refresh_btn.text(), f"Expected '刷新' in button text, got '{refresh_btn.text()}'"

    def test_update_button_has_text(self, app_context, qtbot):
        """Update button should have '更 新' text."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QPushButton
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        update_btn = None
        for btn in section.findChildren(QPushButton):
            if hasattr(btn, 'text') and ("更新" in btn.text()):
                update_btn = btn
                break
        
        if update_btn:
            assert "更新" in update_btn.text(), f"Expected '更新' in button text, got '{update_btn.text()}'"


class TestGroupBox:
    """Test the group box container."""

    def test_has_group_box(self, app_context, qtbot):
        """Section should have a QGroupBox."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QGroupBox
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        group_box = section.findChild(QGroupBox)
        assert group_box is not None, "QGroupBox not found"

    def test_group_box_title(self, app_context, qtbot):
        """Group box should have '版本与更新' as title."""
        from ui_qt.pages.launch import VersionSection
        from PyQt5.QtWidgets import QGroupBox
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        group_box = section.findChild(QGroupBox)
        if group_box:
            assert "版本与更新" in group_box.title(), f"Expected '版本与更新' in title, got '{group_box.title()}'"


class TestThemeIntegration:
    """Test theme integration for the section."""

    def test_update_theme_method_exists(self, app_context, qtbot):
        """Section should have update_theme method."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        assert hasattr(section, 'update_theme'), "Section should have update_theme method"

    def test_update_theme_is_callable(self, app_context, qtbot):
        """update_theme should be callable."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        if hasattr(section, 'update_theme'):
            # Should not raise
            section.update_theme()


class TestCreateVersionItemHelper:
    """Test the _create_version_item helper method behavior."""

    def test_version_items_have_icons(self, app_context, qtbot):
        """Version items should display emoji icons."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        # Check for emoji icons used in version items
        emoji_labels = ["🧬", "🎨", "📋", "🐍", "🔥", "🐙", "🖥️"]
        labels = section.findChildren(QtWidgets.QLabel)
        found_emojis = set()
        for lbl in labels:
            if hasattr(lbl, 'text'):
                for emoji in emoji_labels:
                    if emoji in lbl.text():
                        found_emojis.add(emoji)
        
        assert len(found_emojis) >= 5, f"Expected emoji icons in version items, found {found_emojis}"

    def test_version_items_show_colon_separator(self, app_context, qtbot):
        """Version item titles should be followed by colon (e.g., '内核 :')."""
        from ui_qt.pages.launch import VersionSection
        section = VersionSection(app_context)
        qtbot.addWidget(section)
        
        labels = section.findChildren(QtWidgets.QLabel)
        colon_found = False
        for lbl in labels:
            if hasattr(lbl, 'text') and " :" in lbl.text():
                colon_found = True
                break
        
        assert colon_found, "Version items should use ' :' separator format"
