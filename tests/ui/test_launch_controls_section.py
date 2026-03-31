"""
Tests for LaunchControlsSection - RED phase (class does not exist yet).

These tests define the expected interface for the LaunchControlsSection class
which will be extracted from _build_launch_controls() in launch_page.py.

RED PHASE: All tests should FAIL with ImportError because LaunchControlsSection
does not exist yet. GREEN PHASE will implement minimal extraction to make tests pass.
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt5 import QtWidgets


class TestLaunchControlsSectionImport:
    """Test that LaunchControlsSection can be imported."""

    def test_import_launch_controls_section(self):
        """LaunchControlsSection should be importable from ui_qt.pages.launch_page."""
        from ui_qt.pages.launch_page import LaunchControlsSection

    def test_import_creates_widget(self):
        """LaunchControlsSection should be a QWidget subclass."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QWidget
        assert issubclass(LaunchControlsSection, QWidget)


class TestLaunchControlsSectionInit:
    """Test LaunchControlsSection initialization with app_context."""

    def test_init_requires_app_context(self, app_context, qtbot):
        """LaunchControlsSection should require app_context and qtbot."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)

    def test_init_sets_app_reference(self, app_context, qtbot):
        """LaunchControlsSection should store reference to app."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        section = LaunchControlsSection(app_context)
        assert section.app is app_context


class TestGPUCPURadioButtons:
    """Test GPU/CPU radio button existence and toggling."""

    def test_has_gpu_radio_button(self, app_context, qtbot):
        """Section should have a GPU radio button."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        gpu_rb = None
        for rb in section.findChildren(QtWidgets.QRadioButton):
            if hasattr(rb, 'text') and rb.text() == "GPU":
                gpu_rb = rb
                break
        assert gpu_rb is not None, "GPU radio button not found"

    def test_has_cpu_radio_button(self, app_context, qtbot):
        """Section should have a CPU radio button."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        cpu_rb = None
        for rb in section.findChildren(QtWidgets.QRadioButton):
            if hasattr(rb, 'text') and rb.text() == "CPU":
                cpu_rb = rb
                break
        assert cpu_rb is not None, "CPU radio button not found"

    def test_gpu_radio_toggles_compute_mode(self, app_context, qtbot):
        """Selecting GPU radio should set app.compute_mode to 'gpu'."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        gpu_rb = None
        for rb in section.findChildren(QtWidgets.QRadioButton):
            if hasattr(rb, 'text') and rb.text() == "GPU":
                gpu_rb = rb
                break
        
        if gpu_rb:
            gpu_rb.setChecked(True)
            if gpu_rb.isChecked():
                app_context.compute_mode.set("gpu")
            
            assert app_context.compute_mode.get() == "gpu"

    def test_cpu_radio_toggles_compute_mode(self, app_context, qtbot):
        """Selecting CPU radio should set app.compute_mode to 'cpu'."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        cpu_rb = None
        for rb in section.findChildren(QtWidgets.QRadioButton):
            if hasattr(rb, 'text') and rb.text() == "CPU":
                cpu_rb = rb
                break
        
        if cpu_rb:
            cpu_rb.setChecked(True)
            if cpu_rb.isChecked():
                app_context.compute_mode.set("cpu")
            
            assert app_context.compute_mode.get() == "cpu"


class TestPortInput:
    """Test port number input field."""

    def test_has_port_line_edit(self, app_context, qtbot):
        """Section should have a port number QLineEdit."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QLineEdit
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        port_edit = section.findChild(QLineEdit)
        assert port_edit is not None, "Port QLineEdit not found"

    def test_port_default_value(self, app_context, qtbot):
        """Port input should default to '8188'."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QLineEdit
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        port_edit = section.findChild(QLineEdit)
        if port_edit:
            # The default from app_context is "8188"
            assert port_edit.text() == "8188"

    def test_port_input_changes_value(self, app_context, qtbot):
        """Changing port input should update app.custom_port."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QLineEdit
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        port_edit = section.findChild(QLineEdit)
        if port_edit:
            port_edit.setText("8888")
            assert app_context.custom_port.get() == "8888"


class TestLANAccessCheckbox:
    """Test LAN access checkbox."""

    def test_has_listen_all_checkbox(self, app_context, qtbot):
        """Section should have a 'Allow LAN access' checkbox."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QCheckBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        listen_chk = section.findChild(QCheckBox)
        assert listen_chk is not None, "LAN access checkbox not found"

    def test_listen_checkbox_toggles(self, app_context, qtbot):
        """Toggling listen checkbox should update app.listen_all."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QCheckBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        listen_chk = section.findChild(QCheckBox)
        if listen_chk:
            listen_chk.setChecked(False)
            assert app_context.listen_all.get() is False
            
            listen_chk.setChecked(True)
            assert app_context.listen_all.get() is True


class TestMemoryStrategyComboBox:
    """Test memory strategy (VRAM) combo box."""

    def test_has_vram_combo_box(self, app_context, qtbot):
        """Section should have a VRAM strategy combo box."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QComboBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        vram_combo = None
        for combo in section.findChildren(QComboBox):
            for i in range(combo.count()):
                if "High" in combo.itemText(i) or "Normal" in combo.itemText(i) or "Low" in combo.itemText(i):
                    vram_combo = combo
                    break
            if vram_combo:
                break
        assert vram_combo is not None, "VRAM strategy combo box not found"

    def test_vram_combo_has_expected_options(self, app_context, qtbot):
        """VRAM combo should have expected strategy options."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QComboBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        expected_options = [
            "由 ComfyUI 决定（推荐）",
            "显存充足 (High)",
            "中等显存 (Normal)",
            "低显存 (Low)",
            "极低显存 (No)",
        ]
        
        # Find VRAM combo
        vram_combo = None
        for combo in section.findChildren(QComboBox):
            if hasattr(combo, 'currentText'):
                text = combo.currentText()
                if "High" in text or "Normal" in text or "决定" in text:
                    vram_combo = combo
                    break
        
        if vram_combo:
            actual_options = [vram_combo.itemText(i) for i in range(vram_combo.count())]
            for expected in expected_options:
                assert expected in actual_options, f"Expected option '{expected}' not found"


class TestAttentionOptimization:
    """Test attention optimization combo box."""

    def test_has_attention_combo_box(self, app_context, qtbot):
        """Section should have an attention optimization combo box."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QComboBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        attn_combo = None
        for combo in section.findChildren(QComboBox):
            for i in range(combo.count()):
                if "PyTorch" in combo.itemText(i) or "Flash" in combo.itemText(i) or "Sage" in combo.itemText(i):
                    attn_combo = combo
                    break
            if attn_combo:
                break
        assert attn_combo is not None, "Attention optimization combo not found"

    def test_attention_combo_has_expected_options(self, app_context, qtbot):
        """Attention combo should have expected optimization options."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QComboBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        expected_options = [
            "默认 (Default)",
            "PyTorch (SDPA)",
            "Flash Attention",
            "Sage Attention",
            "Split Attention",
            "Quad Attention",
        ]
        
        # Find attention combo
        attn_combo = None
        for combo in section.findChildren(QComboBox):
            if hasattr(combo, 'currentText'):
                text = combo.currentText()
                if "PyTorch" in text or "Flash" in text:
                    attn_combo = combo
                    break
        
        if attn_combo:
            actual_options = [attn_combo.itemText(i) for i in range(attn_combo.count())]
            for expected in expected_options:
                assert expected in actual_options, f"Expected option '{expected}' not found"


class TestBrowserSelection:
    """Test browser selection components."""

    def test_has_browser_open_combo(self, app_context, qtbot):
        """Section should have a browser open mode combo box."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QComboBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        # Find browser open combo - should have options like "不自动打开", "默认浏览器"
        browser_combo = None
        for combo in section.findChildren(QComboBox):
            if hasattr(combo, 'currentText'):
                text = combo.currentText()
                if "不自动打开" in text or "默认浏览器" in text:
                    browser_combo = combo
                    break
        assert browser_combo is not None, "Browser open mode combo not found"

    def test_has_select_browser_button(self, app_context, qtbot):
        """Section should have a 'Select browser...' button."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QPushButton
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        # Find button with "选择浏览器" or similar text
        cpath_btn = None
        for btn in section.findChildren(QPushButton):
            if hasattr(btn, 'text') and ("浏览器" in btn.text() or "browser" in btn.text().lower()):
                cpath_btn = btn
                break
        assert cpath_btn is not None, "Select browser button not found"


class TestAutoOpenBrowserCheckbox:
    """Test auto-open-browser combo box (same as browser selection - uses combo not checkbox)."""

    def test_auto_open_browser_combo_options(self, app_context, qtbot):
        """Auto-open browser combo should have correct options."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QComboBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        expected_options = [
            "不自动打开",
            "使用默认浏览器",
            "使用指定浏览器",
        ]
        
        # Find browser combo
        browser_combo = None
        for combo in section.findChildren(QComboBox):
            if hasattr(combo, 'currentText'):
                text = combo.currentText()
                if "不自动打开" in text or "默认浏览器" in text:
                    browser_combo = combo
                    break
        
        if browser_combo:
            actual_options = [browser_combo.itemText(i) for i in range(browser_combo.count())]
            for expected in expected_options:
                assert expected in actual_options


class TestCheckboxes:
    """Test FP16, API, and plugin DEBUG checkboxes."""

    def test_has_fp16_checkbox(self, app_context, qtbot):
        """Section should have a 'Fast FP16' checkbox."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QCheckBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        # Find checkbox with "FP16" or "快速" text
        fp16_chk = None
        for chk in section.findChildren(QCheckBox):
            if hasattr(chk, 'text') and ("FP16" in chk.text() or "快速" in chk.text()):
                fp16_chk = chk
                break
        assert fp16_chk is not None, "FP16 checkbox not found"

    def test_fp16_checkbox_toggles(self, app_context, qtbot):
        """FP16 checkbox should toggle app.use_fast_mode."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QCheckBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        fp16_chk = None
        for chk in section.findChildren(QCheckBox):
            if hasattr(chk, 'text') and ("FP16" in chk.text() or "快速" in chk.text()):
                fp16_chk = chk
                break
        
        if fp16_chk:
            fp16_chk.setChecked(True)
            assert app_context.use_fast_mode.get() is True
            
            fp16_chk.setChecked(False)
            assert app_context.use_fast_mode.get() is False

    def test_has_api_checkbox(self, app_context, qtbot):
        """Section should have a 'Disable API nodes' checkbox."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QCheckBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        # Find checkbox with "API" or "禁用API" text
        api_chk = None
        for chk in section.findChildren(QCheckBox):
            if hasattr(chk, 'text') and ("API" in chk.text() or "禁用API" in chk.text()):
                api_chk = chk
                break
        assert api_chk is not None, "API checkbox not found"

    def test_api_checkbox_toggles(self, app_context, qtbot):
        """API checkbox should toggle app.disable_api_nodes."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QCheckBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        api_chk = None
        for chk in section.findChildren(QCheckBox):
            if hasattr(chk, 'text') and ("API" in chk.text() or "禁用API" in chk.text()):
                api_chk = chk
                break
        
        if api_chk:
            api_chk.setChecked(True)
            assert app_context.disable_api_nodes.get() is True

    def test_has_plugin_debug_checkbox(self, app_context, qtbot):
        """Section should have a 'Disable all plugins (DEBUG)' checkbox."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QCheckBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        # Find checkbox with "插件" or "DEBUG" text
        debug_chk = None
        for chk in section.findChildren(QCheckBox):
            if hasattr(chk, 'text') and ("插件" in chk.text() or "DEBUG" in chk.text()):
                debug_chk = chk
                break
        assert debug_chk is not None, "Plugin DEBUG checkbox not found"

    def test_plugin_debug_checkbox_toggles(self, app_context, qtbot):
        """Plugin DEBUG checkbox should toggle app.disable_all_custom_nodes."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QCheckBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        debug_chk = None
        for chk in section.findChildren(QCheckBox):
            if hasattr(chk, 'text') and ("插件" in chk.text() or "DEBUG" in chk.text()):
                debug_chk = chk
                break
        
        if debug_chk:
            debug_chk.setChecked(True)
            assert app_context.disable_all_custom_nodes.get() is True
            
            debug_chk.setChecked(False)
            assert app_context.disable_all_custom_nodes.get() is False


class TestExtraLaunchArguments:
    """Test extra launch arguments field."""

    def test_has_extra_args_line_edit(self, app_context, qtbot):
        """Section should have an extra arguments QLineEdit."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QLineEdit
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        # Find the extra args line edit - should have placeholder text
        extra_edit = None
        for le in section.findChildren(QLineEdit):
            if hasattr(le, 'placeholderText') and le.placeholderText():
                extra_edit = le
                break
        assert extra_edit is not None, "Extra arguments QLineEdit not found"

    def test_extra_args_placeholder_text(self, app_context, qtbot):
        """Extra args field should have placeholder text."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QLineEdit
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        extra_edit = None
        for le in section.findChildren(QLineEdit):
            if hasattr(le, 'placeholderText') and le.placeholderText():
                extra_edit = le
                break
        
        if extra_edit:
            assert "fp16" in extra_edit.placeholderText().lower() or "--" in extra_edit.placeholderText()

    def test_extra_args_changes_value(self, app_context, qtbot):
        """Changing extra args should update app.extra_launch_args."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QLineEdit
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        extra_edit = None
        for le in section.findChildren(QLineEdit):
            if hasattr(le, 'placeholderText') and le.placeholderText():
                extra_edit = le
                break
        
        if extra_edit:
            extra_edit.setText("--disable-smart-memory")
            assert app_context.extra_launch_args.get() == "--disable-smart-memory"


class TestButtonStateChanges:
    """Test button state changes when launching/stopping."""

    def test_section_has_buttons(self, app_context, qtbot):
        """Section should have buttons (toggle, FAQ)."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QPushButton
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        buttons = section.findChildren(QPushButton)
        assert len(buttons) >= 1, f"Expected at least 1 button, found {len(buttons)}"

    def test_buttons_are_pushable(self, app_context, qtbot):
        """Buttons should be clickable."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QPushButton
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        buttons = section.findChildren(QPushButton)
        for btn in buttons:
            assert btn.isEnabled(), f"Button '{btn.text()}' should be enabled"

    def test_buttons_have_text(self, app_context, qtbot):
        """Buttons should have text labels."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QPushButton
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        buttons = section.findChildren(QPushButton)
        for btn in buttons:
            assert btn.text(), f"Button should have text label"


class TestFormGroup:
    """Test the form group box container."""

    def test_has_group_box(self, app_context, qtbot):
        """Section should have a QGroupBox."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QGroupBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        group_box = section.findChild(QGroupBox)
        assert group_box is not None, "QGroupBox not found"

    def test_group_box_title(self, app_context, qtbot):
        """Group box should have '启动控制' as title."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        from PyQt5.QtWidgets import QGroupBox
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        group_box = section.findChild(QGroupBox)
        if group_box:
            assert "启动控制" in group_box.title(), f"Expected '启动控制' in title, got '{group_box.title()}'"


class TestThemeIntegration:
    """Test theme integration for the section."""

    def test_update_theme_method_exists(self, app_context, qtbot):
        """Section should have update_theme method."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        assert hasattr(section, 'update_theme'), "Section should have update_theme method"

    def test_update_theme_is_callable(self, app_context, qtbot):
        """update_theme should be callable."""
        from ui_qt.pages.launch_page import LaunchControlsSection
        section = LaunchControlsSection(app_context)
        qtbot.addWidget(section)
        
        if hasattr(section, 'update_theme'):
            # Should not raise
            section.update_theme()
