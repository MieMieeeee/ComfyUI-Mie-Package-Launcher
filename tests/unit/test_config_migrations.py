"""Tests for config/migrations.py — 多环境迁移与解析。

覆盖：
- migrate_environments: 老 paths → environments[0]，幂等，active_env_id 失配修复
- resolve_active_paths: 命中 / 失配退回 / 回退老 paths / 全空兜底
- find_env / resolve_paths_for_env: CLI --env 解析
- ConfigManager 集成: load_config 触发迁移并落盘
- HeadlessAppContext 集成: CLI 路径也触发迁移
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from config.migrations import (
    find_env,
    make_env_id,
    migrate_environments,
    resolve_active_paths,
    resolve_paths_for_env,
)
from config.manager import ConfigManager
from headless_app import HeadlessAppContext


class TestMigrateEnvironments(unittest.TestCase):
    """migrate_environments 的纯函数测试。"""

    def test_migrates_legacy_paths_into_default_env(self):
        config = {"paths": {"comfyui_root": "E:/Comfy", "python_path": "E:/Comfy/py.exe"}}
        changed = migrate_environments(config)
        self.assertTrue(changed)
        self.assertEqual(len(config["environments"]), 1)
        env = config["environments"][0]
        self.assertEqual(env["id"], "env_default")
        self.assertEqual(env["name"], "默认环境")
        self.assertEqual(env["comfyui_root"], "E:/Comfy")
        self.assertEqual(env["python_path"], "E:/Comfy/py.exe")
        self.assertEqual(config["active_env_id"], "env_default")
        # 老 paths 段保留（作为回退）
        self.assertIn("paths", config)

    def test_idempotent_when_environments_already_present(self):
        config = {
            "environments": [{"id": "env_x", "name": "X", "comfyui_root": ".", "python_path": "py.exe"}],
            "active_env_id": "env_x",
        }
        changed = migrate_environments(config)
        self.assertFalse(changed)
        # 数据不变
        self.assertEqual(config["environments"][0]["id"], "env_x")

    def test_repairs_mismatched_active_env_id(self):
        config = {
            "environments": [
                {"id": "env_a", "name": "A", "comfyui_root": ".", "python_path": "py.exe"},
                {"id": "env_b", "name": "B", "comfyui_root": "/b", "python_path": "/b/py.exe"},
            ],
            "active_env_id": "env_missing",  # 指向不存在的 id
        }
        changed = migrate_environments(config)
        self.assertTrue(changed)
        # active_env_id 被修正为第一个
        self.assertEqual(config["active_env_id"], "env_a")

    def test_creates_empty_env_when_no_paths_and_no_environments(self):
        config = {"launch_options": {}}
        changed = migrate_environments(config)
        self.assertTrue(changed)
        self.assertEqual(len(config["environments"]), 1)
        self.assertEqual(config["environments"][0]["id"], "env_default")
        self.assertEqual(config["active_env_id"], "env_default")

    def test_non_dict_config_returns_false(self):
        self.assertFalse(migrate_environments(None))
        self.assertFalse(migrate_environments("not a dict"))


class TestResolveActivePaths(unittest.TestCase):
    """resolve_active_paths 的四条解析路径。"""

    def test_resolves_active_env_by_id(self):
        config = {
            "environments": [
                {"id": "env_a", "name": "A", "comfyui_root": "/a", "python_path": "/a/py.exe"},
                {"id": "env_b", "name": "B", "comfyui_root": "/b", "python_path": "/b/py.exe"},
            ],
            "active_env_id": "env_b",
        }
        paths = resolve_active_paths(config)
        self.assertEqual(paths["comfyui_root"], "/b")
        self.assertEqual(paths["python_path"], "/b/py.exe")

    def test_falls_back_to_first_when_active_id_mismatched(self):
        config = {
            "environments": [
                {"id": "env_a", "name": "A", "comfyui_root": "/a", "python_path": "/a/py.exe"},
            ],
            "active_env_id": "ghost",
        }
        paths = resolve_active_paths(config)
        self.assertEqual(paths["comfyui_root"], "/a")

    def test_falls_back_to_legacy_paths_when_no_environments(self):
        config = {"paths": {"comfyui_root": "E:/legacy", "python_path": "E:/legacy/py.exe"}}
        paths = resolve_active_paths(config)
        self.assertEqual(paths["comfyui_root"], "E:/legacy")
        self.assertEqual(paths["python_path"], "E:/legacy/py.exe")

    def test_minimal_default_when_completely_empty(self):
        paths = resolve_active_paths({})
        self.assertEqual(paths["comfyui_root"], ".")
        self.assertEqual(paths["python_path"], "python_embeded/python.exe")

    def test_non_dict_returns_minimal_default(self):
        paths = resolve_active_paths(None)
        self.assertIn("comfyui_root", paths)


class TestFindEnvAndResolveForEnv(unittest.TestCase):
    """CLI --env 解析：find_env / resolve_paths_for_env。"""

    def setUp(self):
        self.config = {
            "environments": [
                {"id": "env_a", "name": "A", "comfyui_root": "/a", "python_path": "/a/py.exe"},
                {"id": "env_b", "name": "B", "comfyui_root": "/b", "python_path": "/b/py.exe"},
            ],
            "active_env_id": "env_a",
        }

    def test_find_env_returns_matching_env(self):
        env = find_env(self.config, "env_b")
        self.assertIsNotNone(env)
        self.assertEqual(env["comfyui_root"], "/b")

    def test_find_env_returns_none_for_unknown_id(self):
        self.assertIsNone(find_env(self.config, "ghost"))
        self.assertIsNone(find_env(self.config, ""))

    def test_resolve_paths_for_env_hits(self):
        paths = resolve_paths_for_env(self.config, "env_b")
        self.assertEqual(paths["comfyui_root"], "/b")

    def test_resolve_paths_for_env_miss_falls_back_to_active(self):
        paths = resolve_paths_for_env(self.config, "ghost")
        # 退回激活环境 env_a
        self.assertEqual(paths["comfyui_root"], "/a")


class TestMakeEnvId(unittest.TestCase):
    """id 生成与唯一性。"""

    def test_generates_readable_id_from_name(self):
        self.assertEqual(make_env_id("ComfyUI V8", set()), "env_comfyui_v8")

    def test_appends_suffix_on_collision(self):
        existing = {"env_comfyui_v8"}
        self.assertEqual(make_env_id("ComfyUI V8", existing), "env_comfyui_v8_2")

    def test_handles_empty_and_non_ascii_name(self):
        # 空名和纯非 ASCII 名都被 _slugify 退回 "env"，最终都是 env_env
        self.assertEqual(make_env_id("", set()), "env_env")
        self.assertEqual(make_env_id("中文环境", set()), "env_env")


class TestConfigManagerIntegration(unittest.TestCase):
    """ConfigManager.load_config 触发迁移并落盘。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_file = Path(self.temp_dir.name) / "launcher" / "config.json"
        self.config_file.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_json(self, data):
        self.config_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read_json(self):
        return json.loads(self.config_file.read_text(encoding="utf-8"))

    def test_load_migrates_legacy_paths_to_environments_and_persists(self):
        self.write_json({
            "paths": {"comfyui_root": "E:/Comfy", "python_path": "E:/Comfy/py.exe"},
            "proxy_settings": {},
        })
        loaded = ConfigManager(self.config_file, MagicMock()).load_config()
        persisted = self.read_json()

        for cfg in (loaded, persisted):
            self.assertEqual(len(cfg["environments"]), 1)
            self.assertEqual(cfg["environments"][0]["comfyui_root"], "E:/Comfy")
            self.assertEqual(cfg["active_env_id"], "env_default")

    def test_load_preserves_existing_environments(self):
        self.write_json({
            "environments": [
                {"id": "env_a", "name": "A", "comfyui_root": "/a", "python_path": "/a/py.exe"},
                {"id": "env_b", "name": "B", "comfyui_root": "/b", "python_path": "/b/py.exe"},
            ],
            "active_env_id": "env_b",
            "proxy_settings": {},
        })
        loaded = ConfigManager(self.config_file, MagicMock()).load_config()
        self.assertEqual(len(loaded["environments"]), 2)
        self.assertEqual(loaded["active_env_id"], "env_b")


class TestHeadlessAppContextIntegration(unittest.TestCase):
    """HeadlessAppContext（CLI 路径）也触发迁移 —— 关键坑：不走 ConfigManager。"""

    def setUp(self):
        import tempfile
        self.tmp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmp_dir) / "launcher"
        self.config_dir.mkdir(parents=True)

    def test_cli_path_migrates_legacy_paths_on_init(self):
        config_data = {
            "paths": {"comfyui_root": "E:/CLI", "python_path": "E:/CLI/py.exe"},
            "proxy_settings": {},
        }
        (self.config_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )
        ctx = HeadlessAppContext(self.tmp_dir)
        # 内存里的 config 已迁移
        self.assertEqual(len(ctx.config["environments"]), 1)
        self.assertEqual(ctx.config["environments"][0]["comfyui_root"], "E:/CLI")
        self.assertEqual(ctx.config["active_env_id"], "env_default")
        # 落盘了
        persisted = json.loads((self.config_dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(len(persisted["environments"]), 1)

    def test_get_active_paths_returns_resolved_paths(self):
        config_data = {
            "environments": [
                {"id": "env_a", "name": "A", "comfyui_root": "/a", "python_path": "/a/py.exe"},
                {"id": "env_b", "name": "B", "comfyui_root": "/b", "python_path": "/b/py.exe"},
            ],
            "active_env_id": "env_b",
            "proxy_settings": {},
        }
        (self.config_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )
        ctx = HeadlessAppContext(self.tmp_dir)
        paths = ctx.get_active_paths()
        self.assertEqual(paths["comfyui_root"], "/b")
        self.assertEqual(paths["python_path"], "/b/py.exe")

    def test_get_active_paths_falls_back_to_legacy_paths(self):
        # 未迁移的老配置（模拟迁移失败兜底）
        config_data = {
            "paths": {"comfyui_root": "E:/legacy", "python_path": "E:/legacy/py.exe"},
            "environments": [],  # 空 environments 触发回退
            "proxy_settings": {},
        }
        (self.config_dir / "config.json").write_text(
            json.dumps(config_data), encoding="utf-8"
        )
        ctx = HeadlessAppContext(self.tmp_dir)
        # migrate_environments 会把空 environments 转成默认环境，
        # 所以这里实际上会迁移。验证迁移后仍指向 legacy 数据。
        paths = ctx.get_active_paths()
        self.assertEqual(paths["comfyui_root"], "E:/legacy")


if __name__ == "__main__":
    unittest.main(verbosity=2)
