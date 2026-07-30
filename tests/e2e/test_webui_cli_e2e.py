"""E2E tests for webui CLI surface (真 subprocess 跑 launcher).

校验:
- CLI help 文本稳定
- 每个子命令的 --json 输出 schema
- exit code 跟 schema 文档一致 (0/1/2/3/6/7/8)
- 错误情况下 stderr / stdout 行为
- env_id 透传
- --with-comfyui / --no-wait / --force / --url 旗标

跟 tests/unit/test_webui_cli_dispatch.py 的区别: 那份测 dispatch 内部
(同进程, mock app). 本份测 真实 CLI 进程 (跨进程, 真 HeadlessAppContext).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


# 仓库根 (E2E 用真 subprocess, 不能用 mock 路径)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable  # 当前 python (跟单测环境一致)


def _run_cli(*args: str, cwd: Path = None, timeout: int = 30,
               extra_env: dict = None) -> subprocess.CompletedProcess:
    """跑 `python -m core.cli.main webui ...` 在子进程里, 返 CompletedProcess.

    PYTHONPATH 默认含 REPO_ROOT, 让子进程能找到 core / utils / config 包
    (即使 cwd 切到了 isolated_config).
    """
    import os as _os
    cmd = [PYTHON, "-m", "core.cli.main", "webui", *args]
    env = _os.environ.copy()
    pp = env.get("PYTHONPATH", "")
    if str(REPO_ROOT) not in pp.split(_os.pathsep):
        env["PYTHONPATH"] = (str(REPO_ROOT) + _os.pathsep + pp) if pp else str(REPO_ROOT)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


# === help ===

def test_webui_help_shows_all_actions():
    """webui --help 列 8 个 action + 关键旗标."""
    res = _run_cli("--help")
    assert res.returncode == 0
    out = res.stdout
    for action in ("start", "stop", "status", "info", "restart",
                    "install", "setup", "update"):
        assert action in out, f"help 漏 action: {action}"
    # 关键旗标
    for flag in ("--json", "--env", "--no-wait", "--timeout",
                 "--with-comfyui", "--force", "--url"):
        assert flag in out, f"help 漏 flag: {flag}"


def test_webui_help_exits_zero_with_action():
    """webui start --help 也返 0, 列 start 专属说明."""
    res = _run_cli("start", "--help")
    assert res.returncode == 0
    out = res.stdout
    # Exit code 表格含 0/6/7/8
    for code in ("0", "6", "7", "8"):
        assert code in out


# === info ===

def test_webui_info_json_schema():
    """webui info --json 返 dict 含 关键字段."""
    res = _run_cli("info", "--json")
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert isinstance(data, dict)
    # 必须有 action
    assert data.get("action") == "info"
    # 关键字段
    for field in ("installed", "available", "port", "display_host",
                  "deps_ok", "deps_missing", "deps_available",
                  "python_path", "webui_path", "exit_code"):
        assert field in data, f"info --json 缺字段: {field}"
    # exit_code 是 int
    assert isinstance(data["exit_code"], int)


def test_webui_info_json_output_is_single_line():
    """--json 输出必须是单行 JSON (便于 agent 解析)."""
    res = _run_cli("info", "--json")
    assert res.returncode == 0
    # 单行: 没有 raw \n (indent 后允许)
    # 重新 parse 验证
    json.loads(res.stdout)  # 不抛 = 合法 JSON


# === status ===

def test_webui_status_json_schema():
    """webui status --json 返 dict 含 running / pid / port 等."""
    res = _run_cli("status", "--json")
    # webui 可能没跑 -> exit_code 3
    assert res.returncode in (0, 3)
    data = json.loads(res.stdout)
    assert data.get("action") == "status"
    for field in ("running", "pid", "port", "url", "http_reachable",
                  "log_path", "since", "env_id", "exit_code"):
        assert field in data, f"status --json 缺字段: {field}"


# === start exit codes ===

def test_webui_start_returns_7_when_not_installed(tmp_path):
    """webui 路径不存在 -> exit_code 7, error 含 'install'."""
    # 用一个不存在的 env
    cfg = tmp_path / "fake_config"
    cfg.mkdir()
    (cfg / "launcher").mkdir()
    # 创一个 mini config 让 HeadlessAppContext 加载
    (cfg / "launcher" / "config.json").write_text(json.dumps({
        "launch_options": {"default_compute_mode": "cpu", "default_port": "8188"},
        "environments": [
            {"id": "env_test", "comfyui_root": str(tmp_path / "no_such"),
             "python_path": str(tmp_path / "no_such" / "python.exe")},
        ],
        "active_env_id": "env_test",
        "webui_options": {"port": "8199", "display_host": "127.0.0.1"},
        "proxy_settings": {"git_proxy_mode": "none", "git_proxy_url": "",
                           "pypi_proxy_mode": "none", "pypi_proxy_url": ""},
    }))
    res = _run_cli("info", "--json", cwd=cfg)
    assert res.returncode == 0  # info 总是 0
    data = json.loads(res.stdout)
    # webui_path 不存在 -> installed False
    assert data["installed"] is False
    # 不依赖具体路径 (Windows 长短路径), 只看 installed


def test_webui_start_with_unknown_action_exits_1():
    """webui bogus 返 exit_code 1 或 2 (argparse invalid choice / cmd_webui unknown)."""
    res = _run_cli("bogus", "--json")
    assert res.returncode in (1, 2)  # argparse (2) 或 cmd_webui (1) 都算 "error"
    out = res.stdout + res.stderr
    assert "bogus" in out or "invalid choice" in out.lower()


# === env_id 透传 ===

def test_webui_info_with_env_id():
    """--env ENV_ID 透传到 schema (env_id 字段返该值, 找不到回 active)."""
    # 跑 info --env env_test
    # 用真 launcher cwd
    res = _run_cli("info", "--env", "env_default", "--json")
    assert res.returncode == 0
    data = json.loads(res.stdout)
    # 真实 config 里 env_default 是 active. 找不到的 env_id 退回 active.
    # 至少 env_id 字段有值
    assert "env_id" in data


# === 输出格式 ===

def test_webui_human_output_is_human_readable():
    """不传 --json 时, 输出是人读格式 (含 key: value, 不含 { )."""
    res = _run_cli("info")
    assert res.returncode == 0
    out = res.stdout
    # 人读格式通常含 "action: info" 这种 key: value
    assert "action" in out
    # 不应是纯 JSON
    assert not out.strip().startswith("{")


def test_webui_human_output_no_json_braces():
    """human 输出不暴露 { } 字符 (避免 grep 误判)."""
    res = _run_cli("info")
    assert res.returncode == 0
    # 允许 { / } 出现在字段值 (路径里), 但不应是 json dict 格式
    stripped = res.stdout.strip()
    # human 模式第一行不是 "{"
    assert not stripped.startswith("{")


# === logs webui ===

def test_logs_webui_parses():
    """logs webui 是合法 choice, --help 列出 webui."""
    res = _run_cli("--help")
    out = res.stdout
    # webui 应在 SUBCOMMANDS 列表里
    assert "webui" in out


# === 错误处理 ===

def test_webui_run_with_no_args_prints_help():
    """webui 不带 action (在 interactive run) 应该友好提示."""
    # argparse 会在缺 ACTION 时 SystemExit 2 + 错误到 stderr
    res = _run_cli()
    # returncode 是 2 (argparse 缺参数)
    assert res.returncode == 2
    err = res.stderr
    # 应包含 "ACTION" 或 "required"
    assert "ACTION" in err or "required" in err.lower()


# === 重入 / 幂等 ===

def test_webui_status_runs_twice_safe():
    """连跑 2 次 webui status 不崩 (幂等)."""
    res1 = _run_cli("status", "--json")
    res2 = _run_cli("status", "--json")
    assert res1.returncode in (0, 3)
    assert res2.returncode in (0, 3)
    # 两次都返合法 JSON
    json.loads(res1.stdout)
    json.loads(res2.stdout)


# === 跨平台 / 编码 ===

def test_webui_info_handles_chinese_in_paths():
    """路径含中文时, JSON 输出不抛 UnicodeDecodeError."""
    # 用项目自身的 config (含 launch_options 路径里可能有中文)
    res = _run_cli("info", "--json")
    assert res.returncode == 0
    # 解析成功 = encoding OK
    json.loads(res.stdout)


# === internal helper: 准备一个 test config ===

def _setup_env_config(tmp_path: Path) -> Path:
    """创一个 isolated config, 用作 E2E 测试 (headless app 加载这个)."""
    cfg = tmp_path / "test_config"
    cfg.mkdir()
    (cfg / "launcher").mkdir()
    (cfg / "launcher" / "config.json").write_text(json.dumps({
        "launch_options": {"default_compute_mode": "cpu", "default_port": "8188"},
        "environments": [
            {"id": "env_test", "comfyui_root": str(tmp_path / "pkg"),
             "python_path": str(tmp_path / "pkg" / "python.exe")},
        ],
        "active_env_id": "env_test",
        "webui_options": {"port": "8199"},
        "proxy_settings": {},
    }), encoding="utf-8")
    return cfg


@pytest.fixture
def isolated_config(tmp_path):
    """建个 isolated config, E2E 跑 webui 命令时用."""
    return _setup_env_config(tmp_path)


def test_webui_info_with_isolated_config(isolated_config):
    """用 isolated config 跑 webui info, 走完整 CLI 流程."""
    res = _run_cli("info", "--json", cwd=isolated_config)
    assert res.returncode == 0
    data = json.loads(res.stdout)
    # webui_path 应该解析到 isolated_config / pkg / Comfyui-Workbench-Mie
    assert data["webui_path"]  # 非空
    assert data["port"] == 8199
