"""Tests for CLI dispatch of webui commands."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


# 一个小工具: 不真的跑 cmd_webui, 直接看 parser + dispatch 走通
def _parse(argv):
    from core.cli.parser import build_parser
    p = build_parser()
    return p.parse_args(argv)


def test_webui_in_subcommands():
    from core.cli.parser import SUBCOMMANDS
    assert "webui" in SUBCOMMANDS


def test_webui_in_logs_targets():
    from core.cli.parser import LOGS_TARGETS
    assert "webui" in LOGS_TARGETS


def test_webui_actions_constant():
    from core.cli.parser import WEBUI_ACTIONS
    assert set(WEBUI_ACTIONS) == {
        "start", "stop", "status", "info", "restart", "install", "setup", "update",
    }


def test_webui_start_parses():
    ns = _parse(["webui", "start", "--env", "env_a", "--with-comfyui", "--timeout", "30"])
    assert ns.command == "webui"
    assert ns.webui_action == "start"
    assert ns.env == "env_a"
    assert ns.with_comfyui is True
    assert ns.timeout == 30
    assert ns.no_wait is False


def test_webui_stop_force():
    ns = _parse(["webui", "stop", "--force"])
    assert ns.webui_action == "stop"
    assert ns.force is True


def test_webui_install_url():
    ns = _parse(["webui", "install", "--url", "https://example.com/foo.git"])
    assert ns.webui_action == "install"
    assert ns.url == "https://example.com/foo.git"


def test_webui_info_json():
    ns = _parse(["webui", "--json", "info"])
    assert ns.json is True
    assert ns.webui_action == "info"


def test_webui_dispatch_in_main():
    """main._DISPATCH 应含 webui."""
    from core.cli import main as cli_main
    assert "webui" in cli_main._DISPATCH


def test_webui_dispatch_runs_status():
    """dispatch 走 webui status 应该返 exit_code 0/3 (not GeneralError)."""
    from core.cli.main import dispatch
    from core.cli.parser import build_parser

    # 我们不想真去 spawn webui, 直接 mock _do_status
    from core.cli import cmd_webui
    real_do_status = cmd_webui._do_status

    def _fake_status(app, args):
        return {
            "ok": True, "running": False,
            "pid": None, "port": 8199, "url": "http://127.0.0.1:8199",
            "http_reachable": False,
            "log_path": None, "since": None, "env_id": None,
            "exit_code": 3,
        }
    cmd_webui._do_status = _fake_status
    try:
        args = build_parser().parse_args(["webui", "--json", "status"])
        # 不传 app -> _load_app 会读 config; 用 None 跳过 (mock 掉 _load_app)
        # 改用 _load_app monkeypatch
        from core.cli import main as cli_main
        original_load = cli_main._load_app
        cli_main._load_app = lambda: type("A", (), {"config": {"webui_options": {}}, "pypi_proxy_mode": None, "pypi_proxy_url": None})()
        try:
            rc = dispatch(args)
        finally:
            cli_main._load_app = original_load
    finally:
        cmd_webui._do_status = real_do_status
    assert rc == 3


def test_webui_dispatch_unknown_action():
    """parser 拦了未知 action, 这里走 dispatch 也不会成功."""
    from core.cli.parser import build_parser
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["webui", "bogus"])


def test_logs_webui_parse():
    """logs webui 应该解析到 logs_target='webui'."""
    ns = _parse(["logs", "webui", "-n", "50", "--no-follow"])
    assert ns.command == "logs"
    assert ns.logs_target == "webui"
    assert ns.lines == 50
    assert ns.follow is False


def test_cmd_webui_webui_actions_matches_parser():
    """cmd_webui.WEBUI_ACTIONS 应跟 parser.WEBUI_ACTIONS 一致 (双锁约定)."""
    from core.cli import cmd_webui
    from core.cli.parser import WEBUI_ACTIONS
    assert set(cmd_webui.WEBUI_ACTIONS) == set(WEBUI_ACTIONS)


def test_resolve_log_path_webui(tmp_path):
    """runner._resolve_log_path(app, 'webui') 返 <cwd>/launcher/webui.log."""
    from core.cli.runner import resolve_log_path
    app = type("A", (), {"_cwd": str(tmp_path)})()
    p = resolve_log_path(app, "webui")
    assert p == tmp_path / "launcher" / "webui.log"
