"""
Tests for EnvironmentSection - RED phase (class does not exist yet).

These tests define the expected interface for the EnvironmentSection class
which will be extracted from _build_environment_config() in launch_page.py.

RED PHASE: All tests should FAIL with ImportError because EnvironmentSection
does not exist yet. GREEN PHASE will implement minimal extraction to make tests pass.
"""
import pytest
from unittest.mock import MagicMock, patch
from PyQt5 import QtWidgets


class TestEnvironmentSectionImport:
    """Test that EnvironmentSection can be imported."""

    def test_import_environment_section(self):
        """EnvironmentSection should be importable from ui_qt.pages.launch."""
        from ui_qt.pages.launch import EnvironmentSection

    def test_import_creates_widget(self):
        """EnvironmentSection should be a QWidget subclass."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QWidget
        assert issubclass(EnvironmentSection, QWidget)


class TestEnvironmentSectionInit:
    """Test EnvironmentSection initialization with app_context."""

    def test_init_requires_app_context(self, app_context, qtbot):
        """EnvironmentSection should require app_context and qtbot."""
        from ui_qt.pages.launch import EnvironmentSection
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)

    def test_init_sets_app_reference(self, app_context, qtbot):
        """EnvironmentSection should store reference to app."""
        from ui_qt.pages.launch import EnvironmentSection
        section = EnvironmentSection(app_context)
        assert section.app is app_context


class TestHFMirrorSource:
    """Test HF mirror source combo box and entry."""

    def test_has_hf_mirror_combo(self, app_context, qtbot):
        """Section should have an HF mirror source combo box."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QComboBox
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        # Find combo with HF mirror options
        hf_combo = None
        for combo in section.findChildren(QComboBox):
            if hasattr(combo, 'currentText'):
                items = [combo.itemText(i) for i in range(combo.count())]
                if any("hf" in item.lower() for item in items):
                    hf_combo = combo
                    break
        assert hf_combo is not None, "HF mirror combo box not found"

    def test_has_hf_mirror_entry(self, app_context, qtbot):
        """Section should have an HF mirror URL entry field."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QLineEdit
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        # Find line edit for HF mirror URL
        hf_entry = section.findChild(QLineEdit)
        assert hf_entry is not None, "HF mirror URL entry not found"


class TestGitHubProxy:
    """Test GitHub proxy combo and entry field."""

    def test_has_github_proxy_combo(self, app_context, qtbot):
        """Section should have a GitHub proxy combo box."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QComboBox
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        # Find combo with GitHub proxy options
        gh_combo = None
        for combo in section.findChildren(QComboBox):
            if hasattr(combo, 'currentText'):
                items = [combo.itemText(i) for i in range(combo.count())]
                if any("gh-proxy" in item.lower() or "github" in item.lower() for item in items):
                    gh_combo = combo
                    break
        assert gh_combo is not None, "GitHub proxy combo box not found"

    def test_has_github_proxy_entry(self, app_context, qtbot):
        """Section should have a GitHub proxy URL entry field."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QLineEdit
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        # Find line edit for GitHub proxy URL - there should be multiple entries
        entries = section.findChildren(QLineEdit)
        assert len(entries) >= 1, "GitHub proxy URL entry not found"


class TestPyPIProxy:
    """Test PyPI proxy combo and entry field."""

    def test_has_pypi_proxy_combo(self, app_context, qtbot):
        """Section should have a PyPI proxy combo box."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QComboBox
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        # Find combo with PyPI proxy options
        pypi_combo = None
        for combo in section.findChildren(QComboBox):
            if hasattr(combo, 'currentText'):
                items = [combo.itemText(i) for i in range(combo.count())]
                if any("pypi" in item.lower() or "pip" in item.lower() or "阿里云" in item for item in items):
                    pypi_combo = combo
                    break
        assert pypi_combo is not None, "PyPI proxy combo box not found"

    def test_has_pypi_proxy_entry(self, app_context, qtbot):
        """Section should have a PyPI proxy URL entry field."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QLineEdit
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        # Find line edit for PyPI proxy URL - there should be multiple entries
        entries = section.findChildren(QLineEdit)
        assert len(entries) >= 2, "PyPI proxy URL entry not found"


def _env_edit_dialog(qtbot):
    """构建环境编辑弹窗（根目录 / Python 路径现在在这里编辑）。

    注意：不要给弹窗再套一个临时 parent widget —— 那个临时 widget 在函数
    返回后就会被 GC，PyQt 连带把子对象（弹窗）一起析构，调用方拿到的就是
    一个「已删除的 C++ 对象」。
    """
    from ui_qt.pages.environment_manager_section import _EnvEditDialog
    from ui_qt.theme_manager import ThemeManager

    theme = ThemeManager(dark=True)
    dlg = _EnvEditDialog(None, "编辑环境", "测试环境", "", "", None, theme)
    qtbot.addWidget(dlg)
    return dlg


def _form_field(dlg, label_text):
    """按 QFormLayout 的行标签找该行的字段控件。"""
    from PyQt5 import QtWidgets

    for form in dlg.findChildren(QtWidgets.QFormLayout):
        for row in range(form.rowCount()):
            lbl_item = form.itemAt(row, QtWidgets.QFormLayout.LabelRole)
            field_item = form.itemAt(row, QtWidgets.QFormLayout.FieldRole)
            if lbl_item is None or field_item is None:
                continue
            lbl = lbl_item.widget()
            if lbl is not None and lbl.text() == label_text:
                return field_item.widget()
    return None


class TestRootDirectorySelector:
    """Test root directory display and selection button."""

    def test_has_root_display(self, app_context, qtbot):
        """Section should have a root directory display field."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QLineEdit
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        # Find line edit for root directory
        root_edit = None
        for le in section.findChildren(QLineEdit):
            if hasattr(le, 'placeholderText') or hasattr(le, 'isReadOnly'):
                if le.isReadOnly() or "根目录" in (le.placeholderText() or ""):
                    root_edit = le
                    break
        assert root_edit is not None, "Root directory display not found"

    def test_root_selection_lives_in_environment_edit_dialog(self, app_context, qtbot):
        """根目录选择已从启动页环境区块移到「环境管理」弹窗。

        一个「环境」= ComfyUI 根目录 + python 路径，这两项属于环境定义，
        所以启动页的环境区块不再重复提供，改为由顶部环境栏的路径摘要 +
        环境编辑弹窗统一编辑。这里守住新归属：弹窗里必须有「ComfyUI 根目录」
        行和浏览按钮；启动页区块则不该再有根目录选择按钮（避免两处各改一处）。
        """
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QPushButton
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)

        for btn in section.findChildren(QPushButton):
            assert "根目录" not in btn.text(), \
                "根目录选择已移到环境管理弹窗，启动页环境区块不该重复提供"

        dlg = _env_edit_dialog(qtbot)
        field = _form_field(dlg, "ComfyUI 根目录")
        assert field is not None, "环境编辑弹窗缺少「ComfyUI 根目录」行"
        btns = field.findChildren(QPushButton)
        assert any("浏览" in b.text() for b in btns), \
            "环境编辑弹窗的根目录行缺少「浏览…」按钮"


class TestPythonPathSelector:
    """Test Python path display and selection button."""

    def test_has_python_path_display(self, app_context, qtbot):
        """Section should have a Python path display field."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QLineEdit
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        # Find line edit for Python path
        py_edit = None
        for le in section.findChildren(QLineEdit):
            if hasattr(le, 'placeholderText') or hasattr(le, 'isReadOnly'):
                if le.isReadOnly() or "Python" in (le.placeholderText() or "") or "python" in (le.placeholderText() or "").lower():
                    py_edit = le
                    break
        assert py_edit is not None, "Python path display not found"

    def test_python_selection_lives_in_environment_edit_dialog(self, app_context, qtbot):
        """Python 路径选择同样已从启动页环境区块移到「环境管理」弹窗。

        见 test_root_selection_lives_in_environment_edit_dialog 的说明：
        python 路径属于「环境」定义，只在环境编辑弹窗里编辑。
        """
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QPushButton
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)

        for btn in section.findChildren(QPushButton):
            assert "Python" not in btn.text(), \
                "Python 路径选择已移到环境管理弹窗，启动页环境区块不该重复提供"

        dlg = _env_edit_dialog(qtbot)
        field = _form_field(dlg, "Python 路径")
        assert field is not None, "环境编辑弹窗缺少「Python 路径」行"
        btns = field.findChildren(QPushButton)
        assert any("浏览" in b.text() for b in btns), \
            "环境编辑弹窗的 Python 路径行缺少「浏览…」按钮"


class TestGroupBox:
    """Test the group box container."""

    def test_has_group_box(self, app_context, qtbot):
        """Section should have a QGroupBox."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QGroupBox
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        group_box = section.findChild(QGroupBox)
        assert group_box is not None, "QGroupBox not found"

    def test_group_box_title(self, app_context, qtbot):
        """Group box should have '环境配置' as title."""
        from ui_qt.pages.launch import EnvironmentSection
        from PyQt5.QtWidgets import QGroupBox
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        group_box = section.findChild(QGroupBox)
        if group_box:
            assert "环境配置" in group_box.title(), f"Expected '环境配置' in title, got '{group_box.title()}'"


class TestThemeIntegration:
    """Test theme integration for the section."""

    def test_update_theme_method_exists(self, app_context, qtbot):
        """Section should have update_theme method."""
        from ui_qt.pages.launch import EnvironmentSection
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        assert hasattr(section, 'update_theme'), "Section should have update_theme method"

    def test_update_theme_is_callable(self, app_context, qtbot):
        """update_theme should be callable."""
        from ui_qt.pages.launch import EnvironmentSection
        section = EnvironmentSection(app_context)
        qtbot.addWidget(section)
        
        if hasattr(section, 'update_theme'):
            # Should not raise
            section.update_theme()
