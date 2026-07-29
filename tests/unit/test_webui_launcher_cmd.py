"""Tests for core.webui_launcher_cmd.build_webui_launch_params."""
from __future__ import annotations

import posixpath

CFG = {
    "environments": [
        {"id": "env_a", "comfyui_root": "E:/fake/ComfyUI_Pkg", "python_path": "E:/fake/python_embeded/python.exe"},
    ],
    "active_env_id": "env_a",
    "webui_options": {
        "port": "8299",
        "display_host": "127.0.0.1",
        "extra_args": "--debug --no-reload",
    },
}


def _norm(s):
    return posixpath.normpath(s.replace("\\", "/"))


class _StrVar:
    def __init__(self, v): self._v = v
    def get(self): return self._v


def _make_app(cfg=None, comfyui_port="9999"):
    app = type("A", (), {})()
    app.config = cfg if cfg is not None else CFG
    app.custom_port = _StrVar(comfyui_port)
    return app


def test_basic_cmd_and_env():
    from core.webui_launcher_cmd import build_webui_launch_params
    app = _make_app()
    cmd, env, cwd, py, webui_root = build_webui_launch_params(app)
    assert cmd[0].endswith("python.exe")
    # cmd[1] = "-c", cmd[2] 是 python -c 后的 inner 脚本
    assert cmd[1] == "-c"
    inner = cmd[2]
    # inner 必须含 sys.path.insert + from app.flask_app import main
    assert "sys.path.insert" in inner
    assert "from app.flask_app import main" in inner
    # extra_args 透传到 inner
    assert "--debug" in inner
    assert "--no-reload" in inner
    assert env["FLASK_HOST"] == "127.0.0.1"
    assert env["FLASK_PORT"] == "8299"
    assert env["COMFY_BASE_URL"] == "http://127.0.0.1:9999"
    assert _norm(env["COMFY_INSTALL_DIR"]).endswith("ComfyUI")
    assert _norm(str(webui_root)).endswith("Comfyui-Workbench-Mie")
    assert cwd == str(webui_root)
    assert _norm(str(py)).endswith("python.exe")


def test_default_port_when_options_missing():
    from core.webui_launcher_cmd import build_webui_launch_params
    cfg = dict(CFG)
    cfg["webui_options"] = {}
    app = _make_app(cfg, comfyui_port="8188")
    _, env, _, _, _ = build_webui_launch_params(app)
    assert env["FLASK_PORT"] == "8199"
    assert env["COMFY_BASE_URL"] == "http://127.0.0.1:8188"


def test_default_host_when_options_missing():
    from core.webui_launcher_cmd import build_webui_launch_params
    cfg = dict(CFG)
    cfg["webui_options"] = {"port": "7777"}
    app = _make_app(cfg)
    _, env, _, _, _ = build_webui_launch_params(app)
    assert env["FLASK_HOST"] == "127.0.0.1"


def test_extra_args_handles_quoted_string():
    from core.webui_launcher_cmd import build_webui_launch_params
    cfg = dict(CFG)
    cfg["webui_options"] = {"port": "8199", "extra_args": '--name "my app"'}
    app = _make_app(cfg)
    cmd, *_ = build_webui_launch_params(app)
    inner = cmd[2]
    assert "--name" in inner
    assert "my app" in inner


def test_extra_args_invalid_quotes_falls_back_to_split():
    from core.webui_launcher_cmd import build_webui_launch_params
    cfg = dict(CFG)
    cfg["webui_options"] = {"port": "8199", "extra_args": '--bad "unclosed'}
    app = _make_app(cfg)
    cmd, *_ = build_webui_launch_params(app)
    inner = cmd[2]
    assert "--bad" in inner
    assert "unclosed" in inner


def test_no_extra_args_means_no_extra_tokens():
    from core.webui_launcher_cmd import build_webui_launch_params
    cfg = dict(CFG)
    cfg["webui_options"] = {"port": "8199"}
    app = _make_app(cfg)
    cmd, *_ = build_webui_launch_params(app)
    # 此时 inner 是 "import sys;sys.path.insert(...);from app.flask_app import main;main()"
    inner = cmd[2]
    assert "sys.path.insert" in inner
    assert "--debug" not in inner


def test_env_id_override():
    from core.webui_launcher_cmd import build_webui_launch_params
    cfg = {
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg_a", "python_path": "E:/pkg_a/py/python.exe"},
            {"id": "env_b", "comfyui_root": "E:/pkg_b", "python_path": "E:/pkg_b/py/python.exe"},
        ],
        "active_env_id": "env_a",
        "webui_options": CFG["webui_options"],
    }
    app = _make_app(cfg)
    _, _, _, _, webui_root = build_webui_launch_params(app, env_id="env_b")
    assert _norm(str(webui_root)).startswith("E:/pkg_b")


def test_empty_environments_uses_defaults():
    """environments=[] 时走兜底默认值 (./python_embeded/python.exe), 不 raise."""
    from core.webui_launcher_cmd import build_webui_launch_params
    cfg = {"environments": [], "active_env_id": "env_a"}
    app = _make_app(cfg=cfg)
    cmd, env, cwd, py, webui_root = build_webui_launch_params(app)
    assert cmd[1] == "-c"
    assert env["FLASK_PORT"] == "8199"
    assert env["FLASK_HOST"]


def test_app_without_custom_port_uses_default():
    from core.webui_launcher_cmd import build_webui_launch_params
    app = type("A", (), {})()
    app.config = CFG
    _, env, _, _, _ = build_webui_launch_params(app)
    assert env["COMFY_BASE_URL"] == "http://127.0.0.1:8188"
