"""webui page mirror switch (Gitee / GitHub / Custom) unit tests.

What this locks down:
  - resolve_webui_repo_url maps each mirror to the right URL.
  - _resolve_paths returns download_mirror + mirror_options.
  - _mirror_combo initializes by config; currentIndexChanged wired to _on_mirror_changed.
  - _on_mirror_changed for gitee / github: persists download_mirror; no dialog.
  - _on_mirror_changed for custom: pops QInputDialog; cancel -> combo rolls back.
  - _on_mirror_changed for custom empty URL: shows warning + rolls back.
  - installed (webui_path/.git exists) + choose origin: CustomConfirmDialog + git remote set-url.
  - installed but user chose save-config-only: persist only, no git call.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

from ui_qt.pages import webui_page as wp_module
from ui_qt.pages.webui_page import WebuiPage
from ui_qt.theme_manager import ThemeManager
from core.webui_installer import (
    resolve_webui_repo_url,
    WEBUI_REPOS,
    WEBUI_DEFAULT_MIRROR,
    WEBUI_DEFAULT_REPO,
    WEBUI_REPO_GITEE,
    WEBUI_REPO_GITHUB,
)


# ---- pure function: resolve_webui_repo_url ----
class TestResolveRepoUrl(unittest.TestCase):
    def test_gitee(self):
        self.assertEqual(
            resolve_webui_repo_url("gitee", ""),
            WEBUI_REPO_GITEE,
        )

    def test_github(self):
        self.assertEqual(
            resolve_webui_repo_url("github", ""),
            WEBUI_REPO_GITHUB,
        )

    def test_custom_uses_custom_url(self):
        self.assertEqual(
            resolve_webui_repo_url("custom", "https://example.com/foo.git"),
            "https://example.com/foo.git",
        )

    def test_custom_empty_falls_back_to_default(self):
        self.assertEqual(
            resolve_webui_repo_url("custom", ""),
            WEBUI_DEFAULT_REPO,
        )

    def test_unknown_mirror_falls_back_to_default(self):
        self.assertEqual(
            resolve_webui_repo_url("bitbucket", ""),
            WEBUI_DEFAULT_REPO,
        )

    def test_none_mirror_falls_back_to_default(self):
        self.assertEqual(
            resolve_webui_repo_url(None, ""),
            WEBUI_DEFAULT_REPO,
        )

    def test_case_insensitive(self):
        self.assertEqual(
            resolve_webui_repo_url("GITEE", ""),
            WEBUI_REPO_GITEE,
        )




# ---- app scaffold helper ----
def _make_app(cwd, webui_path, py_path, webui_options=None):
    """"Build minimal app with optional webui_options override."""
    app = type("A", (), {})()
    app._cwd = str(cwd)
    app.config = {
        "environments": [
            {"id": "env_a", "comfyui_root": str(cwd), "python_path": str(py_path)},
        ],
        "active_env_id": "env_a",
        "webui_options": dict(webui_options or {"port": 8199}),
    }
    app.logger = MagicMock()
    app.pypi_proxy_mode = MagicMock()
    app.pypi_proxy_mode.get = lambda: "none"
    app.pypi_proxy_url = MagicMock()
    app.pypi_proxy_url.get = lambda: ""
    app.custom_port = MagicMock()
    app.custom_port.get = lambda: "8188"
    app.services = MagicMock()
    app.services.config = MagicMock()
    app.services.config.save = lambda cfg: cfg
    return app


class _Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.tm = ThemeManager()
        # Globally no-op DialogHelper dialogs; pytest-qt teardown sometimes
        # drains leftover slots and a real modal would hang teardown.
        from ui_qt.widgets import dialog_helper
        cls._patches = [
            patch.object(dialog_helper.DialogHelper, "show_warning", lambda *a, **kw: None),
            patch.object(dialog_helper.DialogHelper, "show_info", lambda *a, **kw: None),
            patch.object(dialog_helper.DialogHelper, "show_error", lambda *a, **kw: None),
            patch.object(dialog_helper.DialogHelper, "show_confirmation", lambda *a, **kw: True),
        ]
        for p in cls._patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()

    def _make_page(self, webui_options=None, with_dot_git=False, webui_path_override=None):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(self._rm_tmp, d)
        webui_path = webui_path_override or (d / "Comfyui-Workbench-Mie")
        webui_path.mkdir(parents=True, exist_ok=True)
        (webui_path / "app").mkdir(parents=True, exist_ok=True)
        (webui_path / "app" / "flask_app.py").write_text("# stub", encoding="utf-8")
        if with_dot_git:
            (webui_path / ".git").mkdir()
        py = d / "python.exe"
        py.touch()
        app = _make_app(d, webui_path, py, webui_options)
        _ok_dep = {"ok": True, "missing": [], "available": ["flask", "requests"]}
        with patch("core.webui_process_manager.WebuiProcessManager.is_running", return_value=False), \
             patch("ui_qt.pages.webui_page.check_webui_dependencies", return_value=_ok_dep):
            page = WebuiPage(app=app, theme_manager=self.tm)
        try:
            page._state_check_timer.stop()
        except Exception:
            pass
        page._deps_cache_key = None
        page._deps_cache_result = None
        try:
            page._stop_log_tail()
        except Exception:
            pass
        return page, app, webui_path, d

    @staticmethod
    def _rm_tmp(d):
        try:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


# ---- _resolve_paths / _mirror_combo ----
class TestResolvePathsMirror(_Fixture):
    def test_resolve_paths_returns_mirror_fields(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "github"},
        )
        info = page._resolve_paths()
        self.assertEqual(info["download_mirror"], "github")
        self.assertEqual(info["download_url"], WEBUI_REPO_GITHUB)
        # mirror_options must always include gitee/github/custom.
        self.assertEqual(set(info["mirror_options"]), {"gitee", "github", "custom"})

    def test_resolve_paths_unknown_mirror_falls_back(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "bitbucket"},
        )
        info = page._resolve_paths()
        self.assertEqual(info["download_mirror"], WEBUI_DEFAULT_MIRROR)

    def test_mirror_combo_init_matches_config(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "github"},
        )
        combo = page._mirror_combo
        self.assertEqual(combo.count(), 3)
        # items: gitee / github / custom
        items = [combo.itemData(i) for i in range(combo.count())]
        self.assertEqual(items, ["gitee", "github", "custom"])
        self.assertEqual(combo.currentData(), "github")

    def test_mirror_combo_default_when_missing(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199},
        )
        self.assertEqual(page._mirror_combo.currentData(), WEBUI_DEFAULT_MIRROR)

    def test_mirror_combo_signal_connected(self):
        """Verify _mirror_combo.currentIndexChanged is connected to _on_mirror_changed.

        Qt captures the bound method at connect() time so patching the
        instance attribute cannot intercept the signal. We instead verify
        the connection statically: read the page source for the connect
        call right after _mirror_combo construction.
        """
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "gitee"},
        )
        import inspect
        src = inspect.getsource(page._setup_ui.__func__)
        self.assertIn("self._mirror_combo.currentIndexChanged.connect(self._on_mirror_changed)", src)


class TestOnMirrorChanged(_Fixture):
    def _combo_index_of(self, combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                return i
        return -1

    def test_select_github_persists(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "gitee"},
        )
        saved = []
        with patch.object(page, "_save_webui_option", side_effect=lambda k, v: (saved.append((k, v)), app.config.setdefault("webui_options", {}).__setitem__(k, v))):
            idx = self._combo_index_of(page._mirror_combo, "github")
            page._on_mirror_changed(idx)
        keys = [k for k, _ in saved]
        self.assertIn("download_mirror", keys)
        self.assertEqual(dict(saved)["download_mirror"], "github")
        # git remote not called (not installed).

    def test_select_gitee_persists(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "github"},
        )
        saved = []
        with patch.object(page, "_save_webui_option", side_effect=lambda k, v: (saved.append((k, v)), app.config.setdefault("webui_options", {}).__setitem__(k, v))):
            idx = self._combo_index_of(page._mirror_combo, "gitee")
            page._on_mirror_changed(idx)
        self.assertEqual(dict(saved)["download_mirror"], "gitee")

    def test_same_mirror_is_noop(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "github"},
        )
        saved = []
        with patch.object(page, "_save_webui_option", side_effect=lambda k, v: (saved.append((k, v)), app.config.setdefault("webui_options", {}).__setitem__(k, v))):
            idx = self._combo_index_of(page._mirror_combo, "github")
            page._on_mirror_changed(idx)
        self.assertEqual(saved, [])

    def test_custom_opens_input_dialog_and_persists(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "gitee"},
        )
        saved = []
        fake_input = MagicMock(return_value=("https://my-mirror.example/foo.git", True))
        with patch.object(page, "_save_webui_option", side_effect=lambda k, v: (saved.append((k, v)), app.config.setdefault("webui_options", {}).__setitem__(k, v))), \
             patch.object(QtWidgets.QInputDialog, "getText", fake_input):
            idx = self._combo_index_of(page._mirror_combo, "custom")
            page._on_mirror_changed(idx)
        d = dict(saved)
        self.assertEqual(d["download_mirror"], "custom")
        self.assertEqual(d["download_url"], "https://my-mirror.example/foo.git")

    def test_custom_cancel_rolls_back(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "gitee"},
        )
        saved = []
        fake_input = MagicMock(return_value=("", False))
        with patch.object(page, "_save_webui_option", side_effect=lambda k, v: (saved.append((k, v)), app.config.setdefault("webui_options", {}).__setitem__(k, v))), \
             patch.object(QtWidgets.QInputDialog, "getText", fake_input):
            # Move combo to custom first (no signal because of blockSignals).
            page._mirror_combo.blockSignals(True)
            page._mirror_combo.setCurrentIndex(self._combo_index_of(page._mirror_combo, "custom"))
            page._mirror_combo.blockSignals(False)
            page._on_mirror_changed(self._combo_index_of(page._mirror_combo, "custom"))
        self.assertEqual(saved, [])
        # combo must be rolled back to gitee.
        self.assertEqual(page._mirror_combo.currentData(), "gitee")

    def test_custom_empty_url_rolls_back(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "gitee"},
        )
        saved = []
        fake_input = MagicMock(return_value=("   ", True))  # user typed only whitespace
        with patch.object(page, "_save_webui_option", side_effect=lambda k, v: (saved.append((k, v)), app.config.setdefault("webui_options", {}).__setitem__(k, v))), \
             patch.object(QtWidgets.QInputDialog, "getText", fake_input):
            page._mirror_combo.blockSignals(True)
            page._mirror_combo.setCurrentIndex(self._combo_index_of(page._mirror_combo, "custom"))
            page._mirror_combo.blockSignals(False)
            page._on_mirror_changed(self._combo_index_of(page._mirror_combo, "custom"))
        self.assertEqual(saved, [])
        self.assertEqual(page._mirror_combo.currentData(), "gitee")


# ---- installed (.git exists) -> CustomConfirmDialog + git remote set-url ----
class TestInstalledMirrorSwitch(_Fixture):
    def _combo_index_of(self, combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                return i
        return -1

    def test_installed_pick_github_runs_git_remote_set_url(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "gitee"},
            with_dot_git=True,
        )
        saved = []
        fake_dlg = MagicMock()
        fake_dlg.exec_ = MagicMock(return_value=None)
        fake_dlg.get_result = MagicMock(return_value=1)  # chose 立即切换 origin
        fake_run = MagicMock(return_value=MagicMock(returncode=0, stderr="", stdout=""))
        with patch.object(page, "_save_webui_option", side_effect=lambda k, v: (saved.append((k, v)), app.config.setdefault("webui_options", {}).__setitem__(k, v))), \
             patch("ui_qt.pages.webui_page.CustomConfirmDialog", return_value=fake_dlg), \
             patch("ui_qt.pages.webui_page.subprocess.run", fake_run):
            idx = self._combo_index_of(page._mirror_combo, "github")
            page._on_mirror_changed(idx)
        # Confirm dialog popped with [save-config-only / switch-origin].
        self.assertTrue(fake_dlg.exec_.called)
        # subprocess.run was called with git remote set-url origin <new_url>.
        self.assertTrue(fake_run.called)
        args = fake_run.call_args[0][0]
        self.assertEqual(args[:4], ["git", "remote", "set-url", "origin"])
        self.assertEqual(args[4], WEBUI_REPO_GITHUB)
        # cwd = webui_path
        self.assertEqual(Path(fake_run.call_args[1]["cwd"]), webui_path.resolve())
        # mirror persisted.
        self.assertEqual(dict(saved)["download_mirror"], "github")

    def test_installed_user_picks_save_config_only_skips_git(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "gitee"},
            with_dot_git=True,
        )
        saved = []
        fake_dlg = MagicMock()
        fake_dlg.exec_ = MagicMock(return_value=None)
        fake_dlg.get_result = MagicMock(return_value=0)  # chose save-config-only
        fake_run = MagicMock()
        with patch.object(page, "_save_webui_option", side_effect=lambda k, v: (saved.append((k, v)), app.config.setdefault("webui_options", {}).__setitem__(k, v))), \
             patch("ui_qt.pages.webui_page.CustomConfirmDialog", return_value=fake_dlg), \
             patch("ui_qt.pages.webui_page.subprocess.run", fake_run):
            idx = self._combo_index_of(page._mirror_combo, "github")
            page._on_mirror_changed(idx)
        self.assertTrue(fake_dlg.exec_.called)
        self.assertFalse(fake_run.called, "save-config-only must NOT run git")
        # mirror still persisted.
        self.assertEqual(dict(saved)["download_mirror"], "github")

    def test_installed_git_failure_shows_error(self):
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "gitee"},
            with_dot_git=True,
        )
        fake_dlg = MagicMock()
        fake_dlg.exec_ = MagicMock(return_value=None)
        fake_dlg.get_result = MagicMock(return_value=1)
        fake_run = MagicMock(return_value=MagicMock(returncode=128, stderr="fatal: not a git repo", stdout=""))
        show_err = MagicMock()
        with patch("ui_qt.pages.webui_page.CustomConfirmDialog", return_value=fake_dlg), \
             patch("ui_qt.pages.webui_page.subprocess.run", fake_run), \
             patch("ui_qt.widgets.dialog_helper.DialogHelper.show_error", show_err):
            idx = self._combo_index_of(page._mirror_combo, "github")
            page._on_mirror_changed(idx)
        self.assertTrue(show_err.called)
        # The error message must mention the stderr.
        kwargs = show_err.call_args[0] if show_err.call_args else ()
        msg = (kwargs[2] if len(kwargs) >= 3 else "")
        self.assertIn("fatal: not a git repo", msg)

    def test_not_installed_skips_confirm_dialog(self):
        """No .git => no CustomConfirmDialog, no git subprocess call."""
        page, app, webui_path, d = self._make_page(
            webui_options={"port": 8199, "download_mirror": "gitee"},
            with_dot_git=False,
        )
        fake_dlg = MagicMock()
        fake_run = MagicMock()
        with patch("ui_qt.pages.webui_page.CustomConfirmDialog", return_value=fake_dlg), \
             patch("ui_qt.pages.webui_page.subprocess.run", fake_run):
            idx = self._combo_index_of(page._mirror_combo, "github")
            page._on_mirror_changed(idx)
        self.assertFalse(fake_dlg.exec_.called)
        self.assertFalse(fake_run.called)


