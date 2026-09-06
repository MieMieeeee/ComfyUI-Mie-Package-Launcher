"""build._scrub_release_dir: 清理发布子目录里跑 boxed exe 留下的本地状态。

历史: 2026-09-06 一次自检 (info --json) 在 release 子目录里跑 boxed exe,
启动器自动建了 launcher/config.json 等, 这些是机器本地状态, AGENTS.md
§3 明确不能进 git。本测试锁住 _scrub_release_dir 的清理行为。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

@pytest.fixture
def fake_release_dir(tmp_path):
    sub = tmp_path / "release_test"
    sub.mkdir()
    (sub / "ComfyUI启动器.exe").write_bytes(b"")
    (sub / "ComfyUI启动器-CLI.cmd").write_text("@echo off\r\n", encoding="utf-8")
    (sub / "使用说明.md").write_text("# 使用说明\n", encoding="utf-8")
    launcher = sub / "launcher"
    launcher.mkdir()
    (launcher / "config.json").write_text(
        json.dumps({"environments": [], "active_env_id": None, "paths": {}}),
        encoding="utf-8",
    )
    (launcher / "crash.log").write_text("[startup] ts=...\n", encoding="utf-8")
    (sub / "dirty.json").write_text("{}", encoding="utf-8")
    return sub

def test_scrub_removes_launcher_subdir_and_stray_json(fake_release_dir):
    sys.path.insert(0, str(PROJECT_ROOT))
    import importlib
    if "build" in sys.modules:
        importlib.reload(sys.modules["build"])
    import build
    build._scrub_release_dir(str(fake_release_dir))
    assert not (fake_release_dir / "launcher").exists(), "launcher/ 子目录应被清掉"
    assert (fake_release_dir / "ComfyUI启动器.exe").exists()
    assert (fake_release_dir / "ComfyUI启动器-CLI.cmd").exists()
    assert (fake_release_dir / "使用说明.md").exists()
    assert not (fake_release_dir / "dirty.json").exists(), "未列入白名单的 .json 应被清掉"

def test_scrub_no_op_on_clean_dir(tmp_path):
    sub = tmp_path / "clean_release"
    sub.mkdir()
    for n in ["ComfyUI启动器.exe", "ComfyUI启动器-CLI.cmd", "使用说明.md", "AGENTS.md", "cli.md"]:
        (sub / n).write_text("", encoding="utf-8")
    sys.path.insert(0, str(PROJECT_ROOT))
    import importlib
    if "build" in sys.modules:
        importlib.reload(sys.modules["build"])
    import build
    build._scrub_release_dir(str(sub))
    assert len(list(sub.iterdir())) == 5, "scrub 在干净目录上应该是 no-op"
    for n in ["ComfyUI启动器.exe", "ComfyUI启动器-CLI.cmd", "使用说明.md", "AGENTS.md", "cli.md"]:
        assert (sub / n).exists()