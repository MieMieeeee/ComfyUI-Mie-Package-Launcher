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
        # 同一实例再读一次（in-memory）：用户写入字段必须存活，迁移 setdefault
        # 不会污染「同一份」配置。
        same_instance_reloaded = service.get_config()
        reloaded_after_init = ConfigService(
            self.config_file, self.logger
        ).get_config()

        self.assertEqual(saved, config_data)
        # 同实例 reload：用户写入字段全部存活且类型一致。
        for k, v in config_data.items():
            self.assertEqual(same_instance_reloaded.get(k), v)
        # 重新构造的 ConfigService 会在 __init__ → load_config 末尾把
        # setdefault 字段（ui_settings 缩放/渲染模式/窗口几何、announcement、
        # package_update 等）写回磁盘。这是 ConfigManager.load_config 的预期
        # 行为：「运行过一次就把缺失的运行时字段补齐并落盘」。验证这条路径：
        for k, v in config_data.items():
            if k == "ui_settings":
                # ui_settings 是 dict，setdefault 在子层级加字段；用户写入的
                # 子键必须仍存在。
                for sk, sv in v.items():
                    self.assertEqual(
                        reloaded_after_init["ui_settings"].get(sk), sv
                    )
                continue
            self.assertEqual(reloaded_after_init.get(k), v)

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
