"""VirtualTerminal 单元测试:极简 VT100 行模型 (\\r 覆盖 / \\n 换行)。

纯 Python 类,无 Qt 依赖。复刻 ComfyUI 前端 xterm.js 的核心语义:
- \\n → finalize 当前行,开新行
- \\r → 光标回行首,后续字符覆盖写(纯覆盖,贴前端 xterm 行为)
- \\r\\n (Windows 换行) → \\r 标记覆盖,\\n finalize,语义正确

这是日志页"和 ComfyUI 前端 console 一致"的核心: tqdm 进度帧被 \\r
覆盖成最终帧,节点状态行不再被错误粘连(修复用户报告的 bug)。
"""
import unittest

from ui_qt.log_viewer import VirtualTerminal


class TestVirtualTerminalBasics(unittest.TestCase):
    """基本 \\r / \\n 语义。"""

    def test_plain_text_accumulates_in_active_line(self):
        vt = VirtualTerminal()
        self.assertEqual(vt.feed("hello"), [])
        self.assertEqual(vt.active_line, "hello")

    def test_newline_finalizes_current_line(self):
        vt = VirtualTerminal()
        self.assertEqual(vt.feed("hello\n"), ["hello"])
        self.assertEqual(vt.active_line, "")

    def test_multiple_newlines_emit_multiple_lines(self):
        vt = VirtualTerminal()
        self.assertEqual(vt.feed("a\nb\nc\n"), ["a", "b", "c"])
        self.assertEqual(vt.active_line, "")

    def test_partial_then_complete(self):
        vt = VirtualTerminal()
        self.assertEqual(vt.feed("partial"), [])
        self.assertEqual(vt.feed("-rest\n"), ["partial-rest"])
        self.assertEqual(vt.active_line, "")


class TestVirtualTerminalCarriageReturn(unittest.TestCase):
    """\\r 覆盖语义(tqdm 进度条核心)。"""

    def test_cr_then_text_overwrites_active_line(self):
        """\\r 后的文本整行覆盖当前行(纯覆盖)。"""
        vt = VirtualTerminal()
        vt.feed("first line")
        self.assertEqual(vt.feed("\rsecond"), [])
        self.assertEqual(vt.active_line, "second")

    def test_consecutive_cr_frames_keep_last(self):
        """tqdm 多帧 \\r 分隔:只留最后一帧(中间帧被覆盖)。"""
        vt = VirtualTerminal()
        vt.feed("  0%|          | 0/8\r")
        vt.feed(" 12%|#| 1/8\r")
        vt.feed(" 39%|####| 4/8\r")
        self.assertEqual(vt.active_line, " 39%|####| 4/8")

    def test_tqdm_burst_then_newline_finalizes_last_frame(self):
        """tqdm 多帧 + 末尾 \\n:finalized 含最终帧,中间帧丢弃。"""
        vt = VirtualTerminal()
        finalized = vt.feed("  0%\r 12%\r 39%\r100%\n")
        self.assertEqual(finalized, ["100%"])
        self.assertEqual(vt.active_line, "")

    def test_cr_does_not_finalize(self):
        """\\r 不产生 finalized 行(只覆盖 active_line);只有 \\n 才 finalize。"""
        vt = VirtualTerminal()
        vt.feed("progress: 50%\r")
        vt.feed("progress: 100%\r")
        self.assertEqual(vt.active_line, "progress: 100%")
        # 没有 \n,所以没有 finalized 行
        # (feed 返回的是这段期间 finalize 的行)
        result = vt.feed("progress: 100%\r")
        self.assertEqual(result, [])

    def test_pure_overwrite_no_trailing_pad(self):
        """纯覆盖:短帧覆盖长帧不留尾部残影(贴前端 xterm,不做空格 pad)。

        注意:tqdm 帧单调变长,实测不残留。但纯覆盖语义下,如果短帧后跟,
        active_line 就是短帧(不补空格)。
        """
        vt = VirtualTerminal()
        vt.feed("longer frame here\r")
        vt.feed("short\r")
        self.assertEqual(vt.active_line, "short")  # 不含 "er frame here" 残影


class TestVirtualTerminalCRLF(unittest.TestCase):
    """\\r\\n (Windows 换行) 序列处理。"""

    def test_crlf_finalizes_line(self):
        """Windows 风格 \\r\\n: \\r 标记覆盖, \\n finalize,内容正确。"""
        vt = VirtualTerminal()
        self.assertEqual(vt.feed("line\r\n"), ["line"])
        self.assertEqual(vt.active_line, "")

    def test_multiple_crlf_lines(self):
        vt = VirtualTerminal()
        self.assertEqual(vt.feed("a\r\nb\r\nc\r\n"), ["a", "b", "c"])

    def test_crlf_does_not_corrupt_content(self):
        """\\r\\n 序列里 \\r 不清空内容: \\n 紧跟其后 finalize 完整行。

        关键: \\r 设 carriage_returned=True, 但 \\n 不走"覆盖写"分支,
        直接 finalize 当前 _current (还没被清空), 所以内容不丢。
        """
        vt = VirtualTerminal()
        finalized = vt.feed("[INFO] some message\r\n")
        self.assertEqual(finalized, ["[INFO] some message"])

    def test_cr_then_crlf_after_progress(self):
        """tqdm 进度帧 (\\r) 后跟 \\r\\n 终结:覆盖 + 换行,最终帧固化。"""
        vt = VirtualTerminal()
        vt.feed("0%\r17%\r50%\r")
        # 现在 active_line = "50%", carriage_returned=True
        finalized = vt.feed("100%\r\n")
        # "100%" 触发覆盖 (carriage_returned), active="100%"
        # 然后 \r 又设 carriage_returned, \n finalize "100%"
        self.assertEqual(finalized, ["100%"])


class TestVirtualTerminalReset(unittest.TestCase):
    """reset() 清空状态。"""

    def test_reset_clears_active_line(self):
        vt = VirtualTerminal()
        vt.feed("some content")
        self.assertNotEqual(vt.active_line, "")
        vt.reset()
        self.assertEqual(vt.active_line, "")

    def test_reset_clears_carriage_returned_flag(self):
        """reset 后,后续字符不被当覆盖(正常 append)。"""
        vt = VirtualTerminal()
        vt.feed("old\r")  # carriage_returned=True
        vt.reset()
        vt.feed("new")
        self.assertEqual(vt.active_line, "new")  # 不是覆盖空行后 append


class TestVirtualTerminalStreaming(unittest.TestCase):
    """流式 feed:多次 feed 累积状态,模拟实时 tail。"""

    def test_streamed_segments_maintain_state(self):
        """分多次 feed(模拟 LogTailer 分块 emit),状态跨 feed 保持。"""
        vt = VirtualTerminal()
        all_finalized = []
        for seg in ["hello ", "world\r", "HELLO ", "WORLD\n", "next\n"]:
            all_finalized.extend(vt.feed(seg))
        # "hello world" 被覆盖成 "HELLO WORLD", 然后 finalize; 再 "next" finalize
        self.assertEqual(all_finalized, ["HELLO WORLD", "next"])

    def test_empty_feed_is_noop(self):
        vt = VirtualTerminal()
        vt.feed("content")
        self.assertEqual(vt.feed(""), [])
        self.assertEqual(vt.active_line, "content")

    def test_empty_newline_emits_empty_line(self):
        """\\n 在空 active_line 上 → finalize 空字符串(合法空行)。"""
        vt = VirtualTerminal()
        self.assertEqual(vt.feed("\n"), [""])
        self.assertEqual(vt.active_line, "")


class TestVirtualTerminalComfyUIScenario(unittest.TestCase):
    """复刻用户报告的真实 ComfyUI 日志场景(端到端语义验证)。"""

    def test_node_status_then_progress_no_glue(self):
        """用户报告的 bug 核心场景: 节点状态行独立一行, 不被后续进度条粘连。

        真实字节流: 节点行以 \\n 终结(独立行), 进度条是后续独立的 \\r/\\n 序列。
        VT100 模型下, \\n 终结的行不会被后续覆盖。
        """
        vt = VirtualTerminal()
        # 模拟 LogTailer 按边界 emit 的段
        segs = [
            "#163 [UnetLoaderGGUF]: 0.05s - vram 0b\n",   # 节点行,独立
            "[INFO] loaded completely\n",                  # 普通行
            "  0%|          | 0/6\r",                       # tqdm 开始
            " 17%|##       | 1/6\r",
            " 50%|#####    | 3/6\r",
            "100%|##########| 6/6 [00:10<00:00, 1.83s/it]\n",  # 最终帧 + \n
            "#146 [KSampler]: 17.46s - vram 9169015770b\n",
        ]
        finalized = []
        for seg in segs:
            finalized.extend(vt.feed(seg))
        # 期望: 节点行 + INFO + 进度最终帧 + KSampler, 各自独立行
        self.assertEqual(finalized, [
            "#163 [UnetLoaderGGUF]: 0.05s - vram 0b",
            "[INFO] loaded completely",
            "100%|##########| 6/6 [00:10<00:00, 1.83s/it]",
            "#146 [KSampler]: 17.46s - vram 9169015770b",
        ])
        # 节点行和进度条不在同一行 (finalized 里是分开的)
        self.assertNotIn("#163 [UnetLoaderGGUF]: 0.05s - vram 0b100%", finalized[0])

    def test_tqdm_burst_only_final_frame(self):
        """tqdm 多帧 burst (一次写盘多帧): 只留最终帧。"""
        vt = VirtualTerminal()
        # 一条物理行里多个 \r 分隔的进度帧 + 末尾 \n
        seg = "  0%|     | 0/6\r 17%|##   | 1/6\r 50%|#####| 3/6\r100%|##########| 6/6\n"
        finalized = vt.feed(seg)
        self.assertEqual(finalized, ["100%|##########| 6/6"])


if __name__ == "__main__":
    unittest.main()
