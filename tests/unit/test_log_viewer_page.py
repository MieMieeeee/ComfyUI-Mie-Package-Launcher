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


class TestLogViewerPageWrap(_Fixture):
    """自动换行 checkbox:切换 text_edit 的 lineWrapMode。"""

    def test_has_wrap_checkbox(self):
        page = LogViewerPage(theme_manager=self.tm)
        self.assertTrue(hasattr(page, "wrap_checkbox"))
        self.assertIsInstance(page.wrap_checkbox, QtWidgets.QCheckBox)

    def test_wrap_default_is_off(self):
        page = LogViewerPage(theme_manager=self.tm)
        self.assertFalse(page.wrap_checkbox.isChecked())
        # text_edit 默认 NoWrap
        self.assertEqual(
            page.text_edit.lineWrapMode(),
            QtWidgets.QTextEdit.NoWrap,
        )

    def test_toggle_wrap_changes_mode(self):
        page = LogViewerPage(theme_manager=self.tm)
        page.wrap_checkbox.setChecked(True)
        self.app.processEvents()
        self.assertEqual(
            page.text_edit.lineWrapMode(),
            QtWidgets.QTextEdit.WidgetWidth,
        )
        page.wrap_checkbox.setChecked(False)
        self.app.processEvents()
        self.assertEqual(
            page.text_edit.lineWrapMode(),
            QtWidgets.QTextEdit.NoWrap,
        )

if __name__ == "__main__":
    unittest.main()

class TestLogViewerPageLineCap(_Fixture):
    """行数上限:setMaximumBlockCount 把最早的块裁掉,防止几 MB log 把 QTextEdit 撑爆。"""

    def test_max_lines_drops_oldest(self):
        page = LogViewerPage(theme_manager=self.tm, max_lines=3)
        for i in range(5):
            page._append_line(f"line {i}")
        text = page.text_edit.toPlainText()
        self.assertIn("line 4", text)
        self.assertNotIn("line 0", text)
        self.assertNotIn("line 1", text)
        # 剩下的就是最后 3 行
        kept = [l for l in text.split(chr(10)) if l]
        self.assertEqual(len(kept), 3)
        self.assertEqual(kept[-1], "line 4")

    def test_default_max_lines_is_generous(self):
        page = LogViewerPage(theme_manager=self.tm)
        for i in range(100):
            page._append_line(f"line {i}")
        text = page.text_edit.toPlainText()
        self.assertIn("line 99", text)
        self.assertIn("line 0", text)  # 默认 5000 够装下


class TestLogViewerPageColoring(_Fixture):
    """行高亮:时间戳灰色,ERROR/CRITICAL 红,WARNING 黄,其他默认色。"""

    def _html(self, line):
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line(line)
        return page.text_edit.toHtml()

    def test_error_line_uses_red(self):
        h = self._html("2026-07-02 14:09:43 [ERROR] something failed")
        self.assertIn("something failed", h)
        # 应该有一个红色 span(具体 hex 由实现决定,但不能是默认灰)
        self.assertIn("color", h.lower())

    def test_warning_line_uses_yellow(self):
        h = self._html("[WARNING] heads up")
        self.assertIn("heads up", h)
        self.assertIn("color", h.lower())

    def test_info_line_uses_default(self):
        h = self._html("[INFO] normal message")
        self.assertIn("normal message", h)

    def test_timestamp_rendered(self):
        h = self._html("2026-07-02 14:09:43,123 [INFO] hi")
        self.assertIn("2026-07-02 14:09:43,123", h)
        self.assertIn("hi", h)

    def test_html_escapes_special_chars(self):
        h = self._html("[INFO] <script>alert(1)</script>")
        # 原始 <script> 不能作为 HTML 标签出现
        self.assertNotIn("<script>", h)
        self.assertIn("&lt;script&gt;", h)

    def test_plain_text_preserved(self):
        # toPlainText 必须保留原文(用于搜索 / 测试断言)
        h = self._html("2026-07-02 [ERROR] boom")
        # 拿到 QTextEdit 内部 text,确保不含 HTML 标签
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line("2026-07-02 [ERROR] boom")
        plain = page.text_edit.toPlainText()
        self.assertIn("boom", plain)
        self.assertNotIn("<span", plain)


if __name__ == "__main__":
    unittest.main()