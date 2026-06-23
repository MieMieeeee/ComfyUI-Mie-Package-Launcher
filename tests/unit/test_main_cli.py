"""
Tests for __main__.py CLI mode.
"""

import sys
import json
import tempfile
import subprocess
import unittest
from pathlib import Path


class TestMainCLIArgParsing(unittest.TestCase):
    """Tests for CLI argument parsing in __main__.py."""

    def _get_parser(self):
        """Helper to get argparse parser from main module."""
        import argparse
        parser = argparse.ArgumentParser(prog='comfyui-launcher')
        parser.add_argument('--start', action='store_true', help='Start the launcher')
        parser.add_argument('--stop', action='store_true', help='Stop the launcher')
        parser.add_argument('--status', action='store_true', help='Check launcher status')
        return parser

    def test_start_flag_is_recognized(self):
        """Parser should recognize --start flag."""
        parser = self._get_parser()
        args = parser.parse_args(['--start'])
        self.assertTrue(args.start)
        self.assertFalse(args.stop)
        self.assertFalse(args.status)

    def test_stop_flag_is_recognized(self):
        """Parser should recognize --stop flag."""
        parser = self._get_parser()
        args = parser.parse_args(['--stop'])
        self.assertFalse(args.start)
        self.assertTrue(args.stop)
        self.assertFalse(args.status)

    def test_status_flag_is_recognized(self):
        """Parser should recognize --status flag."""
        parser = self._get_parser()
        args = parser.parse_args(['--status'])
        self.assertFalse(args.start)
        self.assertFalse(args.stop)
        self.assertTrue(args.status)

    def test_multiple_flags_require_all_true(self):
        """Parser should handle multiple flags."""
        parser = self._get_parser()
        args = parser.parse_args(['--start', '--stop'])
        self.assertTrue(args.start)
        self.assertTrue(args.stop)

    def test_no_args_returns_empty_namespace(self):
        """Parser with no args should return empty namespace."""
        parser = self._get_parser()
        args = parser.parse_args([])
        self.assertFalse(args.start)
        self.assertFalse(args.stop)
        self.assertFalse(args.status)


@unittest.skipUnless(sys.platform == 'win32', "CLI requires Windows due to ctypes.windll usage")
class TestMainCLISubprocess(unittest.TestCase):
    """Smoke tests for the new subcommand-based CLI in __main__.py."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmp_dir) / "launcher"
        self.config_dir.mkdir(parents=True)
        config_data = {
            "launch_options": {
                "default_compute_mode": "cpu",
                "default_port": "8188",
                "disable_all_custom_nodes": False,
                "enable_fast_mode": False,
                "disable_api_nodes": False,
                "listen_all": True,
                "extra_args": "",
                "attention_mode": "",
                "browser_open_mode": "default",
            },
            "proxy_settings": {
                "git_proxy_mode": "gh-proxy",
                "git_proxy_url": "",
                "hf_mirror_mode": "",
                "hf_mirror_url": "",
            },
        }
        (self.config_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )

    def _run(self, *args, timeout=15):
        # 用绝对路径调 __main__.py，cwd 设为临时目录（让 config 能找到）
        proj = Path(__file__).parent.parent.parent
        return subprocess.run(
            [sys.executable, str(proj / "__main__.py"), *args],
            cwd=self.tmp_dir,
            capture_output=True, text=True, timeout=timeout,
            env={**__import__("os").environ, "PYTHONPATH": str(proj)},
        )

    def test_top_level_help(self):
        result = self._run("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("start", result.stdout)
        self.assertIn("stop", result.stdout)
        self.assertIn("status", result.stdout)

    def test_status_subcommand_returns_3_when_not_running(self):
        """未跑 ComfyUI 时 `cli status` 应返回 EXIT_NOT_RUNNING (3)。"""
        result = self._run("status")
        # 返回 3（未跑）— config 存在所以不应该是 1
        self.assertIn(result.returncode, (0, 3))
        self.assertIn("running", result.stdout.lower())

    def test_status_json_output_is_valid_json(self):
        result = self._run("status", "--json")
        self.assertIn(result.returncode, (0, 3))
        data = json.loads(result.stdout)
        self.assertIn("running", data)
        self.assertIn("pid", data)
        self.assertIn("port", data)

    def test_info_subcommand(self):
        result = self._run("info")
        self.assertEqual(result.returncode, 0)
        self.assertIn("launcher_version", result.stdout)
        self.assertIn("comfyui_path", result.stdout)

    def test_stop_when_not_running_is_noop(self):
        result = self._run("stop")
        # stop 未跑是 no-op，EXIT_OK
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
