# -*- coding: utf-8 -*-
"""Tests for PackageUpdatePage._on_load_file: 必须经 manifest.validate 才进 _set_manifest (issue 3)。

背景：
- _on_load_url / _on_load_paste 都先 svc().validate(manifest) 拦截坏 manifest
- _on_load_file 原本跳过 validate 直接 _set_manifest
- 修复：与 URL/粘贴入口对齐，加 validate 短路 → DialogHelper.show_error
"""
from unittest.mock import MagicMock, patch
import pytest

pytest.importorskip("PyQt5")


def _bad_manifest():
    return {
        "manifest_version": 99,
        "id": "bad",
        "name": "bad",
        "package_target": {"channel": "v9"},
        "items": [],
    }


def _good_manifest():
    return {
        "manifest_version": 1,
        "id": "good",
        "name": "good",
        "package_target": {"channel": "v9"},
        "items": [],
    }


def _make_page(monkeypatch):
    from PyQt5 import QtWidgets
    from PyQt5.QtWidgets import QApplication
    from ui_qt.pages.package_update_page import PackageUpdatePage
    app = QApplication.instance() or QApplication([])
    mock_app = MagicMock()
    mock_app.config = {}
    mock_app.get_active_paths = MagicMock(return_value={"comfyui_root": "F:/V9", "python_path": "python"})
    pkg_svc = MagicMock()
    mock_app.services.package = pkg_svc
    mock_app.services.model = None
    # theme_manager 用 MagicMock，但 _apply_initial_theme 会调到 styles.c.dark / colors
    # 这里直接 patch 掉 _apply_initial_theme 避免无意义的样式应用
    monkeypatch.setattr(PackageUpdatePage, "_apply_initial_theme", lambda self: None)
    # 用真实的 ThemeManager (ThemeStyles 内部 setStyleSheet 需要真实字符串)
    from ui_qt.theme_manager import ThemeManager
    page = PackageUpdatePage(mock_app, theme_manager=ThemeManager(dark=True))
    return page, pkg_svc


class TestOnLoadFileValidatesManifest:
    """_on_load_file 必须调 validate，坏 manifest 不进 _set_manifest。"""

    def test_bad_manifest_short_circuits_to_error_dialog(self, monkeypatch):
        page, pkg_svc = _make_page(monkeypatch)
        bad = _bad_manifest()
        pkg_svc.load_source.return_value = (bad, "F:/bad.json")
        pkg_svc.validate.return_value = (False, "manifest_version 超出支持范围")

        with patch("PyQt5.QtWidgets.QFileDialog.getOpenFileName", return_value=("F:/bad.json", "")), \
             patch("ui_qt.pages.package_update_page.DialogHelper.show_error") as mock_show, \
             patch.object(page, "_set_manifest") as mock_set:
            page._on_load_file()

        assert pkg_svc.validate.call_count == 1
        pkg_svc.validate.assert_called_with(bad)
        assert mock_show.call_count == 1
        args, _kwargs = mock_show.call_args
        assert args[1] == "manifest 无效"
        assert mock_set.call_count == 0

    def test_good_manifest_proceeds_to_set_manifest(self, monkeypatch):
        page, pkg_svc = _make_page(monkeypatch)
        good = _good_manifest()
        pkg_svc.load_source.return_value = (good, "F:/good.json")
        pkg_svc.validate.return_value = (True, None)

        with patch("PyQt5.QtWidgets.QFileDialog.getOpenFileName", return_value=("F:/good.json", "")), \
             patch.object(page, "_set_manifest") as mock_set:
            page._on_load_file()

        assert pkg_svc.validate.call_count == 1
        assert mock_set.call_count == 1
        args, _ = mock_set.call_args
        assert args[0] is good

    def test_sha256_mismatch_short_circuits(self, monkeypatch):
        page, pkg_svc = _make_page(monkeypatch)
        bad = _good_manifest()
        bad["sha256"] = "0" * 64
        pkg_svc.load_source.return_value = (bad, "F:/bad.json")
        pkg_svc.validate.return_value = (False, "sha256 不匹配")

        with patch("PyQt5.QtWidgets.QFileDialog.getOpenFileName", return_value=("F:/bad.json", "")), \
             patch("ui_qt.pages.package_update_page.DialogHelper.show_error") as mock_show, \
             patch.object(page, "_set_manifest") as mock_set:
            page._on_load_file()

        assert pkg_svc.validate.call_count == 1
        assert mock_show.call_count == 1
        assert mock_set.call_count == 0
class TestGuiPersistDelegatesToService:
    """GUI _persist_report 必须复用 PackageUpdateService.save_report（review 遗留 2）。

    之前 GUI 自己写一份 json + path，service 层 save_report 又写一份，重复代码。
    修复后 GUI 应只调 svc.save_report(report)。
    """

    def test_persist_report_calls_service_save(self, monkeypatch):
        """PackageUpdatePage._persist_report 必须调 svc.save_report，不再自己写盘。"""
        from PyQt5.QtWidgets import QApplication
        from ui_qt.pages.package_update_page import PackageUpdatePage
        from ui_qt.theme_manager import ThemeManager
        app = QApplication.instance() or QApplication([])
        mock_app = MagicMock()
        mock_app.config = {}
        mock_app.get_active_paths = MagicMock(return_value={"comfyui_root": "F:/V9", "python_path": "python"})
        pkg_svc = MagicMock()
        pkg_svc.save_report = MagicMock(return_value=None)
        mock_app.services.package = pkg_svc
        mock_app.services.model = None
        monkeypatch.setattr(PackageUpdatePage, "_apply_initial_theme", lambda self: None)
        page = PackageUpdatePage(mock_app, theme_manager=ThemeManager(dark=True))
        report = {"run_id": "gui-run-001", "manifest_id": "m1"}
        page._persist_report(report)
        assert pkg_svc.save_report.call_count == 1, f"GUI 应调 svc.save_report 一次，实际 {pkg_svc.save_report.call_count}"
        assert pkg_svc.save_report.call_args.args[0] is report