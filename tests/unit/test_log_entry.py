"""LogEntry 解析:从一行日志里抽出 [时间戳] 和正文。"""
import unittest

from ui_qt.log_viewer import parse_log_entry


class TestParseLogEntry(unittest.TestCase):
    def test_standard_log_line(self):
        ts, body = parse_log_entry("2026-07-02 14:09:43,123 [INFO] Starting server")
        self.assertEqual(ts, "2026-07-02 14:09:43,123")
        self.assertEqual(body, "[INFO] Starting server")

    def test_iso_timestamp_with_milliseconds(self):
        ts, body = parse_log_entry("[2026-07-02 14:09:43.456] hello world")
        self.assertEqual(ts, "2026-07-02 14:09:43.456")
        self.assertEqual(body, "hello world")

    def test_line_without_timestamp_returns_empty_ts(self):
        ts, body = parse_log_entry("plain line without timestamp")
        self.assertEqual(ts, "")
        self.assertEqual(body, "plain line without timestamp")

    def test_empty_line(self):
        ts, body = parse_log_entry("")
        self.assertEqual(ts, "")
        self.assertEqual(body, "")

    def test_partial_timestamp_does_not_match(self):
        # 日期格式不对,应该当作普通行
        ts, body = parse_log_entry("2026-7-2 14:09 [INFO] bad date")
        self.assertEqual(ts, "")
        self.assertEqual(body, "2026-7-2 14:09 [INFO] bad date")

    def test_chinese_body_preserved(self):
        ts, body = parse_log_entry("2026-07-02 14:09:43,000 [INFO] 中文日志 emoji")
        self.assertEqual(ts, "2026-07-02 14:09:43,000")
        self.assertEqual(body, "[INFO] 中文日志 emoji")

    def test_unix_timestamp_does_not_match(self):
        ts, body = parse_log_entry("1234567890 some text")
        self.assertEqual(ts, "")
        self.assertEqual(body, "1234567890 some text")


    def test_timestamp_without_milliseconds(self):
        # 部分日志不带毫秒(子进程 stdout 重定向、stdout 简单 print 等)
        ts, body = parse_log_entry("2026-07-02 14:09:43 [INFO] no millis")
        self.assertEqual(ts, "2026-07-02 14:09:43")
        self.assertEqual(body, "[INFO] no millis")

    def test_timestamp_without_milliseconds_bracketed(self):
        ts, body = parse_log_entry("[2026-07-02 14:09:43] also no millis")
        self.assertEqual(ts, "2026-07-02 14:09:43")
        self.assertEqual(body, "also no millis")

if __name__ == "__main__":
    unittest.main()