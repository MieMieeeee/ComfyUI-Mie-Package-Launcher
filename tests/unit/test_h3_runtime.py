"""Tests for core.companion.h3_runtime (H3 短剧工作台的路径/依赖/命令/健康探针).

重点盯这几处真机踩过的坑:
  - 相对 python_path 必须按**所选环境的包根**解析 (不能落到启动器自己那份);
  - MieNodes 资产库缺失 = 硬失败 (引擎侧会兜底到别的机器的硬编码路径);
  - 注入的 MIE_* 环境变量一个都不能少 (少了就读错资产库/写错密钥);
  - 就绪判据不能只看端口 (端口通不等于「跑的是我们的工作台」).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


class _App:
    def __init__(self, cwd=None, cfg=None):
        self._cwd = str(cwd) if cwd else "."
        self.config = cfg if cfg is not None else {}
        self.logger = type("L", (), {"info": lambda *a, **kw: None,
                                     "warning": lambda *a, **kw: None})()


def _mk_env(tmp_path: Path, *, mie_nodes_name="comfyui_mienodes",
            with_engine=True, with_python=True) -> Path:
    """造一个假整合包: <pkg>/ComfyUI/custom_nodes/ComfyUI-Mie-H3-Engine/..."""
    pkg = tmp_path / "pkg"
    custom_nodes = pkg / "ComfyUI" / "custom_nodes"
    custom_nodes.mkdir(parents=True)
    if with_engine:
        engine = custom_nodes / "ComfyUI-Mie-H3-Engine"
        (engine / "webapp").mkdir(parents=True)
        (engine / "webapp" / "__main__.py").write_text("# entry", encoding="utf-8")
    if mie_nodes_name:
        nodes = custom_nodes / mie_nodes_name
        (nodes / "asset_library").mkdir(parents=True)
        (nodes / "mie_llm_keys.json").write_text("{}", encoding="utf-8")
    if with_python:
        py_dir = pkg / "python_embeded"
        py_dir.mkdir(parents=True, exist_ok=True)
        (py_dir / "python.exe").write_text("# fake", encoding="utf-8")
    return pkg


def _cfg(pkg: Path, *, python_path="python_embeded/python.exe", env_id="env_a"):
    return {
        "environments": [
            {"id": env_id, "comfyui_root": str(pkg), "python_path": python_path},
        ],
        "active_env_id": env_id,
    }


# ---------------- 路径解析 ----------------

def test_resolve_paths_points_at_engine_entry(tmp_path):
    from core.companion import h3_runtime
    pkg = _mk_env(tmp_path)
    paths = h3_runtime.resolve_paths(_App(tmp_path, _cfg(pkg)))
    assert paths["entry"] == (pkg / "ComfyUI" / "custom_nodes"
                              / "ComfyUI-Mie-H3-Engine" / "webapp" / "__main__.py")
    assert paths["root"] == (pkg / "ComfyUI" / "custom_nodes"
                             / "ComfyUI-Mie-H3-Engine")
    # 设置/任务/快照目录跟启动器状态放一起, 按环境分开
    assert paths["settings_file"] == pkg / "launcher" / "h3-engine" / "settings.json"
    assert paths["comfyui_root"] == pkg / "ComfyUI"


def test_resolve_paths_accepts_all_mie_nodes_dir_names(tmp_path):
    """三种历史命名都认 (comfyui_mienodes / ComfyUI_MieNodes / ComfyUI-MieNodes)."""
    from core.companion import h3_runtime
    for i, name in enumerate(("comfyui_mienodes", "ComfyUI_MieNodes", "ComfyUI-MieNodes")):
        # 注意: Windows 上目录名大小写不敏感, 三种命名只有大小写不同 →
        # 每个用例必须用不同的父目录, 否则第二次 mkdir 就撞 FileExistsError.
        pkg = _mk_env(tmp_path / f"env{i}", mie_nodes_name=name)
        paths = h3_runtime.resolve_paths(_App(tmp_path, _cfg(pkg)))
        assert paths["mie_nodes"] is not None, name
        assert paths["mie_nodes"].name.lower() == name.lower()


def test_relative_python_path_resolves_against_selected_env(tmp_path):
    """相对 python_path 按**所选环境的包根**解析, 不是启动器自己那份.

    部署包的 config 写的就是相对路径 "python_embeded/python.exe"; 用 --env
    指向别的包时, 解析到启动器自己的 python 会缺 mie_llm/mie_craft.
    """
    from core.companion import h3_runtime
    pkg_a = _mk_env(tmp_path / "a")
    pkg_b = _mk_env(tmp_path / "b")
    cfg = {
        "environments": [
            {"id": "env_a", "comfyui_root": str(pkg_a),
             "python_path": "python_embeded/python.exe"},
            {"id": "env_b", "comfyui_root": str(pkg_b),
             "python_path": "python_embeded/python.exe"},
        ],
        "active_env_id": "env_a",
    }
    app = _App(tmp_path, cfg)
    pa = h3_runtime.resolve_paths(app, env_id="env_a")
    pb = h3_runtime.resolve_paths(app, env_id="env_b")
    assert pa["py"] == pkg_a / "python_embeded" / "python.exe"
    assert pb["py"] == pkg_b / "python_embeded" / "python.exe"


def test_absolute_python_path_wins(tmp_path):
    from core.companion import h3_runtime
    pkg = _mk_env(tmp_path)
    other = tmp_path / "other_python.exe"
    other.write_text("# fake", encoding="utf-8")
    cfg = _cfg(pkg, python_path=str(other))
    paths = h3_runtime.resolve_paths(_App(tmp_path, cfg))
    assert paths["py"] == other


# ---------------- 依赖闸门 ----------------

def test_check_deps_missing_mie_nodes_is_hard_failure(tmp_path):
    """找不到 MieNodes 资产库必须判失败 —— 引擎侧会兜底到别的包的硬编码路径."""
    from core.companion import h3_runtime
    pkg = _mk_env(tmp_path, mie_nodes_name=None)
    paths = h3_runtime.resolve_paths(_App(tmp_path, _cfg(pkg)))
    res = h3_runtime.check_deps(paths)
    assert res["ok"] is False
    assert any("MieNodes" in m for m in res["missing"])


def test_check_deps_missing_imports_is_hard_failure(tmp_path, monkeypatch):
    from core.companion import h3_runtime
    pkg = _mk_env(tmp_path)
    paths = h3_runtime.resolve_paths(_App(tmp_path, _cfg(pkg)))
    monkeypatch.setattr(h3_runtime, "_probe_imports",
                        lambda py, timeout=20: (False, ["mie_llm"]))
    res = h3_runtime.check_deps(paths)
    assert res["ok"] is False
    assert any("mie_llm" in m for m in res["missing"])


def test_check_deps_ok_when_everything_present(tmp_path, monkeypatch):
    from core.companion import h3_runtime
    pkg = _mk_env(tmp_path)
    paths = h3_runtime.resolve_paths(_App(tmp_path, _cfg(pkg)))
    monkeypatch.setattr(h3_runtime, "_probe_imports",
                        lambda py, timeout=20: (True, []))
    res = h3_runtime.check_deps(paths)
    assert res["ok"] is True
    assert res["missing"] == []


# ---------------- 命令构建 ----------------

def test_build_steps_injects_all_mie_env_vars(tmp_path):
    """MIE_* 一个都不能少: 少一个就可能读到别的包的资产库/密钥."""
    from core.companion import h3_runtime
    pkg = _mk_env(tmp_path)
    app = _App(tmp_path, _cfg(pkg))
    paths = h3_runtime.resolve_paths(app)
    steps = h3_runtime.build_steps(paths, {"app": 8200}, 8188)
    assert len(steps) == 1
    step = steps[0]
    assert step["kind"] == "long"
    assert step["role"] == "app"
    assert step["cmd"][0] == str(paths["py"])
    assert step["cmd"][1] == "-u"
    assert step["cmd"][2] == str(paths["entry"])
    assert step["cwd"] == str(paths["root"])
    env = step["env"]
    assert env["MIE_WEB_PORT"] == "8200"
    assert env["MIE_WEB_HOST"] == "127.0.0.1"
    assert env["MIE_COMFYUI_ROOT"] == str(pkg / "ComfyUI")
    assert env["MIE_COMFYUI_URL"] == "http://127.0.0.1:8188"
    assert env["MIE_PLUGIN_ROOT"] == str(paths["mie_nodes"])
    assert env["MIE_LLM_KEYS_FILE"].endswith("mie_llm_keys.json")
    assert env["MIE_WEB_SETTINGS"] == str(paths["settings_file"])


def test_build_steps_uses_resolved_port(tmp_path):
    from core.companion import h3_runtime
    pkg = _mk_env(tmp_path)
    paths = h3_runtime.resolve_paths(_App(tmp_path, _cfg(pkg)))
    steps = h3_runtime.build_steps(paths, {"app": 8301}, 8188)
    assert steps[0]["env"]["MIE_WEB_PORT"] == "8301"


def test_log_mode_is_file(tmp_path):
    """CLI 退出后子进程要还能写日志 → 必须文件直写, 不能走管道."""
    from core.companion import h3_runtime
    assert h3_runtime.log_mode() == "file"


# ---------------- 健康探针 ----------------

def test_ready_probe_requires_status_and_app(monkeypatch):
    from core.companion import h3_runtime
    monkeypatch.setattr(h3_runtime, "_health_payload",
                        lambda port, timeout=2.0: {"status": "ok",
                                                  "app": "comfyui-mie-web"})
    assert h3_runtime.ready_probe({}, {"app": 8200}) is True
    monkeypatch.setattr(h3_runtime, "_health_payload",
                        lambda port, timeout=2.0: {"status": "ok", "app": "别的"})
    assert h3_runtime.ready_probe({}, {"app": 8200}) is False
    monkeypatch.setattr(h3_runtime, "_health_payload",
                        lambda port, timeout=2.0: None)
    assert h3_runtime.ready_probe({}, {"app": 8200}) is False


def test_health_info_flags_foreign_plugin_root(tmp_path, monkeypatch):
    """plugin_root 不是当前环境的资产库 → plugin_root_ok=False."""
    from core.companion import h3_runtime
    pkg = _mk_env(tmp_path)
    paths = h3_runtime.resolve_paths(_App(tmp_path, _cfg(pkg)))
    monkeypatch.setattr(
        h3_runtime, "_health_payload",
        lambda port, timeout=2.0: {"status": "ok", "app": "comfyui-mie-web",
                                   "plugin_root": str(paths["mie_nodes"])})
    info = h3_runtime.health_info(paths, {"app": 8200})
    assert info["plugin_root_ok"] is True
    monkeypatch.setattr(
        h3_runtime, "_health_payload",
        lambda port, timeout=2.0: {"status": "ok", "app": "comfyui-mie-web",
                                   "plugin_root": "C:\\别的包\\comfyui_mienodes"})
    info = h3_runtime.health_info(paths, {"app": 8200})
    assert info["plugin_root_ok"] is False


def test_same_dir_is_text_compare_not_samefile():
    """刻意不用 os.path.samefile: 那会把两个环境指向的同一份 junction 目标
    判成「同一个」, 恰好毁掉「plugin_root 属于当前环境」的意义."""
    from core.companion import h3_runtime
    assert h3_runtime._same_dir("C:\\Pkg\\Custom", "c:/pkg/custom/") is True
    assert h3_runtime._same_dir("C:\\Pkg\\Custom", "C:\\Other\\Custom") is False


# ---------------- 更新链 ----------------

def test_update_is_refused_with_pointer_to_plugin_manager():
    """H3 引擎本体走插件管理, 本命令只管工作台启停."""
    from core.companion import h3_runtime
    res = h3_runtime.update(None, {})
    assert res["ok"] is False
    assert "插件管理" in res["error"]
