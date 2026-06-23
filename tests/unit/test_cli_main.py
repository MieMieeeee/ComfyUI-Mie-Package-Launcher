"""Tests for core.cli.main.

main 是 CLI 入口：根据 parser 解出的 command 字段分派到对应 cmd_*.run，
统一设置 sys.argv 之外的 default（cwd / app 加载），返回退出码。

约定：
- 不在 main 内部 print 任何额外东西（sub-command 自己负责输出）
- 找不到 command → 退 1（理论不会发生：parser.required=True 已经拦住）
- 子命令 run 抛异常 → 退 1 + stderr 一行 trace
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

from core.cli import main as cli_main
from core.cli.exitcodes import EXIT_OK, EXIT_ERROR


def _ns(command: str, **kwargs):
    n = MagicMock()
    n.command = command
    n.json = kwargs.pop("json", False)
    n.verbose = kwargs.pop("verbose", 0)
    for k, v in kwargs.items():
        setattr(n, k, v)
    return n


class TestDispatch:
    def test_dispatches_to_status(self):
        args = _ns("status")
        with patch("core.cli.main._load_app", return_value=MagicMock()), \
             patch("core.cli.cmd_status.run", return_value=EXIT_OK) as mock_run:
            rc = cli_main.dispatch(args)
        assert rc == EXIT_OK
        assert mock_run.called

    def test_dispatches_to_start(self):
        args = _ns("start", no_wait=False, timeout=60)
        with patch("core.cli.main._load_app", return_value=MagicMock()), \
             patch("core.cli.cmd_start.run", return_value=EXIT_OK) as mock_run:
            rc = cli_main.dispatch(args)
        assert rc == EXIT_OK
        assert mock_run.called

    def test_dispatches_to_stop(self):
        args = _ns("stop", timeout=10, force=False)
        with patch("core.cli.main._load_app", return_value=MagicMock()), \
             patch("core.cli.cmd_stop.run", return_value=EXIT_OK) as mock_run:
            rc = cli_main.dispatch(args)
        assert rc == EXIT_OK

    def test_dispatches_to_restart(self):
        args = _ns("restart", no_wait=False, timeout=60)
        with patch("core.cli.main._load_app", return_value=MagicMock()), \
             patch("core.cli.cmd_restart.run", return_value=EXIT_OK) as mock_run:
            rc = cli_main.dispatch(args)
        assert rc == EXIT_OK

    def test_dispatches_to_info(self):
        args = _ns("info")
        with patch("core.cli.main._load_app", return_value=MagicMock()), \
             patch("core.cli.cmd_info.run", return_value=EXIT_OK) as mock_run:
            rc = cli_main.dispatch(args)
        assert rc == EXIT_OK

    def test_dispatches_to_logs(self):
        args = _ns("logs", logs_target="comfyui", lines=10, follow=False)
        with patch("core.cli.main._load_app", return_value=MagicMock()), \
             patch("core.cli.cmd_logs.run", return_value=EXIT_OK) as mock_run:
            rc = cli_main.dispatch(args)
        assert rc == EXIT_OK

    def test_dispatches_to_update(self):
        args = _ns("update", update_target="comfyui", yes=True, dry_run=False)
        with patch("core.cli.main._load_app", return_value=MagicMock()), \
             patch("core.cli.cmd_update.run", return_value=EXIT_OK) as mock_run:
            rc = cli_main.dispatch(args)
        assert rc == EXIT_OK

    def test_unknown_command_returns_exit_1(self, capsys):
        # 用一个 mock parser 解析不到 command 的情况
        from core.cli.parser import build_parser
        p = build_parser()
        # 手工构造一个 Namespace with command='weird'
        args = _ns("weird")
        with patch("core.cli.main._load_app", return_value=MagicMock()):
            rc = cli_main.dispatch(args)
        assert rc == EXIT_ERROR
        captured = capsys.readouterr()
        out_err = captured.out + captured.err
        assert "weird" in out_err or "unknown" in out_err.lower() or "未知" in out_err


class TestLoadApp:
    def test_load_app_uses_cwd_by_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # 写一个最小 config
        cfg_dir = tmp_path / "launcher"
        cfg_dir.mkdir(parents=True)
        (cfg_dir / "config.json").write_text("{}", encoding="utf-8")
        app = cli_main._load_app()
        assert app is not None

    def test_load_app_returns_none_on_missing_config(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        # 没 launcher/config.json
        app = cli_main._load_app()
        assert app is None
        captured = capsys.readouterr()
        assert "config" in captured.out.lower() or "config" in captured.err.lower()


class TestSubcommandErrorHandling:
    def test_subcommand_exception_returns_exit_1(self, capsys):
        args = _ns("status")
        with patch("core.cli.main._load_app", return_value=MagicMock()), \
             patch("core.cli.cmd_status.run", side_effect=RuntimeError("boom")):
            rc = cli_main.dispatch(args)
        assert rc == EXIT_ERROR
        captured = capsys.readouterr()
        assert "boom" in captured.out or "boom" in captured.err
