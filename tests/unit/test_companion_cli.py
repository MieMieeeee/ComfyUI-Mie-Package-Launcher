"""Tests for core.cli.cmd_service (service 子命令) + parser 契约一致性."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _App:
    def __init__(self, cwd=None, cfg=None):
        self._cwd = str(cwd) if cwd else "."
        self.config = cfg if cfg is not None else {}
        self.logger = type("L", (), {"info": lambda *a, **kw: None,
                                     "warning": lambda *a, **kw: None})()


def _args(action, service_id=None, **kw):
    base = {"service_action": action, "service_id": service_id, "json": False}
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------- parser 契约 ----------------

def test_parser_constants_consistency():
    from core.cli.parser import SERVICE_ACTIONS, SUBCOMMANDS, LOGS_TARGETS
    import core.cli.cmd_service as cmd_service
    assert set(SERVICE_ACTIONS) == set(cmd_service.SERVICE_ACTIONS)
    assert "service" in SUBCOMMANDS
    assert "openjutsu" in LOGS_TARGETS


def test_parser_service_shapes():
    from core.cli.parser import build_parser
    p = build_parser()
    a = p.parse_args(["service", "list"])
    assert a.service_action == "list" and a.service_id is None
    a = p.parse_args(["service", "start", "openjutsu", "--no-wait", "--timeout", "60"])
    assert a.service_id == "openjutsu" and a.no_wait and a.timeout == 60
    a = p.parse_args(["service", "stop", "webui", "--force"])
    assert a.force is True


def test_dispatch_registers_service():
    from core.cli.main import _DISPATCH
    import core.cli.cmd_service as cmd_service
    assert _DISPATCH["service"] is cmd_service


def test_exitcodes_service_aliases_match_webui():
    from core.cli.exitcodes import (
        EXIT_WEBUI_CORE_NOT_RUNNING, EXIT_WEBUI_NOT_INSTALLED, EXIT_WEBUI_DEPS_MISSING,
        EXIT_SERVICE_CORE_NOT_RUNNING, EXIT_SERVICE_NOT_INSTALLED, EXIT_SERVICE_DEPS_MISSING,
    )
    assert EXIT_SERVICE_CORE_NOT_RUNNING == EXIT_WEBUI_CORE_NOT_RUNNING == 6
    assert EXIT_SERVICE_NOT_INSTALLED == EXIT_WEBUI_NOT_INSTALLED == 7
    assert EXIT_SERVICE_DEPS_MISSING == EXIT_WEBUI_DEPS_MISSING == 8


# ---------------- run() 分派 ----------------

def test_run_rejects_unknown_action(capsys):
    from core.cli.cmd_service import run
    app = _App()
    rc = run(_args("frobnicate", "openjutsu", json=True), app)
    assert rc == 1
    assert "unsupported service action" in capsys.readouterr().out


def test_run_rejects_missing_service_id(capsys):
    from core.cli.cmd_service import run
    rc = run(_args("start", None, json=True), _App())
    assert rc == 1
    assert "需要服务 id" in capsys.readouterr().out


def test_run_rejects_unknown_service(capsys):
    from core.cli.cmd_service import run
    rc = run(_args("start", "nope", json=True), _App())
    assert rc == 1
    assert "未知服务" in capsys.readouterr().out


def test_run_list_shape(tmp_path, capsys):
    from core.cli.cmd_service import run
    rc = run(_args("list", json=True), _App(cwd=tmp_path))
    assert rc == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    ids = {s["id"] for s in payload["services"]}
    assert ids == {"webui", "openjutsu", "h3-engine"}
    by_id = {s["id"]: s for s in payload["services"]}
    assert by_id["webui"]["runtime"] == "webui-legacy"
    assert by_id["openjutsu"]["requires_comfyui"] is True
    assert by_id["h3-engine"]["runtime"] == "h3-engine"
    assert by_id["h3-engine"]["requires_comfyui"] is False


def test_run_status_openjutsu_not_running_exit3(tmp_path, capsys):
    from core.cli.cmd_service import run
    cfg = {"environments": [{"id": "e", "comfyui_root": str(tmp_path), "python_path": "py"}],
           "active_env_id": "e"}
    rc = run(_args("status", "openjutsu", json=True), _App(cwd=tmp_path, cfg=cfg))
    assert rc == 3
    import json
    payload = json.loads(capsys.readouterr().out)
    assert payload["running"] is False
    assert payload["service"] == "openjutsu"


def test_run_status_webui_delegates_legacy(tmp_path, capsys):
    """webui 名义条目: status 转发 WebuiProcessManager, 输出补 service_id, 退出码同 webui."""
    from core.cli.cmd_service import run
    fake_status = {"running": True, "pid": 123, "port": 8199, "url": "http://127.0.0.1:8199",
                   "http_reachable": True, "log_path": "x", "since": None, "env_id": None}
    with patch("core.webui_process_manager.WebuiProcessManager") as PM:
        PM.return_value.status.return_value = dict(fake_status)
        rc = run(_args("status", "webui", json=True), _App(cwd=tmp_path))
    assert rc == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert payload["running"] is True
    assert payload["service"] == "webui"
    assert payload["service_id"] == "webui"


def test_run_start_webui_delegates_legacy(tmp_path, capsys):
    from core.cli.cmd_service import run
    fake = {"ok": True, "pid": 5, "port": 8199, "url": "u", "elapsed_sec": 0.1,
            "error": None, "exit_code": 0, "already_running": True}
    with patch("core.cli.cmd_webui._do_start", return_value=dict(fake)) as m:
        rc = run(_args("start", "webui", json=True), _App(cwd=tmp_path))
    assert rc == 0
    assert m.called
    import json
    payload = json.loads(capsys.readouterr().out)
    assert payload["already_running"] is True
    assert payload["service"] == "webui"


def test_run_info_openjutsu_unavailable_still_exits0(tmp_path, capsys):
    """info 不因未安装而报错 (对照退出码语义: 7 只属于 start/update 的拒绝路径)."""
    from core.cli.cmd_service import run
    cfg = {"environments": [{"id": "e", "comfyui_root": str(tmp_path), "python_path": "py"}],
           "active_env_id": "e"}
    rc = run(_args("info", "openjutsu", json=True), _App(cwd=tmp_path, cfg=cfg))
    assert rc == 0
    import json
    payload = json.loads(capsys.readouterr().out)
    assert payload["installed"] is False
    assert payload["requires_comfyui"] is True


def test_logs_target_openjutsu_resolves(tmp_path):
    from core.cli.runner import _resolve_log_path
    p = _resolve_log_path(_App(cwd=tmp_path), "openjutsu")
    assert p == Path(tmp_path) / "launcher" / "openjutsu.log"
    # webui 目标不受影响
    assert _resolve_log_path(_App(cwd=tmp_path), "webui") == Path(tmp_path) / "launcher" / "webui.log"
