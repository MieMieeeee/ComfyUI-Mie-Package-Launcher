import unittest
from pathlib import Path
from dataclasses import asdict


class TestAppState(unittest.TestCase):
    """Tests for AppState in core.app_state module.

    These tests define the expected interface for AppState:
    - A dataclass holding business state (no UI/Qt dependencies)
    - Serialization via to_dict() / from_dict()
    - Field access via properties or direct dataclass fields
    """

    def test_app_state_module_exists(self):
        """AppState should be importable from core.app_state"""
        from core.app_state import AppState

    def test_default_initialization(self):
        """AppState should initialize with sensible defaults"""
        from core.app_state import AppState

        state = AppState()
        self.assertEqual(state.compute_mode, "cpu")
        self.assertEqual(state.vram_mode, "normal")
        self.assertIsNone(state.python_path)
        self.assertIsNone(state.comfyui_path)
        self.assertEqual(state.enable_fast_mode, False)
        self.assertEqual(state.disable_all_custom_nodes, False)
        self.assertEqual(state.extra_args, "")
        self.assertEqual(state.attention_mode, "")
        self.assertEqual(state.listen_all, True)
        self.assertEqual(state.default_port, "8188")

    def test_initialization_from_dict(self):
        """AppState should be creatable from a dict"""
        from core.app_state import AppState

        data = {
            "compute_mode": "cuda",
            "vram_mode": "high",
            "python_path": Path("/path/to/python"),
            "comfyui_path": Path("/path/to/comfyui"),
            "enable_fast_mode": True,
            "disable_all_custom_nodes": False,
            "extra_args": "--verbose",
            "attention_mode": "--use-sage-attention",
            "listen_all": False,
            "default_port": "8888",
        }
        state = AppState.from_dict(data)

        self.assertEqual(state.compute_mode, "cuda")
        self.assertEqual(state.vram_mode, "high")
        self.assertEqual(state.python_path, Path("/path/to/python"))
        self.assertEqual(state.comfyui_path, Path("/path/to/comfyui"))
        self.assertEqual(state.enable_fast_mode, True)
        self.assertEqual(state.disable_all_custom_nodes, False)
        self.assertEqual(state.extra_args, "--verbose")
        self.assertEqual(state.attention_mode, "--use-sage-attention")
        self.assertEqual(state.listen_all, False)
        self.assertEqual(state.default_port, "8888")

    def test_serialization_roundtrip(self):
        """to_dict() -> from_dict() should preserve all fields"""
        from core.app_state import AppState

        original = AppState(
            compute_mode="cuda:0",
            vram_mode="low",
            python_path=Path("/usr/bin/python"),
            comfyui_path=Path("/home/user/ComfyUI"),
            enable_fast_mode=True,
            disable_all_custom_nodes=True,
            extra_args="--debug",
            attention_mode="--use-split-cross-attention",
            listen_all=False,
            default_port="9999",
        )

        # Serialize then deserialize
        data = original.to_dict()
        restored = AppState.from_dict(data)

        self.assertEqual(restored.compute_mode, original.compute_mode)
        self.assertEqual(restored.vram_mode, original.vram_mode)
        self.assertEqual(restored.python_path, original.python_path)
        self.assertEqual(restored.comfyui_path, original.comfyui_path)
        self.assertEqual(restored.enable_fast_mode, original.enable_fast_mode)
        self.assertEqual(restored.disable_all_custom_nodes, original.disable_all_custom_nodes)
        self.assertEqual(restored.extra_args, original.extra_args)
        self.assertEqual(restored.attention_mode, original.attention_mode)
        self.assertEqual(restored.listen_all, original.listen_all)
        self.assertEqual(restored.default_port, original.default_port)

    def test_to_dict_returns_dict(self):
        """to_dict() should return a plain dict"""
        from core.app_state import AppState

        state = AppState()
        result = state.to_dict()

        self.assertIsInstance(result, dict)
        self.assertIn("compute_mode", result)
        self.assertIn("vram_mode", result)

    def test_compute_mode_getter_setter(self):
        """compute_mode should be readable and writable"""
        from core.app_state import AppState

        state = AppState()
        self.assertEqual(state.compute_mode, "cpu")

        state.compute_mode = "cuda"
        self.assertEqual(state.compute_mode, "cuda")

    def test_vram_mode_getter_setter(self):
        """vram_mode should be readable and writable"""
        from core.app_state import AppState

        state = AppState()
        self.assertEqual(state.vram_mode, "normal")

        state.vram_mode = "high"
        self.assertEqual(state.vram_mode, "high")

    def test_python_path_getter_setter(self):
        """python_path should be readable and writable"""
        from core.app_state import AppState

        state = AppState()
        self.assertIsNone(state.python_path)

        new_path = Path("/custom/python")
        state.python_path = new_path
        self.assertEqual(state.python_path, new_path)

    def test_comfyui_path_getter_setter(self):
        """comfyui_path should be readable and writable"""
        from core.app_state import AppState

        state = AppState()
        self.assertIsNone(state.comfyui_path)

        new_path = Path("/custom/comfyui")
        state.comfyui_path = new_path
        self.assertEqual(state.comfyui_path, new_path)

    def test_enable_fast_mode_getter_setter(self):
        """enable_fast_mode should be readable and writable"""
        from core.app_state import AppState

        state = AppState()
        self.assertFalse(state.enable_fast_mode)

        state.enable_fast_mode = True
        self.assertTrue(state.enable_fast_mode)

    def test_disable_all_custom_nodes_getter_setter(self):
        """disable_all_custom_nodes should be readable and writable"""
        from core.app_state import AppState

        state = AppState()
        self.assertFalse(state.disable_all_custom_nodes)

        state.disable_all_custom_nodes = True
        self.assertTrue(state.disable_all_custom_nodes)

    def test_extra_args_getter_setter(self):
        """extra_args should be readable and writable"""
        from core.app_state import AppState

        state = AppState()
        self.assertEqual(state.extra_args, "")

        state.extra_args = "--verbose --debug"
        self.assertEqual(state.extra_args, "--verbose --debug")

    def test_attention_mode_getter_setter(self):
        """attention_mode should be readable and writable"""
        from core.app_state import AppState

        state = AppState()
        self.assertEqual(state.attention_mode, "")

        state.attention_mode = "--use-sage-attention"
        self.assertEqual(state.attention_mode, "--use-sage-attention")

    def test_listen_all_getter_setter(self):
        """listen_all should be readable and writable"""
        from core.app_state import AppState

        state = AppState()
        self.assertTrue(state.listen_all)

        state.listen_all = False
        self.assertFalse(state.listen_all)

    def test_default_port_getter_setter(self):
        """default_port should be readable and writable"""
        from core.app_state import AppState

        state = AppState()
        self.assertEqual(state.default_port, "8188")

        state.default_port = "8888"
        self.assertEqual(state.default_port, "8888")


if __name__ == "__main__":
    unittest.main(verbosity=2)
