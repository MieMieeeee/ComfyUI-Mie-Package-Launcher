"""
Tests for utils/paths.py functions.
"""

from pathlib import Path

from utils import paths as PATHS


class TestPathsRoot:
    def test_get_comfy_root_default(self):
        from utils.paths import get_comfy_root
        r = get_comfy_root({})
        assert str(r).endswith("ComfyUI") or str(r)

    def test_get_comfy_root_from_config(self):
        from utils.paths import get_comfy_root
        base = Path.cwd()
        cfg = {"comfyui_root": str(base)}
        r = get_comfy_root(cfg)
        assert r == (base / "ComfyUI").resolve()

    def test_child_dirs_join(self):
        base = Path.cwd() / "ComfyUI"
        assert PATHS.logs_file(base) == base / "user" / "comfyui.log"
        assert PATHS.input_dir(base) == base / "input"
        assert PATHS.output_dir(base) == base / "output"
        assert PATHS.plugins_dir(base) == base / "custom_nodes"
        assert PATHS.workflows_dir(base) == base / "user" / "default" / "workflows"
