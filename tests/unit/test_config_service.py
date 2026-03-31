import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.config_service import ConfigService


class TestConfigServiceCharacterization(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_file = Path(self.temp_dir.name) / "launcher" / "config.json"
        self.logger = MagicMock()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_json(self, data):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read_json(self):
        return json.loads(self.config_file.read_text(encoding="utf-8"))

    def test_service_save_then_reload_returns_equivalent_config(self):
        service = ConfigService(self.config_file, self.logger)
        config_data = service.get_config()
        config_data["launch_options"]["default_compute_mode"] = "cpu"
        config_data["unknown_top_level"] = {"round_trip": True}
        config_data["proxy_settings"]["custom_proxy_key"] = "https://proxy.example.com"

        saved = service.save(config_data)
        reloaded = ConfigService(self.config_file, self.logger).load()

        self.assertEqual(saved, config_data)
        self.assertEqual(reloaded, config_data)
        self.assertEqual(self.read_json(), config_data)

    def test_service_load_applies_legacy_migration_and_url_normalization(self):
        self.write_json(
            {
                "paths": {"hf_mirror": "legacy-mode"},
                "proxy_settings": {
                    "git_proxy_url": " `https://git.example.com/` ",
                    "pypi_proxy_url": " `https://pypi.example.com/simple/` ",
                    "hf_mirror_url": " `https://hf.example.com` ",
                },
                "unknown_top_level": {"keep": "me"},
            }
        )

        loaded = ConfigService(self.config_file, self.logger).load()

        self.assertEqual(loaded["proxy_settings"]["hf_mirror_mode"], "legacy-mode")
        self.assertEqual(
            loaded["proxy_settings"]["git_proxy_url"], "https://git.example.com/"
        )
        self.assertEqual(
            loaded["proxy_settings"]["pypi_proxy_url"],
            "https://pypi.example.com/simple/",
        )
        self.assertEqual(
            loaded["proxy_settings"]["hf_mirror_url"], "https://hf.example.com"
        )
        self.assertNotIn("hf_mirror", loaded["paths"])
        self.assertEqual(loaded["unknown_top_level"], {"keep": "me"})

    def test_service_uses_default_config_for_corrupt_json(self):
        self.write_json({"launch_options": {"default_port": "9000"}})
        self.config_file.write_text("{broken json", encoding="utf-8")

        service = ConfigService(self.config_file, self.logger)

        self.assertEqual(service.get_config(), service.cm.get_default_config())
        self.logger.warning.assert_called()

    def test_service_save_returns_current_config_when_tempfile_permission_fails(self):
        service = ConfigService(self.config_file, self.logger)
        original_data = self.read_json()
        updated_data = service.get_config()
        updated_data["launch_options"]["default_port"] = "9001"

        with patch(
            "config.manager.tempfile.mkstemp",
            side_effect=PermissionError("write denied"),
        ):
            returned = service.save(updated_data)

        self.assertEqual(returned, updated_data)
        self.assertEqual(service.get_config(), updated_data)
        self.assertEqual(self.read_json(), original_data)
        self.logger.error.assert_called()

    def test_service_save_returns_current_config_when_temp_write_fails(self):
        service = ConfigService(self.config_file, self.logger)
        original_data = self.read_json()
        updated_data = service.get_config()
        updated_data["launch_options"]["default_port"] = "9002"

        with patch(
            "config.manager.json.dump", side_effect=OSError("temp write failed")
        ):
            returned = service.save(updated_data)

        self.assertEqual(returned, updated_data)
        self.assertEqual(service.get_config(), updated_data)
        self.assertEqual(self.read_json(), original_data)
        self.logger.error.assert_called()

    def test_service_save_returns_current_config_when_replace_fails(self):
        service = ConfigService(self.config_file, self.logger)
        original_data = self.read_json()
        updated_data = service.get_config()
        updated_data["launch_options"]["default_port"] = "9003"

        with patch(
            "config.manager.os.replace",
            side_effect=PermissionError("replace denied"),
        ):
            returned = service.save(updated_data)

        self.assertEqual(returned, updated_data)
        self.assertEqual(service.get_config(), updated_data)
        self.assertEqual(self.read_json(), original_data)
        self.logger.error.assert_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
