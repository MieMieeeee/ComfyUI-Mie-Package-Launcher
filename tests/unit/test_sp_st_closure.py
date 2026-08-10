"""Pure-Python unit test for the ``self._sp``/``self._st`` closure-capture
contract — runnable even when ``ui_qt.qt_app`` cannot be imported (the
pre-existing PyQt5/sip ABI segfault that blocks PyQtLauncher construction
on some machines).

The bug (review issue): in ``qt_app._setup_ui`` the helpers were defined as

    self._scale = self._compute_current_scale()
    _scale = self._scale
    self._sp = lambda base: max(1, int(round(base * _scale)))   # closes over local _scale

After ``_apply_screen_change`` updates ``self._scale = new_scale``, the
lambda still sees the *captured-at-construction-time* ``_scale``, so
``self._sp(100)`` returns the stale value. The fix is to read
``self._scale`` inside the lambda so it tracks the live attribute.

This test does NOT import ``ui_qt.qt_app`` (which segfaults here). Instead
it reads the source of ``_setup_ui`` and asserts the helper definitions
reference ``self._scale``, not a bare captured ``_scale``. That's a
source-level guard (same pattern as ``test_circle_avatar_paint.py`` which
bans ``setDevicePixelRatio`` at the source level), so it runs in every
environment.

The behavioral assertion (``self._sp(100) == 125`` after
``self._scale = 1.25``) lives in ``test_screen_change_scaling.py`` and
exercises the real window in a subprocess on machines where it imports.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
QT_APP = REPO_ROOT / "ui_qt" / "qt_app.py"


class TestSpStClosureContract(unittest.TestCase):
    """Source-level contract: ``self._sp``/``self._st`` must read live ``self._scale``."""

    @classmethod
    def setUpClass(cls):
        # Read the source once; fail loudly if the file moves/disappears
        # (a moved file silently passing is worse than a clear error).
        cls.src = QT_APP.read_text(encoding="utf-8")

    def _find_lambda_line(self, name: str) -> str:
        """Find the ``self._sp = lambda ...`` (or self._st) source line.

        Searches the whole file for the assignment. The two definitions
        live in ``_setup_ui`` but may be separated by comment lines, so we
        match each independently rather than as a consecutive block.
        """
        # ``self._sp = lambda base: <expr>`` up to the inline comment / EOL.
        m = re.search(
            rf"{re.escape(name)}\s*=\s*lambda[^#\n]*",
            self.src,
        )
        self.assertIsNotNone(m, f"Could not locate {name} lambda definition")
        return m.group(0)

    def test_sp_reads_live_self_scale(self):
        """``self._sp`` must read ``self._scale`` (live), not a captured local.

        Acceptable forms:
            self._sp = lambda base: max(1, int(round(base * self._scale)))
            self._sp = lambda base: max(1, int(round(base * self._scale)))  # comment

        A bare ``_scale`` (no ``self.``) in the multiplier is the bug.
        """
        for name in ("self._sp", "self._st"):
            line = self._find_lambda_line(name)
            # Must reference self._scale (with self. prefix) as the multiplier.
            self.assertIn(
                "self._scale",
                line,
                f"{name} lambda does not read live self._scale; it likely "
                f"captures a stale local _scale (review issue). Line: {line}",
            )
            # Must NOT reference a bare _scale (no self.) as the multiplier.
            # ``(?<!self\.)`` rejects ``self._scale`` while flagging bare ``_scale``.
            bare = re.findall(r"(?<!self\.)_scale", line)
            self.assertEqual(
                bare,
                [],
                f"{name} lambda references bare _scale (captured local) "
                f"instead of self._scale. Line: {line}",
            )


if __name__ == "__main__":
    unittest.main()
