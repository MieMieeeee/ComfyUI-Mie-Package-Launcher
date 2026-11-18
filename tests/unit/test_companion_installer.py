"""Tests for core.companion.installer (通用 clone/pull + 用户数据保护).

最要紧的一条是「更新不能碰用户的资产与密钥」:
`git fetch + reset --hard origin/HEAD` 会把**被 git 跟踪**的文件还原回仓库版本,
而用户的资产库 (实测 220MB) 与 LLM 密钥就住在插件目录里. 未跟踪 + 被 .gitignore
忽略的文件不受影响 —— installer.protect_user_data 负责在更新前体检, 发现被
跟踪就自动从索引摘掉.

用**本地 git 仓库**当源 (不起网络), 真跑 git 命令.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                       text=True, errors="ignore",
                       env={**GIT_ENV, "PATH": __import__("os").environ.get("PATH", "")},
                       timeout=60)
    assert r.returncode == 0, "git %s failed: %s" % (args, r.stderr)
    return r.stdout


@pytest.fixture()
def git_repo(tmp_path):
    """一个本地 git 仓库: 有 webapp/__main__.py 入口 + 被忽略的用户数据."""
    repo = tmp_path / "src"
    repo.mkdir()
    (repo / "webapp").mkdir()
    (repo / "webapp" / "__main__.py").write_text("# entry", encoding="utf-8")
    (repo / "requirements.txt").write_text("flask>=3.0\n", encoding="utf-8")
    (repo / ".gitignore").write_text("asset_library/\nmie_llm_keys.json\n",
                                     encoding="utf-8")
    _git(repo, "init", "-q", ".")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


class _App:
    def __init__(self, cwd=None, cfg=None):
        self._cwd = str(cwd) if cwd else "."
        self.config = cfg if cfg is not None else {}
        self.logger = type("L", (), {"info": lambda *a, **kw: None,
                                     "warning": lambda *a, **kw: None})()

    def resolve_git(self):
        return "git", None


# ---------------- clone ----------------

def test_clone_service_clones_local_repo(tmp_path, git_repo):
    from core.companion import installer
    target = tmp_path / "dst" / "ComfyUI-Mie-H3-Engine"
    res = installer.clone_service(
        _App(tmp_path), target, repo_url=str(git_repo),
        entry_markers=("webapp/__main__.py",))
    assert res["ok"] is True
    assert (target / "webapp" / "__main__.py").exists()


def test_clone_service_skips_existing_dir(tmp_path, git_repo):
    """目录已有内容 → 跳过下载 (绝不删用户数据)."""
    from core.companion import installer
    target = tmp_path / "dst"
    target.mkdir()
    (target / "my_stuff.txt").write_text("keep me", encoding="utf-8")
    res = installer.clone_service(
        _App(tmp_path), target, repo_url=str(git_repo),
        entry_markers=("webapp/__main__.py",))
    assert res["ok"] is True
    assert res["already_exists"] is True
    assert (target / "my_stuff.txt").exists()


def test_clone_service_reports_missing_entry(tmp_path, git_repo):
    from core.companion import installer
    target = tmp_path / "dst"
    res = installer.clone_service(
        _App(tmp_path), target, repo_url=str(git_repo),
        entry_markers=("webapp/__main__.py",))
    assert res["ok"] is True
    # 再对同一个源 clone 到别处但故意要求一个不存在的入口 → 应报错
    bad = tmp_path / "dst2"
    res2 = installer.clone_service(
        _App(tmp_path), bad, repo_url=str(git_repo),
        entry_markers=("webapp/does_not_exist.py",))
    assert res2["ok"] is False
    assert "does_not_exist.py" in (res2["error"] or "")


# ---------------- 用户数据保护 ----------------

def test_protect_user_data_leaves_untracked_data_alone(tmp_path, git_repo):
    """数据没被跟踪 + 被 .gitignore 忽略 → 原样不动."""
    from core.companion import installer
    lib = git_repo / "asset_library"
    lib.mkdir()
    (lib / "hero.json").write_text("{}", encoding="utf-8")
    (git_repo / "mie_llm_keys.json").write_text("{}", encoding="utf-8")
    res = installer.protect_user_data(
        _App(tmp_path), git_repo, ("asset_library", "mie_llm_keys.json"))
    assert res["ok"] is True
    assert res["tracked"] == []
    assert res["stashed"] == {}
    assert (lib / "hero.json").exists()


def test_protect_user_data_stashes_tracked_data(tmp_path, git_repo):
    """数据被跟踪了 → 挪到仓库外暂存 (文件不会丢), 恢复后原样回来."""
    from core.companion import installer
    lib = git_repo / "asset_library"
    lib.mkdir()
    (lib / "hero.json").write_text("{\"mine\": true}", encoding="utf-8")
    (git_repo / "mie_llm_keys.json").write_text("{\"key\": \"secret\"}", encoding="utf-8")
    # 强行提交进去 (模拟历史遗留: 数据曾经被跟踪)
    _git(git_repo, "add", "-f", "asset_library/hero.json", "mie_llm_keys.json")
    _git(git_repo, "commit", "-qm", "accidentally tracked user data")

    res = installer.protect_user_data(
        _App(tmp_path), git_repo, ("asset_library", "mie_llm_keys.json"))
    assert res["ok"] is True
    assert "asset_library" in res["tracked"]
    assert "asset_library" in res["stashed"]
    # 原位置空了 (数据在仓库外的暂存里)
    assert not (git_repo / "asset_library" / "hero.json").exists()
    # 恢复后原样回来
    installer.restore_user_data(git_repo, res["stashed"])
    assert "mine" in (git_repo / "asset_library" / "hero.json").read_text(encoding="utf-8")
    assert "secret" in (git_repo / "mie_llm_keys.json").read_text(encoding="utf-8")


def test_pull_service_keeps_user_data_after_reset(tmp_path, git_repo):
    """**核心保证**: 更新 (fetch + reset --hard) 之后用户的数据还在."""
    from core.companion import installer
    # 先把数据提交进去 (最坏情况)
    lib = git_repo / "asset_library"
    lib.mkdir()
    (lib / "hero.json").write_text("{}", encoding="utf-8")
    (git_repo / "mie_llm_keys.json").write_text("{}", encoding="utf-8")
    _git(git_repo, "add", "-f", "asset_library/hero.json", "mie_llm_keys.json")
    _git(git_repo, "commit", "-qm", "tracked user data")

    target = tmp_path / "dst"
    _git(tmp_path, "clone", "-q", str(git_repo), str(target))

    # 源仓库再推一个新提交 (模拟远端有新版本)
    (git_repo / "webapp" / "__main__.py").write_text("# entry v2", encoding="utf-8")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "v2")

    # 用户数据在目标里 (且被跟踪 —— 最坏情况)
    tlib = target / "asset_library"
    tlib.mkdir(exist_ok=True)
    (tlib / "hero.json").write_text("{\"mine\": true}", encoding="utf-8")
    (target / "mie_llm_keys.json").write_text("{\"key\": \"secret\"}", encoding="utf-8")
    res = installer.pull_service(
        _App(tmp_path), target, protected_paths=("asset_library", "mie_llm_keys.json"))
    assert res["ok"] is True, res.get("error")
    # 代码更新了
    assert "entry v2" in (target / "webapp" / "__main__.py").read_text(encoding="utf-8")
    # **用户数据还在, 内容没变**
    assert (tlib / "hero.json").exists()
    assert "mine" in (tlib / "hero.json").read_text(encoding="utf-8")
    assert (target / "mie_llm_keys.json").exists()
    assert "secret" in (target / "mie_llm_keys.json").read_text(encoding="utf-8")


# ---------------- 依赖安装 (镜像滞后回退) ----------------

def test_install_requirements_retries_missing_from_official_pypi(tmp_path, monkeypatch):
    """镜像上没有的新版本 → 用官方 PyPI 再试一次 (不能传 None: 那会用 pip.ini 的镜像).

    注意: **催镜像收录是发布侧的事** (各包仓库 tools/notify_mirrors.py), 启动器
    不去请求镜像 —— 安装侧只负责「按首页配置的镜像装 → 没有就用官方源兜底」。
    """
    from core.companion import installer
    import utils.pip as PIPUTILS

    req = tmp_path / "requirements.txt"
    req.write_text("comfyui-mie-craft>=0.2.0\n", encoding="utf-8")
    py = tmp_path / "python.exe"
    py.write_text("# fake", encoding="utf-8")

    calls = []

    def _fake_requirements_file(requirements_file, python_exec, **kw):
        calls.append(("bulk", kw.get("index_url")))
        return {"success": False, "partial": True, "installed": [],
                "satisfied": [], "missing": ["comfyui-mie-craft>=0.2.0"],
                "failed": [], "frozen": [], "error": None}

    def _fake_install_one(spec, python_exec, index_url=None, **kw):
        calls.append(("one", index_url))
        return {"success": True, "error": None}

    monkeypatch.setattr(PIPUTILS, "install_requirements_file", _fake_requirements_file)
    monkeypatch.setattr(PIPUTILS, "install_or_update_package", _fake_install_one)
    monkeypatch.setattr("utils.net.resolve_pypi_index_url",
                        lambda app: "https://mirror.example/simple/")

    res = installer.install_requirements(_App(tmp_path), py, req)
    assert res["ok"] is True
    assert res["missing"] == []
    # 先按镜像装, 再用官方源兜底
    assert ("bulk", "https://mirror.example/simple/") in calls
    assert ("one", installer.OFFICIAL_PYPI_INDEX) in calls
    assert installer.OFFICIAL_PYPI_INDEX.startswith("https://pypi.org")


def test_install_requirements_uses_homepage_mirror_config(tmp_path, monkeypatch):
    """镜像地址必须来自**首页（启动与更新页的环境区）那份配置**."""
    from core.companion import installer
    import utils.pip as PIPUTILS

    req = tmp_path / "requirements.txt"
    req.write_text("flask\n", encoding="utf-8")
    py = tmp_path / "python.exe"
    py.write_text("# fake", encoding="utf-8")

    seen = {}

    def _fake_requirements_file(requirements_file, python_exec, **kw):
        seen["index_url"] = kw.get("index_url")
        return {"success": True, "installed": ["flask"], "satisfied": [],
                "missing": [], "failed": [], "error": None}

    monkeypatch.setattr(PIPUTILS, "install_requirements_file", _fake_requirements_file)
    # app 只有 config (没有 GUI 的实时变量) → 也必须解析出首页那份镜像
    app = _App(tmp_path, {"proxy_settings": {
        "pypi_proxy_mode": "huaweicloud",
        "pypi_proxy_url": "",
    }})
    res = installer.install_requirements(app, py, req)
    assert res["ok"] is True
    assert "huaweicloud" in seen["index_url"]


def test_install_requirements_reports_failure(tmp_path, monkeypatch):
    from core.companion import installer
    import utils.pip as PIPUTILS

    req = tmp_path / "requirements.txt"
    req.write_text("nope>=1\n", encoding="utf-8")
    py = tmp_path / "python.exe"
    py.write_text("# fake", encoding="utf-8")

    monkeypatch.setattr(
        PIPUTILS, "install_requirements_file",
        lambda f, p, **kw: {"success": False, "installed": [], "satisfied": [],
                            "missing": ["nope>=1"], "failed": [], "error": None})
    monkeypatch.setattr(
        PIPUTILS, "install_or_update_package",
        lambda spec, p, index_url=None, **kw: {"success": False,
                                               "error": "装不上"})
    monkeypatch.setattr("utils.net.resolve_pypi_index_url",
                        lambda app: "https://mirror.example/simple/")
    res = installer.install_requirements(_App(tmp_path), py, req)
    assert res["ok"] is False
    assert res["missing"] == ["nope>=1"]


def test_pull_service_uses_commit_from_proxy_not_origin_head(tmp_path, git_repo, monkeypatch):
    from core.companion import installer

    target = tmp_path / "target"
    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(git_repo), str(target))
    _git(tmp_path, "clone", "-q", str(git_repo), str(mirror))
    _git(target, "remote", "set-url", "origin", "https://github.com/example/repo.git")
    (mirror / "requirements.txt").write_text("flask>=3.1\n", encoding="utf-8")
    _git(mirror, "commit", "-qam", "mirror update")
    expected = _git(mirror, "rev-parse", "HEAD").strip()
    monkeypatch.setattr(installer, "_proxy_settings", lambda app: {"git_proxy_mode": "custom"})
    monkeypatch.setattr(installer, "_apply_git_proxy", lambda app, url: str(mirror))

    result = installer.pull_service(_App(tmp_path), target)
    assert result["ok"] and result["updated"], result
    assert _git(target, "rev-parse", "HEAD").strip() == expected
    again = installer.pull_service(_App(tmp_path), target)
    assert again["ok"] and not again["updated"], again


def test_pull_refuses_dirty_and_divergent_code(tmp_path, git_repo):
    from core.companion import installer

    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(git_repo), str(target))
    code = target / "requirements.txt"
    code.write_text("flask>=3.5" + chr(10), encoding="utf-8")
    before = _git(target, "rev-parse", "HEAD")
    assert not installer.pull_service(_App(tmp_path), target)["ok"]
    assert _git(target, "rev-parse", "HEAD") == before
    assert "3.5" in code.read_text(encoding="utf-8")
    _git(target, "commit", "-qam", "local code")
    (git_repo / "requirements.txt").write_text("flask>=3.1" + chr(10), encoding="utf-8")
    _git(git_repo, "commit", "-qam", "upstream code")
    before = _git(target, "rev-parse", "HEAD")
    assert not installer.pull_service(_App(tmp_path), target)["ok"]
    assert _git(target, "rev-parse", "HEAD") == before


def test_partial_backup_is_restored(tmp_path, git_repo, monkeypatch):
    from core.companion import installer

    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(git_repo), str(target))
    library = target / "asset_library"
    library.mkdir()
    (library / "user.txt").write_text("my asset", encoding="utf-8")
    keys = target / "mie_llm_keys.json"
    keys.write_text("my settings", encoding="utf-8")
    upstream_library = git_repo / "asset_library"
    upstream_library.mkdir()
    (upstream_library / "example").touch()
    (git_repo / "mie_llm_keys.json").touch()
    _git(git_repo, "add", "-f", "asset_library", "mie_llm_keys.json")
    _git(git_repo, "commit", "-qm", "track template files")
    original_replace = type(target).replace

    def replace(source, dst):
        if source == keys:
            raise OSError("simulated failed move")
        return original_replace(source, dst)

    monkeypatch.setattr(type(target), "replace", replace)
    before = _git(target, "rev-parse", "HEAD")
    result = installer.pull_service(_App(tmp_path), target,
                                    protected_paths=("asset_library", keys.name))
    assert not result["ok"]
    assert _git(target, "rev-parse", "HEAD") == before
    assert (library / "user.txt").read_text(encoding="utf-8") == "my asset"
    assert keys.read_text(encoding="utf-8") == "my settings"


def test_restore_failure_reports_recovery_copy(tmp_path, git_repo, monkeypatch):
    from core.companion import installer

    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(git_repo), str(target))
    keys = target / "mie_llm_keys.json"
    keys.write_text("my original settings", encoding="utf-8")
    (git_repo / keys.name).write_text("default", encoding="utf-8")
    _git(git_repo, "add", "-f", keys.name)
    _git(git_repo, "commit", "-qm", "track template")
    original_replace = type(keys).replace

    def replace(source, dst):
        if dst == keys:
            raise OSError("simulated failed restore")
        return original_replace(source, dst)

    monkeypatch.setattr(type(keys), "replace", replace)
    result = installer.pull_service(_App(tmp_path), target, protected_paths=(keys.name,))
    copy, = tmp_path.glob(f"{target.name}.userdata.bak-*/{keys.name}")
    assert not result["ok"] and str(copy) in result["error"]
    assert copy.read_text(encoding="utf-8") == "my original settings"
