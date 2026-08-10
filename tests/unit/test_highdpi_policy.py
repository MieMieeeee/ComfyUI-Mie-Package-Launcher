"""Tests for Qt high-DPI attribute setup at GUI launch.

Background (review issue): ``comfyui_launcher_pyqt.launch_gui`` set
``AA_EnableHighDpiScaling`` + ``AA_UseHighDpiPixmaps`` but did NOT call
``setHighDpiScaleFactorRoundingPolicy(PassThrough)``. The default rounding
policy depends on the PyQt5/Qt version (Floor on older Qt5, PassThrough on
newer), which means a 150% Windows scaling could be floored to 100% on some
builds — an unpredictable, version-dependent behavior. We want it pinned.

These tests are source-level (read ``comfyui_launcher_pyqt.py`` text and
assert the call sites) so they run in every environment — including the
PyQt5/sip ABI combo where ``import ui_qt.qt_app`` segfaults (pre-existing
baseline issue that blocks any live-window test here). The behavioral
assertion (the policy actually gets applied at runtime) is covered by the
compiled-exe boot E2E (``tests/e2e/test_compiled_exe_boot.py``) on machines
that can build/run the launcher.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LAUNCHER_SRC = REPO_ROOT / "comfyui_launcher_pyqt.py"


class TestHighDpiPolicyConfig(unittest.TestCase):
    """Source-level contract for the HiDPI setup block."""

    @classmethod
    def setUpClass(cls):
        cls.src = LAUNCHER_SRC.read_text(encoding="utf-8")

    # ---- PassThrough rounding policy -------------------------------------

    def test_pass_through_rounding_policy_is_set(self):
        """``launch_gui`` must explicitly set PassThrough rounding policy.

        Acceptable: a call to ``setHighDpiScaleFactorRoundingPolicy`` with
        ``PassThrough`` (or its full qualified path), guarded by ``hasattr``
        so older PyQt5 without the enum doesn't crash. A bare default
        (no explicit call) is the bug — behavior then depends on Qt version.
        """
        # Look for the setter call anywhere in the module.
        # Tolerate either QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        # or HighDpiScaleFactorRoundingPolicy.PassThrough (if star-imported).
        setter_re = re.compile(
            r"setHighDpiScaleFactorRoundingPolicy\s*\(\s*"
            r"[A-Za-z_.]*HighDpiScaleFactorRoundingPolicy\.PassThrough\s*\)",
            re.MULTILINE,
        )
        self.assertIsNotNone(
            setter_re.search(self.src),
            "comfyui_launcher_pyqt.py does not explicitly call "
            "setHighDpiScaleFactorRoundingPolicy(PassThrough). The default "
            "rounding policy is Qt-version-dependent (Floor on older Qt5), "
            "which can truncate 150% scaling to 100% unpredictably.",
        )

    def test_pass_through_call_is_guarded_by_hasattr(self):
        """The PassThrough call must be guarded so old PyQt5 doesn't crash.

        ``QtCore.Qt.HighDpiScaleFactorRoundingPolicy`` was added in Qt 5.14
        (PyQt5 5.14+). On older bindings it's absent and the call would raise
        AttributeError. The guard (typically ``hasattr(QtCore.Qt, ...)``) must
        appear within a few lines BEFORE the actual setter CALL site.

        We anchor on the real call (``QApplication.setHighDpiScaleFactorRoundingPolicy(``)
        rather than any docstring mention of the name, then look ~300 chars
        back for the hasattr guard.
        """
        src = self.src
        # Anchor on the real call: a ``.setHighDpiScaleFactorRoundingPolicy(``
        # invocation (preceded by QApplication or QtWidgets.QApplication).
        # This skips docstring mentions of the bare name.
        setter_match = re.search(
            r"QApplication\.setHighDpiScaleFactorRoundingPolicy\s*\(",
            src,
        )
        self.assertIsNotNone(
            setter_match, "Real PassThrough setter call not found"
        )
        preceding = src[max(0, setter_match.start() - 300): setter_match.start()]
        self.assertTrue(
            "hasattr" in preceding
            and "HighDpiScaleFactorRoundingPolicy" in preceding,
            "PassThrough rounding policy call is not guarded by a hasattr "
            "check on HighDpiScaleFactorRoundingPolicy — old PyQt5 (<5.14) "
            "will crash with AttributeError.",
        )

    # ---- HiDPI setup is centralized (no copy-paste duplication) ----------

    def test_highdpi_setup_is_extracted_to_helper(self):
        """The two AA_* attribute ``setAttribute`` calls should appear once.

        Originally ``launch_gui`` and ``_show_single_instance_dialog`` each
        duplicated the same try/hasattr/setAttribute block (review issue:
        fragile duplication). After refactor, both delegate to a shared
        helper. We count actual ``setAttribute(...AA_EnableHighDpiScaling...)``
        *call sites* (not docstring/comment mentions of the name) and require
        at most one — i.e. no copy-pasted attribute-setting block survives.

        Mentions inside docstrings/comments (the helper's own docstring, etc.)
        are tolerated; what matters is that only ONE place actually issues
        the ``setAttribute`` call.
        """
        # Match a real call: setAttribute( ... AA_EnableHighDpiScaling ... )
        # The argument may be qualified (QtCore.Qt.AA_EnableHighDpiScaling).
        call_sites = re.findall(
            r"setAttribute\s*\(\s*[A-Za-z_.]*AA_EnableHighDpiScaling",
            self.src,
        )
        self.assertLessEqual(
            len(call_sites),
            1,
            "setAttribute(AA_EnableHighDpiScaling) is invoked "
            f"{len(call_sites)} times — should be centralized in a single "
            "helper (e.g. _configure_qt_highdpi) so launch_gui and "
            "_show_single_instance_dialog both delegate to it.",
        )

    def test_configure_qt_highdpi_helper_exists(self):
        """A module-level ``_configure_qt_highdpi`` helper must exist.

        Both call sites delegate to it (this is the dedup mechanism).
        """
        self.assertIn(
            "def _configure_qt_highdpi(",
            self.src,
            "_configure_qt_highdpi helper not defined — needed to "
            "centralize the HiDPI attribute setup.",
        )

    def test_both_call_sites_delegate_to_helper(self):
        """launch_gui and _show_single_instance_dialog both call the helper."""
        # Each call site should invoke the helper.
        calls = re.findall(r"_configure_qt_highdpi\s*\(\s*\)", self.src)
        # 1 def + at least 2 call sites (launch_gui + single-instance dialog).
        self.assertGreaterEqual(
            len(calls),
            2,
            f"Expected _configure_qt_highdpi() to be CALLED from at least 2 "
            f"sites (launch_gui + _show_single_instance_dialog); found "
            f"{len(calls)} non-definition invocations.",
        )


if __name__ == "__main__":
    unittest.main()
