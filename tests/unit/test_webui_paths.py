"""Tests for utils.paths.webui_path_from_config and config.migrations.resolve_active_paths_for_webui."""
from __future__ import annotations

import posixpath
from pathlib import Path


def _norm(s: str) -> str:
    """统一斜杠 / 末尾, 跨平台比 Path 字符串."""
    return posixpath.normpath(s.replace("\\", "/"))


CFG_ONE_ENV = {
    "environments": [
        {"id": "env_a", "comfyui_root": "E:/fake/ComfyUI_Pkg", "python_path": "E:/fake/python_embeded/python.exe"},
    ],
    "active_env_id": "env_a",
}


def test_webui_dir_name_constant():
    from utils.paths import WEBUI_DIR_NAME
    assert WEBUI_DIR_NAME == "Comfyui-Workbench-Mie"


def test_webui_path_active_env():
    from utils.paths import webui_path_from_config
    p = webui_path_from_config(CFG_ONE_ENV)
    assert p is not None
    s = _norm(str(p))
    assert s.endswith("Comfyui-Workbench-Mie")
    assert s.startswith("E:/fake/ComfyUI_Pkg")


def test_webui_path_explicit_env_id():
    from utils.paths import webui_path_from_config
    cfg = {
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg_a", "python_path": "py"},
            {"id": "env_b", "comfyui_root": "E:/pkg_b", "python_path": "py"},
        ],
        "active_env_id": "env_a",
    }
    p = webui_path_from_config(cfg, env_id="env_b")
    assert _norm(str(p)).startswith("E:/pkg_b")


def test_webui_path_bad_env_id_falls_back_to_active():
    from utils.paths import webui_path_from_config
    p = webui_path_from_config(CFG_ONE_ENV, env_id="env_missing")
    assert _norm(str(p)).startswith("E:/fake/ComfyUI_Pkg")


def test_webui_path_empty_config_returns_path():
    """空 config 不报错, 落到 cwd 兜底."""
    from utils.paths import webui_path_from_config
    p = webui_path_from_config({})
    assert p is not None
    assert _norm(str(p)).endswith("Comfyui-Workbench-Mie")


def test_webui_path_none_config():
    from utils.paths import webui_path_from_config
    assert webui_path_from_config(None) is not None


def test_resolve_active_paths_for_webui_active():
    from config.migrations import resolve_active_paths_for_webui
    out = resolve_active_paths_for_webui(CFG_ONE_ENV)
    assert out["comfyui_root"] == "E:/fake/ComfyUI_Pkg"
    assert out["python_path"] == "E:/fake/python_embeded/python.exe"
    assert out["env_id"] == "env_a"
    assert _norm(out["webui_path"]).endswith("Comfyui-Workbench-Mie")


def test_resolve_active_paths_for_webui_with_env_id():
    from config.migrations import resolve_active_paths_for_webui
    cfg = {
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg_a", "python_path": "py_a"},
            {"id": "env_b", "comfyui_root": "E:/pkg_b", "python_path": "py_b"},
        ],
        "active_env_id": "env_a",
    }
    out = resolve_active_paths_for_webui(cfg, env_id="env_b")
    assert out["comfyui_root"] == "E:/pkg_b"
    assert out["python_path"] == "py_b"
    assert out["env_id"] == "env_b"
    assert _norm(out["webui_path"]).startswith("E:/pkg_b")


def test_resolve_active_paths_for_webui_bad_env_id():
    """找不到 id 退回激活 env."""
    from config.migrations import resolve_active_paths_for_webui
    out = resolve_active_paths_for_webui(CFG_ONE_ENV, env_id="env_x")
    assert out["env_id"] == "env_a"
    assert out["comfyui_root"] == "E:/fake/ComfyUI_Pkg"


def test_resolve_active_paths_for_webui_none():
    from config.migrations import resolve_active_paths_for_webui
    out = resolve_active_paths_for_webui(None)
    assert out["comfyui_root"] is None
    assert out["python_path"] is None
    assert out["env_id"] is None
    assert out["webui_path"] is None


def test_resolve_active_paths_for_webui_empty():
    from config.migrations import resolve_active_paths_for_webui
    out = resolve_active_paths_for_webui({})
    assert out["env_id"] is None
    assert out["webui_path"] is not None
