"""Tests for core.cli.pidfile.

pidfile 是 CLI 跨进程协调 start / stop 的契约：
- start 写入 {pid, port, started_at, log_path}
- stop 清理文件
- status 读取并校验 PID 是否还活着（stale 文件当成不存在）

文件位置：<cwd>/launcher/comfyui.pid
"""
import json
import os
import time
from pathlib import Path

import pytest

from core.cli.pidfile import (
    PIDFILE_NAME,
    default_path,
    read,
    write,
    clear,
    is_alive,
    is_stale,
)


# ---------- default_path ----------

def test_default_path_is_under_launcher_dir(tmp_path):
    """默认 pidfile 路径必须在 <cwd>/launcher/comfyui.pid。"""
    p = default_path(tmp_path)
    assert p == tmp_path / "launcher" / "comfyui.pid"


def test_default_path_creates_launcher_dir_if_missing(tmp_path):
    """cwd 存在但 launcher/ 不存在时，路径仍应指向 launcher/comfyui.pid（不自动建，调用方负责）。"""
    p = default_path(tmp_path)
    assert p.parent.name == "launcher"
    # 不会自动创建
    assert not p.parent.exists()


# ---------- write / read / clear round-trip ----------

def test_write_creates_file_with_expected_fields(tmp_path):
    """write 后文件应包含 pid / port / started_at / log_path 四个字段。"""
    target = default_path(tmp_path)
    write(target, pid=1234, port=8188, log_path=Path("C:/logs/x.log"))
    assert target.exists()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["pid"] == 1234
    assert data["port"] == 8188
    assert data["log_path"] == "C:\\logs\\x.log" or data["log_path"] == "C:/logs/x.log"
    assert "started_at" in data
    # started_at 应是 ISO 8601 格式
    from datetime import datetime
    datetime.fromisoformat(data["started_at"])


def test_read_returns_none_when_missing(tmp_path):
    """pidfile 不存在时 read 应返回 None，不抛异常。"""
    assert read(default_path(tmp_path)) is None


def test_read_returns_data_when_fresh(tmp_path, monkeypatch):
    """PID 还在运行时 read 返回该 pidfile 内容。"""
    target = default_path(tmp_path)
    # 写一个我们自己进程当 pid — 它一定活着
    my_pid = os.getpid()
    write(target, pid=my_pid, port=8188, log_path=None)
    data = read(target)
    assert data is not None
    assert data["pid"] == my_pid
    assert data["port"] == 8188


def test_read_returns_none_when_pid_dead(tmp_path):
    """PID 已死时（stale），read 返回 None，让调用方按未运行处理。"""
    target = default_path(tmp_path)
    # 写一个一定不存在的 PID（高位数字降低撞车概率）
    dead_pid = 999_999_999
    write(target, pid=dead_pid, port=8188, log_path=None)
    assert read(target) is None


def test_read_returns_none_when_file_malformed(tmp_path):
    """pidfile 内容不是合法 JSON 时 read 返回 None，不抛异常。"""
    target = default_path(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not json {{{", encoding="utf-8")
    assert read(target) is None


def test_read_returns_none_when_pid_missing(tmp_path):
    """pidfile JSON 缺 pid 字段时 read 返回 None（视为损坏）。"""
    target = default_path(tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"port": 8188}), encoding="utf-8")
    assert read(target) is None


def test_clear_removes_file(tmp_path):
    """clear 应删除 pidfile。"""
    target = default_path(tmp_path)
    write(target, pid=os.getpid(), port=8188, log_path=None)
    assert target.exists()
    clear(target)
    assert not target.exists()


def test_clear_is_noop_when_missing(tmp_path):
    """pidfile 不存在时 clear 不应抛异常。"""
    target = default_path(tmp_path)
    # 文件不存在
    clear(target)  # 不抛


# ---------- is_alive ----------

def test_is_alive_self_true():
    """当前进程一定活着。"""
    assert is_alive(os.getpid()) is True


def test_is_alive_dead_pid_false():
    """不存在的 PID 应判定为 dead。"""
    assert is_alive(999_999_999) is False


def test_is_alive_invalid_pid_false():
    """非法 PID（0 / 负数）应判定为 dead，不抛异常。"""
    assert is_alive(0) is False
    assert is_alive(-1) is False


# ---------- is_stale ----------

def test_is_stale_missing_file(tmp_path):
    """文件不存在时 is_stale == True（等价于 stale）。"""
    assert is_stale(default_path(tmp_path)) is True


def test_is_stale_dead_pid(tmp_path):
    """PID 已死时 is_stale == True。"""
    target = default_path(tmp_path)
    write(target, pid=999_999_999, port=8188, log_path=None)
    assert is_stale(target) is True


def test_is_stale_alive_pid(tmp_path):
    """PID 还在跑时 is_stale == False。"""
    target = default_path(tmp_path)
    write(target, pid=os.getpid(), port=8188, log_path=None)
    assert is_stale(target) is False


def test_pidfile_name_constant():
    """PIDFILE_NAME 暴露给其他模块用，文件名应稳定。"""
    assert PIDFILE_NAME == "comfyui.pid"
