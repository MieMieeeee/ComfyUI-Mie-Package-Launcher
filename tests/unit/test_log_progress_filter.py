"""ProgressCollapseFilter 单元测试:折叠 / 实时刷出 ComfyUI 日志中连续的 \r 进度行。

新版语义(实时刷出):
- 每个新值 -> emit 一条 "[progress #N] <seg>"(N=累计刷新次数)
- 同值重复 / 距上次 emit 太近(< _LIVE_INTERVAL 秒) -> 静默累计,不刷屏
- 普通行到达 -> 先吐 "... N updates: <last>" 总结,再吐本行,并清状态
- flush() -> 有累积就吐总结
**"""
import time
import unittest

from ui_qt.log_viewer import ProgressCollapseFilter


class TestNoCollapse(unittest.TestCase):
    def test_normal_lines_pass_through(self):
        f = ProgressCollapseFilter()
        self.assertEqual(f.feed("hello"), ["hello"])
        self.assertEqual(f.feed("world"), ["world"])

    def test_empty_line_passes_through(self):
        f = ProgressCollapseFilter()
        self.assertEqual(f.feed(""), [""])

    def test_unicode_line_passes_through(self):
        f = ProgressCollapseFilter()
        self.assertEqual(f.feed("[INFO] 中文日志"), ["[INFO] 中文日志"])


class TestLiveEmit(unittest.TestCase):
    """实时刷出:tqdm 跨步刷新的可见性。

    这是修复的"主目标"——任务运行期间用户能看到进度在动,而不是黑屏
    一直等到任务结束。
    """

    def test_first_new_value_emits_live_update(self):
        f = ProgressCollapseFilter()
        out = f.feed("Loading: 50%\r")
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("[progress"),
                        f"expected live emit, got {out[0]!r}")
        self.assertIn("Loading: 50%", out[0])

    def test_same_value_does_not_emit_again(self):
        """tqdm 重绘同一帧(常见:同一百分比在两次 update 间重画)不应刷屏。"""
        f = ProgressCollapseFilter()
        first = f.feed("Loading: 30%\r")
        self.assertEqual(len(first), 1)
        # 同值再喂一次 -> 不 emit
        second = f.feed("Loading: 30%\r")
        self.assertEqual(second, [])

    def test_burst_segments_emit_only_first_within_rate_limit(self):
        """tqdm 一次写盘把整段多帧压成一条物理行,LogTailer 切 \r 段后
        可能在毫秒级内连续 emit 几十条。速率限让 burst 情况只露第一帧,
        其余静默累计到 summary(避免 UI 闪屏)。"""
        f = ProgressCollapseFilter()
        all_emits = []
        # 10 帧不同值,毫秒级连续 feed,模拟 LogTailer 切段后 burst
        for i in range(10):
            line = f"  {i*10}%|...| {i}/10\r"
            all_emits.extend(f.feed(line))
        # 只有第一帧 emit 出来,其余都被速率限挡掉
        self.assertEqual(len(all_emits), 1)
        self.assertIn("0%", all_emits[0])

    def test_consecutive_cr_lines_each_emit_live_when_spaced(self):
        """间隔 >= _LIVE_INTERVAL 秒的不同值,逐帧 emit。
        模拟 tqdm 真实跨步刷新节奏(每步 0.5s+)。"""
        f = ProgressCollapseFilter()
        all_emits = []
        for s in ["Loading: 10%\r", "Loading: 20%\r", "Loading: 30%\r", "Loading: 40%\r"]:
            all_emits.extend(f.feed(s))
            time.sleep(0.4)  # > _LIVE_INTERVAL (0.3s)
        self.assertEqual(len(all_emits), 4)
        for i, expected in enumerate(["10%", "20%", "30%", "40%"]):
            self.assertIn(expected, all_emits[i],
                          f"emit[{i}] missing {expected!r}: {all_emits[i]!r}")


class TestNormalLineBehavior(unittest.TestCase):
    """普通行到达 / flush 时的收尾行为。"""

    def test_normal_line_after_progress_emits_summary_then_line(self):
        f = ProgressCollapseFilter()
        # 累积若干进度(同值短间隔,只露第一帧)
        f.feed("Loading: 10%\r")
        f.feed("Loading: 20%\r")  # burst,被速率限掉
        f.feed("Loading: 30%\r")
        # 普通行到达:先 summary,再本行
        out = f.feed("done")
        self.assertEqual(len(out), 2)
        self.assertIn("updates", out[0])
        self.assertIn("Loading: 30%", out[0])
        self.assertEqual(out[1], "done")

    def test_normal_line_resets_live_state(self):
        """普通行 emit summary 后清状态,下次进度从 0 开始重新累计。"""
        f = ProgressCollapseFilter()
        f.feed("Loading: 50%\r")
        f.feed("done")  # 清状态
        # 新一轮进度应该能 emit(因为 _last_live_segment 已清空)
        out = f.feed("Loading: 50%\r")
        self.assertEqual(len(out), 1)
        self.assertIn("Loading: 50%", out[0])

    def test_normal_line_without_pending_progress_passes_through(self):
        f = ProgressCollapseFilter()
        self.assertEqual(f.feed("hello"), ["hello"])

    def test_consecutive_normal_lines_no_marker(self):
        f = ProgressCollapseFilter()
        self.assertEqual(f.feed("x"), ["x"])
        self.assertEqual(f.feed("y"), ["y"])
        self.assertEqual(f.feed("z"), ["z"])


class TestFlush(unittest.TestCase):
    def test_flush_emits_summary_when_pending(self):
        f = ProgressCollapseFilter()
        f.feed("a\r")
        f.feed("b\r")
        out = f.flush()
        self.assertEqual(len(out), 1)
        self.assertIn("updates", out[0])
        self.assertIn("b", out[0])

    def test_flush_no_pending_returns_empty(self):
        f = ProgressCollapseFilter()
        self.assertEqual(f.flush(), [])
        # flush 后再 flush 仍然空
        f.feed("x")
        f.flush()
        self.assertEqual(f.flush(), [])

    def test_flush_resets_state(self):
        """flush 后状态应清空,下一次进度能重新 emit。"""
        f = ProgressCollapseFilter()
        f.feed("a\r")
        f.flush()
        out = f.feed("a\r")
        # 之前 "a" 已经 live emit 过,flush 后清空,现在能再 emit
        self.assertEqual(len(out), 1)


class TestMarkerFormat(unittest.TestCase):
    def test_live_marker_prefix(self):
        f = ProgressCollapseFilter()
        out = f.feed("Loading: 75% 5.0GB/s\r")
        self.assertTrue(out[0].startswith("[progress"),
                        f"expected [progress] prefix, got {out[0]!r}")
        self.assertIn("Loading: 75% 5.0GB/s", out[0])

    def test_summary_includes_count_and_last_text(self):
        f = ProgressCollapseFilter()
        f.feed("a\r")
        f.feed("b\r")
        out = f.flush()
        self.assertEqual(len(out), 1)
        self.assertIn("2", out[0])
        self.assertIn("b", out[0])

    def test_long_segment_kept_as_plain_text_not_repr(self):
        """tqdm bar 含 unicode 块字符,不能被 repr() 包成乱码。"""
        f = ProgressCollapseFilter()
        bar = "\u2588" * 50
        line = f"  100%|{bar}| 8/8 [00:06<00:00,  1.21it/s]\r"
        out = f.feed(line)
        # live emit 时直接拼原文,不 repr
        self.assertEqual(len(out), 1)
        self.assertIn(bar, out[0])
        self.assertNotIn(chr(39), out[0])  # 没有 repr 的单引号


class TestMultiSegmentLine(unittest.TestCase):
    """整段进度压成一条物理行(单行多 \r 形态)。

    真实 ComfyUI / tqdm 在重定向文件里,一个采样步骤的所有 \r 刷新
    会压成一条物理行,以 \n 收尾。LogTailer 已经按 \r 切段成多条线,
    但 Filter 直接被单测调用时仍可能被喂这种"含多 \r"的单行。
    """

    def test_single_line_multiple_cr_emits_only_last_segment_in_live(self):
        """单行多 \r:count = \r 个数,但 live emit 只含最后一段文本,
        不能把整条超长串塞进 marker(原 bug:emit 2KB 乱码)。"""
        f = ProgressCollapseFilter()
        segments = [f"tracking: {i}%|{'\u2588'*(i//10)}| {i}/81" for i in range(0, 82)]
        progress_line = "\r".join(segments)
        # 单行多 \r 在 burst 中被速率限,只 emit 一条
        out = f.feed(progress_line)
        self.assertEqual(len(out), 1)
        marker = out[0]
        # 只保留最后一段(81/81),不含前面任何百分比
        self.assertIn("81/81", marker)
        self.assertNotIn("0/81", marker)
        self.assertNotIn("40/81", marker)
        # 关键:标记行不能是 2KB 超长串(原 bug 的 repr 把整条都塞进去了)
        self.assertLess(len(marker), 200)

    def test_single_line_multiple_cr_summary_has_correct_count(self):
        """单行 81 个 \r -> 累计 81 次刷新。"""
        f = ProgressCollapseFilter()
        segments = [f"x{i}|{i}/81" for i in range(82)]
        progress_line = "\r".join(segments)
        f.feed(progress_line)
        out = f.flush()
        self.assertEqual(len(out), 1)
        # 81 个 \r -> 累计 81 次
        self.assertIn("81", out[0])
        self.assertIn("81/81", out[0])


class TestTrailingCR(unittest.TestCase):
    def test_single_line_trailing_cr_does_not_emit_empty_last(self):
        """'a\\rb\\r' 末尾空段应忽略,回到上一个非空段 'b'。"""
        f = ProgressCollapseFilter()
        out = f.feed("a\rb\r")
        # 第一帧 live emit 'b'
        self.assertEqual(len(out), 1)
        self.assertIn("b", out[0])
        # 不应把空串当 last
        self.assertNotIn("collapsed: ", out[0])
