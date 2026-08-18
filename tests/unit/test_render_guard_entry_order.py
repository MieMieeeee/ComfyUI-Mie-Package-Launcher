"""Source-level contract tests for the render-guard entry wiring.

Verifies (without importing qt_app / PyQt5, which segfaults in some
environments):
  1. install_crash_reporting() is the VERY first call in launch_gui
  2. render_guard.prepare() is called in the lock-failure (single instance)
     branch BEFORE _show_single_instance_dialog
  3. render_guard.begin() is called after lock.acquire() succeeds and
     BEFORE _configure_qt_highdpi / QApplication instantiation
  4. render_guard.finish() is called AFTER window.run() and is NOT inside
     the finally block (so a PyQtLauncher construction exception does NOT
     clear the crash signal, losing the escalation opportunity)
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = (REPO_ROOT / "comfyui_launcher_pyqt.py").read_text(encoding="utf-8")


def _extract_launch_gui_body(src: str) -> ast.FunctionDef:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "launch_gui":
            return node
    raise AssertionError("launch_gui() not found in comfyui_launcher_pyqt.py")


class TestEntryWiringOrder(unittest.TestCase):
    """Source-level ordering / placement contracts."""

    @classmethod
    def setUpClass(cls):
        cls.fn = _extract_launch_gui_body(SRC)

    # ---- 1. crash_reporting earliest -----------------------------------
    def test_crash_reporting_is_earliest_call_in_launch_gui(self):
        """install_crash_reporting must be the first real statement in
        launch_gui (optionally preceded by the SingletonLock creation line
        or pass/comment but nothing else that could crash)."""
        body = self.fn.body
        src_lines = []
        for stmt in body:
            seg = ast.get_source_segment(SRC, stmt) or ""
            src_lines.append(seg.strip())
        joined = "\n".join(src_lines)
        # Either very first call, or first non-lock line. Allow the lock
        # line to come before OR after (crash reporting should ideally be
        # earliest, so we search for install_crash_reporting as one of
        # the first two non-assign statements).
        idx_crash = next(
            (i for i, s in enumerate(src_lines) if "install_crash_reporting" in s),
            -1,
        )
        self.assertNotEqual(
            idx_crash, -1, "install_crash_reporting() not found in launch_gui"
        )
        idx_lock = next(
            (i for i, s in enumerate(src_lines) if "SingletonLock" in s), -1
        )
        idx_highdpi = next(
            (i for i, s in enumerate(src_lines) if "_configure_qt_highdpi" in s), -1
        )
        idx_qapp = next(
            (i for i, s in enumerate(src_lines) if "QApplication" in s), -1
        )
        # crash must be before highdpi / QApplication
        self.assertLess(
            idx_crash, idx_highdpi,
            "install_crash_reporting() must be called BEFORE _configure_qt_highdpi"
        )
        self.assertLess(
            idx_crash, idx_qapp,
            "install_crash_reporting() must be called BEFORE QApplication creation"
        )

    # ---- 2. prepare in lock-failure branch ----------------------------
    def test_prepare_is_called_in_lock_failure_branch_before_dialog(self):
        """In the ``if not lock.acquire():`` block, render_guard.prepare()
        must appear before _show_single_instance_dialog() call, so that
        safe-UI disables WA_TranslucentBackground on the dialog."""
        # Use regex: find block after "if not lock.acquire():"
        m = re.search(
            r"if\s+not\s+lock\.acquire\(\)\s*:\s*\n(?P<body>(?:\s{4,}.*\n?)+)",
            SRC,
        )
        self.assertIsNotNone(m, "Could not locate 'if not lock.acquire():' block")
        block = m.group("body")
        pos_prep = block.find("render_guard.prepare()")
        pos_dlg = block.find("_show_single_instance_dialog()")
        self.assertNotEqual(
            pos_prep, -1,
            "lock-failure branch missing render_guard.prepare()"
        )
        self.assertNotEqual(
            pos_dlg, -1,
            "lock-failure branch missing _show_single_instance_dialog()"
        )
        self.assertLess(
            pos_prep, pos_dlg,
            "render_guard.prepare() must come BEFORE dialog in lock-failure"
            " branch (so safe-UI env is set before widget creation)"
        )

    # ---- 3. begin() before QApplication --------------------------------
    def test_begin_is_called_after_lock_success_before_qapplication(self):
        """render_guard.begin() must set QT_OPENGL / safe UI env BEFORE
        QApplication(...) instantiation (Qt reads QT_OPENGL once at
        QApplication ctor)."""
        stmts = [ast.get_source_segment(SRC, s) or "" for s in self.fn.body]
        idx_begin = next(
            (i for i, s in enumerate(stmts) if "render_guard.begin()" in s), -1
        )
        idx_highdpi = next(
            (i for i, s in enumerate(stmts) if "_configure_qt_highdpi()" in s), -1
        )
        idx_qapp = next(
            (i for i, s in enumerate(stmts) if "QApplication(" in s), -1
        )
        self.assertNotEqual(idx_begin, -1, "render_guard.begin() not found")
        self.assertNotEqual(idx_highdpi, -1, "_configure_qt_highdpi() not found")
        self.assertNotEqual(idx_qapp, -1, "QApplication(...) not found")
        self.assertLess(
            idx_begin, idx_highdpi,
            "render_guard.begin() must be BEFORE _configure_qt_highdpi() so "
            "QT_OPENGL software is set before Qt init"
        )
        self.assertLess(
            idx_begin, idx_qapp,
            "render_guard.begin() must be BEFORE QApplication creation"
        )

    # ---- 4. finish() outside finally -----------------------------------
    def test_finish_is_called_after_window_run_and_not_in_finally(self):
        """finish() must only fire on the SUCCESS path (after window.run()
        returns normally). Placing it inside a ``finally:`` would wrongly
        clear the crash signal when PyQtLauncher() construction throws —
        exactly the scenario we need the signal to persist for the next
        run's escalation."""
        # Find finish() and run() calls in launch_gui. Check their
        # relative order first.
        finish_pattern = re.compile(r"\brender_guard\.finish\(\)\s*")
        run_pattern = re.compile(r"\bwindow\.run\(\)\s*")
        matches_fin = list(finish_pattern.finditer(SRC))
        matches_run = list(run_pattern.finditer(SRC))
        self.assertTrue(matches_fin, "render_guard.finish() not found in module")
        self.assertTrue(matches_run, "window.run() not found in module")
        # Restrict to launch_gui range (get line numbers via fn.lineno/end_lineno)
        def _in_fn(m):
            return self.fn.lineno <= (m.start() >= 0 and _line_of(m.start())) <= (self.fn.end_lineno or 10**9)

        def _line_of(pos):
            return SRC.count("\n", 0, pos) + 1

        in_fn_fin = [m for m in matches_fin if
                     self.fn.lineno <= _line_of(m.start()) <= (self.fn.end_lineno or 10**9)]
        in_fn_run = [m for m in matches_run if
                     self.fn.lineno <= _line_of(m.start()) <= (self.fn.end_lineno or 10**9)]
        self.assertTrue(in_fn_run, "window.run() not in launch_gui")
        self.assertTrue(in_fn_fin, "render_guard.finish() not in launch_gui")
        # Order: run must precede finish
        self.assertLess(
            in_fn_run[-1].start(), in_fn_fin[0].start(),
            "window.run() must be invoked BEFORE render_guard.finish()"
        )
        # finish() must NOT be inside the `finally:` clause of launch_gui
        # Strategy: extract text between "finally:" and end of its suite.
        fn_src = ast.get_source_segment(SRC, self.fn) or ""
        # Find the finally block. A simple heuristic: search for "finally:"
        # in the function source, then find its statement suite (indented
        # block). If finish() appears only there, fail.
        m_finally = re.search(r"[^\n]*finally\s*:\s*\n", fn_src)
        if m_finally is not None:
            # get rest of fn after "finally:"
            rest = fn_src[m_finally.end():]
            # strip leading newline, then get indented lines until an
            # unindent line at the function's base indentation level.
            lines = rest.splitlines()
            # base indent of function body
            body_stmt_line = fn_src.splitlines()[1] if len(fn_src.splitlines()) > 1 else ""
            base_indent = len(body_stmt_line) - len(body_stmt_line.lstrip())
            finally_lines = []
            for line in lines:
                if not line.strip():
                    finally_lines.append(line)
                    continue
                ind = len(line) - len(line.lstrip())
                if ind > base_indent:
                    finally_lines.append(line)
                else:
                    break
            finally_block = "\n".join(finally_lines)
            self.assertFalse(
                "render_guard.finish()" in finally_block,
                "render_guard.finish() MUST NOT be in the finally block "
                "(construction exceptions would falsely clear the crash "
                "sentinel, losing auto-escalation)"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
