"""
Tests for services/launcher_update_service.py - RED phase TDD.
These tests define expected behavior for dual-channel update system.

RED phase: Tests are written BEFORE implementation to define requirements.
These tests should FAIL until the feature is properly implemented.
"""

import hashlib
import json
import os
import tempfile
import unittest
from email.message import Message
from typing import cast
from urllib.error import HTTPError, URLError
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestLauncherUpdateServiceChannel(unittest.TestCase):
    """Test stable vs test channel selection in LauncherUpdateService."""

    def setUp(self):
        """Set up test fixtures with temp directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.mock_app = MagicMock()
        self.mock_app.logger = MagicMock()

    def tearDown(self):
        """Clean up temp directory."""
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stable_channel_uses_correct_url(self):
        """Stable channel should use launcher/updates/index.json."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # Should have UPDATE_SOURCES containing stable channel URL
        stable_url = "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/updates/index.json"

        # The service should have a way to select stable channel
        self.assertIn(stable_url, service.UPDATE_SOURCES)

        # Should be able to get the stable channel URL
        self.assertTrue(hasattr(service, "get_stable_channel_url"))
        self.assertEqual(service.get_stable_channel_url(), stable_url)

    def test_test_channel_uses_correct_url(self):
        """Test channel should use launcher/updates/test/index.json."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # Should have a test channel URL
        test_url = "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/updates/test/index.json"

        # Should be able to get the test channel URL
        self.assertTrue(hasattr(service, "get_test_channel_url"))
        self.assertEqual(service.get_test_channel_url(), test_url)

    def test_set_channel_switches_update_source(self):
        """Setting channel should switch the UPDATE_SOURCES used."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        stable_url = "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/updates/index.json"
        test_url = "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/updates/test/index.json"

        # Should be able to set channel to 'stable'
        service.set_channel("stable")
        self.assertEqual(service.get_stable_channel_url(), stable_url)

        # Should be able to set channel to 'test'
        service.set_channel("test")
        self.assertEqual(service.get_test_channel_url(), test_url)

    def test_default_channel_is_stable(self):
        """Default channel should be stable."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # Default channel should be stable
        self.assertTrue(hasattr(service, "get_current_channel"))
        self.assertEqual(service.get_current_channel(), "stable")


class TestLauncherUpdateServiceUpgrade(unittest.TestCase):
    """Test version comparison logic in LauncherUpdateService."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_app = MagicMock()
        self.mock_app.logger = MagicMock()

    def test_version_tuple_basic_comparison(self):
        """_version_tuple should correctly compare semantic versions."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # v1.0.10 > v1.0.9
        tuple_1_0_10 = service._version_tuple("v1.0.10")
        tuple_1_0_9 = service._version_tuple("v1.0.9")
        self.assertGreater(tuple_1_0_10, tuple_1_0_9)

        # v1.0.9 < v1.0.10
        self.assertLess(tuple_1_0_9, tuple_1_0_10)

        # v1.0.10 > v1.0.9 (without v prefix)
        tuple_1_0_10_no_v = service._version_tuple("1.0.10")
        tuple_1_0_9_no_v = service._version_tuple("1.0.9")
        self.assertGreater(tuple_1_0_10_no_v, tuple_1_0_9_no_v)

    def test_version_tuple_three_component_validation(self):
        """_version_tuple should return 3-component tuples."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # Single component
        result = service._version_tuple("1")
        self.assertEqual(len(result), 3)
        self.assertEqual(result, (1, 0, 0))

        # Two components
        result = service._version_tuple("1.2")
        self.assertEqual(len(result), 3)
        self.assertEqual(result, (1, 2, 0))

        # Three components
        result = service._version_tuple("1.2.3")
        self.assertEqual(len(result), 3)
        self.assertEqual(result, (1, 2, 3))

        # Four components (should truncate to 3)
        result = service._version_tuple("1.2.3.4")
        self.assertEqual(len(result), 3)
        self.assertEqual(result, (1, 2, 3))

    def test_version_tuple_beta_less_than_stable(self):
        """Beta versions should be less than stable versions."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # v1.0.9-beta < v1.0.9 (stable)
        tuple_beta = service._version_tuple("v1.0.9-beta")
        tuple_stable = service._version_tuple("v1.0.9")
        self.assertLess(
            tuple_beta, tuple_stable, "Beta version should be less than stable version"
        )

        # v1.0.10-beta < v1.0.10 (stable)
        tuple_beta_10 = service._version_tuple("v1.0.10-beta")
        tuple_stable_10 = service._version_tuple("v1.0.10")
        self.assertLess(
            tuple_beta_10,
            tuple_stable_10,
            "Beta version should be less than stable version",
        )

    def test_version_tuple_prerelease_flag_handling(self):
        """Prerelease versions should have proper prerelease flag handling."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # Alpha should be less than beta which should be less than stable
        tuple_alpha = service._version_tuple("v1.0.0-alpha")
        tuple_beta = service._version_tuple("v1.0.0-beta")
        tuple_rc = service._version_tuple("v1.0.0-rc")
        tuple_stable = service._version_tuple("v1.0.0")

        self.assertLess(tuple_alpha, tuple_beta)
        self.assertLess(tuple_beta, tuple_rc)
        self.assertLess(tuple_rc, tuple_stable)

    def test_version_tuple_invalid_version_returns_zeros(self):
        """Invalid version strings should return (0, 0, 0)."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # Empty string
        result = service._version_tuple("")
        self.assertEqual(result, (0, 0, 0))

        # None
        result = service._version_tuple(cast(str, None))
        self.assertEqual(result, (0, 0, 0))

        # Random string
        result = service._version_tuple("not-a-version")
        self.assertEqual(result, (0, 0, 0))

    def test_version_tuple_case_insensitive_v_prefix(self):
        """V prefix should be case insensitive."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        lower_v = service._version_tuple("v1.0.0")
        upper_v = service._version_tuple("V1.0.0")

        self.assertEqual(lower_v, upper_v)


class TestUpgradeExeScript(unittest.TestCase):
    """Test upgrade script generation and execution."""

    def setUp(self):
        """Set up test fixtures with temp directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.mock_app = MagicMock()
        self.mock_app.logger = MagicMock()

    def tearDown(self):
        """Clean up temp directory."""
        import shutil

        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sha256_calculation(self):
        """SHA256 calculation should produce correct hash."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # Create a test file
        test_file = Path(self.temp_dir) / "test.exe"
        test_content = b"test content for hashing"
        test_file.write_bytes(test_content)

        # Calculate expected SHA256
        expected_hash = hashlib.sha256(test_content).hexdigest()

        # Calculate using service method
        self.assertTrue(hasattr(service, "calculate_sha256"))
        calculated_hash = service.calculate_sha256(str(test_file))

        self.assertEqual(calculated_hash, expected_hash)

    def test_read_version_from_build_parameters(self):
        """Should read version from build_parameters.json."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # Create a mock build_parameters.json
        build_params = {
            "version": "v1.2.3",
            "build_number": "456",
            "build_date": "2024-01-01",
        }

        # Test reading from file
        config_dir = Path(self.temp_dir)
        build_params_file = config_dir / "build_parameters.json"
        build_params_file.write_text(json.dumps(build_params), encoding="utf-8")

        # Should be able to read version
        self.assertTrue(hasattr(service, "read_version_from_file"))
        version = service.read_version_from_file(str(build_params_file))
        self.assertEqual(version, "v1.2.3")

    def test_build_parameters_multiple_locations(self):
        """Should find build_parameters.json in multiple candidate locations."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # Create build_parameters.json in one of the candidate locations
        # The service checks: cwd, cwd/launcher, sys.executable parent
        candidates = [
            Path.cwd() / "build_parameters.json",
            Path.cwd() / "launcher" / "build_parameters.json",
        ]

        # Find one that exists or create it in temp
        build_params = {"version": "v2.0.0"}

        # Use the temp dir as cwd
        original_cwd = os.getcwd()
        try:
            os.chdir(self.temp_dir)

            # Create launcher subdirectory with build_parameters.json
            launcher_dir = Path(self.temp_dir) / "launcher"
            launcher_dir.mkdir(exist_ok=True)
            bp_file = launcher_dir / "build_parameters.json"
            bp_file.write_text(json.dumps(build_params), encoding="utf-8")

            # Service should find it
            service_with_new_cwd = LauncherUpdateService(self.mock_app)
            version = service_with_new_cwd.get_current_version()

            self.assertEqual(version, "v2.0.0")
        finally:
            os.chdir(original_cwd)

    def test_prepare_update_creates_bat_script(self):
        """prepare_update should create a valid batch script."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        # Mock _get_update_dir and _get_bat_script
        update_dir = Path(self.temp_dir) / "update"
        update_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(service, "_get_update_dir", return_value=update_dir):
            with patch.object(
                service, "_get_bat_script", return_value=update_dir / "apply_update.bat"
            ):
                # Create a fake downloaded file
                downloaded_file = update_dir / "launcher_new.exe"
                downloaded_file.write_bytes(b"fake exe content")

                # Set last update info
                service._last_update_info = {
                    "latest": "v1.0.0",
                    "download_url": "http://example.com/download",
                }

                result = service.prepare_update(str(downloaded_file))

                self.assertTrue(result)

                # Check bat script was created
                bat_path = update_dir / "apply_update.bat"
                self.assertTrue(bat_path.exists())

                # Check bat script content
                bat_content = bat_path.read_text(encoding="utf-8")
                self.assertIn("copy /y", bat_content)
                self.assertIn(str(downloaded_file.resolve()), bat_content)

    def test_prepare_update_creates_pending_flag(self):
        """prepare_update should create pending_update.flag file."""
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        update_dir = Path(self.temp_dir) / "update"
        update_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(service, "_get_update_dir", return_value=update_dir):
            with patch.object(
                service, "_get_bat_script", return_value=update_dir / "apply_update.bat"
            ):
                with patch.object(
                    service,
                    "_get_pending_flag",
                    return_value=update_dir / "pending_update.flag",
                ):
                    downloaded_file = update_dir / "launcher_new.exe"
                    downloaded_file.write_bytes(b"fake exe content")

                    service._last_update_info = {"latest": "v1.0.0"}

                    service.prepare_update(str(downloaded_file))

                    flag_path = update_dir / "pending_update.flag"
                    self.assertTrue(flag_path.exists())

                    flag_data = json.loads(flag_path.read_text(encoding="utf-8"))
                    self.assertEqual(flag_data["new_version"], "v1.0.0")


class TestLauncherUpdateServiceCheckUpdate(unittest.TestCase):
    def setUp(self):
        self.mock_app = MagicMock()
        self.mock_app.logger = MagicMock()

    def _mock_response(self, payload: bytes):
        response = MagicMock()
        response.read.return_value = payload
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        return response

    def test_check_update_returns_not_configured_for_empty_payload(self):
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        with patch.object(service, "get_current_version", return_value="v1.0.0"):
            with patch(
                "services.launcher_update_service.urlopen",
                return_value=self._mock_response(b"{}"),
            ):
                result = service.check_update()

        self.assertEqual(result["has_update"], False)
        self.assertEqual(result["reason"], "not_configured")
        self.assertEqual(result["current"], "v1.0.0")
        self.assertIsNone(service._last_update_info)

    def test_check_update_returns_none_for_malformed_json(self):
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        with patch.object(service, "get_current_version", return_value="v1.0.0"):
            with patch(
                "services.launcher_update_service.urlopen",
                return_value=self._mock_response(b'{"latest_version":'),
            ):
                result = service.check_update()

        self.assertIsNone(result)
        self.assertIsNone(service._last_update_info)
        self.mock_app.logger.warning.assert_called()

    def test_check_update_returns_none_on_timeout(self):
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        with patch.object(service, "get_current_version", return_value="v1.0.0"):
            with patch(
                "services.launcher_update_service.urlopen",
                side_effect=URLError("timed out"),
            ):
                result = service.check_update()

        self.assertIsNone(result)
        self.assertIsNone(service._last_update_info)

    def test_check_update_returns_none_on_non_404_http_error(self):
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        with patch.object(service, "get_current_version", return_value="v1.0.0"):
            with patch(
                "services.launcher_update_service.urlopen",
                side_effect=HTTPError(
                    "https://example.com", 500, "server error", Message(), None
                ),
            ):
                result = service.check_update()

        self.assertIsNone(result)
        self.assertIsNone(service._last_update_info)

    def test_check_update_returns_not_configured_on_404(self):
        from services.launcher_update_service import LauncherUpdateService

        service = LauncherUpdateService(self.mock_app)

        with patch.object(service, "get_current_version", return_value="v1.0.0"):
            with patch(
                "services.launcher_update_service.urlopen",
                side_effect=HTTPError(
                    "https://example.com", 404, "not found", Message(), None
                ),
            ):
                result = service.check_update()

        self.assertEqual(result["has_update"], False)
        self.assertEqual(result["reason"], "not_configured")
        self.assertEqual(result["latest"], "v1.0.0")


class TestDownloadSha256Verification(unittest.TestCase):
    """TDD Round 1: download_update 必须校验 SHA256。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.mock_app = MagicMock()
        self.mock_app.logger = MagicMock()

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _mock_download_response(self, content: bytes, total_size: int = 0):
        """构造一个 mock HTTP 响应，read() 依次返回 chunk 然后 b''。"""
        resp = MagicMock()
        resp.headers = {"Content-Length": str(total_size or len(content))}
        resp.read.side_effect = [content, b""]
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_download_update_verifies_sha256_success(self):
        """SHA256 匹配时应返回文件路径。"""
        from services.launcher_update_service import LauncherUpdateService
        service = LauncherUpdateService(self.mock_app)

        content = b"fake exe content for sha256 test"
        expected_hash = hashlib.sha256(content).hexdigest()

        update_dir = Path(self.temp_dir)
        with patch.object(service, "_get_update_dir", return_value=update_dir):
            with patch("services.launcher_update_service.urlopen") as mock_urlopen:
                mock_urlopen.return_value = self._mock_download_response(content)
                result = service.download_update(
                    "http://example.com/test.exe",
                    expected_sha256=expected_hash,
                )

        self.assertIsNotNone(result)
        self.assertTrue(Path(result).exists())

    def test_download_update_rejects_sha256_mismatch(self):
        """SHA256 不匹配时应删除文件并返回 None。"""
        from services.launcher_update_service import LauncherUpdateService
        service = LauncherUpdateService(self.mock_app)

        content = b"fake exe content"
        wrong_hash = "0" * 64  # 明确错误的 hash

        update_dir = Path(self.temp_dir)
        with patch.object(service, "_get_update_dir", return_value=update_dir):
            with patch("services.launcher_update_service.urlopen") as mock_urlopen:
                mock_urlopen.return_value = self._mock_download_response(content)
                result = service.download_update(
                    "http://example.com/test.exe",
                    expected_sha256=wrong_hash,
                )

        self.assertIsNone(result)
        # 临时文件应该被删除
        self.assertFalse((update_dir / "launcher_new.exe").exists())
        # 应该记录错误日志
        self.mock_app.logger.error.assert_called()

    def test_download_update_skips_sha256_when_empty(self):
        """expected_sha256 为空时跳过校验（向后兼容）。"""
        from services.launcher_update_service import LauncherUpdateService
        service = LauncherUpdateService(self.mock_app)

        content = b"any content"

        update_dir = Path(self.temp_dir)
        with patch.object(service, "_get_update_dir", return_value=update_dir):
            with patch("services.launcher_update_service.urlopen") as mock_urlopen:
                mock_urlopen.return_value = self._mock_download_response(content)
                result = service.download_update(
                    "http://example.com/test.exe",
                    expected_sha256="",
                )

        self.assertIsNotNone(result)
        self.assertTrue(Path(result).exists())


class TestBatScriptHardening(unittest.TestCase):
    """TDD Round 3: batch 脚本必须检查 copy 错误并重试。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.mock_app = MagicMock()
        self.mock_app.logger = MagicMock()

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _prepare_service(self):
        from services.launcher_update_service import LauncherUpdateService
        service = LauncherUpdateService(self.mock_app)
        update_dir = Path(self.temp_dir) / "update"
        update_dir.mkdir(parents=True, exist_ok=True)
        downloaded_file = update_dir / "launcher_new.exe"
        downloaded_file.write_bytes(b"fake exe content")
        service._last_update_info = {"latest": "v1.0.1"}
        return service, update_dir, downloaded_file

    def test_prepare_update_bat_checks_errorlevel(self):
        """bat 脚本必须在 copy 后检查 errorlevel。"""
        service, update_dir, downloaded_file = self._prepare_service()

        with patch.object(service, "_get_update_dir", return_value=update_dir):
            with patch.object(service, "_get_bat_script", return_value=update_dir / "apply_update.bat"):
                with patch.object(service, "_get_pending_flag", return_value=update_dir / "pending_update.flag"):
                    service.prepare_update(str(downloaded_file))

        bat_content = (update_dir / "apply_update.bat").read_text(encoding="utf-8")
        self.assertIn("errorlevel", bat_content.lower())

    def test_prepare_update_bat_has_retry_on_copy_failure(self):
        """bat 脚本在 copy 失败后必须重试。"""
        service, update_dir, downloaded_file = self._prepare_service()

        with patch.object(service, "_get_update_dir", return_value=update_dir):
            with patch.object(service, "_get_bat_script", return_value=update_dir / "apply_update.bat"):
                with patch.object(service, "_get_pending_flag", return_value=update_dir / "pending_update.flag"):
                    service.prepare_update(str(downloaded_file))

        bat_content = (update_dir / "apply_update.bat").read_text(encoding="utf-8")
        # 应该有两次 copy 命令（初次 + 重试）
        self.assertGreaterEqual(bat_content.lower().count("copy /y"), 2)

    def test_prepare_update_bat_launches_old_exe_on_failure(self):
        """bat 脚本在重试仍失败时必须启动旧 exe（不损坏）。"""
        service, update_dir, downloaded_file = self._prepare_service()

        with patch.object(service, "_get_update_dir", return_value=update_dir):
            with patch.object(service, "_get_bat_script", return_value=update_dir / "apply_update.bat"):
                with patch.object(service, "_get_pending_flag", return_value=update_dir / "pending_update.flag"):
                    service.prepare_update(str(downloaded_file))

        bat_content = (update_dir / "apply_update.bat").read_text(encoding="utf-8")
        # 失败路径里应该有 start 命令启动旧 exe
        # 找第二个 start 命令（第一个可能在成功路径）
        lines = bat_content.splitlines()
        start_count = sum(1 for l in lines if l.strip().lower().startswith("start"))
        self.assertGreaterEqual(start_count, 2, "bat 应至少有 2 个 start 命令（成功路径 + 失败路径）")


if __name__ == "__main__":
    unittest.main()
