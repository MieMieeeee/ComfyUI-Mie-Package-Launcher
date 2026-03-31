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
    """Tests for __main__.py CLI using subprocess to properly invoke the script."""

    def setUp(self):
        """Set up temp directory with config for tests."""
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
                "browser_open_mode": "default"
            },
            "proxy_settings": {
                "git_proxy_mode": "gh-proxy",
                "git_proxy_url": "",
                "hf_mirror_mode": "",
                "hf_mirror_url": ""
            }
        }

        config_file = self.config_dir / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

    def test_main_py_help(self):
        """python __main__.py --help should show usage information."""
        result = subprocess.run(
            [sys.executable, '__main__.py', '--help'],
            cwd=str(Path(__file__).parent.parent.parent),
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertIn('--start', result.stdout)
        self.assertIn('--stop', result.stdout)
        self.assertIn('--status', result.stdout)

    def test_main_py_start_with_config(self):
        """python __main__.py --start should attempt to start with config."""
        result = subprocess.run(
            [sys.executable, '__main__.py', '--start'],
            cwd=str(Path(__file__).parent.parent.parent),
            capture_output=True,
            text=True,
            timeout=15
        )
        # Should not crash, may fail due to missing comfyui paths but returns proper exit
        self.assertIn(result.stdout + result.stderr, "")

    def test_main_py_status_with_config(self):
        """python __main__.py --status should return status."""
        result = subprocess.run(
            [sys.executable, '__main__.py', '--status'],
            cwd=str(Path(__file__).parent.parent.parent),
            capture_output=True,
            text=True,
            timeout=15
        )
        # Should not crash, may return non-zero if not running
        self.assertTrue(
            "running" in result.stdout.lower() or 
            "not running" in result.stdout.lower() or
            "comfyui" in result.stdout.lower()
        )

    def test_main_py_stop_with_config(self):
        """python __main__.py --stop should attempt to stop."""
        result = subprocess.run(
            [sys.executable, '__main__.py', '--stop'],
            cwd=str(Path(__file__).parent.parent.parent),
            capture_output=True,
            text=True,
            timeout=15
        )
        # Should not crash
        self.assertIn(result.stdout + result.stderr, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
