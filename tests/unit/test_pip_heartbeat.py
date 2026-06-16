"""Tests for the pip streaming heartbeat / stall detector.

pip 在解析依赖 / 排队下载阶段可能 5~30s 都不打任何 stdout/stderr，
不打任何东西 UI 就一直卡在"开始安装…"。心跳线程负责在这种情况
下每 5s 推一条"已等待 Ns"覆盖 UI。
"""
import os
import subprocess
import sys
import threading
import re
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _StallStream:
    """第一次 read 阻塞 stall_seconds（模拟 pip 卡在解析/下载），
    之后返回 final_data，再之后 EOF。"""

    def __init__(self, stall_seconds: float, final_data: bytes = b""):
        self._stall = stall_seconds
        self._final = final_data
        self._read_count = 0
        self._final_pos = 0

    def read(self, n=-1):
        self._read_count += 1
        if self._read_count == 1:
            time.sleep(self._stall)
            if self._final:
                # 一次返回所有 final_data
                return self._final
            return b""
        if self._read_count == 2:
            if self._final_pos < len(self._final):
                end = min(self._final_pos + (n if n and n > 0 else 512),
                          len(self._final))
                out = self._final[self._final_pos:end]
                self._final_pos = end
                return out
            return b""
        return b""


class _ChunkedSlowStream:
    """每次 read 慢一点，但持续返回数据（模拟 pip 在慢速但稳定地打行）。
    delay 是每次 read 的 sleep 秒数。"""

    def __init__(self, data: bytes, delay: float = 0.3):
        self._buf = data
        self._pos = 0
        self._delay = delay

    def read(self, n=-1):
        if self._pos >= len(self._buf):
            return b""
        time.sleep(self._delay)
        end = min(self._pos + (n if n and n > 0 else 512), len(self._buf))
        out = self._buf[self._pos:end]
        self._pos = end
        return out


def _make_proc(stdout, stderr=b"", returncode=0):
    fake = MagicMock()
    fake.stdout = stdout
    fake.stderr = stderr or _StallStream(0.0, b"")
    fake.returncode = returncode
    fake.wait = lambda: returncode
    return fake


class TestHeartbeatFiresOnStall(unittest.TestCase):
    """心跳线程在 pip 静默超过阈值时推消息覆盖 UI。"""

    def test_heartbeat_fires_after_5s_with_no_lines(self):
        """stdout 第一次 read 阻塞 7s，期间不应该有任何真实行 → 心跳必须打。"""
        from utils.pip import _run_pip_streaming

        events = []
        on_progress = lambda text, percent=None: events.append(text)
        # 7s stall, no final data → launcher 第一次 read 阻塞 7s 后返回 b""
        # 之后 loop 立即 break。这 7s 里心跳必须至少打 1 次。
        fake = _make_proc(_StallStream(stall_seconds=7.0))

        t0 = time.monotonic()
        with patch("subprocess.Popen", return_value=fake):
            _run_pip_streaming(["python", "-m", "pip"], logger=None,
                                on_progress=on_progress)
        elapsed = time.monotonic() - t0

        heartbeats = [e for e in events if "已等待" in e]
        self.assertTrue(
            heartbeats,
            f"no heartbeat in {elapsed:.1f}s, events={events!r}",
        )
        # 心跳消息里必须有秒数（5s 或 10s 之类的）
        self.assertTrue(any("5s" in e or "10s" in e for e in heartbeats),
                        f"heartbeat missing seconds: {heartbeats!r}")

    def test_heartbeat_updates_with_elapsed_seconds(self):
        """心跳消息里的秒数应该会随时间增长。"""
        from utils.pip import _run_pip_streaming

        events = []
        on_progress = lambda text, percent=None: events.append(text)
        # 12s stall → 至少 2 次心跳（5s、10s）
        fake = _make_proc(_StallStream(stall_seconds=12.0))

        with patch("subprocess.Popen", return_value=fake):
            _run_pip_streaming(["python", "-m", "pip"], logger=None,
                                on_progress=on_progress)

        heartbeats = [e for e in events if "已等待" in e]
        # 抽秒数：中文逗号是与 "5s" 连在一起的，
        # 用正则拼出所有 "<数字>s" 。
        seconds_seen = []
        for h in heartbeats:
            for m in re.finditer(r"(\d+)s", h):
                seconds_seen.append(int(m.group(1)))
        # 至少要看到 1 个不同的秒数（说明心跳在跑）
        self.assertTrue(seconds_seen,
                        f"no parsed seconds: {heartbeats!r}")
        # 至少 1 个 >= 5s 的数
        self.assertTrue(any(s >= 5 for s in seconds_seen),
                        f"no >= 5s in {seconds_seen!r}")


class TestHeartbeatDoesNotDisturbActive(unittest.TestCase):
    """pip 持续在打真实行 → 心跳必须闭嘴，不污染 pip 的状态显示。"""

    def test_heartbeat_silent_during_streaming_progress(self):
        """每 ~0.3s 一行 progress bar（10s 总长）→ 心跳不能跳出来。"""
        from utils.pip import _run_pip_streaming

        events = []
        on_progress = lambda text, percent=None: events.append(text)
        # 50 行 progress bar，每行大约 14 字节，0.3s/次 read
        # launcher 一次 read 拿 512 字节，约 36 行，0.3s sleep
        # 50 行总耗时 ~0.6s，远不到 5s
        many = b"".join(f"  {i}.0/100.0 MB\n".encode() for i in range(1, 51))
        stdout = b"Collecting foo==1.0\n" + many
        fake = _make_proc(_ChunkedSlowStream(stdout, delay=0.3))

        with patch("subprocess.Popen", return_value=fake):
            _run_pip_streaming(["python", "-m", "pip"], logger=None,
                                on_progress=on_progress)

        heartbeats = [e for e in events if "已等待" in e]
        self.assertFalse(heartbeats,
                          f"heartbeat fired while pip active: {heartbeats!r}")
        # pip 的 progress bar 应该有出现
        bar = [e for e in events if "MB" in e and "/" in e]
        self.assertGreater(len(bar), 10, f"too few bars: {len(bar)}")

    def test_heartbeat_resumes_after_silence_following_activity(self):
        """先打几行 progress bar → 静默 7s → 心跳必须重新出现。"""
        from utils.pip import _run_pip_streaming

        events = []
        on_progress = lambda text, percent=None: events.append(text)
        # 第一次 read 立刻返回 2 行 progress bar（不 stall）
        # 第二次 read 阻塞 7s（模拟 stall）
        # 第三次 read 返回 b""（EOF）
        # 用 _StallStream 不行，因为它只在第一次 stall；需要一个能混着用的 stream
        head = b"Collecting foo==1.0\n  1.0/10.0 MB\n  2.0/10.0 MB\n"
        stream = _MixedStallStream(initial_data=head, stall_seconds=7.0)
        fake = _make_proc(stream)

        with patch("subprocess.Popen", return_value=fake):
            _run_pip_streaming(["python", "-m", "pip"], logger=None,
                                on_progress=on_progress)

        # 应该有 progress bar（来自 head）
        bar = [e for e in events if "MB" in e and "/" in e]
        self.assertTrue(bar, f"no bar events: {events!r}")
        # 也应该有 heartbeat（来自 7s 的 stall）
        heartbeats = [e for e in events if "已等待" in e]
        self.assertTrue(heartbeats, f"no heartbeat after silence: {events!r}")


class _MixedStallStream:
    """第一次 read 立即返回 initial_data，第二次 read 阻塞 stall_seconds，第三次返回 b""。"""

    def __init__(self, initial_data: bytes, stall_seconds: float):
        self._initial = initial_data
        self._stall = stall_seconds
        self._n = 0

    def read(self, n=-1):
        self._n += 1
        if self._n == 1:
            return self._initial
        if self._n == 2:
            time.sleep(self._stall)
            return b""
        return b""


class TestHeartbeatStopsAfterFinish(unittest.TestCase):
    """心跳必须在 pip 退出后立即停，不留尾巴。"""

    def test_heartbeat_does_not_fire_after_finish(self):
        from utils.pip import _run_pip_streaming

        events = []
        on_progress = lambda text, percent=None: events.append(text)
        # 立即完成：0s stall + no data
        fake = _make_proc(_StallStream(stall_seconds=0.0))

        with patch("subprocess.Popen", return_value=fake):
            _run_pip_streaming(["python", "-m", "pip"], logger=None,
                                on_progress=on_progress)

        # 等 1.5s 确认心跳已经停
        before = len(events)
        time.sleep(1.5)
        after = len(events)
        self.assertEqual(after, before,
                          f"heartbeat kept firing after finish: "
                          f"delta={after - before}")


if __name__ == "__main__":
    unittest.main()
