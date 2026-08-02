"""LogTailer 单元测试:后台线程 tail 文件,新行通过回调 emit。

LogTailer 现在按 \r 或 \n 任一边界 emit"段",保留边界字符。消费方
(VirtualTerminal) 按边界字符解释覆盖(\r)/换行(\n)语义。

注意:Windows 上 write_text 默认把 \n 转成 \r\n,所以测试断言用 VirtualTerminal
做最终语义验证(而不是绑定具体切法),保证跨平台稳健。
"""
import threading
import time
import unittest
from pathlib import Path

from ui_qt.log_viewer import LogTailer, VirtualTerminal


def _wait_for(predicate, timeout=2.0, interval=0.02):
    """轮询等 predicate 为 True,带超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _feed_all_to_vt(segments):
    """把 LogTailer emit 的段全部喂给 VirtualTerminal,返回 (finalized 行, active_line)。"""
    vt = VirtualTerminal()
    finalized = []
    for seg in segments:
        finalized.extend(vt.feed(seg))
    return finalized, vt.active_line


class TestLogTailerEmits(unittest.TestCase):
    def test_emits_existing_lines_when_start_from_beginning(self):
        with _tmpfile("a\nb\nc\n") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                self.assertTrue(_wait_for(lambda: len(received) >= 3), "should emit segments")
                # 喂给 VirtualTerminal 后应得到 3 行 (跨 \r\n / \n 切法都成立)
                finalized, active = _feed_all_to_vt(received)
                self.assertEqual(finalized, ["a", "b", "c"])
                self.assertEqual(active, "")
            finally:
                tailer.stop()

    def test_emits_only_new_lines_when_start_from_end(self):
        with _tmpfile("a\nb\n") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=False)
            tailer.start()
            try:
                time.sleep(0.1)
                self.assertEqual(received, [])
                with open(path, "a", encoding="utf-8") as f:
                    f.write("d\ne\n")
                self.assertTrue(_wait_for(lambda: len(received) >= 2),
                                "should emit new lines only")
                finalized, _ = _feed_all_to_vt(received)
                self.assertEqual(finalized, ["d", "e"])
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
                self.assertTrue(_wait_for(lambda: len(received) >= 3))
                finalized, _ = _feed_all_to_vt(received)
                self.assertEqual(finalized, ["line1", "line2", "line3"])
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
                time.sleep(0.15)
                self.assertEqual(received, [])
                with open(path, "a", encoding="utf-8") as f:
                    f.write("-rest\n")
                self.assertTrue(_wait_for(lambda: received))
                finalized, _ = _feed_all_to_vt(received)
                self.assertEqual(finalized, ["partial-rest"])
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
                self.assertTrue(_wait_for(lambda: len(received) >= 2))
                finalized, _ = _feed_all_to_vt(received)
                self.assertEqual(finalized, ["[INFO] 中文日志", "[INFO] emoji 🎉"])
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
            time.sleep(0.1)
            self.assertEqual(received, [])
            with open(path, "a", encoding="utf-8") as f:
                f.write("created\n")
            self.assertTrue(_wait_for(lambda: received, timeout=3.0),
                            "should emit segment after file appears")
            finalized, _ = _feed_all_to_vt(received)
            self.assertEqual(finalized, ["created"])
        finally:
            tailer.stop()

    def test_recovers_from_truncation(self):
        """truncate 重写更短的内容(size 变小)→ position 超出新 size → 触发重 open"""
        with _tmpfile("first line here\n") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                self.assertTrue(_wait_for(lambda: received))
                # snapshot 当前的 received,避免后续 truncate 内容混入这次断言
                finalized_before, _ = _feed_all_to_vt(list(received))
                self.assertEqual(finalized_before, ["first line here"])
                with open(path, "w", encoding="utf-8") as f:
                    f.write("rotated\n")
                # 等 received 增长(truncate 后重读新内容)
                self.assertTrue(_wait_for(lambda: len(_feed_all_to_vt(received)[0]) >= 2, timeout=3.0),
                                "should detect truncation and re-read")
                finalized, _ = _feed_all_to_vt(received)
                self.assertEqual(finalized, ["first line here", "rotated"])
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
            self.assertTrue(_wait_for(lambda: received))
            finalized_before, _ = _feed_all_to_vt(list(received))
            self.assertEqual(finalized_before, ["old"])
            prev = tmpdir / "test.prev.log"
            _os.rename(path, prev)
            with open(path, "w", encoding="utf-8") as f:
                f.write("new after rotate\n")
            self.assertTrue(_wait_for(lambda: len(_feed_all_to_vt(received)[0]) >= 2, timeout=3.0),
                            "should detect rename+recreate and re-read new file")
            finalized, _ = _feed_all_to_vt(received)
            self.assertEqual(finalized, ["old", "new after rotate"])
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


class TestLogTailerBoundarySplitting(unittest.TestCase):
    """LogTailer 按 \\r 或 \\n 任一边界 emit"段"(保留边界字符)。

    这是给 VirtualTerminal 用的:消费方按边界字符解释覆盖(\\r)/换行(\\n)语义。
    tqdm 重定向到文件时,进度帧之间用 \\r 分隔,只有最后一个帧之后才 \\n;
    LogTailer 现在按 \\r 也切(不只按 \\n),所以 tqdm 跑几分钟时每个 \\r 帧
    到达就 emit,VirtualTerminal 把它覆盖成最新帧作 active_line,用户实时看到进度。

    断言用 VirtualTerminal 做最终语义验证(跨平台、跨具体切法都成立)。
    """

    def test_tqdm_multi_frame_progress_emits_incrementally(self):
        """tqdm 多帧进度(\\r 分隔,末尾 \\n)实时 emit;最终只留最后一帧。"""
        raw = (
            "\r  0%|          | 0/8 [00:00<?, ?it/s]"
            "\r 12%|█| 1/8 [00:03<00:26, 3.77s/it]"
            "\r100%|" + "█" * 10 + "| 8/8 [00:06<00:00, 1.21it/s]\r\n"
        )
        with _tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(raw)
                # 至少 emit 多个段(每个 \r / \n 边界都 emit),证明实时性
                self.assertTrue(_wait_for(lambda: len(received) >= 3, timeout=3.0),
                                f"should emit multiple segments for tqdm frames, got {received!r}")
                # 喂给 VT:最终 finalized 应只含 100% 帧(中间 0%/12% 被 \r 覆盖)
                finalized, active = _feed_all_to_vt(received)
                self.assertEqual(finalized, ["100%|" + "█" * 10 + "| 8/8 [00:06<00:00, 1.21it/s]"])
                self.assertEqual(active, "")
            finally:
                tailer.stop()

    def test_cr_terminated_progress_emits_before_newline(self):
        """tqdm 只写回车刷新(没换行)时也实时 emit,VirtualTerminal 据此更新 active_line。"""
        with _tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "ab", buffering=0) as f:
                    f.write(b" 15%|###| 3/20 [00:07<00:37, 2.20s/it]\r")
                self.assertTrue(
                    _wait_for(lambda: received, timeout=1.0),
                    f"progress segment should emit before newline, got {received!r}",
                )
                # 喂给 VT:没有 \n,所以不 finalize,active_line 是该进度帧
                finalized, active = _feed_all_to_vt(received)
                self.assertEqual(finalized, [])
                self.assertIn("3/20", active)
            finally:
                tailer.stop()

    def test_consecutive_cr_emits_incrementally(self):
        """连续 \\r(tqdm 写新值前先 \\r 归位)每个都 emit;VT 覆盖后只留最终内容。

        不再像旧实现那样"丢弃空段"——边界字符都 emit,VT 自己处理覆盖语义
        (纯 \\r 段覆盖成空 active_line,不产生噪音)。
        """
        with _tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("\r\r\ronly_one\r\r\n")
                self.assertTrue(_wait_for(lambda: received, timeout=2.0))
                # 喂给 VT:最终只 finalize 一行 "only_one",active 为空
                finalized, active = _feed_all_to_vt(received)
                self.assertEqual(finalized, ["only_one"])
                self.assertEqual(active, "")
            finally:
                tailer.stop()

    def test_normal_line_passes_through(self):
        """不含 \\r 的普通行经 VT 解释后正常 finalize 成一行。"""
        with _tmpfile("") as path:
            received = []
            tailer = LogTailer(path, on_line=received.append, start_from_beginning=True)
            tailer.start()
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("[INFO] normal line\n")
                self.assertTrue(_wait_for(lambda: received, timeout=2.0))
                finalized, _ = _feed_all_to_vt(received)
                self.assertEqual(finalized, ["[INFO] normal line"])
            finally:
                tailer.stop()


if __name__ == "__main__":
    unittest.main()