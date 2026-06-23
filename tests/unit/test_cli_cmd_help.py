"""Tests for core.cli.cmd_help.

help 子命令：无参 → 顶层 help；带 <sub> → 该子命令的 help。
"""
import argparse
from unittest.mock import MagicMock, patch

import pytest

from core.cli import cmd_help
from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli.parser import build_parser, SUBCOMMANDS


def _args(help_target=None, json=False):
    a = MagicMock()
    a.help_target = help_target
    a.json = json
    a.verbose = 0
    return a


def _app():
    return MagicMock()


class TestHelpNoArgs:
    def test_no_args_prints_top_level_help(self, capsys):
        args = _args()
        app = _app()
        rc = cmd_help.run(args, app)
        assert rc == EXIT_OK
        out = capsys.readouterr().out
        # 顶层 help 出现 7 个子命令 + help 自己
        for name in SUBCOMMANDS:
            assert name in out, f"top-level help should mention {name}"

    def test_no_args_returns_exit_ok(self, capsys):
        rc = cmd_help.run(_args(), _app())
        assert rc == EXIT_OK


class TestHelpWithSubcommand:
    @pytest.mark.parametrize("name", SUBCOMMANDS)
    def test_with_each_subcommand_prints_its_help(self, capsys, name):
        args = _args(help_target=name)
        app = _app()
        rc = cmd_help.run(args, app)
        assert rc == EXIT_OK
        out = capsys.readouterr().out
        # 至少含子命令的 usage 行和 Exit codes 段
        assert "Exit codes" in out
        # 顶部 usage 提到 <command> 的具体名字
        assert name in out or "usage" in out.lower()


class TestHelpUnknown:
    def test_unknown_target_returns_exit_1(self, capsys):
        args = _args(help_target="definitely_not_a_command")
        app = _app()
        rc = cmd_help.run(args, app)
        assert rc == EXIT_ERROR
        captured = capsys.readouterr()
        out_err = captured.out + captured.err
        # 错误信息应提到未知名字
        assert "definitely_not_a_command" in out_err
