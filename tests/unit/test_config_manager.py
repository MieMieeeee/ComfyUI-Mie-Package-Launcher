import builtins
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.manager import ConfigManager


class TestConfigManagerCharacterization(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_file = Path(self.temp_dir.name) / "launcher" / "config.json"
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_json(self, data):
        self.config_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read_json(self):
        return json.loads(self.config_file.read_text(encoding="utf-8"))

    def test_save_then_load_returns_equivalent_config(self):
        manager = ConfigManager(self.config_file, self.logger)
        config_data = manager.get_default_config()
        config_data["launch_options"]["default_compute_mode"] = "cpu"
        config_data["custom_top_level"] = {"keep": True}
        config_data["proxy_settings"]["custom_proxy_key"] = "https://example.com/proxy"

        saved = manager.save_config(config_data)
        loaded = ConfigManager(self.config_file, self.logger).load_config()

        self.assertEqual(saved, config_data)
        self.assertEqual(loaded, config_data)
        self.assertEqual(self.read_json(), config_data)

    def test_default_config_includes_version_preferences_background_fetch_delay(self):
        manager = ConfigManager(self.config_file, self.logger)
        cfg = manager.get_default_config()
        vp = cfg.get("version_preferences", {})
        self.assertEqual(vp.get("background_fetch_delay_seconds"), 180)

    def test_load_config_falls_back_to_defaults_for_corrupt_json_without_overwriting_file(
        self,
    ):
        self.config_file.write_text('{"broken": ', encoding="utf-8")

        manager = ConfigManager(self.config_file, self.logger)
        loaded = manager.load_config()

        self.assertEqual(loaded, manager.get_default_config())
        self.assertEqual(self.config_file.read_text(encoding="utf-8"), '{"broken": ')
        self.logger.warning.assert_called()

    def test_load_config_migrates_legacy_hf_mirror_and_normalizes_proxy_urls(self):
        self.write_json(
            {
                "paths": {
                    "comfyui_root": ".",
                    "hf_mirror": "legacy-hf-mode",
                },
                "proxy_settings": {
                    "git_proxy_url": "  `https://git.example.com/`  ",
                    "pypi_proxy_url": "\n`https://pypi.example.com/simple/`\t",
                    "hf_mirror_url": "  `https://hf.example.com`  ",
                },
            }
        )

        loaded = ConfigManager(self.config_file, self.logger).load_config()
        persisted = self.read_json()

        for config_data in (loaded, persisted):
            self.assertEqual(
                config_data["proxy_settings"]["hf_mirror_mode"], "legacy-hf-mode"
            )
            self.assertEqual(
                config_data["proxy_settings"]["git_proxy_url"],
                "https://git.example.com/",
            )
            self.assertEqual(
                config_data["proxy_settings"]["pypi_proxy_url"],
                "https://pypi.example.com/simple/",
            )
            self.assertEqual(
                config_data["proxy_settings"]["hf_mirror_url"], "https://hf.example.com"
            )
            self.assertNotIn("hf_mirror", config_data["paths"])

    def test_load_config_preserves_unknown_keys_after_normalization_save(self):
        self.write_json(
            {
                "paths": {
                    "comfyui_root": ".",
                    "hf_mirror": "legacy-mode",
                },
                "proxy_settings": {
                    "git_proxy_url": " https://git.example.com/ ",
                    "custom_nested": {"keep": [1, 2, 3]},
                },
                "unknown_top_level": {"hello": "world"},
            }
        )

        loaded = ConfigManager(self.config_file, self.logger).load_config()
        persisted = self.read_json()

        self.assertEqual(loaded["unknown_top_level"], {"hello": "world"})
        self.assertEqual(loaded["proxy_settings"]["custom_nested"], {"keep": [1, 2, 3]})
        self.assertEqual(persisted["unknown_top_level"], {"hello": "world"})
        self.assertEqual(
            persisted["proxy_settings"]["custom_nested"], {"keep": [1, 2, 3]}
        )

    def test_load_config_logs_permission_error_and_leaves_existing_file_unchanged(self):
        original_data = {
            "launch_options": {"default_port": "9000"},
            "proxy_settings": {},
        }
        self.write_json(original_data)
        original_text = self.config_file.read_text(encoding="utf-8")

        def guarded_open(file, mode="r", *args, **kwargs):
            if Path(file) == self.config_file and "r" in mode:
                raise PermissionError("read denied")
            return builtins.open(file, mode, *args, **kwargs)

        manager = ConfigManager(self.config_file, self.logger)
        with patch("config.manager.open", side_effect=guarded_open):
            loaded = manager.load_config()

        self.assertEqual(loaded, manager.get_default_config())
        self.assertEqual(self.config_file.read_text(encoding="utf-8"), original_text)
        self.logger.warning.assert_called()

    def test_save_config_logs_tempfile_permission_error_and_keeps_existing_file_contents(
        self,
    ):
        original_data = {
            "launch_options": {"default_port": "8188"},
            "proxy_settings": {},
        }
        self.write_json(original_data)
        updated_data = {
            "launch_options": {"default_port": "9000"},
            "proxy_settings": {"git_proxy_url": "https://new.example.com/"},
        }

        manager = ConfigManager(self.config_file, self.logger)
        with patch(
            "config.manager.tempfile.mkstemp",
            side_effect=PermissionError("write denied"),
        ):
            returned = manager.save_config(updated_data)

        self.assertEqual(returned, updated_data)
        self.assertEqual(manager.get_config(), updated_data)
        self.assertEqual(self.read_json(), original_data)
        self.logger.error.assert_called()

    def test_save_config_logs_temp_write_error_and_keeps_existing_file_contents(self):
        original_data = {
            "launch_options": {"default_port": "8188"},
            "proxy_settings": {},
        }
        self.write_json(original_data)
        updated_data = {
            "launch_options": {"default_port": "9002"},
            "proxy_settings": {"git_proxy_url": "https://temp-write.example.com/"},
        }

        manager = ConfigManager(self.config_file, self.logger)
        with patch(
            "config.manager.json.dump", side_effect=OSError("temp write failed")
        ):
            returned = manager.save_config(updated_data)

        self.assertEqual(returned, updated_data)
        self.assertEqual(manager.get_config(), updated_data)
        self.assertEqual(self.read_json(), original_data)
        self.logger.error.assert_called()

    def test_save_config_logs_replace_error_and_keeps_existing_file_contents(self):
        original_data = {
            "launch_options": {"default_port": "8188"},
            "proxy_settings": {},
        }
        self.write_json(original_data)
        updated_data = {
            "launch_options": {"default_port": "9003"},
            "proxy_settings": {"git_proxy_url": "https://replace.example.com/"},
        }

        manager = ConfigManager(self.config_file, self.logger)
        with patch(
            "config.manager.os.replace",
            side_effect=PermissionError("replace denied"),
        ):
            returned = manager.save_config(updated_data)

        self.assertEqual(returned, updated_data)
        self.assertEqual(manager.get_config(), updated_data)
        self.assertEqual(self.read_json(), original_data)
        self.logger.error.assert_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
