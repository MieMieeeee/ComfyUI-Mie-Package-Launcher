"""LogViewerPage 单元测试:实时 tail ComfyUI 日志并显示。"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertTrue(hasattr(page, "open_in_explorer_btn"))


class TestOpenInExplorer(_Fixture):
    """「📁 打开日志文件」按钮:在文件管理器里选中日志文件。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.tm = ThemeManager()

    def test_button_exists_with_label(self):
        page = LogViewerPage(theme_manager=self.tm)
        self.assertTrue(hasattr(page, "open_in_explorer_btn"))
        self.assertIn("打开", page.open_in_explorer_btn.text())

    def test_invokes_explorer_select_on_windows(self):
        """Windows 上点按钮 → explorer /select,<path> 选中文件。"""
        d = self._tmpdir()
        log = d / "comfyui.log"
        log.write_text("some log\n", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        cmds = []
        with patch("ui_qt.log_viewer.subprocess.Popen", side_effect=lambda *a, **k: cmds.append(a[0] if a else k.get("args"))) as m, \
             patch("ui_qt.log_viewer.platform.system", return_value="Windows"):
            page._on_open_in_explorer()
        m.assert_called_once()
        # 命令含 explorer + /select, + 文件路径
        called = cmds[0]
        self.assertIn("explorer", called)
        self.assertIn("/select,", called)
        self.assertIn(str(log), called)

    def test_noop_when_no_log_path(self):
        """未设置日志路径 → 提示而非崩溃(实际弹框,这里 mock 掉避免 offscreen 崩)。"""
        page = LogViewerPage(theme_manager=self.tm)
        with patch("ui_qt.log_viewer.subprocess.Popen") as m, \
             patch("ui_qt.log_viewer.QtWidgets.QMessageBox.information"):
            page._on_open_in_explorer()  # 不抛
        m.assert_not_called()

    def test_noop_when_log_file_missing(self):
        """日志文件不存在(ComfyUI 未启动) → 不调 explorer。"""
        d = self._tmpdir()
        log = d / "missing.log"  # 不创建
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        with patch("ui_qt.log_viewer.subprocess.Popen") as m, \
             patch("ui_qt.log_viewer.QtWidgets.QMessageBox.information"):
            page._on_open_in_explorer()
        m.assert_not_called()


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

    def test_wrap_default_is_on(self):
        page = LogViewerPage(theme_manager=self.tm)
        self.assertTrue(page.wrap_checkbox.isChecked())
        # text_edit 默认 WidgetWidth,窄窗口也能看全
        self.assertEqual(
            page.text_edit.lineWrapMode(),
            QtWidgets.QTextEdit.WidgetWidth,
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
        page._flush_batch()  # 批量缓冲需手动 flush(测试不等 50ms 定时器)
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
        page._flush_batch()
        text = page.text_edit.toPlainText()
        self.assertIn("line 99", text)
        self.assertIn("line 0", text)  # 默认 5000 够装下


class TestLogViewerPagePlainText(_Fixture):
    """纯文本模式(移除颜色标识后):内容正确渲染、ANSI 剥离、HTML 转义。

    日志文本不再着色——纯文本批量 append,避免逐行 charFormat 的 O(n²) 富文本布局。
    level 仅用于未读红点,不参与着色。
    """

    def _flush_and_plain(self, page):
        """强制 flush 批量缓冲后取纯文本(测试里不等 50ms 定时器)。"""
        page._flush_batch()
        return page.text_edit.toPlainText()

    def test_error_line_content_preserved(self):
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line("2026-07-02 14:09:43 [ERROR] something failed")
        text = self._flush_and_plain(page)
        self.assertIn("something failed", text)
        self.assertIn("[ERROR]", text)

    def test_warning_line_content_preserved(self):
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line("[WARNING] heads up")
        text = self._flush_and_plain(page)
        self.assertIn("heads up", text)

    def test_info_line_content_preserved(self):
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line("[INFO] normal message")
        text = self._flush_and_plain(page)
        self.assertIn("normal message", text)

    def test_timestamp_rendered(self):
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line("2026-07-02 14:09:43,123 [INFO] hi")
        text = self._flush_and_plain(page)
        self.assertIn("2026-07-02 14:09:43,123", text)
        self.assertIn("hi", text)

    def test_no_color_spans(self):
        """纯文本模式:toHtml 不应包含用户加的颜色 span(用 insertText 写纯文本)。"""
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line("[ERROR] boom")
        html = page.text_edit.toHtml()
        # 不含我们之前用的 inline color span(style="color:...")——Qt 自己的 HTML 骨架不算
        self.assertNotIn('color:#cc', html)
        self.assertNotIn('color:#ff6b6b', html)

    def test_ansi_escape_stripped(self):
        """ANSI 转义码(如 \\x1b[32m 绿色)应被剥掉,不残留进显示文本。"""
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line("\x1b[32m[INFO] green text\x1b[0m")
        text = self._flush_and_plain(page)
        self.assertIn("[INFO] green text", text)
        self.assertNotIn("\x1b", text)

    def test_plain_text_preserved(self):
        # toPlainText 必须保留原文(用于搜索 / 测试断言)
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line("2026-07-02 [ERROR] boom")
        plain = self._flush_and_plain(page)
        self.assertIn("boom", plain)
        self.assertNotIn("<span", plain)


class TestReadTailLines(_Fixture):
    """read_tail_lines:读文件最后 n 行,大文件线性单遍。"""

    def test_returns_last_n_lines(self):
        from ui_qt.log_viewer import read_tail_lines
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("\n".join(f"line {i}" for i in range(100)) + "\n", encoding="utf-8")
        result = read_tail_lines(log, 5)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[-1], "line 99")
        self.assertEqual(result[0], "line 95")

    def test_returns_all_when_fewer_than_n(self):
        from ui_qt.log_viewer import read_tail_lines
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("a\nb\nc\n", encoding="utf-8")
        result = read_tail_lines(log, 100)
        self.assertEqual(result, ["a", "b", "c"])

    def test_strips_carriage_return(self):
        from ui_qt.log_viewer import read_tail_lines
        d = self._tmpdir()
        log = d / "test.log"
        log.write_bytes(b"line1\r\nline2\r\n")
        result = read_tail_lines(log, 10)
        self.assertEqual(result, ["line1", "line2"])

    def test_missing_file_returns_empty(self):
        from ui_qt.log_viewer import read_tail_lines
        d = self._tmpdir()
        self.assertEqual(read_tail_lines(d / "nope.log", 10), [])


class TestHistoryLazyLoad(_Fixture):
    """历史日志按需加载:启动只 tail 末尾,首次切到页面才读最近 N 行。"""

    def test_history_loaded_on_first_show_event(self):
        """showEvent 首次触发 → 读文件末尾 N 行填充视图。"""
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("\n".join(f"old line {i}" for i in range(600)) + "\n", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        # 模拟首次切到本页(showEvent)
        from PyQt5 import QtGui
        page.showEvent(QtGui.QShowEvent())
        text = page.text_edit.toPlainText()
        # 最近 500 行里有 line 599(末尾),没有 line 49(太早,在 500 行窗口外)
        self.assertIn("old line 599", text)
        self.assertNotIn("old line 49\n", text)  # 用 \n 锚定,避免匹配到 line 490 等

    def test_history_loaded_only_once(self):
        """再次 showEvent 不重复读历史。"""
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("first\n", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        from PyQt5 import QtGui
        page.showEvent(QtGui.QShowEvent())
        # 往文件追加新行(模拟 tailer 不在跑的纯历史场景)
        log.write_text("first\nsecond\n", encoding="utf-8")
        page._flush_batch()
        page.showEvent(QtGui.QShowEvent())  # 再次触发,不重读
        text = page.text_edit.toPlainText()
        # second 不应被历史加载拉进来(只首次加载过)
        self.assertNotIn("second", text)

    def test_no_history_load_until_show(self):
        """不触发 showEvent → 不读历史(tailer 只从末尾跟随新行)。"""
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("old content\n", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        # 不调 showEvent,直接查文本
        self.assertEqual(page.text_edit.toPlainText(), "")


class TestBatchRendering(_Fixture):
    """批量渲染:行进缓冲,定时器 flush 时一次性 append。"""

    def test_lines_buffered_until_flush(self):
        """_append_line 后行在缓冲里,不立即写 QTextEdit。"""
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line("buffered line")
        # 没调 _flush_batch,文本里不应有
        self.assertEqual(page.text_edit.toPlainText(), "")
        self.assertEqual(len(page._batch_buffer), 1)

    def test_flush_writes_buffered_lines(self):
        page = LogViewerPage(theme_manager=self.tm)
        page._append_line("a")
        page._append_line("b")
        page._append_line("c")
        page._flush_batch()
        text = page.text_edit.toPlainText()
        self.assertIn("a", text)
        self.assertIn("b", text)
        self.assertIn("c", text)
        self.assertEqual(len(page._batch_buffer), 0)

    def test_flush_empty_buffer_is_noop(self):
        page = LogViewerPage(theme_manager=self.tm)
        page._flush_batch()  # 空 buffer 不抛、不写
        self.assertEqual(page.text_edit.toPlainText(), "")


if __name__ == "__main__":
    unittest.main()