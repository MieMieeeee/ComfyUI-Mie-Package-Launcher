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
        with _tmpfile("a\nb\nc\n") as path:
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
        with _tmpfile("a\nb\n") as path:
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
        with _tmpfile("") as path:
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
        with _tmpfile("") as path:
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
        with _tmpfile("") as path:
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
        with _tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            self.assertTrue(tailer.is_alive())
            tailer.stop()
            self.assertTrue(_wait_for(lambda: not tailer.is_alive(), timeout=1.0),
                            "thread should terminate after stop()")

    def test_double_stop_is_safe(self):
        with _tmpfile("") as path:
            tailer = LogTailer(path, on_line=lambda l: None, start_from_beginning=True)
            tailer.start()
            tailer.stop()
            tailer.stop()  # 第二次 stop 不应抛
            self.assertFalse(tailer.is_alive())

    def test_callback_runs_on_daemon_thread(self):
        with _tmpfile("") as path:
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
        tmpdir = Path(_tmpdir())
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
        """truncate 重写更短的内容(size 变小)→ position 超出新 size → 触发重 open"""
        with _tmpfile("first line here\n") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                self.assertTrue(_wait_for(lambda: received == ["first line here"]))
                # 模拟日志被 truncate 后重写更短的内容
                with open(path, "w", encoding="utf-8") as f:
                    f.write("rotated\n")
                self.assertTrue(_wait_for(lambda: received == ["first line here", "rotated"], timeout=3.0),
                                "should detect truncation and re-read")
            finally:
                tailer.stop()

    def test_recovers_from_rename_recreate(self):
        """轮转(重命名 + 新建同名文件,ComfyUI-Manager 的方式)→ inode 变化 → 触发重 open。

        关键:tailer 持有读 fd 时,用共享模式打开(允许 rename/delete),
        这样 ComfyUI-Manager 才能 rename 旧文件。否则 Windows 上 rename 会
        PermissionError [WinError 32]。
        """
        import os as _os
        tmpdir = Path(_tmpdir())
        path = tmpdir / "test.log"
        path.write_text("old\n", encoding="utf-8")
        received = []
        tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
        tailer.start()
        try:
            self.assertTrue(_wait_for(lambda: received == ["old"]))
            # 模拟 ComfyUI-Manager 轮转: rename 旧文件 + 新建同名文件
            # tailer 仍持有旧 fd,但用共享模式打开,所以 rename 能成功
            prev = tmpdir / "test.prev.log"
            _os.rename(path, prev)
            with open(path, "w", encoding="utf-8") as f:
                f.write("new after rotate\n")
            self.assertTrue(_wait_for(lambda: received == ["old", "new after rotate"], timeout=3.0),
                            "should detect rename+recreate and re-read new file")
        finally:
            tailer.stop()

    # ----- 临时文件辅助 -----

def _tmpdir():
    import tempfile
    return tempfile.mkdtemp()


def _tmpfile(content):
    """返回上下文管理器,exit 时清理临时文件。"""
    import tempfile
    import shutil
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        tmpdir = Path(tempfile.mkdtemp())
        p = tmpdir / "test.log"
        p.write_text(content, encoding="utf-8")
        try:
            yield p
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return _ctx()


class TestLogTailerCarriageReturnSplitting(unittest.TestCase):
    """LogTailer \r 分段:tqdm 重定向到文件时整段进度压在一条物理行里,
    必须按 \r 切段成多行才能让 ProgressCollapseFilter 实时刷出。
    """

    def test_single_line_with_multiple_cr_emits_each_segment(self):
        """一条物理行里有 3 段 \r 分隔的内容 -> emit 3 条带 \r 的行。"""
        # 用 str 写盘,_tmpfile 接受 str;转义后的 \r 物理写入就是真 \r
        raw = "\r  0%|          | 0/8 [00:00<?, ?it/s]\r 12%|█| 1/8 [00:03<00:26, 3.77s/it]\r100%|" + "█" * 10 + "| 8/8 [00:06<00:00, 1.21it/s]\r\n"
        with _tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(raw)
                self.assertTrue(_wait_for(lambda: len(received) == 3, timeout=3.0),
                                f"should emit 3 \r-separated segments, got {received!r}")
                # 每段都保留 \r 标记,给 Filter 识别
                for line in received:
                    self.assertTrue(line.endswith("\r"),
                                    f"segment missing \r marker: {line!r}")
                # 内容分别对应 0%、12%、100%
                self.assertIn("0%", received[0])
                self.assertIn("12%", received[1])
                self.assertIn("100%", received[2])
                self.assertIn("8/8", received[2])
            finally:
                tailer.stop()

    def test_empty_segments_between_cr_are_skipped(self):
        """连续 \r 之间的空段(tqdm 写新值前先 \r 把光标归位)直接丢弃。"""
        raw = "\r\r\r  only_one  \r\r\n"
        with _tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(raw)
                self.assertTrue(_wait_for(lambda: len(received) >= 1, timeout=2.0))
                # 只有 1 段非空内容,不应有 7 段(3 leading + 中间 1 + 3 trailing)
                non_empty = [r for r in received if r.strip(" \r")]
                self.assertEqual(len(non_empty), 1, f"got segments: {received!r}")
                self.assertIn("only_one", non_empty[0])
            finally:
                tailer.stop()

    def test_normal_line_without_cr_passes_through_unchanged(self):
        """不含 \r 的普通行透传,不加 \r 后缀(Filter 不当进度处理)。"""
        with _tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("[INFO] normal line\n")
                self.assertTrue(_wait_for(lambda: received == ["[INFO] normal line"], timeout=2.0))
                self.assertEqual(received[0], "[INFO] normal line")
                self.assertFalse(received[0].endswith("\r"))
            finally:
                tailer.stop()


if __name__ == "__main__":
    unittest.main()