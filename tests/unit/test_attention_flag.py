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


class TestAttentionFlag(unittest.TestCase):
    def test_append_attention_flag(self):
        from core.launcher_cmd import build_launch_params
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            comfy = base / "ComfyUI"
            comfy.mkdir(parents=True, exist_ok=True)
            (comfy / "main.py").write_text("print('x')", encoding="utf-8")
            py_emb = base / "python_embeded"
            py_emb.mkdir(parents=True, exist_ok=True)
            py_exec = py_emb / ("python.exe")
            py_exec.write_text("", encoding="utf-8")

        class App:
            def __init__(self):
                self.config = {"paths": {"comfyui_root": str(base), "python_path": str(py_exec)}}
                self.compute_mode = _Var("gpu")
                self.use_fast_mode = _Var(False)
                self.enable_cors = _Var(False)
                self.listen_all = _Var(False)
                self.custom_port = _Var("8188")
                self.extra_launch_args = _Var("")
                self.attention_mode = _Var("--use-flash-attention")
                self.selected_hf_mirror = _Var("不使用镜像")
                self.hf_mirror_url = _Var("")
            def save_config(self):
                pass

        app = App()
        cmd, env, run_cwd, py, main = build_launch_params(app)
        self.assertIn("--use-flash-attention", cmd)

    def test_skip_duplicate_attention_flag(self):
        from core.launcher_cmd import build_launch_params
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            comfy = base / "ComfyUI"
            comfy.mkdir(parents=True, exist_ok=True)
            (comfy / "main.py").write_text("print('x')", encoding="utf-8")
            py_emb = base / "python_embeded"
            py_emb.mkdir(parents=True, exist_ok=True)
            py_exec = py_emb / ("python.exe")
            py_exec.write_text("", encoding="utf-8")

        class App:
            def __init__(self):
                self.config = {"paths": {"comfyui_root": str(base), "python_path": str(py_exec)}}
                self.compute_mode = _Var("gpu")
                self.use_fast_mode = _Var(False)
                self.enable_cors = _Var(False)
                self.listen_all = _Var(False)
                self.custom_port = _Var("8188")
                self.extra_launch_args = _Var("--use-split-cross-attention")
                self.attention_mode = _Var("--use-split-cross-attention")
                self.selected_hf_mirror = _Var("不使用镜像")
                self.hf_mirror_url = _Var("")
            def save_config(self):
                pass

        app = App()
        cmd, env, run_cwd, py, main = build_launch_params(app)
        self.assertEqual(cmd.count("--use-split-cross-attention"), 1)

    def test_append_kitchen_attention_flag(self):
        from core.launcher_cmd import build_launch_params
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            comfy = base / "ComfyUI"
            comfy.mkdir(parents=True, exist_ok=True)
            (comfy / "main.py").write_text("print('x')", encoding="utf-8")
            py_emb = base / "python_embeded"
            py_emb.mkdir(parents=True, exist_ok=True)
            py_exec = py_emb / ("python.exe")
            py_exec.write_text("", encoding="utf-8")

        class App:
            def __init__(self):
                self.config = {"paths": {"comfyui_root": str(base), "python_path": str(py_exec)}}
                self.compute_mode = _Var("gpu")
                self.use_fast_mode = _Var(False)
                self.enable_cors = _Var(False)
                self.listen_all = _Var(False)
                self.custom_port = _Var("8188")
                self.extra_launch_args = _Var("")
                self.attention_mode = _Var("--use-ck-attention")
                self.selected_hf_mirror = _Var("不使用镜像")
                self.hf_mirror_url = _Var("")
            def save_config(self):
                pass

        app = App()
        cmd, env, run_cwd, py, main = build_launch_params(app)
        self.assertIn("--use-ck-attention", cmd)

if __name__ == "__main__":
    unittest.main(verbosity=2)