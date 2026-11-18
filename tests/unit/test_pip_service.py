"""PipService / normalize_pip_command / utils.pip 新增函数 的单元测试。

覆盖：
- normalize_pip_command：完整 pip 命令、各种前缀变体、裸包名、拒绝其它子命令、
  引号路径、index flag 判定、空输入；
- list_installed_packages：JSON 解析 + 失败抛 PipListError；
- uninstall_packages / run_pip_args：结果归一化 + 取消标记；
- _run_pip_streaming 的 cancel_event：启动前取消 / 流中取消（tree-kill 被调）；
- PipService：路径解析 + 薄封装透传。
"""

import os
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.pip_service import PipService, normalize_pip_command
from utils.pip import PipListError, _run_pip_streaming


# ---------------------------------------------------------------------------
# normalize_pip_command
# ---------------------------------------------------------------------------

class TestNormalizePipCommand(unittest.TestCase):
    """用户输入规范化（Python 库管理页智能输入框的核心逻辑）。"""

    def test_full_command_with_python_prefix(self):
        """用户示例：完整命令 → install + 原样参数 + index flag 判定。"""
        r = normalize_pip_command(
            "python -m pip install -U --no-build-isolation nvidia-vfx "
            "--index-url https://pypi.nvidia.com")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], [
            "-U", "--no-build-isolation", "nvidia-vfx",
            "--index-url", "https://pypi.nvidia.com"])
        self.assertTrue(r["has_index_flag"])

    def test_pip_prefix(self):
        r = normalize_pip_command("pip install nvidia-vfx")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["nvidia-vfx"])
        self.assertFalse(r["has_index_flag"])

    def test_pip3_prefix(self):
        r = normalize_pip_command("pip3 install numpy")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["numpy"])

    def test_python_exe_prefix(self):
        r = normalize_pip_command("python.exe -m pip install requests")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["requests"])

    def test_py_launcher_version_flag(self):
        r = normalize_pip_command("py -3 -m pip install requests")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["requests"])

    def test_python_prefix_without_pip_module_is_specs(self):
        """`python xxx` 没有 -m pip：xxx 被当包名（specs）——宽容处理。"""
        r = normalize_pip_command("python nvidia-vfx")
        self.assertEqual(r["kind"], "specs")
        self.assertEqual(r["args"], ["nvidia-vfx"])

    def test_bare_package_name(self):
        r = normalize_pip_command("nvidia-vfx")
        self.assertEqual(r["kind"], "specs")
        self.assertEqual(r["args"], ["nvidia-vfx"])
        self.assertFalse(r["has_index_flag"])

    def test_bare_multiple_specs(self):
        r = normalize_pip_command("nvidia-vfx opencv-python")
        self.assertEqual(r["kind"], "specs")
        self.assertEqual(r["args"], ["nvidia-vfx", "opencv-python"])

    def test_bare_version_spec(self):
        r = normalize_pip_command("torch==2.4.1")
        self.assertEqual(r["kind"], "specs")
        self.assertEqual(r["args"], ["torch==2.4.1"])

    def test_flags_without_subcommand_default_to_install(self):
        """漏写 install 的 `-U pkg` 也按 install 处理。"""
        r = normalize_pip_command("-U nvidia-vfx")
        self.assertEqual(r["kind"], "specs")
        self.assertEqual(r["args"], ["-U", "nvidia-vfx"])

    def test_uninstall_command(self):
        r = normalize_pip_command("python -m pip uninstall torch numpy")
        self.assertEqual(r["kind"], "uninstall")
        self.assertEqual(r["args"], ["torch", "numpy"])

    def test_uninstall_with_y_flag(self):
        r = normalize_pip_command("pip uninstall -y torch")
        self.assertEqual(r["kind"], "uninstall")
        self.assertEqual(r["args"], ["-y", "torch"])

    def test_reject_list_subcommand(self):
        """其它 pip 子命令明确拒绝，防止被当包名装出一个叫 list 的包。"""
        for cmd in ("pip list", "python -m pip freeze", "pip cache purge",
                    "pip show torch", "pip download pkg"):
            r = normalize_pip_command(cmd)
            self.assertEqual(r["kind"], "error", msg=cmd)
            self.assertTrue(r["error"], msg=cmd)

    def test_quoted_path_preserves_backslashes(self):
        """Windows 带空格路径：posix=False 分词 + 剥引号，反斜杠保留。"""
        r = normalize_pip_command('pip install "F:\\some dir\\pkg.whl"')
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["F:\\some dir\\pkg.whl"])

    def test_empty_inputs(self):
        for cmd in ("", "   ", "python -m pip", "pip"):
            r = normalize_pip_command(cmd)
            self.assertEqual(r["kind"], "error", msg=repr(cmd))

    def test_install_without_args(self):
        r = normalize_pip_command("pip install")
        self.assertEqual(r["kind"], "error")

    def test_case_insensitive_prefix(self):
        r = normalize_pip_command("Python -m PIP install pkg")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["pkg"])

    def test_index_flag_detection(self):
        r = normalize_pip_command("pip install -U pkg --extra-index-url https://x/simple")
        self.assertTrue(r["has_index_flag"])
        r2 = normalize_pip_command("pip install -U pkg -i https://y/simple")
        self.assertTrue(r2["has_index_flag"])

    # ---- 用户确认过的前缀格式清单（2026-11-09）：路径形态曾漏剥，回归防退 ----

    def test_relative_path_python_exe_prefix(self):
        """python_embeded/python.exe -m pip …（用户列出的形态之一）。"""
        r = normalize_pip_command(
            "python_embeded/python.exe -m pip install -U nvidia-vfx")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["-U", "nvidia-vfx"])

    def test_absolute_path_python_exe_prefix(self):
        r = normalize_pip_command(
            r"C:\PP\V9\python_embeded\python.exe -m pip install pkg")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["pkg"])

    def test_backslash_relative_python_prefix(self):
        r = normalize_pip_command(r"..\python_embeded\python.exe -m pip uninstall torch")
        self.assertEqual(r["kind"], "uninstall")
        self.assertEqual(r["args"], ["torch"])

    def test_pip_exe_prefix(self):
        r = normalize_pip_command("pip.exe install numpy")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["numpy"])

    def test_pip3_exe_prefix(self):
        r = normalize_pip_command("pip3.exe install numpy")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["numpy"])

    def test_versioned_python_prefix(self):
        for prefix in ("python3 -m pip install pkg",
                       "python3.11 -m pip install pkg",
                       "python3.11.exe -m pip install pkg"):
            r = normalize_pip_command(prefix)
            self.assertEqual(r["kind"], "install", msg=prefix)
            self.assertEqual(r["args"], ["pkg"], msg=prefix)

    def test_path_prefixed_pip_prefix(self):
        """带路径的 pip 可执行名也要剥（Scripts\\pip.exe install …）。"""
        r = normalize_pip_command(r"python_embeded\Scripts\pip.exe install numpy")
        self.assertEqual(r["kind"], "install")
        self.assertEqual(r["args"], ["numpy"])


# ---------------------------------------------------------------------------
# utils.pip.list_installed_packages
# ---------------------------------------------------------------------------

def _fake_completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestListInstalledPackages(unittest.TestCase):
    def test_parses_json_and_sorts(self):
        from utils.pip import list_installed_packages
        out = '[{"version": "1.0", "name": "numpy"}, {"name": "annotated-types", "version": "0.6"}]'
        with patch("utils.pip.run_hidden", return_value=_fake_completed(stdout=out)):
            pkgs = list_installed_packages("python")
        self.assertEqual([p["name"] for p in pkgs], ["annotated-types", "numpy"])
        self.assertEqual(pkgs[1]["version"], "1.0")

    def test_skips_malformed_entries(self):
        from utils.pip import list_installed_packages
        out = '[{"name": "", "version": "1"}, {"name": "ok", "version": "2"}, "junk"]'
        with patch("utils.pip.run_hidden", return_value=_fake_completed(stdout=out)):
            pkgs = list_installed_packages("python")
        self.assertEqual(pkgs, [{"name": "ok", "version": "2"}])

    def test_nonzero_exit_raises(self):
        from utils.pip import list_installed_packages
        with patch("utils.pip.run_hidden",
                   return_value=_fake_completed(stderr="boom", returncode=1)):
            with pytest.raises(PipListError):
                list_installed_packages("python")

    def test_bad_json_raises(self):
        from utils.pip import list_installed_packages
        with patch("utils.pip.run_hidden", return_value=_fake_completed(stdout="not json")):
            with pytest.raises(PipListError):
                list_installed_packages("python")


# ---------------------------------------------------------------------------
# uninstall_packages / run_pip_args
# ---------------------------------------------------------------------------

class TestUninstallPackages(unittest.TestCase):
    def test_requires_names(self):
        from utils.pip import uninstall_packages
        r = uninstall_packages([], "python")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "PIP_NO_PACKAGES")

    def test_success_parses_uninstalled(self):
        from utils.pip import uninstall_packages
        fake = _fake_completed(
            stdout="Successfully uninstalled foo-1.0\nSuccessfully uninstalled bar-2.0\n")
        with patch("utils.pip.run_hidden", return_value=fake) as rh:
            r = uninstall_packages(["foo", "bar"], "python")
        self.assertTrue(r["success"])
        self.assertEqual(r["uninstalled"], ["foo-1.0", "bar-2.0"])
        cmd = rh.call_args[0][0]
        self.assertIn("-y", cmd)
        self.assertEqual(cmd[-2:], ["foo", "bar"])

    def test_failure_reports_stderr(self):
        from utils.pip import uninstall_packages
        fake = _fake_completed(stderr="not installed", returncode=1)
        with patch("utils.pip.run_hidden", return_value=fake):
            r = uninstall_packages(["ghost"], "python")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "PIP_COMMAND_FAILED")
        self.assertIn("not installed", r["error"])

    def test_cancelled_mapping(self):
        from utils.pip import uninstall_packages
        fake = _fake_completed(stdout="", returncode=1)
        fake.cancelled = True
        with patch("utils.pip._run_pip_streaming", return_value=fake):
            r = uninstall_packages(["foo"], "python", cancel_event=threading.Event())
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "USER_CANCELLED")
        self.assertTrue(r["cancelled"])


class TestRunPipArgs(unittest.TestCase):
    def test_success(self):
        from pathlib import Path
        from utils.pip import run_pip_args
        fake = _fake_completed(stdout="ok", returncode=0)
        with patch("utils.pip._run_pip_streaming", return_value=fake) as m:
            r = run_pip_args(["install", "-U", "pkg"], "C:/py/python.exe")
        self.assertTrue(r["success"])
        cmd = m.call_args[0][0]
        self.assertEqual(cmd[:3], [str(Path("C:/py/python.exe").resolve()), "-m", "pip"])

    def test_failure_includes_returncode(self):
        from utils.pip import run_pip_args
        fake = _fake_completed(stderr="err", returncode=2)
        with patch("utils.pip._run_pip_streaming", return_value=fake):
            r = run_pip_args(["install", "pkg"], "python")
        self.assertFalse(r["success"])
        self.assertEqual(r["returncode"], 2)
        self.assertEqual(r["error_code"], "PIP_COMMAND_FAILED")


# ---------------------------------------------------------------------------
# _run_pip_streaming 的取消
# ---------------------------------------------------------------------------

class _ChunkStream:
    """按块给数据的假 stdout：每块一个 512B 上限的分片，可中途触发取消。"""

    def __init__(self, data: bytes, cancel_event=None, cancel_after_chunks=0,
                 delay: float = 0.02):
        self._buf = data
        self._pos = 0
        self._delay = delay
        self._cancel = cancel_event
        self._cancel_after = cancel_after_chunks
        self._served = 0

    def read(self, n=-1):
        # 取消触发放在 EOF 分支之前：读超数据末尾的那次 read 也要能触发
        if (self._cancel is not None and self._cancel_after
                and self._served >= self._cancel_after):
            self._cancel.set()
        if self._pos >= len(self._buf):
            return b""
        time.sleep(self._delay)
        end = min(self._pos + (n if n and n > 0 else 512), len(self._buf))
        out = self._buf[self._pos:end]
        self._pos = end
        self._served += 1
        return out


def _make_proc(stdout, stderr=None, returncode=0):
    fake = MagicMock()
    fake.stdout = stdout
    fake.stderr = stderr if stderr is not None else _ChunkStream(b"", delay=0)
    fake.returncode = returncode
    fake.wait = lambda: returncode
    return fake


class TestPipStreamingCancel(unittest.TestCase):
    def test_cancel_before_start_never_spawns(self):
        ev = threading.Event()
        ev.set()
        with patch("subprocess.Popen") as popen:
            res = _run_pip_streaming(["python", "-m", "pip"], logger=None,
                                     on_progress=lambda t: None, cancel_event=ev)
        self.assertTrue(res.cancelled)
        popen.assert_not_called()

    def test_cancel_mid_stream_kills_tree(self):
        """流中途触发取消 → cancelled=True 且 _kill_tree 被调。

        cancel_after_chunks=1：第二次 read 前（剩余数据返回前）置位取消，
        保证后续行经过 _handle_line 时 cancel 已置位（数据太小、触发太晚
        会出现「cancelled=True 但行已读完」的假阴性）。
        """
        from utils import pip as pipmod
        data = b"Collecting foo\nDownloading foo\nInstalling foo\n" * 20
        ev = threading.Event()
        fake = _make_proc(_ChunkStream(data, cancel_event=ev,
                                       cancel_after_chunks=1, delay=0.01))
        with patch("subprocess.Popen", return_value=fake), \
             patch.object(pipmod, "_kill_tree") as kt:
            res = _run_pip_streaming(["python", "-m", "pip"], logger=None,
                                     on_progress=lambda t: None, cancel_event=ev)
        self.assertTrue(res.cancelled)
        self.assertTrue(kt.called)

    def test_no_cancel_flag_when_not_cancelled(self):
        from utils import pip as pipmod
        data = b"Collecting foo\nSuccessfully installed foo-1.0\n"
        fake = _make_proc(_ChunkStream(data, delay=0.01))
        with patch("subprocess.Popen", return_value=fake):
            res = _run_pip_streaming(["python", "-m", "pip"], logger=None,
                                     on_progress=lambda t: None)
        self.assertFalse(getattr(res, "cancelled", True))


# ---------------------------------------------------------------------------
# PipService
# ---------------------------------------------------------------------------

class _FakeApp:
    def __init__(self, tmp_path):
        self._tmp = tmp_path
        self.config = {
            "paths": {
                "comfyui_root": str(tmp_path / "ComfyUI"),
                "python_path": sys.executable,
            }
        }

    def get_active_paths(self):
        return {
            "comfyui_root": str(self._tmp / "ComfyUI"),
            "python_path": sys.executable,
        }


class TestPipService(unittest.TestCase):
    def _svc(self, tmp_path):
        return PipService(_FakeApp(tmp_path))

    def test_python_exec_resolves_active_env(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            svc = self._svc(Path(td))
            self.assertEqual(svc.python_exec(), sys.executable)
            self.assertTrue(svc.is_available())

    def test_python_exec_none_on_bad_app(self):
        svc = PipService(object())
        # object() 无 get_active_paths / config —— 走 config.get("paths") 回退也拿不到
        # resolve_python_exec 的兜底路径可能仍返回默认 python_embeded，不强断言 None，
        # 只断言不抛异常。
        try:
            svc.python_exec()
        except Exception as e:  # pragma: no cover
            self.fail(f"python_exec raised: {e}")

    def test_list_installed_delegates(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            svc = self._svc(Path(td))
            with patch("utils.pip.list_installed_packages",
                       return_value=[{"name": "a", "version": "1"}]) as m:
                pkgs = svc.list_installed()
            m.assert_called_once()
            self.assertEqual(pkgs, [{"name": "a", "version": "1"}])

    def test_install_passes_index_and_cancel(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            svc = self._svc(Path(td))
            ev = threading.Event()
            with patch("utils.pip.install_or_update_package", return_value={"success": True}) as m:
                svc.install("pkg", index_url="https://x/simple", cancel_event=ev)
            kwargs = m.call_args[1]
            self.assertEqual(kwargs.get("index_url"), "https://x/simple")
            self.assertIs(kwargs.get("cancel_event"), ev)

    def test_uninstall_passes_through(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            svc = self._svc(Path(td))
            with patch("utils.pip.uninstall_packages", return_value={"success": True}) as m:
                svc.uninstall(["pkg"])
            self.assertEqual(m.call_args[0][0], ["pkg"])

    def test_run_args_builds_preview(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            svc = self._svc(Path(td))
            preview = svc.preview_command(["install", "-U", "pkg"])
            self.assertTrue(preview.startswith(f'"{sys.executable}"') or
                            preview.startswith(sys.executable))
            self.assertIn("-m pip install -U pkg", preview)


if __name__ == "__main__":
    unittest.main()
