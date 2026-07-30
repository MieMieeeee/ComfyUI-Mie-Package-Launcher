"""Tests for core.webui_installer.clone_webui / pull_webui."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


class _FakeApp:
    def __init__(self, has_git=True, git_path="C:/fake/git.exe"):
        self.has_git = has_git
        self.git_path = git_path
        self.config = {
            "proxy_settings": {"git_proxy_mode": "none", "git_proxy_url": ""},
        }

    def resolve_git(self):
        if self.has_git:
            return (self.git_path, "fake")
        return (None, "no git")


def test_clone_no_git(tmp_path):
    from core.webui_installer import clone_webui
    app = _FakeApp(has_git=False)
    res = clone_webui(app, tmp_path / "webui")
    assert res["ok"] is False
    assert "git" in res["error"].lower()


def test_clone_target_exists_skips(tmp_path):
    """目标目录已有内容时不重 clone."""
    from core.webui_installer import clone_webui
    target = tmp_path / "webui"
    target.mkdir()
    (target / "app").mkdir()
    (target / "README.md").write_text("placeholder", encoding="utf-8")
    app = _FakeApp()
    res = clone_webui(app, target)
    assert res["ok"] is True
    assert res.get("already_exists") is True


def test_clone_success(monkeypatch, tmp_path):
    from core.webui_installer import clone_webui, WEBUI_DEFAULT_REPO

    popen_calls = []

    class _FakePopen:
        def __init__(self, cmd, **kw):
            popen_calls.append((cmd, kw))
            self.stdout = iter([
                "Cloning into 'Comfyui-Workbench-Mie'...\n",
                "remote: Counting objects: 100, done.\n",
                "Receiving objects: 100% (100/100), done.\n",
            ])

        def wait(self):
            # 模拟成功: 同时创建 flask_app.py 让 validate 通过
            (tmp_path / "webui" / "app").mkdir(parents=True, exist_ok=True)
            (tmp_path / "webui" / "app" / "flask_app.py").write_text("# stub", encoding="utf-8")
            return 0

    def fake_popen(cmd, **kw):
        return _FakePopen(cmd, **kw)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    app = _FakeApp()
    res = clone_webui(app, tmp_path / "webui")
    assert res["ok"] is True
    assert len(popen_calls) == 1
    cmd, _ = popen_calls[0]
    assert cmd[0] == "C:/fake/git.exe"
    assert cmd[1:4] == ["clone", "--depth", "1"]
    assert cmd[4] == WEBUI_DEFAULT_REPO
    assert cmd[5] == str(tmp_path / "webui")


def test_clone_applies_gh_proxy(monkeypatch, tmp_path):
    """gh-proxy mode 时 clone URL 应被改写."""
    from core.webui_installer import clone_webui

    popen_calls = []

    class _FakePopen:
        def __init__(self, cmd, **kw):
            popen_calls.append(cmd)
            self.stdout = iter([])
        def wait(self):
            (tmp_path / "webui" / "app").mkdir(parents=True, exist_ok=True)
            (tmp_path / "webui" / "app" / "flask_app.py").write_text("# stub", encoding="utf-8")
            return 0

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    app = _FakeApp()
    app.config["proxy_settings"]["git_proxy_mode"] = "gh-proxy"
    res = clone_webui(app, tmp_path / "webui")
    assert res["ok"] is True
    cmd = popen_calls[0]
    clone_url = cmd[4]
    assert clone_url.startswith("https://gh-proxy.com/")
    assert "github.com/MieMieeeee/Comfyui-Workbench-Mie" in clone_url


def test_clone_fails_when_no_entry_file(monkeypatch, tmp_path):
    """clone 成功但缺 app/flask_app.py 视为失败."""
    from core.webui_installer import clone_webui

    class _FakePopen:
        def __init__(self, cmd, **kw):
            self.stdout = iter([])
        def wait(self):
            # 不创建 flask_app.py
            (tmp_path / "webui").mkdir(parents=True, exist_ok=True)
            return 0

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    app = _FakeApp()
    res = clone_webui(app, tmp_path / "webui")
    assert res["ok"] is False
    assert "flask_app" in res["error"]


def test_clone_nonzero_exit(monkeypatch, tmp_path):
    from core.webui_installer import clone_webui

    class _FakePopen:
        def __init__(self, cmd, **kw):
            self.stdout = iter(["fatal: repository not found\n"])
        def wait(self):
            return 128

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    app = _FakeApp()
    res = clone_webui(app, tmp_path / "webui")
    assert res["ok"] is False
    assert "128" in res["error"]


def test_pull_no_git_repo(tmp_path):
    from core.webui_installer import pull_webui
    target = tmp_path / "webui"
    target.mkdir()
    app = _FakeApp()
    res = pull_webui(app, target)
    assert res["ok"] is False
    assert "git" in res["error"].lower()


def test_pull_success(monkeypatch, tmp_path):
    from core.webui_installer import pull_webui

    target = tmp_path / "webui"
    target.mkdir()
    (target / ".git").mkdir()

    class _FakePopen:
        def __init__(self, cmd, **kw):
            self.stdout = iter([
                "Updating 1234..5678\n",
                "Fast-forward\n",
                " app/flask_app.py | 2 +-\n",
                "Already up to date.\n",  # 实际是 already up to date 时这句话才出现
            ])
        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    app = _FakeApp()
    res = pull_webui(app, target)
    assert res["ok"] is True


# ---------- 回归: WinError 6 (git clone/pull 在 GUI 模式下继承无效句柄) ----------

def _capture_popen_kwargs(monkeypatch):
    """monkeypatch subprocess.Popen, 捕获 (cmd, kwargs). 返回 captured list."""
    captured = []

    class _FakePopen:
        def __init__(self, cmd, **kw):
            captured.append((cmd, kw))
            self.stdout = iter(["Cloning...\n"])

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: _FakePopen(cmd, **kw))
    return captured


def test_clone_sets_stdin_devnull_to_avoid_winerror6(monkeypatch, tmp_path):
    """clone_webui 的 Popen 必须传 stdin=DEVNULL (GUI 模式下避免 [WinError 6] 句柄无效).

    回归: 原实现 Popen 没设 stdin/creationflags/startupinfo, git 进程 attach console
    时继承无效句柄, subprocess._get_handles 抛 [WinError 6], 用户点"下载工作台"失败.
    """
    from core.webui_installer import clone_webui

    captured = _capture_popen_kwargs(monkeypatch)
    # 让 clone 走到 Popen (target 空 + git 可用)
    target = tmp_path / "webui"
    # 校验入口会失败 (没创建 flask_app.py), 但 Popen kwargs 已被捕获
    clone_webui(_FakeApp(), target)
    assert captured, "应调用 Popen"
    _, kw = captured[0]
    assert kw.get("stdin") == subprocess.DEVNULL, "clone Popen 应设 stdin=DEVNULL 避免 WinError 6"
    # win32 还应有 CREATE_NO_WINDOW + startupinfo
    import os
    if os.name == "nt":
        assert kw.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW, "win32 应设 CREATE_NO_WINDOW"
        assert kw.get("startupinfo") is not None, "win32 应设 startupinfo"


def test_pull_sets_stdin_devnull_to_avoid_winerror6(monkeypatch, tmp_path):
    """pull_webui 的 Popen 必须传 stdin=DEVNULL (同 clone 的 WinError 6 修复)."""
    from core.webui_installer import pull_webui

    captured = _capture_popen_kwargs(monkeypatch)
    target = tmp_path / "webui"
    target.mkdir()
    (target / ".git").mkdir()  # pull 要求 .git 存在
    pull_webui(_FakeApp(), target)
    assert captured, "应调用 Popen"
    _, kw = captured[0]
    assert kw.get("stdin") == subprocess.DEVNULL, "pull Popen 应设 stdin=DEVNULL 避免 WinError 6"
    import os
    if os.name == "nt":
        assert kw.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW, "win32 应设 CREATE_NO_WINDOW"
