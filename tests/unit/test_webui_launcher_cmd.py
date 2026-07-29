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
    assert cmd[1:3] == ["-m", "app.flask_app"]
    assert cmd[3:] == ["--debug", "--no-reload"]
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
    assert cmd[3:] == ["--name", "my app"]


def test_extra_args_invalid_quotes_falls_back_to_split():
    from core.webui_launcher_cmd import build_webui_launch_params
    cfg = dict(CFG)
    cfg["webui_options"] = {"port": "8199", "extra_args": '--bad "unclosed'}
    app = _make_app(cfg)
    cmd, *_ = build_webui_launch_params(app)
    assert "--bad" in cmd
    assert any("unclosed" in part for part in cmd)


def test_no_extra_args_means_no_extra_tokens():
    from core.webui_launcher_cmd import build_webui_launch_params
    cfg = dict(CFG)
    cfg["webui_options"] = {"port": "8199"}
    app = _make_app(cfg)
    cmd, *_ = build_webui_launch_params(app)
    assert cmd == cmd[:3]


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
    assert cmd[1:3] == ["-m", "app.flask_app"]
    assert env["FLASK_PORT"] == "8199"
    assert env["FLASK_HOST"]  # 有默认值


def test_app_without_custom_port_uses_default():
    from core.webui_launcher_cmd import build_webui_launch_params
    app = type("A", (), {})()
    app.config = CFG
    _, env, _, _, _ = build_webui_launch_params(app)
    assert env["COMFY_BASE_URL"] == "http://127.0.0.1:8188"
