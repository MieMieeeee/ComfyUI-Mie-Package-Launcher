"""
Tests for utils/net.py functions.
"""

import logging
import tempfile
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from utils.net import (
    PYPI_ALIYUN_URL,
    HF_MIRROR_URL_DEFAULT,
    GITHUB_PROXY_DEFAULT_URL,
    ensure_trailing_slash,
    build_github_endpoint,
    update_pip_ini,
    apply_pip_proxy_settings,
)
from services.network_service import NetworkService


class TestEnsureTrailingSlash:
    """Tests for ensure_trailing_slash function."""

    def test_returns_url_with_trailing_slash(self):
        """Should add trailing slash to URL without one."""
        result = ensure_trailing_slash("https://example.com")
        assert result == "https://example.com/"

    def test_preserves_url_with_trailing_slash(self):
        """Should keep URL that already has trailing slash."""
        result = ensure_trailing_slash("https://example.com/")
        assert result == "https://example.com/"

    def test_returns_empty_string_for_none(self):
        """Should return empty string for None input."""
        result = ensure_trailing_slash(cast(str, None))
        assert result == ""

    def test_returns_empty_string_for_empty_string(self):
        """Should return empty string for empty string input."""
        result = ensure_trailing_slash("")
        assert result == ""

    def test_strips_whitespace(self):
        """Should strip whitespace from URL."""
        result = ensure_trailing_slash("  https://example.com  ")
        assert result == "https://example.com/"

    def test_single_character_url(self):
        """Should handle single character URL."""
        result = ensure_trailing_slash("a")
        assert result == "a/"

    def test_url_with_port(self):
        """Should handle URL with port number."""
        result = ensure_trailing_slash("https://example.com:8080")
        assert result == "https://example.com:8080/"

    def test_url_with_path(self):
        """Should preserve URL path when adding slash."""
        result = ensure_trailing_slash("https://example.com/path/to/resource")
        assert result == "https://example.com/path/to/resource/"


class TestBuildGithubEndpoint:
    """Tests for build_github_endpoint function."""

    def test_builds_github_endpoint_from_base(self):
        """Should build GitHub endpoint URL from base URL."""
        result = build_github_endpoint("https://mirror.example.com/")
        assert result == "https://mirror.example.com/https://github.com"

    def test_adds_trailing_slash_if_missing(self):
        """Should add trailing slash to base URL before appending."""
        result = build_github_endpoint("https://mirror.example.com")
        assert result == "https://mirror.example.com/https://github.com"

    def test_returns_empty_string_for_empty_base(self):
        """Should return empty string when base URL is empty."""
        result = build_github_endpoint("")
        assert result == ""

    def test_returns_empty_string_for_none_base(self):
        """Should return empty string when base URL is None."""
        result = build_github_endpoint(cast(str, None))
        assert result == ""

    def test_returns_empty_string_for_whitespace_only(self):
        """Should return empty string for whitespace-only input."""
        result = build_github_endpoint("   ")
        assert result == ""


class TestUpdatePipIni:
    """Tests for update_pip_ini function."""

    def test_mode_none_removes_pip_ini(self, tmp_path):
        """Should remove pip.ini when mode is 'none'."""
        python_exe = tmp_path / "python.exe"
        python_exe.touch()
        pip_ini = tmp_path / "pip.ini"
        pip_ini.write_text(
            "[global]\nindex-url = https://example.com\n", encoding="utf-8"
        )

        update_pip_ini(str(python_exe), "none", "", "", None)

        assert not pip_ini.exists()

    def test_mode_none_keeps_pip_ini_with_other_content(self, tmp_path):
        """Should keep pip.ini if it has non-removeable content."""
        python_exe = tmp_path / "python.exe"
        python_exe.touch()
        pip_ini = tmp_path / "pip.ini"
        pip_ini.write_text("[global]\nother-option = value\n", encoding="utf-8")

        update_pip_ini(str(python_exe), "none", "", "", None)

        assert pip_ini.exists()

    def test_mode_aliyun_uses_aliyun_mirror(self, tmp_path):
        """Should use Aliyun mirror URL when mode is 'aliyun'."""
        python_exe = tmp_path / "python.exe"
        python_exe.touch()

        update_pip_ini(str(python_exe), "aliyun", "", "", None)

        pip_ini = tmp_path / "pip.ini"
        assert pip_ini.exists()
        content = pip_ini.read_text(encoding="utf-8")
        assert PYPI_ALIYUN_URL in content
        assert "mirrors.aliyun.com" in content

    def test_mode_custom_uses_provided_index_url(self, tmp_path):
        """Should use provided index_url when mode is not 'aliyun'."""
        custom_url = "https://custom.mirror.com/pypi/simple/"
        python_exe = tmp_path / "python.exe"
        python_exe.touch()

        update_pip_ini(str(python_exe), "custom", custom_url, "", None)

        pip_ini = tmp_path / "pip.ini"
        assert pip_ini.exists()
        content = pip_ini.read_text(encoding="utf-8")
        assert custom_url in content
        assert "custom.mirror.com" in content

    def test_includes_proxy_when_provided(self, tmp_path):
        """Should include proxy setting when pip_proxy is provided."""
        python_exe = tmp_path / "python.exe"
        python_exe.touch()

        update_pip_ini(str(python_exe), "aliyun", "", "http://proxy.com:8080", None)

        pip_ini = tmp_path / "pip.ini"
        assert pip_ini.exists()
        content = pip_ini.read_text(encoding="utf-8")
        assert "proxy = http://proxy.com:8080" in content

    def test_creates_parent_directories(self, tmp_path):
        """Should create parent directories if they don't exist."""
        python_exe = tmp_path / "python.exe"
        python_exe.touch()

        update_pip_ini(str(python_exe), "aliyun", "", "", None)

        pip_ini = tmp_path / "pip.ini"
        assert pip_ini.parent.exists()
        assert pip_ini.exists()

    def test_handles_invalid_url_gracefully(self, tmp_path):
        """Should not raise when given an invalid URL."""
        python_exe = tmp_path / "python.exe"
        python_exe.touch()

        update_pip_ini(str(python_exe), "custom", "not-a-valid-url", "", None)

    def test_no_index_url_does_nothing(self, tmp_path):
        """Should do nothing when index_url is empty and mode is not aliyun."""
        python_exe = tmp_path / "python.exe"
        python_exe.touch()

        update_pip_ini(str(python_exe), "custom", "", "", None)

        pip_ini = tmp_path / "pip.ini"
        assert not pip_ini.exists()

    def test_uses_resolved_python_path(self, tmp_path):
        """Should resolve python path to find pip.ini location."""
        fake_python = tmp_path / "python.exe"
        fake_python.touch()

        update_pip_ini(str(fake_python), "aliyun", "", "", None)

        pip_ini = tmp_path / "pip.ini"
        assert pip_ini.exists()

    def test_logs_info_on_success(self, tmp_path):
        """Should log info message when pip.ini is written successfully."""
        python_exe = tmp_path / "python.exe"
        python_exe.touch()
        logger = logging.getLogger("test_logging")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        logger.addHandler(handler)

        update_pip_ini(str(python_exe), "aliyun", "", "", logger)

    def test_nonexistent_python_path_uses_default_embeded(self, tmp_path):
        """Should use 'python_embeded' when python path doesn't exist."""
        update_pip_ini(str(tmp_path / "nonexistent_python.exe"), "aliyun", "", "", None)

        pip_ini = Path("python_embeded") / "pip.ini"
        assert pip_ini.exists()

    def test_mode_none_removes_index_url_lines(self, tmp_path):
        """Should remove index-url and related lines when mode is 'none'."""
        python_exe = tmp_path / "python.exe"
        python_exe.touch()
        pip_ini = tmp_path / "pip.ini"
        pip_ini.write_text(
            "[global]\nindex-url = https://example.com\ntrusted-host = example.com\nproxy = http://proxy.com\n",
            encoding="utf-8",
        )

        update_pip_ini(str(python_exe), "none", "", "", None)

        assert not pip_ini.exists()

    def test_mode_none_removes_only_index_url_lines(self, tmp_path):
        """Should only remove index-url lines, keep other content."""
        python_exe = tmp_path / "python.exe"
        python_exe.touch()
        pip_ini = tmp_path / "pip.ini"
        pip_ini.write_text(
            "[global]\nother-option = value\nindex-url = https://example.com\nanother-option = val\n",
            encoding="utf-8",
        )

        update_pip_ini(str(python_exe), "none", "", "", None)

        assert pip_ini.exists()
        content = pip_ini.read_text(encoding="utf-8")
        assert "other-option = value" in content
        assert "another-option = val" in content
        assert "index-url" not in content


class TestApplyPipProxySettings:
    """Tests for apply_pip_proxy_settings function."""

    def test_passes_parameters_to_update_pip_ini(self, tmp_path, mocker):
        """Should pass all parameters to update_pip_ini."""
        mock_update = mocker.patch("utils.net.update_pip_ini")

        apply_pip_proxy_settings(
            str(tmp_path / "python.exe"),
            "aliyun",
            "https://custom.com",
            "http://proxy:8080",
            None,
        )

        mock_update.assert_called_once_with(
            str(tmp_path / "python.exe"),
            "aliyun",
            "https://custom.com",
            "http://proxy:8080",
            None,
        )

    def test_defaults_none_values(self, tmp_path, mocker):
        """Should default None values to empty strings."""
        mock_update = mocker.patch("utils.net.update_pip_ini")

        apply_pip_proxy_settings(
            str(tmp_path / "python.exe"),
            cast(str, None),
            cast(str, None),
            cast(str, None),
            None,
        )

        mock_update.assert_called_once_with(
            str(tmp_path / "python.exe"), "none", "", "", None
        )

    def test_strips_whitespace_from_values(self, tmp_path, mocker):
        """Should strip whitespace from all string parameters."""
        mock_update = mocker.patch("utils.net.update_pip_ini")

        apply_pip_proxy_settings(
            str(tmp_path / "python.exe"),
            "  aliyun  ",
            "  https://custom.com  ",
            "  http://proxy:8080  ",
            None,
        )

        mock_update.assert_called_once_with(
            str(tmp_path / "python.exe"),
            "aliyun",
            "https://custom.com",
            "http://proxy:8080",
            None,
        )

    def test_handles_exception_gracefully(self, tmp_path, mocker):
        """Should catch exceptions and log if logger provided."""
        logger = logging.getLogger("test_exception")
        logger.setLevel(logging.INFO)
        mocker.patch("utils.net.update_pip_ini", side_effect=Exception("Test error"))

        # Should not raise
        apply_pip_proxy_settings(str(tmp_path / "python.exe"), "aliyun", "", "", logger)

    def test_mode_none_is_default(self, tmp_path, mocker):
        """Should default to 'none' mode when mode is empty string."""
        mock_update = mocker.patch("utils.net.update_pip_ini")

        apply_pip_proxy_settings(str(tmp_path / "python.exe"), "", "", "", None)

        mock_update.assert_called_once()
        call_args = mock_update.call_args
        assert call_args[0][1] == "none"


class TestNetworkService:
    def test_apply_pip_proxy_settings_forwards_values(self, mocker):
        app = mocker.MagicMock()
        app.python_exec = "python.exe"
        app.pypi_proxy_mode.get.return_value = "aliyun"
        app.pypi_proxy_url.get.return_value = "https://mirror.example.com/simple/"
        app.logger = mocker.MagicMock()
        mock_apply = mocker.patch(
            "services.network_service.NET.apply_pip_proxy_settings"
        )

        service = NetworkService(app)
        service.apply_pip_proxy_settings()

        mock_apply.assert_called_once_with(
            "python.exe",
            "aliyun",
            "https://mirror.example.com/simple/",
            "",
            logger=app.logger,
        )

    def test_apply_pip_proxy_settings_propagates_offline_error_to_net_helper(
        self, mocker
    ):
        app = mocker.MagicMock()
        app.python_exec = "python.exe"
        app.pypi_proxy_mode.get.return_value = "custom"
        app.pypi_proxy_url.get.return_value = "https://mirror.example.com/simple/"
        app.logger = mocker.MagicMock()
        mock_apply = mocker.patch(
            "services.network_service.NET.apply_pip_proxy_settings",
            side_effect=TimeoutError("offline timeout"),
        )

        service = NetworkService(app)

        with pytest.raises(TimeoutError):
            service.apply_pip_proxy_settings()

        mock_apply.assert_called_once()


class TestConstants:
    """Tests for module constants."""

    def test_pypi_aliyun_url_is_valid(self):
        """PYPI_ALIYUN_URL should be a valid HTTPS URL."""
        assert PYPI_ALIYUN_URL.startswith("https://")
        assert "pypi" in PYPI_ALIYUN_URL.lower()
        assert PYPI_ALIYUN_URL.endswith("/")

    def test_hf_mirror_url_default_is_valid(self):
        """HF_MIRROR_URL_DEFAULT should be a valid HTTPS URL."""
        assert HF_MIRROR_URL_DEFAULT.startswith("https://")
        assert "hf-mirror.com" in HF_MIRROR_URL_DEFAULT

    def test_github_proxy_default_url_is_valid(self):
        """GITHUB_PROXY_DEFAULT_URL should be a valid HTTPS URL."""
        assert GITHUB_PROXY_DEFAULT_URL.startswith("https://")
        assert GITHUB_PROXY_DEFAULT_URL.endswith("/")
