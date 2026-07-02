"""ProgressCollapseFilter 单元测试：折叠 ComfyUI 日志中连续的 \r 进度行。"""
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


class TestCarriageReturnCollapse(unittest.TestCase):
    def test_single_cr_line_emits_marker(self):
        f = ProgressCollapseFilter()
        # 单个 \r 行被推迟到下一行 emit
        self.assertEqual(f.feed("Loading: 50%\r"), [])
        # 下一个普通行触发 emit
        out = f.feed("done")
        self.assertEqual(len(out), 2)
        self.assertIn("1 lines collapsed", out[0])
        self.assertIn("Loading: 50%", out[0])
        self.assertEqual(out[1], "done")

    def test_consecutive_cr_lines_collapse_to_one_marker(self):
        f = ProgressCollapseFilter()
        for s in ["Loading: 10%\r", "Loading: 20%\r", "Loading: 30%\r", "Loading: 40%\r"]:
            self.assertEqual(f.feed(s), [])
        out = f.feed("finished")
        self.assertEqual(len(out), 2)
        self.assertIn("4 lines collapsed", out[0])
        self.assertIn("Loading: 40%", out[0])
        self.assertEqual(out[1], "finished")

    def test_cr_line_in_middle_of_normal_text_is_still_cr_line(self):
        f = ProgressCollapseFilter()
        self.assertEqual(f.feed("partial\rpartial"), [])
        out = f.feed("next")
        self.assertIn("1 lines collapsed", out[0])

    def test_collapse_only_emits_once(self):
        f = ProgressCollapseFilter()
        f.feed("a\r")
        f.feed("b\r")
        out = f.feed("c")
        self.assertEqual(len(out), 2)
        self.assertEqual(f.feed("d"), ["d"])
        self.assertEqual(f.feed("e"), ["e"])

    def test_consecutive_normal_lines_no_marker(self):
        f = ProgressCollapseFilter()
        self.assertEqual(f.feed("x"), ["x"])
        self.assertEqual(f.feed("y"), ["y"])
        self.assertEqual(f.feed("z"), ["z"])

    def test_cr_lines_followed_by_eof(self):
        f = ProgressCollapseFilter()
        f.feed("a\r")
        f.feed("b\r")
        out = f.flush()
        self.assertEqual(len(out), 1)
        self.assertIn("2 lines collapsed", out[0])


class TestMarkerFormat(unittest.TestCase):
    def test_marker_prefix_uses_ellipsis(self):
        f = ProgressCollapseFilter()
        f.feed("x\r")
        out = f.feed("y")
        self.assertTrue(out[0].startswith("... "))

    def test_marker_includes_original_text(self):
        f = ProgressCollapseFilter()
        f.feed("Loading: 75% 5.0GB/s\r")
        out = f.feed("done")
        self.assertIn("Loading: 75% 5.0GB/s", out[0])


if __name__ == "__main__":
    unittest.main()