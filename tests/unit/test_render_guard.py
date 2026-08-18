"""Tests for the render-guard auto-escalation mechanism.

Covers:
- prepare/begin/finish lifecycle, env application
- 3-step escalations (auto -> compat -> safe, safe capped)
- clean-sentinel detection (no escalation on clean sentinel)
- render_state.json 3 states (missing / clean / running)
- config atomic write preservation (full config with proxy/paths/environments
  fields survives escalation, only ui_settings.render_mode changes)
- PermissionError finish -> state=clean written
- lock-failure path (only prepare, no state file written)
- DLL missing skips QT_OPENGL env
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_MODES = {"auto", "compat", "safe"}


def _make_full_config() -> dict:
    """A config loaded with non-trivial proxy/paths/environments fields.
    Used to guard against guard.begin() accidentally wiping them out."""
    return {
        "launch_options": {"default_port": "8188", "gpu_device": 0},
        "ui_settings": {
            "theme": "dark",
            "ui_scale": 1.0,
            "window_w": 1350,
            "minimize_to_tray_on_close": False,
        },
        "paths": {
            "comfyui_root": "D:/ComfyUI_Bundle",
            "python_path": "D:/ComfyUI_Bundle/python_embeded/python.exe",
            "custom_nodes": "ComfyUI/custom_nodes",
            "comfyui_path": "ComfyUI",
            "python_embeded": "python_embeded",
            "bat_files_directory": ".",
        },
        "environments": [
            {
                "id": "env_default",
                "name": "默认环境",
                "comfyui_root": "D:/ComfyUI_Bundle",
                "python_path": "D:/ComfyUI_Bundle/python_embeded/python.exe",
            },
            {
                "id": "env_dev",
                "name": "Dev",
                "comfyui_root": "E:/dev_comfy",
                "python_path": "E:/dev_comfy/venv/Scripts/python.exe",
            },
        ],
        "active_env_id": "env_default",
        "proxy_settings": {
            "git_proxy_mode": "gh-proxy",
            "git_proxy_url": "https://gh-proxy.com/",
            "pypi_proxy_mode": "aliyun",
            "pypi_proxy_url": "https://mirrors.aliyun.com/pypi/simple/",
            "hf_mirror_mode": "hf-mirror",
            "hf_mirror_url": "https://hf-mirror.com",
            "custom_secret": "proxy_user_specific_thing",
        },
        "advanced": {"check_environment_changes": True},
        "announcement": {"enabled": True, "source_url": "https://example.com/a.json"},
        "version_preferences": {"stable_only": True, "auto_update_deps": True},
        "package_update": {"respect_frozen_pkgs": True, "cache_ttl_days": 3},
        "unknown_custom_field": {"my_app": {"remember_me": True}},
    }


class _TmpSandbox:
    """Scoped sandbox dir containing launcher/config.json and launcher/.
    All render_guard I/O is redirected here via monkeypatching resolve_runtime_root."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        (self.root / "launcher").mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "launcher" / "config.json"
        self.state_path = self.root / "launcher" / "render_state.json"
        self.crash_path = self.root / "launcher" / "crash.log"
        (self.root / "build_parameters.json").write_text(
            json.dumps({"version": "UT-v1.0.0"}), encoding="utf-8"
        )

    def write_config(self, data: dict):
        self.config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read_config(self) -> dict:
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def write_state(self, data: dict):
        self.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read_state(self) -> dict | None:
        if not self.state_path.exists():
            return None
        return json.loads(self.state_path.read_text(encoding="utf-8"))


@pytest.fixture
def sandbox(tmp_path):
    return _TmpSandbox(tmp_path)


@pytest.fixture(autouse=True)
def patch_runtime_root(monkeypatch, sandbox):
    """All render_guard / paths I/O redirected into the sandbox."""
    monkeypatch.setattr(
        "utils.paths.resolve_runtime_root", lambda: sandbox.root
    )
    # Also patch render_guard's internal import alias if any; re-import each test
    import importlib
    import core.render_guard as rg
    importlib.reload(rg)
    yield


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start each test with fresh env state for the three render guard vars."""
    for k in ("LAUNCHER_RENDER_MODE", "LAUNCHER_SAFE_UI", "QT_OPENGL"):
        monkeypatch.delenv(k, raising=False)
    yield
    # post-test cleanup not necessary because of monkeypatch scope


# ---------------------------------------------------------------------------
# Query helpers (pure env, guard agnostic)
# ---------------------------------------------------------------------------

from core.render_guard import (
    current_mode,
    is_safe_ui,
    escalated_this_run,
    escalated_detail,
)


# ---------------------------------------------------------------------------
# TEST GROUP: prepare()
# ---------------------------------------------------------------------------

class TestPrepare:
    """prepare() must set env based on config.ui_settings.render_mode;
    never touches render_state.json; idempotent."""

    def test_prepare_auto_sets_env_no_safe(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        from core.render_guard import prepare
        prepare()
        assert current_mode() == "auto"
        assert is_safe_ui() is False

    def test_prepare_compat_sets_env_no_safe(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "compat"}})
        from core.render_guard import prepare
        prepare()
        assert current_mode() == "compat"
        assert is_safe_ui() is False

    def test_prepare_safe_sets_env_and_safe_ui(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "safe"}})
        from core.render_guard import prepare
        prepare()
        assert current_mode() == "safe"
        assert is_safe_ui() is True
        assert os.environ.get("LAUNCHER_SAFE_UI") == "1"

    def test_prepare_never_writes_state_file(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        from core.render_guard import prepare
        prepare()
        assert sandbox.read_state() is None

    def test_prepare_defaults_to_auto_when_missing(self, sandbox):
        sandbox.write_config({})  # no ui_settings at all
        from core.render_guard import prepare
        prepare()
        assert current_mode() == "auto"

    def test_prepare_idempotent(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "safe"}})
        from core.render_guard import prepare
        prepare()
        prepare()
        assert current_mode() == "safe"

    def test_prepare_dll_missing_skips_qt_opengl(self, sandbox, monkeypatch):
        """If opengl32sw.dll cannot be found, QT_OPENGL env must not be set."""
        sandbox.write_config({"ui_settings": {"render_mode": "compat"}})
        # Ensure _locate returns None
        monkeypatch.setattr(
            "core.render_guard._locate_opengl32sw", lambda: None
        )
        from core.render_guard import prepare
        prepare()
        assert "QT_OPENGL" not in os.environ

    def test_prepare_compat_dll_found_sets_qt_opengl(self, sandbox, monkeypatch):
        sandbox.write_config({"ui_settings": {"render_mode": "compat"}})
        monkeypatch.setattr(
            "core.render_guard._locate_opengl32sw",
            lambda: Path(sandbox.root / "opengl32sw.dll"),
        )
        from core.render_guard import prepare
        prepare()
        assert os.environ.get("QT_OPENGL") == "software"

    def test_prepare_auto_preserves_user_qt_opengl(self, sandbox, monkeypatch):
        """auto mode must NOT touch user-set QT_OPENGL (e.g. user wants desktop)."""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        monkeypatch.setenv("QT_OPENGL", "desktop")
        monkeypatch.setattr(
            "core.render_guard._locate_opengl32sw",
            lambda: Path(sandbox.root / "opengl32sw.dll"),
        )
        from core.render_guard import prepare
        prepare()
        assert os.environ.get("QT_OPENGL") == "desktop", (
            "auto mode should preserve user-set QT_OPENGL value")

    def test_prepare_compat_dll_missing_preserves_user_qt_opengl(self, sandbox, monkeypatch):
        """compat/safe + DLL missing: keep user QT_OPENGL, don't blindly clear."""
        sandbox.write_config({"ui_settings": {"render_mode": "compat"}})
        monkeypatch.setenv("QT_OPENGL", "angle")
        monkeypatch.setattr(
            "core.render_guard._locate_opengl32sw", lambda: None
        )
        from core.render_guard import prepare
        prepare()
        assert os.environ.get("QT_OPENGL") == "angle", (
            "DLL missing path should preserve user QT_OPENGL instead of clearing")


# ---------------------------------------------------------------------------
# TEST GROUP: begin() escalation + state
# ---------------------------------------------------------------------------

class TestBegin:
    def test_begin_no_state_no_escalation_auto(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        from core.render_guard import begin, finish
        try:
            begin()
            assert current_mode() == "auto"
            assert escalated_this_run() is False
            assert escalated_detail() is None
            state = sandbox.read_state()
            assert state is not None
            assert state["mode"] == "auto"
            assert state["state"] == "running"
        finally:
            # finish to avoid os._exit on guard re-init with stale state
            try:
                finish()
            except Exception:
                pass

    def test_begin_state_file_exists_but_corrupt_triggers_escalation(self, sandbox):
        """Mark exists but not valid JSON → signal of abnormal exit → escalate.

        Atomic writes in begin()/finish() never produce such a file, so its
        presence means the previous run died mid-write (eg power loss,
        taskkill /F, AV interference). Must treat like state=running.
        """
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        st = sandbox.state_path
        st.write_text("{not valid json garbage \x00\x01\xff", encoding="utf-8")
        assert st.exists()
        from core.render_guard import begin, finish, escalated_this_run, escalated_detail
        try:
            begin()
            assert escalated_this_run(), (
                "corrupt state file must trigger escalation")
            assert escalated_detail() == ("auto", "compat"), (
                f"expected auto→compat, got {escalated_detail()}")
        finally:
            try:
                finish()
            except Exception:
                pass

    def test_begin_state_is_running_triggers_escalation_auto_compat(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        sandbox.write_state(
            {"mode": "auto", "pid": 9999, "started_at": 0, "version": "old",
             "state": "running"}
        )
        from core.render_guard import begin, finish
        try:
            begin()
            assert escalated_this_run() is True
            assert escalated_detail() == ("auto", "compat")
            assert current_mode() == "compat"
            # config should be updated atomically
            cfg = sandbox.read_config()
            assert cfg["ui_settings"]["render_mode"] == "compat"
        finally:
            try:
                finish()
            except Exception:
                pass

    def test_begin_state_is_running_triggers_escalation_compat_safe(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "compat"}})
        sandbox.write_state(
            {"mode": "compat", "pid": 9999, "started_at": 0, "version": "old",
             "state": "running"}
        )
        from core.render_guard import begin, finish
        try:
            begin()
            assert escalated_this_run() is True
            assert escalated_detail() == ("compat", "safe")
            assert current_mode() == "safe"
            assert is_safe_ui() is True
        finally:
            try:
                finish()
            except Exception:
                pass

    def test_begin_safe_is_capped_no_further_escalation(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "safe"}})
        sandbox.write_state(
            {"mode": "safe", "pid": 9999, "started_at": 0, "version": "old",
             "state": "running"}
        )
        from core.render_guard import begin, finish
        try:
            begin()
            # safe capped: escalated_this_run True because signal exists, but
            # mode stays at safe. Implementation may choose either boolean;
            # the only strong contract is mode didn't go beyond safe.
            assert current_mode() == "safe"
        finally:
            try:
                finish()
            except Exception:
                pass

    def test_begin_clean_sentinel_does_not_escalate(self, sandbox):
        """finish() wrote state=clean (or remove failed, fell back).
        begin() sees clean -> NO escalation, rewrite as running."""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        sandbox.write_state(
            {"mode": "auto", "started_at": 0, "version": "old",
             "cleaned_at": 1, "state": "clean"}
        )
        from core.render_guard import begin, finish
        try:
            begin()
            assert escalated_this_run() is False
            assert escalated_detail() is None
            assert current_mode() == "auto"
            state = sandbox.read_state()
            assert state["state"] == "running"
        finally:
            try:
                finish()
            except Exception:
                pass

    def test_begin_escalation_preserves_all_other_config_fields(self, sandbox):
        """The config write during escalation MUST NOT wipe out unrelated
        fields (proxy credentials, environments array, custom fields, etc.)."""
        full_cfg = _make_full_config()
        full_cfg["ui_settings"]["render_mode"] = "auto"
        sandbox.write_config(full_cfg)
        # Add an unknown nested field that render guard should never touch.
        cfg_before_text = sandbox.config_path.read_text(encoding="utf-8")

        sandbox.write_state(
            {"mode": "auto", "pid": 9999, "started_at": 0, "version": "old",
             "state": "running"}
        )
        from core.render_guard import begin, finish
        try:
            begin()
        finally:
            try:
                finish()
            except Exception:
                pass

        cfg_after = sandbox.read_config()
        # The only accepted diff: ui_settings.render_mode auto -> compat
        full_cfg["ui_settings"]["render_mode"] = "compat"
        assert cfg_after == full_cfg

    def test_begin_escalation_does_not_overwrite_empty_or_damaged_config(self, sandbox):
        """If config is empty {} / damaged (atomic-write damage guard): skip
        persistence rather than writing a minimal {ui_settings: {render_mode}}
        stub that would break ConfigManager's own corruption handling."""
        # Empty dict config (damaged: no top-level keys)
        sandbox.config_path.write_text("{}", encoding="utf-8")
        sandbox.write_state(
            {"mode": "auto", "pid": 9999, "started_at": 0, "version": "old",
             "state": "running"}
        )
        from core.render_guard import begin, finish, current_mode
        try:
            begin()
        finally:
            try:
                finish()
            except Exception:
                pass

        cfg_text = sandbox.config_path.read_text(encoding="utf-8")
        # Still {} (not persisted)
        import json
        assert json.loads(cfg_text) == {}, (
            f"empty/damaged config must not be mutated by escalation, got {cfg_text}")
        # But process-internal mode still escalated (not persisted)
        # current_mode reads env, which should be compat
        assert current_mode() == "compat"


# ---------------------------------------------------------------------------
# TEST GROUP: finish()
# ---------------------------------------------------------------------------

class TestFinish:
    def test_finish_normal_path_removes_state(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        from core.render_guard import begin, finish
        begin()
        assert sandbox.read_state() is not None
        finish()
        assert sandbox.read_state() is None

    def test_finish_permission_error_writes_clean_sentinel(self, sandbox, monkeypatch):
        """If os.remove on state file fails, finish() must atomically rewrite
        state with state=clean so next begin() does not falsely escalate."""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        from core.render_guard import begin, finish
        begin()
        state_path = sandbox.state_path
        assert state_path.exists()

        real_remove = os.remove

        def fake_remove(p, *args, **kwargs):
            if Path(p) == state_path:
                raise PermissionError("antivirus locked")
            return real_remove(p, *args, **kwargs)

        monkeypatch.setattr(os, "remove", fake_remove)
        finish()

        # state file exists but marked clean
        assert sandbox.state_path.exists()
        st = sandbox.read_state()
        assert st["state"] == "clean"
        assert "cleaned_at" in st
        # next begin must NOT escalate
        from core.render_guard import begin as begin2
        try:
            begin2()
            assert escalated_this_run() is False
            assert current_mode() == "auto"
        finally:
            try:
                monkeypatch.undo()
                os.remove(str(sandbox.state_path))
            except Exception:
                pass


# ---------------------------------------------------------------------------
# TEST GROUP: lock-failure path (only prepare called)
# ---------------------------------------------------------------------------

class TestLockFailurePath:
    def test_prepare_only_without_state_write(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "safe"}})
        # lock failure scenario: user code calls prepare() but never begin()
        from core.render_guard import prepare
        prepare()
        assert current_mode() == "safe"
        assert is_safe_ui() is True
        assert sandbox.read_state() is None  # crucial: no state written


# ---------------------------------------------------------------------------
# TEST GROUP: _locate_opengl32sw DLL search order
# ---------------------------------------------------------------------------

class TestLocateDLL:
    def test_finds_dll_next_to_executable(self, sandbox, monkeypatch):
        dll = sandbox.root / "opengl32sw.dll"
        dll.write_bytes(b"placeholder")
        monkeypatch.setattr(sys, "executable", str(sandbox.root / "launcher.exe"))
        # We need to reset the module-level DLL cache between tests.
        import core.render_guard as rg
        rg._dll_cached = False
        rg._dll_path = None
        found = rg._locate_opengl32sw()
        assert found is not None
        assert Path(found) == dll

    def test_finds_dll_inside_internal_pyqt5_bin(self, sandbox, monkeypatch):
        """Nuitka onedir path: DLL 藏在 exe/_internal/PyQt5/Qt5/bin/。
        顶层（exe 旁）没有 DLL，必须命中 _internal 子路径。"""
        internal_dir = sandbox.root / "_internal" / "PyQt5" / "Qt5" / "bin"
        internal_dir.mkdir(parents=True)
        dll = internal_dir / "opengl32sw.dll"
        dll.write_bytes(b"internal dll placeholder")
        # exe 旁故意不放，确保只走 _internal 分支
        exe_sibling = sandbox.root / "opengl32sw.dll"
        assert not exe_sibling.exists()
        monkeypatch.setattr(sys, "executable", str(sandbox.root / "launcher.exe"))
        # 必须也屏蔽 PyQt5 开发 wheel 路径，否则 find_spec 命中了会走候选 3
        import importlib.util as _iu
        def _mocked_find_spec(name, *a, **k):
            if name == "PyQt5":
                return None
            return _real_iu_find_spec(name, *a, **k)
        _real_iu_find_spec = _iu.find_spec
        monkeypatch.setattr(_iu, "find_spec", _mocked_find_spec)
        import core.render_guard as rg
        rg._dll_cached = False
        rg._dll_path = None
        found = rg._locate_opengl32sw()
        assert found is not None, (
            "_internal/PyQt5/Qt5/bin/opengl32sw.dll 必须被命中")
        assert Path(found).resolve() == dll.resolve()


import sys  # noqa: E402  (used in test above, import here to keep style clean)
