"""Tests for --cuda-device injection in build_launch_params and gpu_device config round-trip."""

import json
import tempfile
import unittest
from pathlib import Path


class _Var:
    def __init__(self, v):
        self._v = v

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


def _build_app(base: Path, py_exec: Path, **overrides):
    class App:
        def __init__(self):
            self.config = {
                "paths": {
                    "comfyui_root": str(base),
                    "python_path": str(py_exec),
                }
            }
            self.compute_mode = _Var(overrides.get("compute_mode", "gpu"))
            self.use_fast_mode = _Var(overrides.get("use_fast_mode", False))
            self.enable_cors = _Var(False)
            self.listen_all = _Var(overrides.get("listen_all", False))
            self.custom_port = _Var(overrides.get("custom_port", "8188"))
            self.extra_launch_args = _Var(overrides.get("extra_launch_args", ""))
            self.attention_mode = _Var("")
            self.selected_hf_mirror = _Var("\u4e0d\u4f7f\u7528\u955c\u50cf")
            self.hf_mirror_url = _Var("")
            self.gpu_device = _Var(overrides.get("gpu_device", -1))

        def save_config(self):
            pass

    return App()


def _make_paths():
    td = tempfile.TemporaryDirectory()
    base = Path(td.name)
    comfy = base / "ComfyUI"
    comfy.mkdir(parents=True, exist_ok=True)
    (comfy / "main.py").write_text("print('x')", encoding="utf-8")
    py_emb = base / "python_embeded"
    py_emb.mkdir(parents=True, exist_ok=True)
    py_exec = py_emb / "python.exe"
    py_exec.write_text("", encoding="utf-8")
    return td, base, py_exec


class TestCudaDeviceFlag(unittest.TestCase):
    def test_default_does_not_emit_cuda_device(self):
        from core.launcher_cmd import build_launch_params
        td, base, py = _make_paths()
        try:
            app = _build_app(base, py)
            cmd, _env, _cwd, _py, _main = build_launch_params(app)
            self.assertNotIn("--cuda-device", cmd)
        finally:
            td.cleanup()

    def test_explicit_zero_emits_cuda_device_0(self):
        from core.launcher_cmd import build_launch_params
        td, base, py = _make_paths()
        try:
            app = _build_app(base, py, gpu_device=0)
            cmd, _env, _cwd, _py, _main = build_launch_params(app)
            self.assertIn("--cuda-device", cmd)
            idx = cmd.index("--cuda-device")
            self.assertEqual(cmd[idx + 1], "0")
        finally:
            td.cleanup()

    def test_explicit_two_emits_cuda_device_2(self):
        from core.launcher_cmd import build_launch_params
        td, base, py = _make_paths()
        try:
            app = _build_app(base, py, gpu_device=2)
            cmd, _env, _cwd, _py, _main = build_launch_params(app)
            self.assertIn("--cuda-device", cmd)
            idx = cmd.index("--cuda-device")
            self.assertEqual(cmd[idx + 1], "2")
        finally:
            td.cleanup()

    def test_cpu_mode_never_emits_cuda_device_even_if_value_set(self):
        from core.launcher_cmd import build_launch_params
        td, base, py = _make_paths()
        try:
            app = _build_app(base, py, compute_mode="cpu", gpu_device=1)
            cmd, _env, _cwd, _py, _main = build_launch_params(app)
            self.assertIn("--cpu", cmd)
            self.assertNotIn("--cuda-device", cmd)
        finally:
            td.cleanup()

    def test_invalid_string_falls_back_to_default(self):
        from core.launcher_cmd import build_launch_params
        td, base, py = _make_paths()
        try:
            app = _build_app(base, py)
            app.gpu_device = _Var("not-a-number")
            cmd, _env, _cwd, _py, _main = build_launch_params(app)
            self.assertNotIn("--cuda-device", cmd)
        finally:
            td.cleanup()

    def test_negative_value_means_default(self):
        from core.launcher_cmd import build_launch_params
        td, base, py = _make_paths()
        try:
            app = _build_app(base, py, gpu_device=-1)
            cmd, _env, _cwd, _py, _main = build_launch_params(app)
            self.assertNotIn("--cuda-device", cmd)
        finally:
            td.cleanup()


class TestGpuDeviceConfigRoundTrip(unittest.TestCase):
    def test_default_config_has_gpu_device_minus_one(self):
        from config.manager import ConfigManager
        with tempfile.TemporaryDirectory() as td:
            cm = ConfigManager(Path(td) / "cfg.json")
            cfg = cm.get_default_config()
            self.assertEqual(cfg["launch_options"].get("gpu_device"), -1)

    def test_persisted_gpu_device_roundtrips(self):
        from config.manager import ConfigManager
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "cfg.json"
            cm = ConfigManager(cfg_path)
            data = cm.get_default_config()
            data["launch_options"]["gpu_device"] = 1
            cm.save_config(data)

            reloaded = ConfigManager(cfg_path).load_config()
            self.assertEqual(reloaded["launch_options"]["gpu_device"], 1)

    def test_legacy_config_without_gpu_device_still_loads(self):
        from config.manager import ConfigManager
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "cfg.json"
            legacy = {
                "launch_options": {
                    "default_compute_mode": "gpu",
                    "default_port": "8188",
                },
                "paths": {"comfyui_root": "."},
            }
            cfg_path.write_text(json.dumps(legacy), encoding="utf-8")
            loaded = ConfigManager(cfg_path).load_config()
            # legacy 字段保留，gpu_device 字段缺失也不报错
            self.assertEqual(loaded["launch_options"]["default_port"], "8188")
            self.assertNotIn("gpu_device", loaded["launch_options"])


class TestGpuEnumerateWorkerParseLines(unittest.TestCase):
    def test_parse_lines_pynvml_format(self):
        from core.version_workers import GpuEnumerateWorker
        sample = "0\x1fNVIDIA GeForce RTX 4090\x1f24576\n1\x1fNVIDIA GeForce RTX 3080\x1f10240"
        out = GpuEnumerateWorker._parse_lines(sample)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["index"], 0)
        self.assertEqual(out[0]["name"], "NVIDIA GeForce RTX 4090")
        self.assertEqual(out[0]["memory_mb"], 24576)
        self.assertEqual(out[1]["index"], 1)
        self.assertEqual(out[1]["memory_mb"], 10240)

    def test_parse_lines_skips_error_and_empty(self):
        from core.version_workers import GpuEnumerateWorker
        sample = "ERROR:nvml not available\n\n0\x1fRTX 4090\x1f24576"
        out = GpuEnumerateWorker._parse_lines(sample)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["index"], 0)

    def test_parse_lines_handles_pipe_separator_fallback(self):
        from core.version_workers import GpuEnumerateWorker
        sample = "0|RTX 4090|24576"
        out = GpuEnumerateWorker._parse_lines(sample)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "RTX 4090")
        self.assertEqual(out[0]["memory_mb"], 24576)


if __name__ == "__main__":
    unittest.main(verbosity=2)
