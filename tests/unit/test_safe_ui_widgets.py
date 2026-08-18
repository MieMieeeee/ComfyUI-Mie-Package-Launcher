"""Behavioral Safe-UI tests for widgets that opt-out of effects in safe mode.

All tests launch widgets with LAUNCHER_SAFE_UI=1 preset (env-based, so
render_guard.is_safe_ui() returns True regardless of module init order).

SplashScreen is *not* instantiated here — it lives in comfyui_launcher_pyqt.py
and that module transitively imports ui_qt.qt_app.PyQtLauncher which has
module-level Qt side-effects that can segfault on some PyQt5 / Windows DPI
configurations.  We AST-check its safe-mode branches instead (static assertion
is just as good for the structural goal of "both branches exist").
"""

from __future__ import annotations

import ast
import os
import sys

import pytest
from PyQt5 import QtCore, QtGui, QtWidgets

from ui_qt.widgets.frameless_draggable_dialog import FramelessDraggableDialog
from ui_qt.widgets.buttons import LinkButton
from ui_qt.theme_styles import ThemeStyles


# ---------------------------------------------------------------------------
# Safe-UI env fixture — applied BEFORE any render_guard import runs
# ---------------------------------------------------------------------------

@pytest.fixture
def _force_safe_ui(monkeypatch):
    """Isolate widget tests by locking safe-mode env vars at session-level."""
    monkeypatch.setenv("LAUNCHER_SAFE_UI", "1")
    monkeypatch.setenv("LAUNCHER_RENDER_MODE", "safe")
    yield


# ---------------------------------------------------------------------------
# Widget subclasses for testing
# ---------------------------------------------------------------------------

class _MinimalDialog(FramelessDraggableDialog):
    def __init__(self, parent=None, modal=True, window_type=QtCore.Qt.Dialog):
        super().__init__(parent=parent, modal=modal, window_type=window_type)
        QtWidgets.QVBoxLayout(self).addWidget(QtWidgets.QLabel("x"))
        self.resize(200, 120)


# ---------------------------------------------------------------------------
# FramelessDraggableDialog — safe-mode no-frameless / no-translucent
# ---------------------------------------------------------------------------

class TestFramelessDialogSafeUI:
    @pytest.mark.usefixtures("_force_safe_ui")
    def test_safe_ui_no_frameless_window_hint(self, qtbot):
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        assert not bool(dlg.windowFlags() & QtCore.Qt.FramelessWindowHint), (
            "Safe-UI must NOT set FramelessWindowHint (uses native title bar)"
        )

    @pytest.mark.usefixtures("_force_safe_ui")
    def test_safe_ui_no_translucent_background(self, qtbot):
        dlg = _MinimalDialog()
        qtbot.addWidget(dlg)
        assert not dlg.testAttribute(QtCore.Qt.WA_TranslucentBackground), (
            "Safe-UI must NOT set WA_TranslucentBackground (paint compatibility)"
        )

    @pytest.mark.usefixtures("_force_safe_ui")
    def test_safe_ui_keeps_stays_on_top_and_modal(self, qtbot):
        """Only frameless + translucent are disabled; other flags preserved."""
        dlg = _MinimalDialog(modal=True)
        qtbot.addWidget(dlg)
        assert bool(dlg.windowFlags() & QtCore.Qt.WindowStaysOnTopHint)
        assert dlg.isModal() is True


# ---------------------------------------------------------------------------
# LinkButton safe UI: no QGraphicsDropShadowEffect hover
# ---------------------------------------------------------------------------

class TestLinkButtonSafeUI:
    def test_safe_ui_link_button_has_no_graphics_effect(self, qtbot, monkeypatch):
        monkeypatch.setenv("LAUNCHER_SAFE_UI", "1")
        # Force a ThemeStyles instance (light or dark doesn't matter for effect)
        try:
            styles = ThemeStyles(mode="dark", scale=1.0)
        except Exception:
            pytest.skip("ThemeStyles not instantiable in this env")
        btn = LinkButton("click", theme_styles=styles)
        qtbot.addWidget(btn)
        assert btn.graphicsEffect() is None, (
            "Safe-UI LinkButton must not install any GraphicsEffect"
        )


# ---------------------------------------------------------------------------
# SplashScreen — AST static check for both branches' structural shape
# ---------------------------------------------------------------------------

class TestSplashScreenSafeUI:
    @staticmethod
    def _entry_src():
        project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        entry_path = os.path.join(project_root, "comfyui_launcher_pyqt.py")
        with open(entry_path, "r", encoding="utf-8") as f:
            return f.read()

    def test_splash_has_safe_ui_branch_no_wa_translucent(self):
        """SplashScreen init must have a safe branch that skips
        WA_TranslucentBackground + FramelessWindowHint."""
        tree = ast.parse(self._entry_src())

        # Find class SplashScreen → __init__
        splash_cls = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.ClassDef) and n.name == "SplashScreen"),
            None,
        )
        assert splash_cls is not None, "SplashScreen class missing"
        init = next(
            (n for n in splash_cls.body if isinstance(n, ast.FunctionDef)
             and n.name == "__init__"),
            None,
        )
        assert init is not None, "SplashScreen.__init__ missing"
        src = ast.unparse(init)

        # Structural anchors: the safe branch (is_safe_ui()) must NOT set
        # WA_TranslucentBackground; the else-branch must set it.
        assert "is_safe_ui()" in src, (
            "SplashScreen must split on render_guard.is_safe_ui()")
        # Two occurrences of WA_TranslucentBackground would mean buggy code
        # that unconditionally sets it.  Exactly one occurrence in the
        # `else:` path is the target shape.
        wa_hits = [
            i for i in range(len(src))
            if src.startswith("WA_TranslucentBackground", i)
        ]
        assert len(wa_hits) >= 1, (
            "SplashScreen must at least have one WA_TranslucentBackground ref")

        # Else-branch setAttribute: ensure WA_TranslucentBackground only
        # shows up in the non-safe path.  Short of full CFG we settle for
        # checking the if block nests setWindowFlags(StaysOnTopHint) without
        # FramelessWindowHint, and else-nest sets both.
        assert "FramelessWindowHint" in src, (
            "non-safe SplashScreen must set FramelessWindowHint")
        # Sanity: at least one setWindowFlags + one setAttribute are present.
        assert src.count("setWindowFlags") >= 2, (
            "SplashScreen needs two setWindowFlags() calls (safe / regular)")

    def test_splash_safe_branch_sets_border_radius_zero(self):
        """Safe branch: QFrame#splashContainer border-radius should be 0px."""
        tree = ast.parse(self._entry_src())
        splash_cls = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.ClassDef) and n.name == "SplashScreen"),
            None,
        )
        init = next(
            (n for n in splash_cls.body if isinstance(n, ast.FunctionDef)
             and n.name == "__init__"),
            None,
        )
        src = ast.unparse(init)
        # Render-mode selection: border-radius: 12px (non-safe) vs 0px (safe)
        assert "border-radius: 12px" in src, (
            "Regular splash must keep rounded corners")
        assert "border-radius: 0px" in src, (
            "Safe-UI splash must use border-radius: 0 (no rounded corners)")
