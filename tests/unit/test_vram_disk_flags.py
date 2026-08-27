import unittest
import tempfile
from pathlib import Path


class _Var:
    def __init__(self, v):
        self._v = v
    def get(self):
        return self._v
    def set(self, v):
        self._v = v


def _make_app(extra_vars):
    base, py_exec = extra_vars["_paths"]
    return _App(base, py_exec, extra_vars)


class _App:
    def __init__(self, base, py_exec, extra_vars):
        self.config = {"paths": {"comfyui_root": str(base), "python_path": str(py_exec)}}
        self.compute_mode = _Var("gpu")
        self.use_fast_mode = _Var(False)
        self.enable_cors = _Var(False)
        self.listen_all = _Var(False)
        self.custom_port = _Var("8188")
        self.extra_launch_args = _Var("")
        self.attention_mode = _Var("")
        self.selected_hf_mirror = _Var("不使用镜像")
        self.hf_mirror_url = _Var("")
        self.disable_dynamic_vram = _Var(extra_vars.get("disable_dynamic_vram", False))
        self.fast_disk = _Var(extra_vars.get("fast_disk", False))
        self.disable_pinned_memory = _Var(extra_vars.get("disable_pinned_memory", False))
    def save_config(self):
        pass


def _setup_tmp():
    td = tempfile.mkdtemp()
    base = Path(td)
    comfy = base / "ComfyUI"
    comfy.mkdir(parents=True, exist_ok=True)
    (comfy / "main.py").write_text("print('x')", encoding="utf-8")
    py_emb = base / "python_embeded"
    py_emb.mkdir(parents=True, exist_ok=True)
    py_exec = py_emb / "python.exe"
    py_exec.write_text("", encoding="utf-8")
    return base, py_exec


class TestVramDiskFlags(unittest.TestCase):
    def test_defaults_omit_dynamic_vram_and_fast_disk(self):
        from core.launcher_cmd import build_launch_params
        base, py_exec = _setup_tmp()
        app = _App(base, py_exec, {})
        cmd, env, run_cwd, py, main = build_launch_params(app)
        self.assertNotIn("--disable-dynamic-vram", cmd)
        self.assertNotIn("--fast-disk", cmd)

    def test_disable_dynamic_vram_appended(self):
        from core.launcher_cmd import build_launch_params
        base, py_exec = _setup_tmp()
        app = _App(base, py_exec, {"disable_dynamic_vram": True})
        cmd, env, run_cwd, py, main = build_launch_params(app)
        self.assertIn("--disable-dynamic-vram", cmd)
        self.assertNotIn("--fast-disk", cmd)

    def test_fast_disk_appended(self):
        from core.launcher_cmd import build_launch_params
        base, py_exec = _setup_tmp()
        app = _App(base, py_exec, {"fast_disk": True})
        cmd, env, run_cwd, py, main = build_launch_params(app)
        self.assertIn("--fast-disk", cmd)
        self.assertNotIn("--disable-dynamic-vram", cmd)

    def test_both_can_stack(self):
        from core.launcher_cmd import build_launch_params
        base, py_exec = _setup_tmp()
        app = _App(base, py_exec, {"disable_dynamic_vram": True, "fast_disk": True})
        cmd, env, run_cwd, py, main = build_launch_params(app)
        self.assertIn("--disable-dynamic-vram", cmd)
        self.assertIn("--fast-disk", cmd)
        # both present exactly once
        self.assertEqual(cmd.count("--disable-dynamic-vram"), 1)
        self.assertEqual(cmd.count("--fast-disk"), 1)


    def test_all_three_can_stack(self):
        from core.launcher_cmd import build_launch_params
        base, py_exec = _setup_tmp()
        app = _App(base, py_exec, {"disable_dynamic_vram": True, "fast_disk": True, "disable_pinned_memory": True})
        cmd, env, run_cwd, py, main = build_launch_params(app)
        self.assertIn("--disable-dynamic-vram", cmd)
        self.assertIn("--fast-disk", cmd)
        self.assertIn("--disable-pinned-memory", cmd)
        self.assertEqual(cmd.count("--disable-dynamic-vram"), 1)
        self.assertEqual(cmd.count("--fast-disk"), 1)
        self.assertEqual(cmd.count("--disable-pinned-memory"), 1)

    def test_disable_pinned_memory_appended(self):
        from core.launcher_cmd import build_launch_params
        base, py_exec = _setup_tmp()
        app = _App(base, py_exec, {"disable_pinned_memory": True})
        cmd, env, run_cwd, py, main = build_launch_params(app)
        self.assertIn("--disable-pinned-memory", cmd)
        self.assertNotIn("--fast-disk", cmd)
        self.assertNotIn("--disable-dynamic-vram", cmd)

    def test_defaults_omit_disable_pinned_memory(self):
        from core.launcher_cmd import build_launch_params
        base, py_exec = _setup_tmp()
        app = _App(base, py_exec, {})
        cmd, env, run_cwd, py, main = build_launch_params(app)
        self.assertNotIn("--disable-pinned-memory", cmd)

if __name__ == "__main__":
    unittest.main(verbosity=2)
