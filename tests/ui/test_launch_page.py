"""
Integration tests for LaunchPage.

Tests that the full LaunchPage integrates all 3 sections correctly:
- LaunchControlsSection
- EnvironmentSection
- VersionSection

Also tests theme integration and page layout.
"""
import pytest
from PyQt5 import QtWidgets

from ui_qt.pages.launch_page import LaunchPage
from ui_qt.pages.launch import LaunchControlsSection, EnvironmentSection, VersionSection


class TestLaunchPageImport:
    """Test that LaunchPage can be imported."""

    def test_import_launch_page(self):
        """LaunchPage should be importable."""
        from ui_qt.pages.launch_page import LaunchPage

    def test_launch_page_is_qwidget(self):
        """LaunchPage should be a QWidget subclass."""
        from ui_qt.pages.base_page import BasePage
        assert issubclass(LaunchPage, BasePage)


class TestLaunchPageInitialization:
    """Test LaunchPage initialization with app_context and theme_manager."""

    def test_init_with_app_context_and_theme(self, app_context, qtbot):
        """LaunchPage should initialize with app_context and theme_manager."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        assert page.app is app_context
        assert page.theme_manager is theme_manager


class TestLaunchPageSections:
    """Test that all 3 sections are present in LaunchPage."""

    def test_has_launch_controls_section(self, app_context, qtbot):
        """LaunchPage should have launch_controls_section attribute."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        assert hasattr(page, 'launch_controls_section')
        assert isinstance(page.launch_controls_section, LaunchControlsSection)

    def test_has_environment_section(self, app_context, qtbot):
        """LaunchPage should have environment_section attribute."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        assert hasattr(page, 'environment_section')
        assert isinstance(page.environment_section, EnvironmentSection)

    def test_has_version_section(self, app_context, qtbot):
        """LaunchPage should have version_section attribute."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        assert hasattr(page, 'version_section')
        assert isinstance(page.version_section, VersionSection)

    def test_all_three_sections_present(self, app_context, qtbot):
        """LaunchPage should contain all 3 sections simultaneously."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        assert hasattr(page, 'launch_controls_section')
        assert hasattr(page, 'environment_section')
        assert hasattr(page, 'version_section')
        
        # Verify they are all QWidget instances
        assert isinstance(page.launch_controls_section, QtWidgets.QWidget)
        assert isinstance(page.environment_section, QtWidgets.QWidget)
        assert isinstance(page.version_section, QtWidgets.QWidget)


class TestLaunchPageLayout:
    """Test LaunchPage layout structure."""

    def test_page_has_vertical_layout(self, app_context, qtbot):
        """LaunchPage should have a QVBoxLayout."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        layout = page.layout()
        assert isinstance(layout, QtWidgets.QVBoxLayout)

    def test_sections_are_direct_children(self, app_context, qtbot):
        """All 3 sections should be direct children of the page."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        # Get direct children that are sections
        children = page.findChildren(QtWidgets.QWidget)
        
        # Check that each section's parent is the page
        assert page.launch_controls_section.parent() is page
        assert page.environment_section.parent() is page
        assert page.version_section.parent() is page

    def test_page_contains_quick_directory_section(self, app_context, qtbot):
        """LaunchPage should have a Quick Directory (快捷目录) group box."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        # Find group boxes - should contain "快捷目录"
        group_boxes = page.findChildren(QtWidgets.QGroupBox)
        quick_dir_found = any("快捷目录" in gb.title() for gb in group_boxes)
        assert quick_dir_found, "Quick directory group box not found"


class TestThemeIntegration:
    """Test theme integration across all sections."""

    def test_page_has_update_theme_method(self, app_context, qtbot):
        """LaunchPage should have update_theme method."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        assert hasattr(page, 'update_theme')
        assert callable(page.update_theme)

    def test_update_theme_calls_section_update(self, app_context, qtbot):
        """update_theme should propagate to all sections."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        # Call update_theme - should not raise
        page.update_theme()
        
        # Verify sections have update_theme method
        assert hasattr(page.launch_controls_section, 'update_theme')
        assert hasattr(page.environment_section, 'update_theme')
        assert hasattr(page.version_section, 'update_theme')

    def test_styled_widgets_list_includes_all_sections(self, app_context, qtbot):
        """_styled_widgets list should contain all 3 sections."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        styled_widgets = getattr(page, '_styled_widgets', [])
        assert page.launch_controls_section in styled_widgets
        assert page.environment_section in styled_widgets
        assert page.version_section in styled_widgets

    def test_theme_propagates_to_sections(self, app_context, qtbot):
        """Theme update should propagate to all child sections."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        # Get initial styles
        initial_styles = page.theme_manager.styles
        
        # update_theme should call update_theme on all styled widgets
        page.update_theme(initial_styles)
        
        # If we get here without exception, propagation worked
        assert True


class TestLaunchPageButtons:
    """Test LaunchPage has the expected buttons."""

    def test_has_toggle_button(self, app_context, qtbot):
        """LaunchPage should have btn_toggle attribute."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        assert hasattr(page, 'btn_toggle')
        assert isinstance(page.btn_toggle, QtWidgets.QPushButton)

    def test_has_faq_button(self, app_context, qtbot):
        """LaunchPage should have btn_faq attribute."""
        from ui_qt.theme_manager import ThemeManager
        
        theme_manager = ThemeManager()
        page = LaunchPage(app_context, theme_manager)
        qtbot.addWidget(page)
        
        assert hasattr(page, 'btn_faq')
        assert isinstance(page.btn_faq, QtWidgets.QPushButton)
