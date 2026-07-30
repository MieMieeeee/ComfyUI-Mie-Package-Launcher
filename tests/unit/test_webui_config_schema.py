"""Tests for webui_options schema in launcher/config.json.

webui_options 是 launcher config.json 里的 webui 子系统配置块.
被 core/cli/cmd_webui.py / core/webui_launcher_cmd.py 读.
本测试锁住: schema 形态 / 字段类型 / 缺失字段兜底 / 异常值处理.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# 启动器真实 config.json 位置 (机器本地, 含绝对路径)
def _real_config_path() -> Path:
    """Pytest conftest 的 app_context fixture 已经把 launcher/config.json 准备好了."""
    # 用 env var 拿 cwd, fallback 到项目根
    import os
    cwd = os.environ.get("LAUNCHER_CWD")
    if cwd:
        return Path(cwd) / "launcher" / "config.json"
    # 找项目根
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "launcher" / "config.json").exists():
            return parent / "launcher" / "config.json"
    raise FileNotFoundError("launcher/config.json not found")


def _read_real_config():
    p = _real_config_path()
    if not p.exists():
        pytest.skip("real launcher/config.json not available")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def test_real_config_has_webui_options():
    """启动器真实 config.json 必须含 webui_options 块."""
    cfg = _read_real_config()
    assert "webui_options" in cfg, "webui_options 块丢了 - launch_plan 5 强制 schema"


def test_webui_options_block_shape():
    """webui_options 必须是 dict, 含核心字段."""
    cfg = _read_real_config()
    opts = cfg["webui_options"]
    assert isinstance(opts, dict)
    for field in ("port", "display_host", "auto_open_browser", "extra_args", "download_url"):
        assert field in opts, f"缺字段: {field}"


def test_webui_options_field_types():
    cfg = _read_real_config()
    opts = cfg["webui_options"]
    assert isinstance(opts["port"], int) and opts["port"] > 0
    assert isinstance(opts["display_host"], str) and opts["display_host"]
    assert isinstance(opts["auto_open_browser"], bool)
    assert isinstance(opts["extra_args"], str)
    assert isinstance(opts["download_url"], str) and opts["download_url"].startswith("https://")


def test_webui_port_default_8199():
    """default port 必须 8199 (跟 Comfyui-Workbench-Mie / app/config.py 对齐)."""
    cfg = _read_real_config()
    assert cfg["webui_options"]["port"] == 8199


def test_webui_download_url_default():
    """download_url 默认指向 Comfyui-Workbench-Mie 仓库."""
    cfg = _read_real_config()
    assert "MieMieeeee/Comfyui-Workbench-Mie" in cfg["webui_options"]["download_url"]


# === 缺失字段兜底 (build_webui_launch_params / cmd_webui 都要正确处理) ===

class _FakeArgs:
    pass


def _make_app(config: dict):
    """构造一个 app mock, config / 通过 attribute 访问拿 custom_port."""
    app = MagicMock()
    app.config = config

    class _V:
        def __init__(self, v): self._v = v
        def get(self): return self._v

    app.custom_port = _V("8188")
    app.pypi_proxy_mode = _V("none")
    app.pypi_proxy_url = _V("")
    app.logger = MagicMock()
    return app


def test_cmd_webui_handles_missing_webui_options():
    """config 缺 webui_options 时, cmd_webui 用默认值 (8199/127.0.0.1/false)."""
    from core.cli import cmd_webui
    app = _make_app({
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg", "python_path": "E:/pkg/python/python.exe"}
        ],
        "active_env_id": "env_a",
        # 没有 webui_options
    })
    res = cmd_webui._do_info(_FakeArgs(), app)
    assert isinstance(res["port"], int)
    assert res["port"] == 8199
    assert res["display_host"] == "127.0.0.1"
    assert "auto_open_browser" not in res  # cmd_webui._do_info 不返 auto_open_browser


def test_build_launch_handles_missing_webui_options():
    """build_webui_launch_params 在 config 缺 webui_options 时返默认值."""
    from core.webui_launcher_cmd import build_webui_launch_params
    app = _make_app({
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg", "python_path": "E:/pkg/python/python.exe"}
        ],
        "active_env_id": "env_a",
        # 没有 webui_options
    })
    cmd, env, cwd, py, webui_root = build_webui_launch_params(app)
    assert cmd[1] == "-c"
    assert env["FLASK_PORT"] == "8199"
    assert env["FLASK_HOST"] == "127.0.0.1"


def test_build_launch_handles_partial_webui_options():
    """config 有 webui_options 但只含部分字段 - 用默认 + 已有."""
    from core.webui_launcher_cmd import build_webui_launch_params
    app = _make_app({
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg", "python_path": "E:/pkg/python/python.exe"}
        ],
        "active_env_id": "env_a",
        "webui_options": {"port": 9999},  # 只指定 port
    })
    cmd, env, cwd, py, webui_root = build_webui_launch_params(app)
    assert env["FLASK_PORT"] == "9999"  # 用提供的
    assert env["FLASK_HOST"] == "127.0.0.1"  # 默认


def test_cmd_webui_handles_webui_options_non_dict():
    """webui_options 是字符串 (config 损坏) 时, cmd_webui 不 crash."""
    from core.cli import cmd_webui
    app = _make_app({
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg", "python_path": "E:/pkg/python/python.exe"}
        ],
        "active_env_id": "env_a",
        "webui_options": "corrupted-not-a-dict",
    })
    res = cmd_webui._do_info(_FakeArgs(), app)
    # 不 crash, 用默认
    assert isinstance(res["port"], int)
    assert res["port"] == 8199


def test_build_launch_handles_webui_options_non_dict():
    """build_webui_launch_params 接受 webui_options 是非 dict."""
    from core.webui_launcher_cmd import build_webui_launch_params
    app = _make_app({
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg", "python_path": "E:/pkg/python/python.exe"}
        ],
        "active_env_id": "env_a",
        "webui_options": "corrupted",
    })
    cmd, env, _, _, _ = build_webui_launch_params(app)
    # .get("port") 不存在 -> 用默认
    assert env["FLASK_PORT"] == "8199"
    assert env["FLASK_HOST"] == "127.0.0.1"


def test_webui_options_with_extra_unknown_fields():
    """webui_options 含未知字段 (向前兼容), 不影响核心逻辑."""
    from core.cli import cmd_webui
    app = _make_app({
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg", "python_path": "E:/pkg/python/python.exe"}
        ],
        "active_env_id": "env_a",
        "webui_options": {
            "port": 8199,
            "display_host": "127.0.0.1",
            "auto_open_browser": False,
            "extra_args": "",
            "download_url": "https://github.com/MieMieeeee/Comfyui-Workbench-Mie.git",
            # 未来扩展字段
            "experimental_theme": "dark",
            "future_field": 42,
        },
    })
    res = cmd_webui._do_info(_FakeArgs(), app)
    assert res["port"] == 8199


def test_webui_options_port_in_range():
    """port 字段必须在 1024-65535 范围 (TCP 合法端口)."""
    cfg = _read_real_config()
    port = cfg["webui_options"]["port"]
    assert 1024 <= port <= 65535


# === 特殊字段 - env vars 写到 spawn env ===

def test_build_launch_includes_python_legacy_windowsstdio():
    """build_webui_launch_params 在 env 里设 PYTHONLEGACYWINDOWSSTDIO=1, 避免 Python 3.13 subprocess 跑 cp1252 字节 UnicodeDecodeError."""
    from core.webui_launcher_cmd import build_webui_launch_params
    app = _make_app({
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg", "python_path": "E:/pkg/python/python.exe"}
        ],
        "active_env_id": "env_a",
        "webui_options": {"port": "8199"},
    })
    _, env, _, _, _ = build_webui_launch_params(app)
    assert env.get("PYTHONLEGACYWINDOWSSTDIO") == "1"
    assert env.get("PYTHONIOENCODING") == "utf-8"


def test_build_launch_includes_pythonpath_insert_in_cmd():
    """cmd 含 python -c \"import sys; sys.path.insert(0, webui_root); ...\" 绕开 python_embeded sys.path 冲突."""
    from core.webui_launcher_cmd import build_webui_launch_params
    app = _make_app({
        "environments": [
            {"id": "env_a", "comfyui_root": "E:/pkg", "python_path": "E:/pkg/python/python.exe"}
        ],
        "active_env_id": "env_a",
        "webui_options": {"port": "8199"},
    })
    cmd, _, _, _, webui_root = build_webui_launch_params(app)
    assert cmd[1] == "-c"
    inner = cmd[2]
    assert "sys.path.insert(0, " in inner
    assert repr(str(webui_root)) in inner  # 字符串字面量 (含转义) 进 inner
    assert "from app.flask_app import main" in inner
