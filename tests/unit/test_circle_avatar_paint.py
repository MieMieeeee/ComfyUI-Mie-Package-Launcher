"""Tests for CircleAvatar.paintEvent rendering.

Regression guard for a bug where the avatar only showed its top-left quarter:
the paint code multiplied the target size by devicePixelRatio and manually
called setDevicePixelRatio, but QPixmap.width() still reports physical (not
logical) pixels, so the centering offset was computed against the wrong
dimension — shifting the pixmap up/left and clipping 3/4 of it outside the
circular clip path.

These tests render the avatar to an offscreen pixmap and assert the avatar
content actually fills the widget area (not just a quarter).
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestCircleAvatarPaint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5 import QtGui, QtWidgets

        cls.QtGui = QtGui
        cls.QtWidgets = QtWidgets
        cls._app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def _make_avatar(self, size=80):
        from PyQt5 import QtCore, QtGui
        from ui_qt.widgets.custom import CircleAvatar

        # A solid-color source pixmap (deterministic, no asset dependency).
        src = QtGui.QPixmap(size * 4, size * 4)
        src.fill(QtGui.QColor(0, 200, 0))  # green avatar content
        av = CircleAvatar(pixmap=src, size=size)
        av.resize(size, size)
        return av

    def _coverage(self, av, size, fill_color, content_predicate):
        """Render av to a pixmap filled with fill_color; return fraction of
        pixels where content_predicate(pixelColor) is True (avatar content)."""
        from PyQt5 import QtGui

        out = QtGui.QPixmap(size, size)
        out.fill(fill_color)
        painter = QtGui.QPainter(out)
        av.render(painter)
        painter.end()
        img = out.toImage()
        n_total = size * size
        n_content = 0
        for y in range(size):
            for x in range(size):
                if content_predicate(img.pixelColor(x, y)):
                    n_content += 1
        return n_content / n_total

    def test_avatar_fills_most_of_circle(self):
        """The avatar image must cover most of the circular widget, not 1/4.

        A full circle inscribed in a square covers ~π/4 ≈ 78.5% of the square.
        With the quarter-avatar bug, coverage dropped to ~20%. Assert >65% to
        allow for antialiasing while still catching the regression.
        """
        size = 80
        av = self._make_avatar(size)
        red = self.QtGui.QColor(255, 0, 0)

        def is_avatar_content(c):
            # Avatar is green; background is red. Green-dominant = content.
            return c.green() > 100 and c.red() < 150

        coverage = self._coverage(av, size, red, is_avatar_content)
        self.assertGreater(
            coverage,
            0.65,
            f"avatar only covers {coverage:.0%} of widget — likely clipped "
            f"(the quarter-avatar regression). Expected >65% for a full circle.",
        )

    def test_avatar_not_shifted_to_corner(self):
        """Specifically guard against the offset bug: content must appear in all
        four quadrants, not just the top-left. Check the center pixel is avatar
        content (would be background if the image shifted to a corner)."""
        size = 80
        av = self._make_avatar(size)
        from PyQt5 import QtGui

        out = QtGui.QPixmap(size, size)
        out.fill(QtGui.QColor(255, 0, 0))  # red background
        painter = QtGui.QPainter(out)
        av.render(painter)
        painter.end()
        img = out.toImage()
        center = img.pixelColor(size // 2, size // 2)
        # Center of the circle should be avatar content (green), not red bg.
        self.assertGreater(
            center.green(), 100, "center pixel is background — avatar is offset/shifted"
        )

    def test_paint_event_does_not_use_manual_dpr(self):
        """Source-level guard: the paint code must NOT manually call
        setDevicePixelRatio / multiply by devicePixelRatio — that's what caused
        the quarter-avatar bug (QPixmap.width() reports physical px after
        setDevicePixelRatio, so the centering offset was computed wrong)."""
        import inspect

        from ui_qt.widgets import custom

        src = inspect.getsource(custom.CircleAvatar.paintEvent)
        self.assertNotIn(
            "setDevicePixelRatio",
            src,
            "paintEvent must not call setDevicePixelRatio — Qt's logical-coord "
            "system + AA_UseHighDpiPixmaps handles HiDPI; manual DPR scaling "
            "broke centering (quarter-avatar bug).",
        )
        self.assertNotIn(
            "* dpr",
            src,
            "paintEvent must not multiply by dpr — see setDevicePixelRatio note.",
        )


if __name__ == "__main__":
    unittest.main()
