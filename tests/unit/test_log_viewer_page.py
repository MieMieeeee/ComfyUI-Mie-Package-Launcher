"""LogViewerPage 单元测试:实时 tail ComfyUI 日志并显示。"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtWidgets

from ui_qt.log_viewer import LogViewerPage
from ui_qt.theme_manager import ThemeManager


def _process_events_for(seconds):
    """Run Qt event loop for `seconds` seconds (so tailer callbacks land)."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)


class _Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.tm = ThemeManager()

    def _tmpdir(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d


class TestLogViewerPageCreation(_Fixture):
    def test_create_with_minimum_args(self):
        page = LogViewerPage(theme_manager=self.tm)
        self.assertIsNotNone(page)

    def test_has_required_controls(self):
        page = LogViewerPage(theme_manager=self.tm)
        # 必须有这几个控件供 UI / 测试用
        self.assertTrue(hasattr(page, "text_edit"))
        self.assertIsInstance(page.text_edit, QtWidgets.QTextEdit)
        self.assertTrue(page.text_edit.isReadOnly())
        self.assertTrue(hasattr(page, "collapse_checkbox"))
        self.assertIsInstance(page.collapse_checkbox, QtWidgets.QCheckBox)
        self.assertTrue(hasattr(page, "pause_btn"))
        self.assertTrue(hasattr(page, "clear_btn"))
        self.assertTrue(hasattr(page, "save_btn"))


class TestLogViewerPageTailing(_Fixture):
    def test_new_lines_appear_in_view(self):
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        with open(log, "a", encoding="utf-8") as f:
            f.write("hello world\n")
        # 等 tailer 抓到这行 + 投递到 UI
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            if "hello world" in page.text_edit.toPlainText():
                return
            time.sleep(0.02)
        self.fail("line not appended: " + repr(page.text_edit.toPlainText()))

    def test_pause_stops_appending(self):
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("first\n", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        _process_events_for(0.3)
        # 暂停
        page.pause_btn.click()
        self.app.processEvents()
        # 暂停时新增的行不应被 append
        with open(log, "a", encoding="utf-8") as f:
            f.write("ignored_line\n")
        _process_events_for(0.5)
        self.assertNotIn("ignored_line", page.text_edit.toPlainText())
        # 恢复
        page.pause_btn.click()
        self.app.processEvents()
        with open(log, "a", encoding="utf-8") as f:
            f.write("after_resume\n")
        _process_events_for(1.0)
        self.assertIn("after_resume", page.text_edit.toPlainText())

    def test_clear_button_empties_view(self):
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("first_line\n", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        _process_events_for(0.3)
        self.assertIn("first_line", page.text_edit.toPlainText())
        page.clear_btn.click()
        self.app.processEvents()
        self.assertEqual(page.text_edit.toPlainText(), "")

    def test_collapse_checkbox_toggles_collapse(self):
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        # 默认折叠开启
        self.assertTrue(page.collapse_checkbox.isChecked())
        with open(log, "a", encoding="utf-8") as f:
            for pct in ("10", "20", "30", "40"):
                f.write(f"Loading: {pct}%\r\n")
            f.write("done\n")
        _process_events_for(0.8)
        text_collapsed = page.text_edit.toPlainText()
        self.assertIn("done", text_collapsed)
        self.assertIn("lines collapsed", text_collapsed)
        # 关掉折叠,清空再写
        page.clear_btn.click()
        self.app.processEvents()
        page.collapse_checkbox.setChecked(False)
        self.app.processEvents()
        with open(log, "a", encoding="utf-8") as f:
            for pct in ("50", "60", "70"):
                f.write(f"Loading: {pct}%\r\n")
            f.write("finished\n")
        _process_events_for(0.8)
        text_raw = page.text_edit.toPlainText()
        self.assertIn("finished", text_raw)
        self.assertNotIn("lines collapsed", text_raw)


if __name__ == "__main__":
    unittest.main()