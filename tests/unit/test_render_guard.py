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
        self.counter_path = self.root / "launcher" / "render_clean_counter.json"
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

    def write_counter(self, data: dict):
        self.counter_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read_counter(self) -> dict | None:
        if not self.counter_path.exists():
            return None
        return json.loads(self.counter_path.read_text(encoding="utf-8"))

    def write_crash_log(self, text: str):
        self.crash_path.write_text(text, encoding="utf-8")


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

# ---------------------------------------------------------------------------
# TEST GROUP: begin() (v9 分类器驱动)
# ---------------------------------------------------------------------------
# v9 算法: 升级依据是 crash.log 段分类（graphics_crash 才升级）, 不是 state
# 文件。state 损坏 / state=running / state=clean 都不再触发升级。begin 永远
# 写 state="starting" (mark_running() 后才转 running)。

# 构造 graphics_crash 段（v3 算法): Windows fatal exception 行 + 当前 [startup]
_GRAPHICS_CRASH_SEG = """\
[startup] ts=prev
[render_guard] mode=auto escalated=False version=v
Windows fatal exception: access violation (0xC0000005)
Current thread 0x0000abcd (most recent call first):
File "C:\\foo\\bar.py", line 42 in some_func
[no Python frame]
[startup] ts=now
"""

# python_exception 段: [uncaught_exception] 块
_PY_EXCEPTION_SEG = """\
[startup] ts=prev
[uncaught_exception] ts=...
Traceback (most recent call last):
  File "C:\\foo\\bar.py", line 10, in <module>
    raise ValueError("x")
ValueError: x
[startup] ts=now
"""

# clean_or_user 段: 仅 marker
_CLEAN_SEG = """\
[startup] ts=prev
[render_guard] mode=auto escalated=False version=v
[startup] ts=now
"""


class TestBegin:
    def test_begin_no_state_no_log_no_escalation_auto(self, sandbox):
        """state 不存在 + crash.log 不存在 → unknown → 不升级。
        v6 勘误: state["state"] == "starting"（不再是 running）"""
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
            assert state["state"] == "starting"
        finally:
            try:
                finish()
            except Exception:
                pass

    def test_begin_graphics_crash_escalates_auto_compat(self, sandbox):
        """crash.log 段 graphics_crash + state=auto → 升 compat。
        v9: state 文件是什么不影响升级, crash.log 内容才是依据。"""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        sandbox.write_crash_log(_GRAPHICS_CRASH_SEG)
        sandbox.write_state({"mode": "auto", "pid": 9999, "started_at": 0, "version": "old", "state": "running"})
        from core.render_guard import begin, finish
        try:
            begin()
            assert escalated_this_run() is True
            assert escalated_detail() == ("auto", "compat")
            assert current_mode() == "compat"
            cfg = sandbox.read_config()
            assert cfg["ui_settings"]["render_mode"] == "compat"
        finally:
            try:
                finish()
            except Exception:
                pass

    def test_begin_graphics_crash_escalates_compat_safe(self, sandbox):
        sandbox.write_config({"ui_settings": {"render_mode": "compat"}})
        sandbox.write_crash_log(_GRAPHICS_CRASH_SEG)
        sandbox.write_state({"mode": "compat", "pid": 9999, "started_at": 0, "version": "old", "state": "running"})
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

    def test_begin_graphics_crash_safe_capped(self, sandbox):
        """graphics_crash + state=safe → detail=(safe,safe), mode 不变。
        v9: from==to 时弹窗静默（from != to 才弹）。"""
        sandbox.write_config({"ui_settings": {"render_mode": "safe"}})
        sandbox.write_crash_log(_GRAPHICS_CRASH_SEG)
        sandbox.write_state({"mode": "safe", "pid": 9999, "started_at": 0, "version": "old", "state": "running"})
        from core.render_guard import begin, finish
        try:
            begin()
            assert escalated_this_run() is True
            assert escalated_detail() == ("safe", "safe")
            assert current_mode() == "safe"
        finally:
            try:
                finish()
            except Exception:
                pass

    def test_begin_python_exception_does_not_escalate(self, sandbox):
        """crash.log 段含 [uncaught_exception] 块 → python_exception → 不升级。
        v9: Python 异常与渲染模式无关, 不应升级。
        v11 R4b: state=running 前置, 走分类器路径（区分门跳过 vs 分类不升级）"""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        sandbox.write_state({"mode": "auto", "pid": 9999, "started_at": 0, "version": "old", "state": "running"})
        sandbox.write_crash_log(_PY_EXCEPTION_SEG)
        from core.render_guard import begin, finish
        try:
            begin()
            assert escalated_this_run() is False
            assert escalated_detail() is None
            assert current_mode() == "auto"
        finally:
            try:
                finish()
            except Exception:
                pass

    def test_begin_clean_or_user_does_not_escalate(self, sandbox):
        """crash.log 段仅 marker → clean_or_user → 不升级（tray-resident / 关机）。
        v11 R4b: state=running 前置, 走分类器路径"""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        sandbox.write_state({"mode": "auto", "pid": 9999, "started_at": 0, "version": "old", "state": "running"})
        sandbox.write_crash_log(_CLEAN_SEG)
        from core.render_guard import begin, finish
        try:
            begin()
            assert escalated_this_run() is False
            assert current_mode() == "auto"
            state = sandbox.read_state()
            assert state["state"] == "starting"
        finally:
            try:
                finish()
            except Exception:
                pass

    def test_begin_escalation_preserves_all_other_config_fields(self, sandbox):
        """升级时 config 写入必须保留其他字段（proxy / environments / custom）。"""
        full_cfg = _make_full_config()
        full_cfg["ui_settings"]["render_mode"] = "auto"
        sandbox.write_config(full_cfg)
        sandbox.write_crash_log(_GRAPHICS_CRASH_SEG)
        sandbox.write_state({"mode": "auto", "pid": 9999, "started_at": 0, "version": "old", "state": "running"})
        from core.render_guard import begin, finish
        try:
            begin()
        finally:
            try:
                finish()
            except Exception:
                pass

        cfg_after = sandbox.read_config()
        full_cfg["ui_settings"]["render_mode"] = "compat"
        assert cfg_after == full_cfg

    def test_begin_escalation_does_not_overwrite_empty_or_damaged_config(self, sandbox):
        """config 损坏时升级不落盘（避免写回空壳 {ui_settings: {render_mode}}）。"""
        sandbox.config_path.write_text("{}", encoding="utf-8")
        sandbox.write_crash_log(_GRAPHICS_CRASH_SEG)
        sandbox.write_state({"mode": "auto", "pid": 9999, "started_at": 0, "version": "old", "state": "running"})
        from core.render_guard import begin, finish
        try:
            begin()
        finally:
            try:
                finish()
            except Exception:
                pass

        cfg_text = sandbox.config_path.read_text(encoding="utf-8")
        import json
        assert json.loads(cfg_text) == {}, (
            f"empty/damaged config must not be mutated by escalation, got {cfg_text}")
        # 但进程内 mode 仍升级
        assert current_mode() == "compat"


# ---------------------------------------------------------------------------
# TEST GROUP: mark_running()
# ---------------------------------------------------------------------------


class TestMarkRunning:
    def test_mark_running_creates_when_no_state(self, sandbox):
        """state 不存在 → 写 running（兜底, begin 写失败场景）。"""
        from core.render_guard import mark_running
        mark_running()
        state = sandbox.read_state()
        assert state is not None
        assert state["state"] == "running"

    def test_mark_running_no_change_when_clean_sentinel(self, sandbox):
        """state=clean → 不动（finish 哨兵被保护, 重写会丢诊断信息）。"""
        existing = {
            "mode": "auto",
            "started_at": 12345,
            "version": "old",
            "cleaned_at": 12346,
            "state": "clean",
        }
        sandbox.write_state(existing)
        from core.render_guard import mark_running
        mark_running()
        state = sandbox.read_state()
        assert state["state"] == "clean"
        assert state["cleaned_at"] == 12346  # 哨兵字段保留

    def test_mark_running_updates_starting_to_running_preserves_fields(self, sandbox):
        """state=starting → running, 保留 counter 等字段（v1 §1.4）。"""
        existing = {
            "mode": "auto",
            "started_at": 99999,
            "version": "v",
            "state": "starting",
        }
        sandbox.write_state(existing)
        from core.render_guard import mark_running
        mark_running()
        state = sandbox.read_state()
        assert state["state"] == "running"
        assert state["mode"] == "auto"
        assert state["started_at"] == 99999
        assert state["version"] == "v"


# ---------------------------------------------------------------------------
# TEST GROUP: classifier (v9 三态分类器)
# ---------------------------------------------------------------------------


class TestClassifier:
    def test_classify_fatal_single_line(self):
        from core.render_guard import _classify_last_exit
        seg = "[startup] ts=p\nWindows fatal exception: x\n[startup] ts=n\n"
        assert _classify_last_exit(seg) == "graphics_crash"

    def test_classify_no_start_returns_unknown(self):
        from core.render_guard import _classify_last_exit
        assert _classify_last_exit("") == "unknown"
        assert _classify_last_exit("hello\n") == "unknown"

    def test_classify_only_one_start_returns_unknown(self):
        from core.render_guard import _classify_last_exit
        assert _classify_last_exit("[startup] ts=now\n") == "unknown"

    def test_classify_only_markers_returns_clean_or_user(self):
        from core.render_guard import _classify_last_exit
        assert _classify_last_exit(_CLEAN_SEG) == "clean_or_user"

    def test_classify_uncaught_block_returns_python_exception(self):
        from core.render_guard import _classify_last_exit
        assert _classify_last_exit(_PY_EXCEPTION_SEG) == "python_exception"

    def test_classify_chained_exception_in_block(self):
        """链式异常分隔行 'During handling of the above exception...' 在 [uncaught_exception]
        块内 → python_exception（v2 行形状匹配漏的 case, v3 块排除兜住）。"""
        from core.render_guard import _classify_last_exit
        seg = (
            "[startup] ts=p\n"
            "[uncaught_exception] ts=...\n"
            "Traceback (most recent call last):\n"
            "  File \"x.py\", line 1\n"
            "ValueError: a\n"
            "\n"
            "During handling of the above exception, another exception occurred:\n"
            "\n"
            "Traceback (most recent call last):\n"
            "  File \"x.py\", line 2\n"
            "TypeError: b\n"
            "[startup] ts=n\n"
        )
        assert _classify_last_exit(seg) == "python_exception"

    def test_classify_fatal_after_uncaught_block_returns_python_exception(self):
        """先 Python 异常后 native crash → 块吞, python_exception（v3:64 + case 3 取舍）。"""
        from core.render_guard import _classify_last_exit
        seg = (
            "[startup] ts=p\n"
            "[uncaught_exception] ts=...\n"
            "ValueError: x\n"
            "Windows fatal exception: access violation (0xC0000005)\n"
            "[startup] ts=n\n"
        )
        assert _classify_last_exit(seg) == "python_exception"


# ---------------------------------------------------------------------------
# TEST GROUP: finish() auto-recovery
# ---------------------------------------------------------------------------


class TestAutoRecovery:
    """v1 §1.5 step 2 + v4 Rev3 裸 JSON 校验 + v4 Rev4 去门 + v9 Rev1 finish 落地。"""

    def test_finish_counter_increment_and_persist(self, sandbox):
        """每次 finish 都无条件中间落盘 counter+1, 跨 state 存活。"""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        from core.render_guard import begin, finish
        begin()
        finish()
        c1 = sandbox.read_counter()
        assert c1 is not None and c1["count"] == 1
        begin()
        finish()
        c2 = sandbox.read_counter()
        assert c2["count"] == 2

    def test_finish_threshold_5_promotes_to_auto_and_clears(self, sandbox):
        """counter 从 4 进 finish → 5 → 触发 promote, 升 auto + 清零。"""
        sandbox.write_config({"ui_settings": {"render_mode": "compat"}})
        sandbox.write_counter({"count": 4, "last_clean_at": 0, "since_mode": "compat"})
        from core.render_guard import begin, finish
        begin()
        finish()
        c = sandbox.read_counter()
        assert c["count"] == 0  # verified → 清零
        assert sandbox.read_config()["ui_settings"]["render_mode"] == "auto"

    def test_finish_threshold_5_in_auto_does_no_op_promote(self, sandbox):
        """counter 4 + mode=auto + finish → no-op promote + 清零（v4 Rev4 去门）。"""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        sandbox.write_counter({"count": 4, "last_clean_at": 0, "since_mode": "auto"})
        from core.render_guard import begin, finish
        begin()
        finish()
        c = sandbox.read_counter()
        assert c["count"] == 0
        assert sandbox.read_config()["ui_settings"]["render_mode"] == "auto"

    def test_finish_promote_write_failure_counter_not_cleared(self, sandbox, monkeypatch):
        """_write_render_mode_to_config 失败 → counter 不清零（v4 Rev3 + v9 Rev1）。"""
        sandbox.write_config({"ui_settings": {"render_mode": "compat"}})
        sandbox.write_counter({"count": 4, "last_clean_at": 0, "since_mode": "compat"})

        def _raise_write(mode):
            raise IOError("disk full")
        monkeypatch.setattr(
            "core.render_guard._write_render_mode_to_config", _raise_write
        )
        from core.render_guard import begin, finish
        begin()
        finish()
        c = sandbox.read_counter()
        assert c["count"] >= 4  # 不清零

    def test_finish_promote_broken_config_counter_not_cleared(self, sandbox):
        """config 损坏 → verify 失败 → counter 不清零（v9 新增 case, Revision 3 判别器）。"""
        sandbox.config_path.write_text("{}", encoding="utf-8")
        sandbox.write_counter({"count": 4, "last_clean_at": 0, "since_mode": "auto"})
        from core.render_guard import begin, finish
        begin()
        finish()
        c = sandbox.read_counter()
        assert c["count"] >= 4  # verify 失败, counter 不清零
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


# ---------------------------------------------------------------------------
# TEST GROUP: audit prefix dynamic regression (v8 Rev1 终版)
# ---------------------------------------------------------------------------


class TestAuditPrefix:
    """v8 Rev1: audit 行必须带 [render_guard] 前缀, 否则裸文本被分类器当
    证据 → 误升级。"""

    def test_begin_audit_lines_dont_trigger_upgrade(self, monkeypatch, sandbox):
        """动态 fixture: monkeypatch _crash_fh → StringIO, 真实 begin 非升级
        路径, 对产出的文本断言下次 begin 分类为 clean_or_user。

        关键: fixture 必须用 sandbox.state_path / sandbox.crash_path
        (autouse patch_runtime_root 把 render_guard I/O 重定向到
        tmp_path/launcher/, begin 才看得见 state + crash.log)。
        """
        from io import StringIO
        import core.render_guard as rg
        fake_log = StringIO()
        monkeypatch.setattr("utils.logging._crash_fh", fake_log)

        # Arrange: state=starting, crash.log 两段 [startup] (上次 clean_or_user)
        sandbox.state_path.write_text(
            '{"state": "starting", "mode": "auto"}', encoding="utf-8"
        )
        sandbox.crash_path.write_text(
            "[startup] ts=prev1\n[startup] ts=prev2\n", encoding="utf-8"
        )

        # Act: 真实 begin() 走非升级路径（state=starting, 上次 clean_or_user）
        rg.begin()

        # Assert: 拼回 fixture 历史, 断言下次分类 clean_or_user
        fake_log.seek(0)
        written = fake_log.read()
        history = sandbox.crash_path.read_text(encoding="utf-8")
        next_session_text = history + written + "\n[startup] ts=next\n"
        assert rg._classify_last_exit(next_session_text) == "clean_or_user"


# ---------------------------------------------------------------------------
# TEST GROUP: classifier edge cases (v3 清单补全)
# ---------------------------------------------------------------------------


class TestClassifierEdges:
    """v6 F6: 补 v3 清单缺的 case (8/11/14/16/17) + v4 三便宜 case."""

    def test_classify_bare_exception_no_traceback(self):
        """case 8: 裸异常 (tb=None, print_exception 只输出异常类型行),
        在 [uncaught_exception] 块内 → python_exception。"""
        from core.render_guard import _classify_last_exit
        seg = (
            "[startup] ts=p\n"
            "[uncaught_exception] ts=...\n"
            "KeyError: 'x'\n"
            "[startup] ts=n\n"
        )
        assert _classify_last_exit(seg) == "python_exception"

    def test_classify_equals_separator_exits_marker_block(self):
        """case 17: = 分隔行 (utils/logging.py:194 写在 [startup] 之前)
        作为 marker 退出条件。"""
        from core.render_guard import _classify_last_exit
        seg = (
            "[startup] ts=p\n"
            "[uncaught_exception] ts=...\n"
            "ValueError: x\n"
            "=" * 60 + "\n"
            "[startup] ts=n\n"
        )
        # 块被 = 行关掉, 后续若再有非空非 marker 行就是 graphics_crash;
        # 这里 seg 在 = 后就到 [startup] 了, 走完 → clean_or_user
        # (没开新块, = 只是退出旧块)
        assert _classify_last_exit(seg) == "clean_or_user"

    def test_classify_marker_after_empty_block(self):
        """case 边界: [uncaught_exception] 后零内容 → 块内空, 走完
        in_marker_block=True → python_exception。"""
        from core.render_guard import _classify_last_exit
        seg = (
            "[startup] ts=p\n"
            "[uncaught_exception] ts=...\n"
            "[startup] ts=n\n"
        )
        assert _classify_last_exit(seg) == "python_exception"

    def test_classify_fatal_before_uncaught_returns_graphics_crash(self):
        """case 2: fatal 在前, uncaught 在后 (双失败边角):
        fatal 行块外直接 return graphics_crash, 不进 uncaught 块。"""
        from core.render_guard import _classify_last_exit
        seg = (
            "[startup] ts=p\n"
            "Windows fatal exception: access violation (0xC0000005)\n"
            "[uncaught_exception] ts=...\n"
            "ValueError: x\n"
            "[startup] ts=n\n"
        )
        assert _classify_last_exit(seg) == "graphics_crash"


# ---------------------------------------------------------------------------
# TEST GROUP: 升级即清零 + compat 未到阈值 (v5 F6)
# ---------------------------------------------------------------------------


class TestBeginCounterClearing:
    """升级触发即清零 + compat 未到阈值不变 mode。"""

    def test_begin_escalation_clears_counter(self, sandbox):
        """升级时 (verified 路径) counter 强制清零 (B 特性闭环)。"""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        sandbox.write_state(
            {"mode": "auto", "pid": 9999, "started_at": 0, "version": "old",
             "state": "running"}
        )
        sandbox.write_crash_log(_GRAPHICS_CRASH_SEG)
        sandbox.write_counter({"count": 7, "last_clean_at": 0, "since_mode": "auto"})

        from core.render_guard import begin
        begin()

        c = sandbox.read_counter()
        assert c["count"] == 0, f"升级后 counter 必须清零, got {c}"

    def test_begin_no_escalation_does_not_clear_counter(self, sandbox):
        """非升级路径 (clean_or_user / unknown) counter 不动。"""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        # state 不存在 → 跳过分类器 → clean_or_user → 不升级
        sandbox.write_counter({"count": 3, "last_clean_at": 0, "since_mode": "auto"})

        from core.render_guard import begin
        begin()

        c = sandbox.read_counter()
        assert c["count"] == 3, f"非升级路径 counter 不动, got {c}"


# ---------------------------------------------------------------------------
# TEST GROUP: 状态门 (v1 §1.3 落地测试)
# ---------------------------------------------------------------------------


class TestStateGate:
    """v10 F2: state 缺失/clean → 跳过分类器; running → 进分类器。"""

    def test_begin_state_missing_skips_classifier(self, sandbox):
        """state 缺失 + crash.log 含 graphics_crash 段 → 不升级
        (taskkill 无 /F / finish 正常删除后, 段内若含良性误报不应误升级)。"""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        # state 不写
        sandbox.write_crash_log(_GRAPHICS_CRASH_SEG)

        from core.render_guard import begin
        begin()
        assert not escalated_this_run(), (
            "state 缺失必须跳过分类器, graphics_crash 段不触发升级")
        assert current_mode() == "auto"

    def test_begin_state_clean_skips_classifier(self, sandbox):
        """state=clean 哨兵 + crash.log 含 graphics_crash 段 → 不升级
        (finish 删除失败写了哨兵, 段内若含良性误报不应误升级)。"""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        sandbox.write_state(
            {"mode": "auto", "started_at": 0, "version": "old",
             "cleaned_at": 1, "state": "clean"}
        )
        sandbox.write_crash_log(_GRAPHICS_CRASH_SEG)

        from core.render_guard import begin
        begin()
        assert not escalated_this_run(), (
            "state=clean 哨兵必须跳过分类器")
        assert current_mode() == "auto"

    def test_begin_state_running_enters_classifier(self, sandbox):
        """state=running (taskkill /F / 断电) + crash.log 含 graphics_crash
        段 → 升级。"""
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        sandbox.write_state(
            {"mode": "auto", "pid": 9999, "started_at": 0, "version": "old",
             "state": "running"}
        )
        sandbox.write_crash_log(_GRAPHICS_CRASH_SEG)

        from core.render_guard import begin
        begin()
        assert escalated_this_run() is True
        assert escalated_detail() == ("auto", "compat")
        assert current_mode() == "compat"

class TestDecodeFailure:
    """v11 R3: F1 strict 读 crash.log, GBK 等非 UTF-8 → UnicodeDecodeError → unknown → 不升级。"""

    def test_begin_gbk_crash_log_does_not_trigger_escalation(self, sandbox):
        import codecs
        sandbox.write_config({"ui_settings": {"render_mode": "auto"}})
        sandbox.write_state(
            {"mode": "auto", "pid": 9999, "started_at": 0, "version": "old",
             "state": "running"}
        )
        # 写 GBK 字节 (非 UTF-8)
        gbk_bytes = "正常内容 + 一些 GBK 字符".encode("gbk")
        # 需要 2 个 [startup] 段, 段内含 GBK 字节
        # 直接 bytes 写入, sandbox.write_crash_log 期望 str
        sandbox.crash_path.write_bytes(
            b"[startup] ts=p\n" + gbk_bytes + b"\n[startup] ts=n\n"
        )

        from core.render_guard import begin
        begin()
        # strict 读取抛 UnicodeDecodeError → crash_text="" → unknown → 不升级
        assert escalated_this_run() is False
        assert current_mode() == "auto"
