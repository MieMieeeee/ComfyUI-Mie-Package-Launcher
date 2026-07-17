import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from headless_app import HeadlessAppContext


def _make_fake_comfy_install(root: Path, python_path: Path) -> None:
    """Create a minimal directory layout that build_launch_params will accept."""
    comfy_root = root / "ComfyUI"
    comfy_root.mkdir(parents=True, exist_ok=True)
    (comfy_root / "main.py").write_text("# fake main\n", encoding="utf-8")
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("# fake python stub\n", encoding="utf-8")


class TestBuildLaunchParamsInjectsUserEnv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)
        self.comfy_root = self.tmp_path / "ComfyUI_root"
        self.comfy_root.mkdir(parents=True)
        self.python_path = self.comfy_root / "python_embeded" / "python.exe"
        _make_fake_comfy_install(self.comfy_root, self.python_path)

        cfg_dir = self.tmp_path / "launcher"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg_file = cfg_dir / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "launch_options": {
                        "default_compute_mode": "cpu",
                        "default_port": "8188",
                        "extra_args": "",
                        "env_vars": "POLARS_SKIP_CPU_CHECK=1, MY_VAR=foo",
                    },
                    "paths": {
                        "comfyui_root": str(self.comfy_root),
                        "python_path": str(self.python_path),
                    },
                    "proxy_settings": {},
                }
            ),
            encoding="utf-8",
        )
        # HeadlessAppContext looks for "<cwd>/launcher/config.json".
        # Patch config_file resolution by symlinking launcher/ into cwd.
        cwd_launcher = self.tmp_path / "cwd"
        cwd_launcher.mkdir(parents=True)
        try:
            (cwd_launcher / "launcher").symlink_to(cfg_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            # On Windows without privilege, fall back to copying.
            import shutil
            shutil.copytree(cfg_dir, cwd_launcher / "launcher")

        self.app = HeadlessAppContext(str(cwd_launcher))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_user_env_vars_present_in_spawn_env(self):
        from core.launcher_cmd import build_launch_params
        cmd, env, run_cwd, py, main = build_launch_params(self.app)
        self.assertEqual(env.get("POLARS_SKIP_CPU_CHECK"), "1")
        self.assertEqual(env.get("MY_VAR"), "foo")

    def test_invalid_segments_are_silently_skipped(self):
        self.app.user_env_vars.set("1FOO=bar, GOOD=ok, =orphan")
        from core.launcher_cmd import build_launch_params
        _, env, *_ = build_launch_params(self.app)
        self.assertNotIn("1FOO", env)
        self.assertNotIn("", env)
        self.assertEqual(env.get("GOOD"), "ok")

    def test_empty_user_env_vars_leaves_spawn_env_alone(self):
        self.app.user_env_vars.set("")
        from core.launcher_cmd import build_launch_params
        _, env, *_ = build_launch_params(self.app)
        # Only launcher's defaults may be present (HF_ENDPOINT/PATH etc.);
        # none of them are user-supplied, and POLARS_SKIP_CPU_CHECK should NOT exist.
        self.assertNotIn("POLARS_SKIP_CPU_CHECK", env)
        self.assertNotIn("MY_VAR", env)

    def test_user_env_vars_override_launcher_default_endpoint(self):
        # If user sets HF_ENDPOINT, it should win over the launcher's HF mirror logic.
        # Since app.selected_hf_mirror is empty (default), the launcher would NOT inject
        # HF_ENDPOINT on its own. Use GIT_PYTHON_GIT_EXECUTABLE instead: the launcher
        # only sets it when git_cmd is truthy and != "git", which it isn't here.
        # So we just assert user vars flow through regardless.
        self.app.user_env_vars.set("HF_ENDPOINT=https://user.example.com")
        from core.launcher_cmd import build_launch_params
        _, env, *_ = build_launch_params(self.app)
        self.assertEqual(env.get("HF_ENDPOINT"), "https://user.example.com")


class TestBuildLaunchParamsUsesActiveEnvironment(unittest.TestCase):
    """多环境支持：build_launch_params 应该用当前激活环境的路径。"""

    def setUp(self):
        import shutil
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)

        # 造两个独立的 ComfyUI 安装
        self.env_a_root = self.tmp_path / "env_a"
        self.env_a_py = self.env_a_root / "python_embeded" / "python.exe"
        _make_fake_comfy_install(self.env_a_root, self.env_a_py)

        self.env_b_root = self.tmp_path / "env_b"
        self.env_b_py = self.env_b_root / "python_embeded" / "python.exe"
        _make_fake_comfy_install(self.env_b_root, self.env_b_py)

        cfg_dir = self.tmp_path / "launcher"
        cfg_dir.mkdir(parents=True)
        cfg_file = cfg_dir / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "launch_options": {
                        "default_compute_mode": "cpu",
                        "default_port": "8188",
                        "extra_args": "",
                        "env_vars": "",
                    },
                    "environments": [
                        {
                            "id": "env_a",
                            "name": "环境A",
                            "comfyui_root": str(self.env_a_root),
                            "python_path": str(self.env_a_py),
                        },
                        {
                            "id": "env_b",
                            "name": "环境B",
                            "comfyui_root": str(self.env_b_root),
                            "python_path": str(self.env_b_py),
                        },
                    ],
                    "active_env_id": "env_b",  # 激活的是 B
                    "proxy_settings": {},
                }
            ),
            encoding="utf-8",
        )
        cwd_launcher = self.tmp_path / "cwd"
        cwd_launcher.mkdir(parents=True)
        try:
            (cwd_launcher / "launcher").symlink_to(cfg_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            shutil.copytree(cfg_dir, cwd_launcher / "launcher")
        self.app = HeadlessAppContext(str(cwd_launcher))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_uses_active_environment_paths(self):
        """active_env_id=env_b → cmd 用 env_b 的 python + main.py。"""
        from core.launcher_cmd import build_launch_params
        cmd, env, run_cwd, py, main = build_launch_params(self.app)
        self.assertEqual(str(py), str(self.env_b_py.resolve()))
        self.assertEqual(str(main), str((self.env_b_root / "ComfyUI" / "main.py").resolve()))

    def test_switching_active_env_changes_paths(self):
        """切到 env_a 后，路径跟着变。"""
        from core.launcher_cmd import build_launch_params
        self.app.config["active_env_id"] = "env_a"
        cmd, env, run_cwd, py, main = build_launch_params(self.app)
        self.assertEqual(str(py), str(self.env_a_py.resolve()))
        self.assertEqual(str(main), str((self.env_a_root / "ComfyUI" / "main.py").resolve()))

    def test_does_not_mutate_config_on_launch(self):
        """build_launch_params 不能把解析后的绝对路径回写 config（多环境污染防护）。"""
        from core.launcher_cmd import build_launch_params
        original_python_path = self.env_b_py
        build_launch_params(self.app)
        # environment 对象里的 python_path 不应被改写
        env_b = next(e for e in self.app.config["environments"] if e["id"] == "env_b")
        self.assertEqual(env_b["python_path"], str(original_python_path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
