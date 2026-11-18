"""Tests for core.companion: spec 声明 / registry 解析 / pidstore / proctree 纯逻辑."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


CFG = {
    "environments": [
        {"id": "env_a", "comfyui_root": None, "python_path": "python_embeded/python.exe"},  # 测试里填 tmp
        {"id": "env_b", "comfyui_root": None, "python_path": "python_embeded/python.exe"},
    ],
    "active_env_id": "env_a",
}


class _App:
    def __init__(self, cwd=None, cfg=None):
        self._cwd = str(cwd) if cwd else "."
        self.config = cfg if cfg is not None else {}
        self.logger = type("L", (), {"info": lambda *a, **kw: None,
                                     "warning": lambda *a, **kw: None})()


def _mk_pkg(tmp_path: Path, env="openjutsu", complete=True) -> Path:
    """造一个假包根: comfyui_root; complete=False 时缺 entry_markers."""
    pkg = tmp_path / "pkg"
    root = pkg / env
    root.mkdir(parents=True)
    if complete:
        (root / "package.json").write_text("{}", encoding="utf-8")
        (root / "patch_proxy.py").write_text("# patch", encoding="utf-8")
    return pkg


def _cfg_with(pkg: Path) -> dict:
    import copy
    cfg = copy.deepcopy(CFG)
    for e in cfg["environments"]:
        e["comfyui_root"] = str(pkg)
    return cfg


# ---------------- spec ----------------

def test_builtin_registry_contents():
    from core.companion.spec import BUILTIN_SERVICES
    assert set(BUILTIN_SERVICES) == {"webui", "openjutsu", "h3-engine"}
    w = BUILTIN_SERVICES["webui"]
    assert w.runtime == "webui-legacy"
    assert w.requires_comfyui is False
    o = BUILTIN_SERVICES["openjutsu"]
    assert o.runtime == "openjutsu"
    assert o.requires_comfyui is True
    assert {b.role for b in o.ports} == {"proxy", "app"}
    assert {b.default_port for b in o.ports} == {8197, 8198}
    assert o.browser_url_role == "app"
    # H3 短剧工作台 (2026-11-18 接入): 单端口 8200, 不要求 ComfyUI 在跑
    h = BUILTIN_SERVICES["h3-engine"]
    assert h.runtime == "h3-engine"
    assert h.requires_comfyui is False
    assert {b.role for b in h.ports} == {"app"}
    assert {b.default_port for b in h.ports} == {8200}
    assert h.browser_url_role == "app"
    # root 一律相对 (服务 100% 在包内的硬约束)
    assert not Path(o.root).is_absolute()
    assert not Path(w.root).is_absolute()
    assert not Path(h.root).is_absolute()
    # 身份规则覆盖所有端口 role
    assert set(o.identity) == {b.role for b in o.ports}
    assert set(h.identity) == {b.role for b in h.ports}


def test_port_binding_config_keys():
    from core.companion.spec import BUILTIN_SERVICES
    o = BUILTIN_SERVICES["openjutsu"]
    for b in o.ports:
        assert b.config_key.startswith("services.openjutsu.")
        assert b.ready == "port"  # start 路径端口优先 (拍板)


# ---------------- registry ----------------

def test_resolve_root_and_availability(tmp_path):
    from core.companion import registry
    from core.companion.spec import OPENJUTSU_SPEC
    pkg = _mk_pkg(tmp_path)
    app = _App(cfg=_cfg_with(pkg))
    root = registry.resolve_root(app, OPENJUTSU_SPEC)
    assert root == (pkg / "openjutsu").resolve()
    avail = registry.availability(app, OPENJUTSU_SPEC)
    assert avail["available"] is True
    assert avail["missing_markers"] == []


def test_availability_missing_markers(tmp_path):
    from core.companion import registry
    from core.companion.spec import OPENJUTSU_SPEC
    pkg = _mk_pkg(tmp_path, complete=False)
    app = _App(cfg=_cfg_with(pkg))
    avail = registry.availability(app, OPENJUTSU_SPEC)
    assert avail["available"] is False
    assert set(avail["missing_markers"]) == {"package.json", "patch_proxy.py"}


def test_availability_env_specific(tmp_path):
    """env_b 的包根没有 openjutsu → 该环境不可用 (服务是环境资产)."""
    from core.companion import registry
    from core.companion.spec import OPENJUTSU_SPEC
    pkg_a = _mk_pkg(tmp_path / "a")
    pkg_b = tmp_path / "b" / "empty_pkg"  # 造不出来, 直接建空目录
    pkg_b.mkdir(parents=True)
    cfg = {
        "environments": [
            {"id": "env_a", "comfyui_root": str(pkg_a), "python_path": "py"},
            {"id": "env_b", "comfyui_root": str(pkg_b), "python_path": "py"},
        ],
        "active_env_id": "env_a",
    }
    app = _App(cfg=cfg)
    assert registry.availability(app, OPENJUTSU_SPEC)["available"] is True
    assert registry.availability(app, OPENJUTSU_SPEC, env_id="env_b")["available"] is False


def test_read_port_override_and_fallback(tmp_path):
    from core.companion import registry
    from core.companion.spec import OPENJUTSU_SPEC
    pkg = _mk_pkg(tmp_path)
    b_app = [b for b in OPENJUTSU_SPEC.ports if b.role == "app"][0]
    b_proxy = [b for b in OPENJUTSU_SPEC.ports if b.role == "proxy"][0]
    # 无 services 块 → 默认
    app = _App(cfg=_cfg_with(pkg))
    assert registry.read_port(app, OPENJUTSU_SPEC, b_app) == 8198
    # 覆盖
    cfg = _cfg_with(pkg)
    cfg["services"] = {"openjutsu": {"app_port": 3100, "proxy_port": "8819"}}
    app2 = _App(cfg=cfg)
    assert registry.read_port(app2, OPENJUTSU_SPEC, b_app) == 3100
    assert registry.read_port(app2, OPENJUTSU_SPEC, b_proxy) == 8819
    # 非法值 → 回落默认
    cfg["services"]["openjutsu"]["app_port"] = "not-a-port"
    assert registry.read_port(app2, OPENJUTSU_SPEC, b_app) == 8198
    # 块类型错 → 回落默认
    cfg["services"] = "oops"
    assert registry.read_port(app2, OPENJUTSU_SPEC, b_app) == 8198


def test_resolve_root_cwd_anchor_fallback(tmp_path, monkeypatch):
    """多候选锚定 (2026-10-31 真机修复): stable 锚定目录不存在时回落 cwd 锚定.

    场景: 相对 comfyui_root 指向的目录在 stable_project_root 下不存在,
    但在 cwd 下存在 (repo 代码 + cwd 在整合包的运行模式) → 必须解析到 cwd 那份.
    """
    from core.companion import registry
    from core.companion.spec import OPENJUTSU_SPEC
    # 用一个 stable_root 下不存在的相对名, 只在 cwd (tmp) 下造出来
    rel = "pkg_cwd_anchor_test"
    pkg = tmp_path / rel
    root = pkg / "openjutsu"
    root.mkdir(parents=True)
    (root / "package.json").write_text("{}", encoding="utf-8")
    (root / "patch_proxy.py").write_text("# p", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    cfg = {"environments": [{"id": "e", "comfyui_root": rel, "python_path": "py"}],
           "active_env_id": "e"}
    app = _App(cfg=cfg)
    resolved = registry.resolve_root(app, OPENJUTSU_SPEC)
    assert resolved == root.resolve()
    assert registry.availability(app, OPENJUTSU_SPEC)["available"] is True


def test_read_openjutsu_version_fallbacks(tmp_path):
    """版本读取: git describe 优先 → package.json version → '未知' (真机 #3 修复)."""
    from ui_qt.pages.openjutsu_page import read_openjutsu_version
    assert read_openjutsu_version(None) == "未安装"
    assert read_openjutsu_version(str(tmp_path / "nope")) == "未安装"
    # 非 git 目录 + package.json 带 version → 读它 (git describe 失败回落)
    d = tmp_path / "withver"
    d.mkdir()
    (d / "package.json").write_text('{"version": "1.2.3"}', encoding="utf-8")
    assert read_openjutsu_version(str(d)) == "1.2.3"
    # 非 git 目录 + package.json 无 version (真机实况) → 未知, 不再是空串
    d2 = tmp_path / "nover"
    d2.mkdir()
    (d2 / "package.json").write_text('{"name": "openjutsu"}', encoding="utf-8")
    assert read_openjutsu_version(str(d2)) == "未知"


# ---------------- pidstore ----------------

def test_pidstore_roundtrip(tmp_path):
    from core.companion import pidstore
    p = tmp_path / "launcher" / "openjutsu.pid"
    pidstore.write(p, "openjutsu",
                  [{"pid": 111, "role": "proxy"}, {"pid": 222, "role": "app"}],
                  {"proxy": 8197, "app": 8198},
                  tmp_path / "openjutsu.log", env_id="env_a")
    data = pidstore.read(p)
    assert data is not None
    assert data["version"] == 2
    assert data["service_id"] == "openjutsu"
    assert data["env_id"] == "env_a"
    assert [e["pid"] for e in data["processes"]] == [111, 222]
    assert data["ports"] == {"proxy": 8197, "app": 8198}
    assert data["log_path"].endswith("openjutsu.log")


def test_pidstore_rejects_v1_and_broken(tmp_path):
    from core.companion import pidstore
    p = tmp_path / "launcher" / "openjutsu.pid"
    p.parent.mkdir(parents=True)
    # v1 扁平 schema (webui.pid 形状) → 拒
    p.write_text(json.dumps({"pid": 1, "port": 8199, "started_at": "x", "env_id": None}),
                 encoding="utf-8")
    assert pidstore.read(p) is None
    # processes 空 / 非 int pid → 拒
    p.write_text(json.dumps({"version": 2, "processes": []}), encoding="utf-8")
    assert pidstore.read(p) is None
    p.write_text(json.dumps({"version": 2, "processes": [{"pid": "x", "role": "r"}]}),
                 encoding="utf-8")
    assert pidstore.read(p) is None
    # 坏 JSON → 拒
    p.write_text("{oops", encoding="utf-8")
    assert pidstore.read(p) is None
    # 缺文件 → None
    assert pidstore.read(tmp_path / "nope.pid") is None


def test_pidstore_clear_idempotent(tmp_path):
    from core.companion import pidstore
    p = tmp_path / "launcher" / "openjutsu.pid"
    pidstore.write(p, "openjutsu", [{"pid": 1, "role": "proxy"}], {}, None)
    pidstore.clear(p)
    assert not p.exists()
    pidstore.clear(p)  # 再删不炸


# ---------------- proctree: identity_matches 纯逻辑 ----------------

def test_identity_matches_all_any():
    from core.companion.spec import IdentityRule
    from core.companion.proctree import identity_matches
    r = IdentityRule(cmdline_all=("comfy_api_proxy",))
    assert identity_matches(r, "python -c from comfy_api_proxy.cli import main", "", None)
    assert not identity_matches(r, "python -c something_else", "", None)
    r2 = IdentityRule(cmdline_any=("npm-cli.js", "next"))
    assert identity_matches(r2, "node.exe run start", "", None) is False
    assert identity_matches(r2, "node.exe npm-cli.js run start", "", None)
    assert identity_matches(r2, "node.exe ...next start", "", None)
    # 空规则 = 恒真 (向后兼容手改 pidstore 的兜底语义由调用方控制)
    assert identity_matches(IdentityRule(), "whatever", "", None)


def test_identity_matches_cwd_under_root(tmp_path):
    from core.companion.spec import IdentityRule
    from core.companion.proctree import identity_matches
    root = tmp_path / "pkg" / "openjutsu"
    r = IdentityRule(cmdline_any=("next",), cwd_under_root=True)
    ok_cmd = "node.exe next start"
    assert identity_matches(r, ok_cmd, str(root).lower(), root)
    # 前缀相同的兄弟目录不算 (openjutsu2 不能命中 openjutsu 的规则)
    sibling = str(tmp_path / "pkg" / "openjutsu2").lower()
    assert not identity_matches(r, ok_cmd, sibling, root)
    # cwd 拿不到 / root 缺 → 保守不匹配
    assert not identity_matches(r, ok_cmd, "", root)
    assert not identity_matches(r, ok_cmd, str(root).lower(), None)


def test_is_service_pid_rejects_self_and_bad():
    from core.companion.spec import IdentityRule
    from core.companion.proctree import is_service_pid
    r = IdentityRule()  # 恒真规则
    assert not is_service_pid(None, r)
    assert not is_service_pid(0, r)
    assert not is_service_pid(-5, r)
    assert not is_service_pid(os.getpid(), r)  # 排除 launcher/测试自身


# ---------------- proctree: script_rel 入口脚本匹配 (2026-11-18 H3 接入) ----------------

def test_identity_matches_script_rel():
    """入口脚本必须出现在命令行里: "<root>/<script_rel>"."""
    from core.companion.spec import IdentityRule
    from core.companion.proctree import identity_matches
    root = Path("E:/env_a/ComfyUI/custom_nodes/ComfyUI-Mie-H3-Engine")
    r = IdentityRule(script_rel="webapp/__main__.py")
    cmd_ok = ("e:\\env_a\\comfyui\\custom_nodes\\comfyui-mie-h3-engine"
              "\\webapp\\__main__.py")
    assert identity_matches(r, cmd_ok, "", root)
    # 别的环境的同一个入口 (路径文本不同) → 不匹配: 这正是多环境共用 junction
    # 目标时的区分手段
    cmd_other = ("e:\\env_b\\comfyui\\custom_nodes\\comfyui-mie-h3-engine"
                 "\\webapp\\__main__.py")
    assert not identity_matches(r, cmd_other, "", root)
    # 别的入口 → 不匹配
    assert not identity_matches(r, "python -c pass", "", root)
    # root 缺 / 命令行缺 → 保守不匹配
    assert not identity_matches(r, cmd_ok, "", None)
    assert not identity_matches(r, "", "", root)


def test_identity_matches_script_rel_accepts_realpath_form(tmp_path):
    """root 的 realpath 形态也要认 (Windows 上 cwd 常被系统归一化成真实路径)."""
    from core.companion.spec import IdentityRule
    from core.companion.proctree import identity_matches
    root = tmp_path / "pkg" / "ComfyUI" / "custom_nodes" / "ComfyUI-Mie-H3-Engine"
    root.mkdir(parents=True)
    r = IdentityRule(script_rel="webapp/__main__.py")
    cmd = (str(root.resolve()) + "/webapp/__main__.py").lower().replace("/", "\\")
    assert identity_matches(r, cmd, "", root)


def test_resolve_root_raw_keeps_junction_form(tmp_path):
    """resolve_root_raw 不 resolve 末级目录 (命令要带环境专属路径文本)."""
    from core.companion import registry
    from core.companion.spec import H3_ENGINE_SPEC
    pkg = tmp_path / "pkg"
    (pkg / "ComfyUI" / "custom_nodes").mkdir(parents=True)
    cfg = {"environments": [{"id": "e", "comfyui_root": str(pkg),
                             "python_path": "py"}],
           "active_env_id": "e"}
    app = _App(cfg=cfg)
    raw = registry.resolve_root_raw(app, H3_ENGINE_SPEC)
    assert raw == pkg / "ComfyUI" / "custom_nodes" / "ComfyUI-Mie-H3-Engine"
    assert not str(raw).startswith("\\\\?\\")  # 不是 Win32 长路径形态
