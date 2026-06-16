"""Tests for _run_pip_streaming stderr/stdout handling.

These tests cover two related concerns:

1. **Stderr installation status reaches the UI.**
   pip emits key install-phase messages (Installing collected packages,
   Uninstalling, Installing, Successfully installed, Running setup.py
   install for) to stderr. The parser must pick them up so the progress
   dialog does not look "stuck" on a stale Downloading line.

2. **Concurrent stdout + stderr reads are safe.**
   stdout is read in the main thread, stderr in a daemon thread. They
   both mutate the shared "current package" state. We verify the result
   still ends up in on_progress without races.
"""
import io
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _FakeStream:
    """Minimal file-like wrapper over bytes that releases a flag when
    fully read so the launcher\'s stream reader can detect EOF."""

    def __init__(self, data: bytes, chunk_size: int = 512):
        self._buf = data
        self._pos = 0
        self._chunk = chunk_size
        self.eof = False

    def read(self, n=-1):
        if n is None or n < 0:
            n = self._chunk
        if self._pos >= len(self._buf):
            self.eof = True
            return b""
        end = min(self._pos + n, len(self._buf))
        out = self._buf[self._pos:end]
        self._pos = end
        if self._pos >= len(self._buf):
            self.eof = True
        return out


def _make_proc(stdout_bytes: bytes, stderr_bytes: bytes, returncode: int = 0):
    """Build a fake subprocess.Popen-like object whose stdout/stderr
    can be preloaded with arbitrary bytes. .wait() is mocked to return
    the given returncode."""

    fake = MagicMock()
    fake.stdout = _FakeStream(stdout_bytes)
    fake.stderr = _FakeStream(stderr_bytes)
    fake.returncode = returncode

    def _wait():
        return returncode

    fake.wait = _wait
    return fake


def _run_with_fake_streams(stdout_bytes: bytes, stderr_bytes: bytes,
                           returncode: int = 0):
    """Invoke _run_pip_streaming with a fake Popen and return the
    (events, result) tuple captured by an on_progress callback."""
    from utils.pip import _run_pip_streaming

    events = []
    on_progress = lambda text, percent=None: events.append(text)

    fake_proc = _make_proc(stdout_bytes, stderr_bytes, returncode=returncode)

    with patch("subprocess.Popen", return_value=fake_proc):
        result = _run_pip_streaming(["python", "-m", "pip", "install", "x"],
                                     logger=None, on_progress=on_progress)
    return events, result


class TestParsePipStdout(unittest.TestCase):
    """Sanity: existing stdout behavior still works after the refactor."""

    def test_downloading_line_emits_status(self):
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"Downloading comfyui_foo-1.0-py3-none-any.whl (10.5 MB)\n",
            stderr_bytes=b"",
        )
        joined = "\n".join(events)
        self.assertIn("正在下载 comfyui_foo", joined)
        self.assertIn("10.5 MB", joined)

    def test_collecting_line_sets_pkg(self):
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"Collecting comfyui-foo==1.0\nDownloading comfyui_foo-1.0-py3-none-any.whl (1.0 MB)\n",
            stderr_bytes=b"",
        )
        # Collecting triggers "正在收集依赖: comfyui-foo"
        self.assertTrue(any("收集依赖" in e for e in events),
                        f"missing collecting event: {events!r}")
        # The following Downloading line should reuse the same pkg
        downloading = [e for e in events if "正在下载" in e]
        self.assertTrue(downloading, f"no download event: {events!r}")
        self.assertIn("comfyui-foo", downloading[-1])

    def test_progress_bar_line_emits_cur_tot(self):
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"Collecting foo==1.0\n  10.0/100.0 MB  5.0 MB/s\n",
            stderr_bytes=b"",
        )
        bar = [e for e in events if "10.0" in e and "100.0" in e and "MB" in e]
        self.assertTrue(bar, f"no progress bar event: {events!r}")


class TestParsePipStderr(unittest.TestCase):
    """The whole point of the refactor: install-phase stderr reaches UI."""

    def test_installing_collected_packages(self):
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"",
            stderr_bytes=b"Installing collected packages: foo, bar\n",
        )
        self.assertTrue(
            any("安装依赖包" in e and "foo, bar" in e
                for e in events),
            f"missing installing-collected event: {events!r}",
        )

    def test_attempting_uninstall(self):
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"",
            stderr_bytes=b"Attempting uninstall: comfyui-foo\n",
        )
        self.assertTrue(
            any("清理旧版" in e and "comfyui-foo" in e
                for e in events),
            f"missing uninstall event: {events!r}",
        )

    def test_uninstalling_line(self):
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"",
            stderr_bytes=b"Uninstalling comfyui-foo-1.2.3:\n",
        )
        self.assertTrue(
            any("卸载" in e and "comfyui-foo" in e for e in events),
            f"missing uninstalling event: {events!r}",
        )

    def test_installing_line(self):
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"",
            stderr_bytes=b"Installing comfyui-foo-1.2.3\n",
        )
        self.assertTrue(
            any("正在安装" in e and "comfyui-foo" in e
                for e in events),
            f"missing installing event: {events!r}",
        )

    def test_successfully_installed(self):
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"",
            stderr_bytes=b"Successfully installed comfyui-foo-1.2.3\n",
        )
        self.assertTrue(
            any("已安装" in e and "comfyui-foo-1.2.3" in e
                for e in events),
            f"missing success event: {events!r}",
        )

    def test_successfully_uninstalled(self):
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"",
            stderr_bytes=b"Successfully uninstalled comfyui-foo-1.2.3\n",
        )
        self.assertTrue(
            any("已卸载" in e and "comfyui-foo-1.2.3" in e
                for e in events),
            f"missing uninstall success event: {events!r}",
        )

    def test_running_setup_py_install_for(self):
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"",
            stderr_bytes=b"Running setup.py install for legacy-pkg: started\n",
        )
        self.assertTrue(
            any("编译" in e and "legacy-pkg" in e for e in events),
            f"missing compile event: {events!r}",
        )

    def test_found_existing_installation_sets_pkg(self):
        # When this stderr line appears before any stdout Collecting line,
        # it should still set pkg so subsequent progress bars get a name.
        events, _ = _run_with_fake_streams(
            stdout_bytes=b"  5.0/20.0 MB\n",
            stderr_bytes=b"Found existing installation: bar-1.0\n",
        )
        bar = [e for e in events if "5.0" in e and "20.0" in e]
        self.assertTrue(bar, f"no bar event after Found existing: {events!r}")
        self.assertTrue(any("bar" in e for e in bar),
                        f"bar event missing pkg: {bar!r}")


class TestStderrBytesPreserved(unittest.TestCase):
    """CompletedProcess.stderr must keep its raw content for downstream
    parsing (e.g. _parse_missing_packages)."""

    def test_stderr_preserved_verbatim(self):
        raw = (
            b"Looking in indexes: https://pypi.org/simple\n"
            b"WARNING: foo is deprecated\n"
            b"Successfully installed bar-1.0\n"
        )
        _, result = _run_with_fake_streams(b"", raw)
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertIn("WARNING: foo is deprecated", result.stderr)
        self.assertIn("Successfully installed bar-1.0", result.stderr)

    def test_stdout_preserved_verbatim(self):
        raw = b"Collecting x==1.0\nDownloading x-1.0.whl (1.0 MB)\n"
        _, result = _run_with_fake_streams(raw, b"")
        self.assertIn("Collecting x==1.0", result.stdout)
        self.assertIn("Downloading x-1.0.whl", result.stdout)

    def test_returncode_propagated(self):
        _, result = _run_with_fake_streams(b"", b"", returncode=42)
        self.assertEqual(result.returncode, 42)


class TestConcurrentStdoutStderr(unittest.TestCase):
    """stdout (main thread) and stderr (daemon thread) both call
    on_progress and mutate pkg_state. Both must work concurrently
    without crashing or losing events."""

    def test_interleaved_stdout_and_stderr(self):
        # Interleave the two streams on purpose: each line should still
        # produce a UI event, and the final list of events should be
        # non-empty and contain messages from both phases.
        stdout = (
            b"Collecting foo==1.0\n"
            b"Downloading foo-1.0.whl (10.0 MB)\n"
            b"  5.0/10.0 MB\n"
        )
        stderr = (
            b"Attempting uninstall: foo\n"
            b"Uninstalling foo-1.0:\n"
            b"Successfully uninstalled foo-1.0\n"
            b"Running setup.py install for foo: started\n"
            b"Successfully installed foo-1.0\n"
        )
        events, _ = _run_with_fake_streams(stdout, stderr)
        joined = "\n".join(events)
        # stdout phases
        self.assertIn("收集依赖", joined)
        self.assertIn("正在下载 foo", joined)
        # stderr phases
        self.assertIn("清理旧版", joined)
        self.assertIn("已卸载", joined)
        self.assertIn("编译", joined)
        self.assertIn("已安装", joined)

    def test_no_race_when_pkg_changes_mid_progress(self):
        # stderr installs a new pkg while stdout is mid-progress-bar.
        # The bar line should pick up the latest pkg.
        stdout = (
            b"Collecting first==1.0\n"
            b"Downloading first-1.0.whl (5.0 MB)\n"
            b"  1.0/5.0 MB\n"
            b"  2.0/5.0 MB\n"
            b"  3.0/5.0 MB\n"
        )
        stderr = (
            b"Found existing installation: second\n"
            b"Attempting uninstall: second\n"
        )
        events, _ = _run_with_fake_streams(stdout, stderr)
        # Some progress bar event should reflect the swap to "second"
        bar = [e for e in events if "first" in e or "second" in e]
        # At least the Attempting uninstall should set pkg to "second"
        self.assertTrue(any("second" in e for e in bar),
                        f"no event references second pkg: {events!r}")


class TestParserRobustness(unittest.TestCase):
    """A broken/garbage line must not crash the parser."""

    def test_unparseable_line_does_not_crash(self):
        # Random binary-looking bytes
        garbage = bytes(range(256)) + b"\n"
        # Should not raise
        events, _ = _run_with_fake_streams(garbage, garbage)
        # No event needs to be emitted for garbage; just verify it ran
        self.assertIsInstance(events, list)

    def test_empty_streams(self):
        events, result = _run_with_fake_streams(b"", b"")
        self.assertEqual(events, [])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_partial_line_at_eof_still_parsed(self):
        # No trailing newline; parser should still emit the event.
        events, _ = _run_with_fake_streams(
            b"Collecting foo==1.0",
            b"",
        )
        self.assertTrue(any("收集依赖" in e for e in events),
                        f"missing event: {events!r}")


if __name__ == "__main__":
    unittest.main()
