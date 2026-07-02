"""LogTailer 单元测试:后台线程 tail 文件,新行通过回调 emit。"""
import threading
import time
import unittest
from pathlib import Path

from ui_qt.log_viewer import LogTailer


def _wait_for(predicate, timeout=2.0, interval=0.02):
    """轮询等 predicate 为 True,带超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class TestLogTailerEmits(unittest.TestCase):
    def test_emits_existing_lines_when_start_from_beginning(self):
        with self._tmpfile("a\nb\nc\n") as path:
            received = []
            ev = threading.Event()
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                self.assertTrue(_wait_for(lambda: len(received) >= 3), "should emit 3 lines")
                self.assertEqual(received, ["a", "b", "c"])
            finally:
                tailer.stop()

    def test_emits_only_new_lines_when_start_from_end(self):
        with self._tmpfile("a\nb\n") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=False)
            tailer.start()
            try:
                # 等线程进入稳定状态
                time.sleep(0.1)
                # 此时不应该 emit 任何东西(只跳过已存在的)
                self.assertEqual(received, [])
                # 追加新行
                with open(path, "a", encoding="utf-8") as f:
                    f.write("d\ne\n")
                self.assertTrue(_wait_for(lambda: received == ["d", "e"]),
                                "should emit new lines only")
            finally:
                tailer.stop()

    def test_emits_lines_appended_in_chunks(self):
        with self._tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("line1\nline2\nline3\n")
                self.assertTrue(_wait_for(lambda: received == ["line1", "line2", "line3"]),
                                "should emit all three lines in order")
            finally:
                tailer.stop()

    def test_partial_line_buffered_until_newline(self):
        with self._tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("partial")
                # 等一会,确认 partial 不被 emit
                time.sleep(0.15)
                self.assertEqual(received, [])
                # 完成这一行
                with open(path, "a", encoding="utf-8") as f:
                    f.write("-rest\n")
                self.assertTrue(_wait_for(lambda: received == ["partial-rest"]),
                                "partial line should be buffered until newline")
            finally:
                tailer.stop()

    def test_unicode_lines_emit_unchanged(self):
        with self._tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("[INFO] 中文日志\n[INFO] emoji 🎉\n")
                self.assertTrue(_wait_for(lambda: len(received) == 2))
                self.assertEqual(received[0], "[INFO] 中文日志")
                self.assertEqual(received[1], "[INFO] emoji 🎉")
            finally:
                tailer.stop()


class TestLogTailerLifecycle(unittest.TestCase):
    def test_stop_terminates_thread(self):
        with self._tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            self.assertTrue(tailer.is_alive())
            tailer.stop()
            self.assertTrue(_wait_for(lambda: not tailer.is_alive(), timeout=1.0),
                            "thread should terminate after stop()")

    def test_double_stop_is_safe(self):
        with self._tmpfile("") as path:
            tailer = LogTailer(path, on_line=lambda l: None, start_from_beginning=True)
            tailer.start()
            tailer.stop()
            tailer.stop()  # 第二次 stop 不应抛
            self.assertFalse(tailer.is_alive())

    def test_callback_runs_on_daemon_thread(self):
        with self._tmpfile("") as path:
            main_thread_ident = threading.get_ident()
            callback_thread_ident = [None]
            ev = threading.Event()

            def cb(line):
                callback_thread_ident[0] = threading.get_ident()
                ev.set()

            tailer = LogTailer(path, on_line=cb, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("hello\n")
                ev.wait(timeout=2.0)
                self.assertIsNotNone(callback_thread_ident[0])
                self.assertNotEqual(callback_thread_ident[0], main_thread_ident,
                                    "callback should not run on main thread")
            finally:
                tailer.stop()


class TestLogTailerResilience(unittest.TestCase):
    def test_waits_for_file_to_appear(self):
        # 文件暂不存在,LogTailer 应当等待(不抛),文件出现后正常 emit
        tmpdir = Path(self._tmpdir())
        path = tmpdir / "later.log"
        received = []
        tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
        tailer.start()
        try:
            # 文件尚未创建,稍等后创建
            time.sleep(0.1)
            self.assertEqual(received, [])
            with open(path, "a", encoding="utf-8") as f:
                f.write("created\n")
            self.assertTrue(_wait_for(lambda: received == ["created"], timeout=3.0),
                            "should emit line after file appears")
        finally:
            tailer.stop()

    def test_recovers_from_truncation(self):
        with self._tmpfile("first\n") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                self.assertTrue(_wait_for(lambda: received == ["first"]))
                # 模拟日志轮转: 截断并重写
                with open(path, "w", encoding="utf-8") as f:
                    f.write("rotated\n")
                self.assertTrue(_wait_for(lambda: received == ["first", "rotated"], timeout=3.0),
                                "should detect truncation and re-read")
            finally:
                tailer.stop()

    # ----- 临时文件辅助 -----

    def _tmpdir(self):
        import tempfile
        return tempfile.mkdtemp()

    def _tmpfile(self, content):
        """返回上下文管理器,exit 时清理临时文件。"""
        import tempfile
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            tmpdir = Path(tempfile.mkdtemp())
            p = tmpdir / "test.log"
            p.write_text(content, encoding="utf-8")
            try:
                yield p
            finally:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)

        return _ctx()


if __name__ == "__main__":
    unittest.main()