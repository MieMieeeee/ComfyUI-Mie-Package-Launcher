"""版本号唯一事实源：core/version.py 的 LAUNCHER_VERSION。

回归背景：版本号曾存放在生成的 build_parameters.json 里，root 与
launcher/ 两份副本会各自漂移（v1.0.17 vs v1.0.16）。现改为代码常量
（编译期随代码打进 exe），build_parameters.json 只保留编译脚本自动
插入的元数据（built_at/suffix/mode/builder/channel）。
"""
import json
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from core.version import LAUNCHER_VERSION


class TestVersionSingleSource(unittest.TestCase):
    def test_version_format(self):
        self.assertRegex(LAUNCHER_VERSION, r"^v\d+\.\d+\.\d+$")

    def test_cmd_info_resolves_constant(self):
        from core.cli.cmd_info import _resolve_version
        self.assertEqual(_resolve_version(), LAUNCHER_VERSION)

    def test_crash_log_version_reads_constant(self):
        from utils.logging import _read_build_version
        self.assertEqual(_read_build_version(Path.cwd()), LAUNCHER_VERSION)

    def test_update_service_current_version_is_constant(self):
        from services.launcher_update_service import LauncherUpdateService
        svc = LauncherUpdateService(MagicMock())
        self.assertEqual(svc.get_current_version(), LAUNCHER_VERSION)

    def test_build_parameters_no_version_key(self):
        """仓库内的 build_parameters.json 不得再携带 version（防回归）。"""
        bp = PROJECT_ROOT / "build_parameters.json"
        data = json.loads(bp.read_text(encoding="utf-8"))
        self.assertNotIn(
            "version", data,
            "build_parameters.json 不应携带 version——版本号唯一事实源是 "
            "core/version.py（编译脚本 update_build_parameters 会自动清洗）",
        )
        # 自动插入的元数据字段仍在
        for key in ("suffix", "mode", "built_at", "builder", "channel"):
            self.assertIn(key, data)


if __name__ == "__main__":
    unittest.main()
