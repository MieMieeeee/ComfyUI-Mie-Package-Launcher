"""Tests for log package service."""
import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _make_app(comfyui_root: Path) -> MagicMock:
    """Create a mock app whose config resolves to the given comfyui root."""
    app = MagicMock()
    app.config.get.return_value = {"comfyui_root": str(comfyui_root)}
    return app


class TestCreateLogPackage:
    """create_log_package should bundle the available logs into a zip."""

    def test_writes_zip_with_all_three_files_when_all_exist(self, tmp_path, monkeypatch):
        from services.log_package_service import create_log_package

        # ComfyUI log
        comfy_log = tmp_path / "ComfyUI" / "user" / "comfyui.log"
        comfy_log.parent.mkdir(parents=True)
        comfy_log.write_text("comfy ui log content", encoding="utf-8")

        # Launcher log + config
        launcher_dir = tmp_path / "launcher"
        launcher_dir.mkdir()
        launcher_log = launcher_dir / "launcher.log"
        launcher_log.write_text("launcher log content", encoding="utf-8")
        config = tmp_path / "config.json"
        config.write_text('{"paths": {"comfyui_root": "."}}', encoding="utf-8")

        app = _make_app(tmp_path)
        monkeypatch.chdir(tmp_path)

        out = tmp_path / "out.zip"
        result = create_log_package(app, out)

        assert result == out
        assert out.exists()

        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            assert "comfyui.log" in names
            assert "launcher.log" in names
            assert "config.json" in names
            assert "manifest.txt" in names

            assert zf.read("comfyui.log").decode("utf-8") == "comfy ui log content"
            assert zf.read("launcher.log").decode("utf-8") == "launcher log content"
            assert b"comfyui_root" in zf.read("config.json")

    def test_skips_missing_files_but_still_writes_zip(self, tmp_path, monkeypatch):
        from services.log_package_service import create_log_package

        # Only launcher log exists
        launcher_dir = tmp_path / "launcher"
        launcher_dir.mkdir()
        launcher_log = launcher_dir / "launcher.log"
        launcher_log.write_text("launcher only", encoding="utf-8")

        app = _make_app(tmp_path)
        monkeypatch.chdir(tmp_path)

        out = tmp_path / "out.zip"
        create_log_package(app, out)

        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            assert "comfyui.log" not in names
            assert "launcher.log" in names
            assert "manifest.txt" in names
            manifest = zf.read("manifest.txt").decode("utf-8")
            assert "comfyui.log" in manifest
            assert "未找到" in manifest  # comfyui is missing

    def test_manifest_contains_env_metadata(self, tmp_path, monkeypatch):
        from services.log_package_service import create_log_package

        app = _make_app(tmp_path)
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "out.zip"
        create_log_package(app, out)

        with zipfile.ZipFile(out) as zf:
            manifest = zf.read("manifest.txt").decode("utf-8")
            assert "ComfyUI 启动器" in manifest
            assert "Python:" in manifest
            assert "系统:" in manifest

    def test_creates_output_parent_dir_if_missing(self, tmp_path, monkeypatch):
        from services.log_package_service import create_log_package

        app = _make_app(tmp_path)
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "deep" / "nested" / "logs.zip"
        create_log_package(app, out)
        assert out.exists()

    def test_overwrites_existing_zip(self, tmp_path, monkeypatch):
        from services.log_package_service import create_log_package

        app = _make_app(tmp_path)
        monkeypatch.chdir(tmp_path)
        out = tmp_path / "out.zip"
        out.write_bytes(b"OLD")

        create_log_package(app, out)
        # Should no longer contain "OLD"
        with zipfile.ZipFile(out) as zf:
            assert "OLD" not in zf.read("manifest.txt").decode("utf-8")


class TestResolveHelpers:
    """Helper resolvers should be tolerant to missing files and bad config."""

    def test_comfyui_log_returns_none_when_missing(self, tmp_path):
        from services.log_package_service import _resolve_comfyui_log
        app = _make_app(tmp_path)
        assert _resolve_comfyui_log(app) is None

    def test_comfyui_log_returns_none_when_config_breaks(self):
        from services.log_package_service import _resolve_comfyui_log
        app = MagicMock()
        app.config.get.side_effect = Exception("boom")
        assert _resolve_comfyui_log(app) is None

    def test_launcher_log_returns_none_when_missing(self, tmp_path, monkeypatch):
        from services.log_package_service import _resolve_launcher_log
        monkeypatch.chdir(tmp_path)
        assert _resolve_launcher_log(MagicMock()) is None

    def test_config_returns_none_when_missing(self, tmp_path, monkeypatch):
        from services.log_package_service import _resolve_config
        monkeypatch.chdir(tmp_path)
        assert _resolve_config(MagicMock()) is None
