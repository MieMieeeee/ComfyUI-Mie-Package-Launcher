"""
Tests for headless_app.py module.

Tests cover:
- StringVar: PyQt StringVar mimic with .get()/.set()
- BoolVar: PyQt BoolVar mimic with .get()/.set()
- _NoOpRoot: .after() that executes functions immediately
- _NoOpLogger: print-based logging fallback
- _VersionManagerProxy: proxy for version_manager attributes
- HeadlessAppContext: headless app context with same interface as PyQt app
- get_headless_app(): factory function
"""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from headless_app import (
    BoolVar,
    HeadlessAppContext,
    StringVar,
    _NoOpLogger,
    _NoOpRoot,
    _VersionManagerProxy,
    get_headless_app,
)


class TestStringVar(unittest.TestCase):
    """Tests for StringVar mimicking PyQt's StringVar."""

    def test_default_initialization(self):
        """StringVar should initialize with empty string by default."""
        var = StringVar()
        self.assertEqual(var.get(), "")
        self.assertIsInstance(var.get(), str)

    def test_initialization_with_value(self):
        """StringVar should initialize with provided string value."""
        var = StringVar("hello")
        self.assertEqual(var.get(), "hello")

    def test_set_updates_value(self):
        """StringVar.set() should update the internal value."""
        var = StringVar("initial")
        var.set("updated")
        self.assertEqual(var.get(), "updated")

    def test_set_returns_none(self):
        """StringVar.set() should return None."""
        var = StringVar()
        result = var.set("test")
        self.assertIsNone(result)

    def test_set_with_empty_string(self):
        """StringVar.set() should accept empty string."""
        var = StringVar("hello")
        var.set("")
        self.assertEqual(var.get(), "")

    def test_set_with_unicode(self):
        """StringVar should handle unicode strings."""
        var = StringVar()
        var.set("中文测试")
        self.assertEqual(var.get(), "中文测试")


class TestBoolVar(unittest.TestCase):
    """Tests for BoolVar mimicking PyQt's BoolVar."""

    def test_default_initialization(self):
        """BoolVar should initialize with False by default."""
        var = BoolVar()
        self.assertFalse(var.get())
        self.assertIsInstance(var.get(), bool)

    def test_initialization_with_true(self):
        """BoolVar should initialize with True when passed True."""
        var = BoolVar(True)
        self.assertTrue(var.get())

    def test_initialization_with_false(self):
        """BoolVar should initialize with False when passed False."""
        var = BoolVar(False)
        self.assertFalse(var.get())

    def test_initialization_with_int(self):
        """BoolVar should convert int to bool (non-zero is True)."""
        var = BoolVar(1)
        self.assertTrue(var.get())
        var_zero = BoolVar(0)
        self.assertFalse(var_zero.get())

    def test_initialization_with_string(self):
        """BoolVar should convert string to bool (non-empty is True)."""
        var_truthy = BoolVar("true")
        self.assertTrue(var_truthy.get())
        var_empty = BoolVar("")
        self.assertFalse(var_empty.get())

    def test_set_updates_value(self):
        """BoolVar.set() should update the internal value."""
        var = BoolVar(False)
        var.set(True)
        self.assertTrue(var.get())

    def test_set_with_bool_conversion(self):
        """BoolVar.set() should convert value to bool."""
        var = BoolVar(False)
        var.set(1)
        self.assertTrue(var.get())
        var.set(0)
        self.assertFalse(var.get())

    def test_set_returns_none(self):
        """BoolVar.set() should return None."""
        var = BoolVar()
        result = var.set(True)
        self.assertIsNone(result)


class TestNoOpRoot(unittest.TestCase):
    """Tests for _NoOpRoot with .after() method."""

    def test_after_executes_function_immediately(self):
        """_NoOpRoot.after() should execute the function immediately."""
        root = _NoOpRoot()
        executed = []

        def callback():
            executed.append(1)

        root.after(1000, callback)  # 1000ms delay ignored
        self.assertEqual(executed, [1])

    def test_after_passes_no_arguments(self):
        """_NoOpRoot.after() should call function with no args."""
        root = _NoOpRoot()
        result = []

        def callback():
            result.append("called")

        root.after(500, callback)
        self.assertEqual(result, ["called"])

    def test_after_returns_none(self):
        """_NoOpRoot.after() should return None."""
        root = _NoOpRoot()
        result = root.after(100, lambda: None)
        self.assertIsNone(result)


class TestNoOpLogger(unittest.TestCase):
    """Tests for _NoOpLogger using print as fallback."""

    def test_info_outputs_message(self):
        """_NoOpLogger.info() should print the message."""
        var = _NoOpLogger()
        # Should not raise, uses print
        var.info("test message")
        var.info("hello %s", "world")

    def test_warning_outputs_message(self):
        """_NoOpLogger.warning() should print with WARNING prefix."""
        var = _NoOpLogger()
        # Should not raise, uses print
        var.warning("warn message")
        var.warning("warning %s", "test")

    def test_error_outputs_message(self):
        """_NoOpLogger.error() should print with ERROR prefix."""
        var = _NoOpLogger()
        # Should not raise, uses print
        var.error("error message")
        var.error("error %s", "test")


class TestVersionManagerProxy(unittest.TestCase):
    """Tests for _VersionManagerProxy."""

    def test_initialization_with_defaults(self):
        """_VersionManagerProxy should use default proxy values."""
        config = {}
        proxy = _VersionManagerProxy(config)

        self.assertIsInstance(proxy.proxy_mode_var, StringVar)
        self.assertEqual(proxy.proxy_mode_var.get(), "gh-proxy")
        self.assertIsInstance(proxy.proxy_url_var, StringVar)
        self.assertEqual(proxy.proxy_url_var.get(), "")

    def test_initialization_with_custom_values(self):
        """_VersionManagerProxy should use config values when provided."""
        config = {
            "git_proxy_mode": "custom-proxy",
            "git_proxy_url": "https://custom.proxy.com",
        }
        proxy = _VersionManagerProxy(config)

        self.assertEqual(proxy.proxy_mode_var.get(), "custom-proxy")
        self.assertEqual(proxy.proxy_url_var.get(), "https://custom.proxy.com")

    def test_proxy_mode_var_is_string_var(self):
        """proxy_mode_var should be a StringVar instance."""
        proxy = _VersionManagerProxy({})
        self.assertIsInstance(proxy.proxy_mode_var, StringVar)

    def test_proxy_url_var_is_string_var(self):
        """proxy_url_var should be a StringVar instance."""
        proxy = _VersionManagerProxy({})
        self.assertIsInstance(proxy.proxy_url_var, StringVar)


class TestHeadlessAppContext(unittest.TestCase):
    """Tests for HeadlessAppContext main class."""

    def setUp(self):
        """Set up temp directory with config for each test."""
        import tempfile

        self.tmp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmp_dir) / "launcher"
        self.config_dir.mkdir(parents=True)

        self.config_data = {
            "launch_options": {
                "default_compute_mode": "cuda",
                "default_port": "8888",
                "disable_all_custom_nodes": True,
                "enable_fast_mode": True,
                "disable_api_nodes": True,
                "listen_all": False,
                "extra_args": "--verbose",
                "attention_mode": "--use-sage-attention",
                "browser_open_mode": "chrome",
            },
            "proxy_settings": {
                "git_proxy_mode": "gh-proxy",
                "git_proxy_url": "https://gh-proxy.com/",
                "hf_mirror_mode": "tuna",
                "hf_mirror_url": "https://mirrors.tuna.tsinghua.edu.cn",
            },
        }

        config_file = self.config_dir / "config.json"
        config_file.write_text(json.dumps(self.config_data), encoding="utf-8")

    def test_initialization_loads_config(self):
        """HeadlessAppContext should load config from file."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertEqual(
            context.config["launch_options"]["default_compute_mode"], "cuda"
        )

    def test_initialization_creates_string_vars(self):
        """HeadlessAppContext should create StringVar for string options."""
        context = HeadlessAppContext(self.tmp_dir)

        self.assertIsInstance(context.compute_mode, StringVar)
        self.assertIsInstance(context.vram_mode, StringVar)
        self.assertIsInstance(context.custom_port, StringVar)
        self.assertIsInstance(context.extra_launch_args, StringVar)
        self.assertIsInstance(context.attention_mode, StringVar)
        self.assertIsInstance(context.browser_open_mode, StringVar)

    def test_initialization_creates_bool_vars(self):
        """HeadlessAppContext should create BoolVar for boolean options."""
        context = HeadlessAppContext(self.tmp_dir)

        self.assertIsInstance(context.use_fast_mode, BoolVar)
        self.assertIsInstance(context.listen_all, BoolVar)
        self.assertIsInstance(context.disable_all_custom_nodes, BoolVar)
        self.assertIsInstance(context.disable_api_nodes, BoolVar)

    def test_compute_mode_default_value(self):
        """compute_mode should use default_compute_mode from config."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertEqual(context.compute_mode.get(), "cuda")

    def test_custom_port_default_value(self):
        """custom_port should use default_port from config."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertEqual(context.custom_port.get(), "8888")

    def test_use_fast_mode_default_value(self):
        """use_fast_mode should reflect enable_fast_mode from config."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertTrue(context.use_fast_mode.get())

    def test_listen_all_default_value(self):
        """listen_all should reflect listen_all from config."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertFalse(context.listen_all.get())

    def test_disable_all_custom_nodes_default_value(self):
        """disable_all_custom_nodes should reflect config value."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertTrue(context.disable_all_custom_nodes.get())

    def test_disable_api_nodes_default_value(self):
        """disable_api_nodes should reflect config value."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertTrue(context.disable_api_nodes.get())

    def test_extra_launch_args_default_value(self):
        """extra_launch_args should use extra_args from config."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertEqual(context.extra_launch_args.get(), "--verbose")

    def test_attention_mode_default_value(self):
        """attention_mode should use attention_mode from config."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertEqual(context.attention_mode.get(), "--use-sage-attention")

    def test_browser_open_mode_default_value(self):
        """browser_open_mode should use browser_open_mode from config."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertEqual(context.browser_open_mode.get(), "chrome")

    def test_hf_mirror_settings(self):
        """HF mirror settings should be properly initialized."""
        context = HeadlessAppContext(self.tmp_dir)

        self.assertIsInstance(context.selected_hf_mirror, StringVar)
        self.assertIsInstance(context.hf_mirror_url, StringVar)
        self.assertEqual(context.selected_hf_mirror.get(), "tuna")
        self.assertEqual(
            context.hf_mirror_url.get(), "https://mirrors.tuna.tsinghua.edu.cn"
        )

    def test_version_manager_proxy(self):
        """version_manager should be a _VersionManagerProxy instance."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertIsInstance(context.version_manager, _VersionManagerProxy)

    def test_logger_is_noop_logger(self):
        """logger should be a _NoOpLogger instance."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertIsInstance(context.logger, _NoOpLogger)

    def test_root_is_noop_root(self):
        """root should be a _NoOpRoot instance."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertIsInstance(context.root, _NoOpRoot)

    def test_ui_post_executes_callback_immediately(self):
        context = HeadlessAppContext(self.tmp_dir)
        calls = []

        context.ui_post(lambda: calls.append("posted"))

        self.assertEqual(calls, ["posted"])

    def test_launching_flag_initial_false(self):
        """_launching should be False initially."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertFalse(context._launching)

    def test_services_has_runtime(self):
        """services should have a runtime attribute."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertTrue(hasattr(context.services, "runtime"))

    def test_missing_config_raises_file_not_found_error(self):
        """HeadlessAppContext should raise FileNotFoundError if config missing."""
        import tempfile

        empty_dir = tempfile.mkdtemp()

        with self.assertRaises(FileNotFoundError) as ctx:
            HeadlessAppContext(empty_dir)

        self.assertIn("Config not found", str(ctx.exception))

    def test_save_config_returns_config(self):
        """save_config() should return the config dict."""
        context = HeadlessAppContext(self.tmp_dir)
        result = context.save_config()
        self.assertIsInstance(result, dict)
        self.assertIn("launch_options", result)

    def test_save_config_writes_to_file(self):
        """save_config() should write config to file."""
        context = HeadlessAppContext(self.tmp_dir)
        # Modify config directly (simulating config changes)
        context.config["launch_options"]["default_compute_mode"] = "cpu"

        context.save_config()

        # Read back from file
        config_file = self.config_dir / "config.json"
        saved_config = json.loads(config_file.read_text(encoding="utf-8"))
        self.assertEqual(saved_config["launch_options"]["default_compute_mode"], "cpu")

    def test_save_config_raises_on_temp_write_failure_and_keeps_existing_file(self):
        context = HeadlessAppContext(self.tmp_dir)
        config_file = self.config_dir / "config.json"
        original_text = config_file.read_text(encoding="utf-8")
        context.config["launch_options"]["default_compute_mode"] = "cpu"

        with patch(
            "config.manager.json.dump", side_effect=OSError("temp write failed")
        ):
            with self.assertRaises(OSError):
                context.save_config()

        self.assertEqual(config_file.read_text(encoding="utf-8"), original_text)

    def test_save_config_raises_on_replace_failure_and_keeps_existing_file(self):
        context = HeadlessAppContext(self.tmp_dir)
        config_file = self.config_dir / "config.json"
        original_text = config_file.read_text(encoding="utf-8")
        context.config["launch_options"]["default_compute_mode"] = "cpu"

        with patch(
            "config.manager.os.replace",
            side_effect=PermissionError("replace denied"),
        ):
            with self.assertRaises(PermissionError):
                context.save_config()

        self.assertEqual(config_file.read_text(encoding="utf-8"), original_text)

    def test_use_new_manager_default_false(self):
        """use_new_manager should default to False."""
        context = HeadlessAppContext(self.tmp_dir)
        self.assertIsInstance(context.use_new_manager, BoolVar)
        self.assertFalse(context.use_new_manager.get())


class TestGetHeadlessApp(unittest.TestCase):
    """Tests for get_headless_app factory function."""

    def setUp(self):
        """Set up temp directory with config."""
        import tempfile

        self.tmp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmp_dir) / "launcher"
        self.config_dir.mkdir(parents=True)

        config_data = {
            "launch_options": {"default_compute_mode": "cpu", "default_port": "8188"},
            "proxy_settings": {},
        }

        config_file = self.config_dir / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

    def test_returns_headless_app_context(self):
        """get_headless_app should return HeadlessAppContext instance."""
        result = get_headless_app(self.tmp_dir)
        self.assertIsInstance(result, HeadlessAppContext)

    def test_passes_cwd_to_context(self):
        """get_headless_app should pass cwd to HeadlessAppContext."""
        context = get_headless_app(self.tmp_dir)
        self.assertEqual(context._cwd, self.tmp_dir)

    def test_missing_cwd_raises_error(self):
        """get_headless_app should raise FileNotFoundError for missing cwd."""
        import tempfile

        empty_dir = tempfile.mkdtemp()

        with self.assertRaises(FileNotFoundError):
            get_headless_app(empty_dir)


if __name__ == "__main__":
    unittest.main(verbosity=2)
