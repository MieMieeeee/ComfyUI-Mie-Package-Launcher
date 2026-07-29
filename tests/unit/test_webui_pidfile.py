"""Tests for core.cli.webui_pidfile.

跟 tests/unit/test_cli_pidfile.py 同模式, 但路径独立 (webui.pid vs comfyui.pid).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def fake_cwd(tmp_path, monkeypatch) -> Path:
    """pyfakefs 不在 requirements, 用 tmp_path 模拟 cwd."""
    (tmp_path / "launcher").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_payload(pid: int, port: int = 8199, env_id: str = "env_a") -> Path:
    """直接构造一个 webui.pid (死 PID) 用于 stale 测试."""
    import sys
    # 借用已 import 的 webui_pidfile 模块
    from core.cli import webui_pidfile
    p = webui_pidfile.default_path(webui_pidfile.Path(tmp_path if False else Path.cwd()).parent)  # noqa
    return p


def test_default_path(fake_cwd):
    from core.cli.webui_pidfile import default_path
    p = default_path(fake_cwd)
    assert p == fake_cwd / "launcher" / "webui.pid"


def test_read_missing_returns_none(fake_cwd):
    from core.cli.webui_pidfile import read
    assert read(fake_cwd / "launcher" / "webui.pid") is None


def test_is_alive_negative():
    from core.cli.webui_pidfile import is_alive
    assert is_alive(0) is False
    assert is_alive(-1) is False
    assert is_alive(None) is False  # type: ignore


def test_write_then_read_with_live_pid(fake_cwd):
    """写一个当前 python 进程的 pid, 立即 read 应该能读出来."""
    from core.cli import webui_pidfile
    p = webui_pidfile.default_path(fake_cwd)
    pid = os.getpid()
    webui_pidfile.write(p, pid, 8199, log_path=fake_cwd / "webui.log", env_id="env_a")
    data = webui_pidfile.read(p)
    assert data is not None
    assert data["pid"] == pid
    assert data["port"] == 8199
    assert data["env_id"] == "env_a"
    assert data["log_path"].endswith("webui.log")


def test_read_returns_none_for_dead_pid(fake_cwd):
    """写一个明显死亡的 PID, read 应该返 None (stale 校验)."""
    from core.cli import webui_pidfile
    p = webui_pidfile.default_path(fake_cwd)
    # 999999 一般不在跑
    webui_pidfile.write(p, 999999, 8199, log_path=None, env_id="env_a")
    assert webui_pidfile.read(p) is None


def test_is_stale_missing(fake_cwd):
    from core.cli.webui_pidfile import is_stale
    assert is_stale(fake_cwd / "launcher" / "webui.pid") is True


def test_clear_missing(fake_cwd):
    """clear 对不存在的文件应该 no-op, 不抛."""
    from core.cli.webui_pidfile import clear
    p = fake_cwd / "launcher" / "webui.pid"
    assert not p.exists()
    clear(p)
    assert not p.exists()


def test_clear_existing(fake_cwd):
    from core.cli import webui_pidfile
    p = webui_pidfile.default_path(fake_cwd)
    webui_pidfile.write(p, os.getpid(), 8199, log_path=fake_cwd/"webui.log", env_id="env_a")
    assert p.exists()
    webui_pidfile.clear(p)
    assert not p.exists()


def test_write_creates_parent_dir(tmp_path):
    """父目录 launcher/ 不存在时, write 自动建."""
    from core.cli.webui_pidfile import write
    p = tmp_path / "launcher" / "webui.pid"
    assert not p.parent.exists()
    write(p, os.getpid(), 8199, log_path=None, env_id="env_a")
    assert p.exists()


def test_read_corrupted_json_returns_none(fake_cwd):
    from core.cli.webui_pidfile import read
    p = fake_cwd / "launcher" / "webui.pid"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json{", encoding="utf-8")
    assert read(p) is None
