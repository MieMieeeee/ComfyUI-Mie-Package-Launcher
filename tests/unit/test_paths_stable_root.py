"""Regression tests for utils.paths stable_project_root + relative path anchoring.

User-reported bug: launcher.exe launched from a different cwd (cmd shell /
Task Scheduler / file manager with shifted cwd) would resolve relative
``comfyui_root="."`` and ``python_path="python_embeded/python.exe"``
against ``Path.cwd()`` instead of the launcher's own directory. Result:

  comfyui_root  -> <cwd>/ComfyUI
  parent        -> <cwd>
  python_path   -> <cwd>/python_embeded/python.exe

leading to a bogus ``F:\\python_embeded\\python.exe`` and a "python
不可执行" dialog when starting the webui workbench.

These tests lock down stable_project_root + the relative-anchoring contract.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.paths import (
    stable_project_root,
    resolve_python_exec,
    get_comfy_root,
    comfy_root_from_config,
)


def _make_project_root(d: Path) -> Path:
    """Synthesize a launcher project tree under ``d``.

    Layout mimics a real packaged launcher:
      <root>/ComfyUI/main.py
      <root>/python_embeded/python.exe
    """
    comfy = d / "ComfyUI"
    comfy.mkdir(parents=True, exist_ok=True)
    (comfy / "main.py").write_text("# stub\n", encoding="utf-8")
    pe = d / "python_embeded"
    pe.mkdir(parents=True, exist_ok=True)
    (pe / "python.exe").write_text("", encoding="utf-8")
    return d


class TestStableProjectRoot(unittest.TestCase):
    def test_exe_dir_with_comfyui_marker_wins_over_cwd(self):
        """When running as a packaged .exe, sys.executable's parent contains
        ComfyUI/main.py -- that should win even if cwd is somewhere else
        (e.g. user double-clicked from a different shell cwd)."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fake_exe_dir = _make_project_root(d)
            fake_exe = str(fake_exe_dir / "Launcher.exe")
            old_cwd = os.getcwd()
            try:
                os.chdir("F:/")  # 任意其他目录, 模拟用户从 cmd shell 启动
                with mock.patch.object(sys, "executable", fake_exe):
                    r = stable_project_root()
                self.assertEqual(r.resolve(), fake_exe_dir.resolve(),
                                 f"expected {fake_exe_dir}, got {r}")
            finally:
                os.chdir(old_cwd)

    def test_first_existing_candidate_is_used_when_no_marker(self):
        """If no candidate has ComfyUI/main.py, fall back to the first
        existing candidate (EXE dir preferred)."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            # Empty tempdir (no ComfyUI/main.py). Just need a fake exe path
            # that exists.
            fake_exe = str(d / "fake.exe")  # nonexistent on purpose for sandbox,
            # but cwd DOES exist
            with mock.patch.object(sys, "executable", "/nonexistent/Fake.exe"):
                with mock.patch("os.getcwd", return_value=str(d)):
                    r = stable_project_root()
            self.assertTrue(r.exists())


class TestGetComfyRootRelative(unittest.TestCase):
    def test_relative_dot_resolves_to_stable_project_root_not_cwd(self):
        """`comfyui_root="."` should anchor to stable_project_root, not cwd.

        Setup: launcher project at ``d`` (with ComfyUI/main.py), cwd = some
        other location. get_comfy_root with "." must return ``d/ComfyUI``.
        """
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fake_exe_dir = _make_project_root(d)
            old_cwd = os.getcwd()
            try:
                os.chdir("F:/")  # NOT the launcher dir
                with mock.patch.object(sys, "executable", str(fake_exe_dir / "L.exe")):
                    root = get_comfy_root({"comfyui_root": "."})
                self.assertEqual(root.resolve(), (fake_exe_dir / "ComfyUI").resolve())
                # Importantly NOT F:/ComfyUI
                self.assertNotEqual(str(root), r"F:\ComfyUI")
            finally:
                os.chdir(old_cwd)

    def test_absolute_path_passes_through(self):
        """Absolute comfyui_root is honored as-is (no anchoring)."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "ComfyUI").mkdir()
            root = get_comfy_root({"comfyui_root": str(d)})
            self.assertEqual(root, (d / "ComfyUI").resolve())


class TestResolvePythonExecRelative(unittest.TestCase):
    def test_relative_python_path_anchors_to_stable_project_root(self):
        """relative `python_path="python_embeded/python.exe"` + passing
        comfy_root=Path('.') with cwd somewhere else should still resolve
        to launcher_dir/python_embeded/python.exe (which exists).
        """
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fake_exe_dir = _make_project_root(d)
            old_cwd = os.getcwd()
            try:
                os.chdir("F:/")  # cwd != launcher dir
                with mock.patch.object(sys, "executable", str(fake_exe_dir / "L.exe")):
                    py = resolve_python_exec(Path("."), "python_embeded/python.exe")
                self.assertTrue(Path(py).exists(),
                                f"resolved python {py} should exist under launcher dir")
                # Resolved should match the launcher's bundled python, not
                # F:\\\\python_embeded\\\\python.exe (which doesn't exist).
                self.assertEqual(
                    Path(py).resolve(),
                    (fake_exe_dir / "python_embeded" / "python.exe").resolve(),
                )
            finally:
                os.chdir(old_cwd)

    def test_absolute_python_path_works(self):
        """Absolute configured python path that's valid is used directly."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "python.exe").write_text("", encoding="utf-8")
            py = resolve_python_exec(d, str(d / "python.exe"))
            self.assertEqual(Path(py).resolve(), (d / "python.exe").resolve())

    def test_fallback_uses_launcher_python_not_cwd(self):
        """When the configured python is bogus, fallback resolves to
        launcher_dir/python_embeded/python.exe (NOT <cwd>/python_embeded/python.exe,
        which is the historical bug)."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fake_exe_dir = _make_project_root(d)
            old_cwd = os.getcwd()
            try:
                os.chdir("F:/")
                with mock.patch.object(sys, "executable", str(fake_exe_dir / "L.exe")):
                    py = resolve_python_exec(d, "/nonexistent/python.exe")
                # Fallback lands in launcher's bundled python, exists.
                self.assertTrue(Path(py).exists())
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()