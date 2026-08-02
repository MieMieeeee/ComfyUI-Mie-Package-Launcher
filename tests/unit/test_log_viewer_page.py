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
        # "折叠连续进度" checkbox 已移除 (VirtualTerminal 的 \r 覆盖语义天然折叠进度)
        self.assertFalse(hasattr(page, "collapse_checkbox"))
        self.assertTrue(hasattr(page, "wrap_checkbox"))
        self.assertIsInstance(page.wrap_checkbox, QtWidgets.QCheckBox)
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

    def _wait_for_line(self, page, needle, timeout=3.0):
        """等 needle 出现在视图里,最多 timeout 秒;到了返回 True,超时 False。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if needle in page.text_edit.toPlainText():
                return True
            time.sleep(0.02)
        return False

    def test_no_duplicate_lines_after_env_switch(self):
        """回归:切环境(stop→set_log_path→start)后,新日志每行只出现一次。

        复现真实 bug:PyQt5 对 bound method 做 disconnect 可能静默失败,
        导致 line_received signal 上累积多个指向 _on_line_main 的连接,
        切环境后每行日志被触发多次(用户实测重复 2 次)。
        修复:每次 start_tailing 重建 emitter(连带丢弃旧 emitter 上的残留连接)。
        """
        d = self._tmpdir()
        log_a = d / "env_a.log"
        log_b = d / "env_b.log"
        log_a.write_text("", encoding="utf-8")
        log_b.write_text("", encoding="utf-8")

        page = LogViewerPage(theme_manager=self.tm)
        self.addCleanup(page.stop_tailing)

        # 1. tail 环境 A
        page.set_log_path(log_a)
        page.start_tailing(start_from_beginning=True)
        with open(log_a, "a", encoding="utf-8") as f:
            f.write("line_from_A\n")
        self.assertTrue(self._wait_for_line(page, "line_from_A"))
        # 切换前:每行只出现一次
        self.assertEqual(page.text_edit.toPlainText().count("line_from_A"), 1)

        # 2. 模拟 refresh_after_env_switch 的日志页刷新序列:
        #    stop_tailing() → set_log_path(b) → start_tailing()
        page.stop_tailing()
        page.set_log_path(log_b)
        page.start_tailing(start_from_beginning=True)

        # 3. 环境 B 写一行
        with open(log_b, "a", encoding="utf-8") as f:
            f.write("line_from_B\n")
        self.assertTrue(self._wait_for_line(page, "line_from_B"))

        # 关键断言:切环境后新日志每行只出现一次(bug 触发时会是 2 次)
        self.assertEqual(
            page.text_edit.toPlainText().count("line_from_B"), 1,
            "切换环境后日志行重复了: " + repr(page.text_edit.toPlainText()),
        )

    def test_pause_freezes_view_then_resume_shows_backlog(self):
        """暂停时画面冻结(新行不立即显示),但后台累积;继续后补显示暂停期间的所有新行。

        新语义(类似 ComfyUI 前端 xterm 的暂停):画面冻结但日志不丢。
        tailer 线程不受暂停影响,继续读文件;UI 把暂停期间的段累积到 _pending,
        继续时一次性 feed 给 VirtualTerminal,补显示到末尾。
        """
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
        # 暂停期间写新行 —— 画面应冻结(不立即显示)
        with open(log, "a", encoding="utf-8") as f:
            f.write("paused_line\n")
        _process_events_for(0.5)
        self.assertNotIn("paused_line", page.text_edit.toPlainText(),
                         "暂停期间画面应冻结,新行不立即显示")
        # 继续 —— 暂停期间的 paused_line 应补显示
        page.pause_btn.click()
        _process_events_for(0.5)
        self.assertIn("paused_line", page.text_edit.toPlainText(),
                      "继续后应补显示暂停期间的行")
        # 继续后再写新行,正常显示
        with open(log, "a", encoding="utf-8") as f:
            f.write("after_resume\n")
        _process_events_for(1.0)
        self.assertIn("after_resume", page.text_edit.toPlainText())

    def test_pause_accumulates_and_resume_feeds_to_vt(self):
        """回归(单元级):暂停期间多行累积,继续后按顺序补显示,\\r/\\n 语义保持。

        直接调 _on_line_main + _on_pause_toggled,不依赖真实文件 tail 时序。
        """
        page = LogViewerPage(theme_manager=self.tm)
        page._on_line_main("line1\n")
        page._flush_batch()
        # 暂停
        page._on_pause_toggled(True)
        # 暂停期间来行(含进度条场景:\r 覆盖)
        page._on_line_main("progress: 50%\r")
        page._on_line_main("progress: 100%\n")
        page._on_line_main("line_after\n")
        page._flush_batch()
        # 画面冻结在 line1
        self.assertEqual(page.text_edit.toPlainText(), "line1\n")
        # 继续
        page._on_pause_toggled(False)
        page._flush_batch()
        # 暂停期间的行补显示;进度条 \r 覆盖语义保持(只留 100%)
        text = page.text_edit.toPlainText()
        self.assertIn("line1", text)
        self.assertIn("progress: 100%", text)
        self.assertNotIn("progress: 50%", text)  # 被 \r 覆盖
        self.assertIn("line_after", text)
        # 顺序正确
        self.assertLess(text.index("line1"), text.index("progress: 100%"))
        self.assertLess(text.index("progress: 100%"), text.index("line_after"))
        # pending 清空
        self.assertEqual(page._pending_while_paused, [])

    def test_clear_drops_pending_while_paused(self):
        """暂停期间点清空,累积的 pending 也清掉(继续后不补显示已清空的内容)。"""
        page = LogViewerPage(theme_manager=self.tm)
        page._on_line_main("before\n")
        page._flush_batch()
        page._on_pause_toggled(True)
        page._on_line_main("paused\n")
        page._flush_batch()
        self.assertEqual(len(page._pending_while_paused), 1)
        # 清空(暂停状态下)
        page._on_clear_clicked()
        self.assertEqual(page._pending_while_paused, [])
        self.assertEqual(page.text_edit.toPlainText(), "")
        # 继续 —— paused 不补显示(已被清空)
        page._on_pause_toggled(False)
        page._flush_batch()
        self.assertNotIn("paused", page.text_edit.toPlainText())

    def test_pause_pending_has_cap_drops_oldest(self):
        """暂停累积有 cap:超限后丢最旧的,保留最近(_pending_while_paused 不无限增长)。

        防 OOM:用户暂停几小时 + 高频 tqdm 日志时,pending 列表不能无限增长。
        超出 _PAUSED_PENDING_CAP 后丢最旧的,继续后只补显示最近的 cap 条。
        """
        page = LogViewerPage(theme_manager=self.tm)
        # 用小 cap 方便测试(临时改类属性)
        original_cap = page._PAUSED_PENDING_CAP
        page._PAUSED_PENDING_CAP = 10
        try:
            page._on_pause_toggled(True)
            # 喂 20 个段,超出 cap=10
            for i in range(20):
                page._on_line_main(f"line{i}\n")
            # pending 应被 cap 到 10,且保留最近的(line10..line19)
            self.assertEqual(len(page._pending_while_paused), 10,
                             f"pending 应被 cap 到 10, 实际 {len(page._pending_while_paused)}")
            self.assertIn("line10", page._pending_while_paused[0])
            self.assertIn("line19", page._pending_while_paused[-1])
            # 最旧的 line0..line9 应被丢弃
            self.assertNotIn("line0\n", page._pending_while_paused)
            self.assertNotIn("line9\n", page._pending_while_paused)
            # 继续后补显示最近的 cap 条
            page._on_pause_toggled(False)
            page._flush_batch()
            text = page.text_edit.toPlainText()
            self.assertIn("line19", text)
            self.assertIn("line10", text)
            self.assertNotIn("line0", text)
            self.assertNotIn("line9", text)
        finally:
            page._PAUSED_PENDING_CAP = original_cap

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

    def test_progress_frames_collapse_to_latest(self):
        """VT100 行模型天然折叠 tqdm 多帧进度:只留最终帧,不需 checkbox。

        替代旧的 test_collapse_checkbox_toggles_collapse(checkbox 已移除)。
        VirtualTerminal 的 \\r 覆盖语义自动把多帧进度覆盖成最后一帧。
        注意纯覆盖语义:最后的 done (不带 \\r) 会覆盖 Loading: 40%。
        所以这里用纯 tqdm 序列(末尾是进度帧 + \\n)验证折叠。
        """
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        with open(log, "ab", buffering=0) as f:
            for pct in (10, 20, 30, 40):
                f.write(f"Loading: {pct}%\r".encode())
            f.write(b"Loading: 100%\n")  # 末尾进度帧以 \n 终结
        _process_events_for(0.8)
        text = page.text_edit.toPlainText()
        # 只留最终帧 100%,早期 10%/20%/30%/40% 被 \r 覆盖
        self.assertIn("Loading: 100%", text)
        self.assertNotIn("Loading: 10%", text)
        self.assertNotIn("Loading: 40%", text)


class TestLogViewerPageNewLogSignal(_Fixture):
    """新日志通知信号 new_logs_received 的语义。

    历史上信号按 [LEVEL] 区分 INFO/WARNING/ERROR,主窗口据此显示绿/黄/红
    三色灯。现在改成简单的 "*" 前缀,所以信号只发 "__new__" sentinel,
    不再做日志级别解析。这里锁住这几个契约:

    - 新日志(页面不可见 + notify 开启)-> emit "__new__"
    - showEvent -> emit "__viewed__"
    - 关掉 notify -> emit "__cleared__"
    - 关掉 notify 后,新行不再 emit 信号(开关应该静默生效)
    """

    def _capture_emits(self, page):
        """订阅 new_logs_received,返回 captures 列表"""
        captures = []
        page.new_logs_received.connect(lambda marker: captures.append(marker))
        return captures

    def test_new_line_emits_new_marker(self):
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        captures = self._capture_emits(page)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        # 触发 showEvent(_unread_since_view 初始为 False,需要 view 一次)
        page.showEvent(None)
        self.app.processEvents()
        # 模拟窗口隐藏(默认情况,因为我们没 show()) -> set isVisible False 后 emit
        # 但测试环境下 page 实际是 visible 的,所以 _append_line 不会 emit。
        # 改用 hide() 后再写行。
        page.hide()
        self.app.processEvents()
        with open(log, "a", encoding="utf-8") as f:
            f.write("[INFO] hello\n")
        _process_events_for(0.5)
        # 应该看到 "__new__" sentinel
        self.assertIn("__new__", captures,
                      f"expected __new__ marker, got {captures!r}")
        # 不应该有 INFO/WARNING/ERROR 之类级别字符串
        for marker in captures:
            self.assertNotIn(marker, ("INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL"),
                             f"unexpected level marker leaked: {marker!r}")

    def test_show_event_emits_viewed_marker(self):
        page = LogViewerPage(theme_manager=self.tm)
        captures = self._capture_emits(page)
        page.showEvent(None)
        self.app.processEvents()
        self.assertEqual(captures, ["__viewed__"])

    def test_notify_off_emits_cleared_marker(self):
        page = LogViewerPage(theme_manager=self.tm)
        captures = self._capture_emits(page)
        # 默认开启 notify -> 关掉 -> emit __cleared__
        self.assertTrue(page.notify_checkbox.isChecked())
        page.notify_checkbox.setChecked(False)
        self.app.processEvents()
        self.assertIn("__cleared__", captures)

    def test_notify_off_suppresses_further_emits(self):
        """关掉 notify 后,新行不再 emit(信号通路完全静默)。"""
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        captures = self._capture_emits(page)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        page.showEvent(None)
        page.notify_checkbox.setChecked(False)
        self.app.processEvents()
        # 清空来自 __cleared__ 的 capture,只看后续新行
        captures.clear()
        page.hide()
        self.app.processEvents()
        with open(log, "a", encoding="utf-8") as f:
            f.write("[WARN] should not emit\n")
            f.write("[ERROR] also should not emit\n")
        _process_events_for(0.5)
        self.assertEqual(captures, [],
                         f"expected no emits after notify off, got {captures!r}")

    def test_no_level_parsing_in_signal(self):
        """原始数据里包含 [ERROR] 时,信号也是 __new__,不带 ERROR 级别。
        这是新语义的关键:不解析 level,只关心"有没有新"。"""
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        captures = self._capture_emits(page)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        page.showEvent(None)
        page.hide()
        self.app.processEvents()
        with open(log, "a", encoding="utf-8") as f:
            f.write("[ERROR] oh no\n")
            f.write("[CRITICAL] really bad\n")
            f.write("plain line\n")
        _process_events_for(0.8)
        # 三行都该 emit __new__(旧实现会在第一条 emit ERROR)
        self.assertEqual(captures.count("__new__"), 3,
                         f"expected 3 __new__ emits, got {captures!r}")
        self.assertNotIn("ERROR", captures)
        self.assertNotIn("CRITICAL", captures)


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



class TestVirtualTerminalOverwrite(_Fixture):
    """照搬 ComfyUI 前端 console 的语义:\\r 覆盖当前行,\\n 才换行。

    用户原话:"为什么我们不照抄一下 ComfyUI 前端的逻辑呢 页面上的 console 里
    运行的很好啊"。ComfyUI web console 用 xterm.js(VT100 终端):\\r 直接覆盖
    当前行,只有 \\n 才把行 finalize 然后开新行。我们用 VirtualTerminal 复刻这套语义。

    关键差异(对比旧 prefix/progress 双缓冲实现):
    - 旧实现试图"保留节点状态行 prefix",导致 #163 [...] 被错误粘连进度条(bug 根因)。
    - 新实现纯覆盖:进度帧覆盖当前行,节点状态行如果同处一行会被覆盖 —— 这正是
      xterm 的真实行为,也是用户期望的"和前端一致"。
    """

    def test_cr_segments_overwrite_the_same_line(self):
        """连续 \\r 段只保留最后一个(tqdm 多帧刷新场景)。

        文件内容:tqdm 把 3 个百分比帧压成一条物理行 \\r 分隔,末尾 \\n。
        期望:视图里只看到最新进度(39%),前面的 0%/12% 被 \\r 覆盖。
        """
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        bar = chr(0x2588)
        raw = (
            b"  0%|          | 0/8 [00:00<?, ?it/s]"
            b"\r 12%|" + bar.encode("utf-8") + b"| 1/8 [00:03<00:26, 3.77s/it]"
            b"\r 39%|" + (bar * 4).encode("utf-8") + b"| 4/8 [00:09<00:15, 2.50s/it]\n"
        )
        with open(log, "ab", buffering=0) as f:
            f.write(raw)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            text = page.text_edit.toPlainText()
            if "39%" in text:
                self.assertNotIn("0/8", text)
                self.assertNotIn("12%", text)
                return
            time.sleep(0.02)
        self.fail("39% never appeared: " + repr(page.text_edit.toPlainText()))

    def test_node_id_line_then_progress_overwrites_node_line(self):
        """节点状态行("#335 [...]")后跟 \\r + tqdm 进度帧时,进度帧覆盖节点状态行。

        这是纯覆盖语义(VT100/xterm 行为):\\r 回行首,后续字符整行重写。
        旧实现试图保留节点行作为 prefix,反而引入了 #163 粘连进度条的 bug。
        新实现贴前端:进度覆盖节点行,只显示最终进度帧。
        """
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        # 一条物理行:节点状态行 + \r + tqdm 帧 + \n
        with open(log, "ab", buffering=0) as f:
            f.write(b'#335 [PrimitiveFloat]: 0.00s - vram 0b')
            f.write(b"\r 37%|" + (chr(0x2588) * 4).encode("utf-8") + b"| 30/81 [00:04<00:07,  6.57it/s]")
            f.write(b"\n")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            text = page.text_edit.toPlainText()
            if "37%" in text:
                # 进度帧覆盖了节点状态行(纯覆盖,贴前端 xterm 行为)
                self.assertIn("37%", text)
                self.assertIn("30/81", text)
                # 节点状态行被覆盖,不应残留
                self.assertNotIn("#335 [PrimitiveFloat]", text)
                return
            time.sleep(0.02)
        self.fail("never appeared: " + repr(page.text_edit.toPlainText()))

    def test_node_status_on_own_line_not_overwritten(self):
        """节点状态行如果自己一行(末尾 \\n),不被后续进度条覆盖 —— 这才是真实场景。

        用户报告的 bug 根因:节点行 `#163 [...]` 是被 \\n 正常 finalize 的(独立行),
        旧实现的 prefix 启发式却错误地把它当成下一段进度的 prefix,导致粘连。
        新 VT100 模型下,\\n 终结的行不会被后续覆盖。
        """
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        with open(log, "ab", buffering=0) as f:
            f.write(b'#163 [UnetLoaderGGUF]: 0.05s - vram 0b\n')   # 独立行,正常 finalize
            f.write(b"[INFO] loaded completely\n")                   # 独立行
            f.write(b"\r  0%|          | 0/6\r")                     # tqdm 开始(覆盖 active_line)
            f.write(b"100%|" + (chr(0x2588) * 10).encode("utf-8") + b"| 6/6 [00:10<00:00, 1.83s/it]\n")
            f.write(b"#146 [KSampler]: 17.46s - vram 9169015770b\n")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            text = page.text_edit.toPlainText()
            if "#146 [KSampler]" in text:
                # 节点状态行独立保留(不被进度条粘连) —— 这是 bug 修复的核心断言
                self.assertIn("#163 [UnetLoaderGGUF]: 0.05s - vram 0b", text)
                self.assertIn("[INFO] loaded completely", text)
                # 进度条只留最终帧,在独立行
                self.assertIn("100%|", text)
                self.assertNotIn("0/6", text)
                # KSampler 行独立
                self.assertIn("#146 [KSampler]", text)
                # 关键:节点行和进度条不在同一行(用换行分隔)
                idx_node = text.index("#163 [UnetLoaderGGUF]")
                idx_progress = text.index("100%|")
                # 节点行完整一行(后面紧跟换行,不是直接接进度条)
                node_line_end = text.index("\n", idx_node)
                self.assertLess(idx_node, node_line_end)
                self.assertLess(node_line_end, idx_progress)
                return
            time.sleep(0.02)
        self.fail("never appeared: " + repr(page.text_edit.toPlainText()))

    def test_normal_line_after_progress_finalizes_the_progress_line(self):
        """\\r 覆盖活动行后,下一条普通行(\\n 终结)把活动行固化,然后开新行。"""
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        with open(log, "ab", buffering=0) as f:
            f.write(b"Loading: 40%\r")
            f.write(b"\n")
            f.write(b"next normal line\n")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            text = page.text_edit.toPlainText()
            if "next normal line" in text:
                self.assertIn("Loading: 40%", text)
                self.assertLess(text.index("Loading: 40%"), text.index("next normal line"))
                return
            time.sleep(0.02)
        self.fail("next normal line never appeared: " + repr(page.text_edit.toPlainText()))

    def test_last_cr_segment_not_duplicated(self):
        """tqdm 整段进度末尾的最终 frame 只出现一次(不被重复 emit)。

        回归:旧 LogTailer 把最后一段 \\r 段当普通行再次 emit,导致重复。
        新实现按 \\r/\\n 边界 emit,VT 解释覆盖,内容只出现一次。
        """
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        with open(log, "ab", buffering=0) as f:
            f.write(b" 39%|" + (b"\xe2\x96\x88" * 10) + b"| 8/8 [00:06<00:00, 1.21it/s]\r\n")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            text = page.text_edit.toPlainText()
            if "39%" in text:
                self.assertEqual(text.count("8/8"), 1)
                self.assertEqual(text.count("1.21it/s"), 1)
                return
            time.sleep(0.02)
        self.fail("never appeared: " + repr(page.text_edit.toPlainText()))

    def test_loading_then_done_overwrites_to_done(self):
        """Loading: 40%\\r done\\n 场景:done 覆盖 Loading: 40%(纯覆盖,贴前端)。

        旧实现的 %| 启发式试图"不覆盖进度",新实现纯覆盖:done 整行重写。
        这与 ComfyUI 前端 xterm 行为一致。
        """
        d = self._tmpdir()
        log = d / "test.log"
        log.write_text("", encoding="utf-8")
        page = LogViewerPage(theme_manager=self.tm)
        page.set_log_path(log)
        page.start_tailing(start_from_beginning=True)
        self.addCleanup(page.stop_tailing)
        with open(log, "ab", buffering=0) as f:
            for pct in ("10", "20", "30", "40"):
                f.write(f"Loading: {pct}%\r".encode())
            f.write(b"done\n")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            text = page.text_edit.toPlainText()
            if "done" in text:
                # done 覆盖了所有 Loading 帧(纯覆盖)
                self.assertIn("done", text)
                self.assertNotIn("Loading: 40%", text)
                self.assertNotIn("Loading: 10%", text)
                return
            time.sleep(0.02)
        self.fail("missing: " + repr(page.text_edit.toPlainText()))

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

    def test_live_progress_replaces_active_line(self):
        """进度帧(\\r 边界)实时覆盖 active_line:只留最新帧。"""
        page = LogViewerPage(theme_manager=self.tm)
        page._on_line_main("  5%|#| 1/20 [00:02<00:38]\r")  # \r 边界,active_line
        page._flush_batch()
        page._on_line_main(" 15%|###| 3/20 [00:07<00:37]\r")
        page._flush_batch()
        text = page.text_edit.toPlainText()
        self.assertNotIn("1/20", text)
        self.assertIn("3/20", text)
        self.assertEqual(text.count("3/20"), 1)

    def test_progress_burst_renders_only_latest_value(self):
        """连续多帧进度 burst:VT 覆盖后只留最终帧。"""
        page = LogViewerPage(theme_manager=self.tm)
        for step in range(1, 6):
            page._on_line_main(f" {step * 5}%|#| {step}/20\r")
        page._flush_batch()
        text = page.text_edit.toPlainText()
        self.assertIn("5/20", text)
        self.assertNotIn("1/20", text)
        self.assertEqual(text.count("/20"), 1)

    def test_normal_line_finalizes_active_progress(self):
        """进度帧 \\n 终结后固化成独立行,后续普通行另起一行。

        真实字节流:进度帧以 \\n 结束(如 100%|...|\\n),下一条普通行
        (Prompt executed\\n)是全新一行,不覆盖进度。
        """
        page = LogViewerPage(theme_manager=self.tm)
        page._on_line_main(" 15%|###| 3/20 [00:07<00:37]\r")  # active_line
        page._on_line_main("100%|#####| 3/20 [00:07<00:37]\n")  # \n 终结,固化进度
        page._flush_batch()
        page._on_line_main("Prompt executed\n")  # 全新一行
        page._flush_batch()
        text = page.text_edit.toPlainText()
        self.assertIn("3/20", text)
        self.assertIn("Prompt executed", text)
        self.assertLess(text.index("3/20"), text.index("Prompt executed"))

    def test_finalize_during_active_progress_no_glue(self):
        """回归:进度条 active 时,普通行 finalize,再继续进度,最后 \\n 结束 ——
        普通行不能和进度条粘连(用户报告的 #104 [...]b100%|... bug)。

        根因:_flush_batch 删活动行块时用了 BlockUnderCursor,连带删了块分隔符,
        导致后续 insertText 把新内容拼到前一行末尾(换行丢失)。
        修法:用 StartOfBlock + EndOfBlock(KeepAnchor) 只删块内文本,保留分隔符。
        """
        page = LogViewerPage(theme_manager=self.tm)
        # 进度条先 active
        page._on_line_main(" 50%|#####     | 3/6\r")
        page._flush_batch()
        # #104 行 finalize(进度条还在 active)
        page._on_line_main("#104 [VAEDecode]: 0.29s - vram 2302995876b\n")
        page._flush_batch()
        # 进度条继续刷新
        page._on_line_main("100%|##########| 6/6\r")
        page._flush_batch()
        # 进度条结束
        page._on_line_main("\n")
        page._flush_batch()
        text = page.text_edit.toPlainText()
        # #104 行必须独立成行,不能直接接进度条
        self.assertNotIn("#104 [VAEDecode]: 0.29s - vram 2302995876b100%|", text,
                         "#104 行和进度条粘连: " + repr(text))
        self.assertNotIn("2302995876b100%", text,
                         "进度条粘在 #104 行末尾: " + repr(text))
        # 进度条最终帧在独立行
        self.assertIn("100%|##########| 6/6", text)
        # 整体结构:#104\n + 100%...\n
        self.assertEqual(
            text,
            "#104 [VAEDecode]: 0.29s - vram 2302995876b\n100%|##########| 6/6\n",
            "结构不符: " + repr(text),
        )


if __name__ == "__main__":
    unittest.main()