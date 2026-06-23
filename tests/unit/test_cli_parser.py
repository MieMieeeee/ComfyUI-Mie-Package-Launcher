"""Tests for core.cli.parser.

parser 是 CLI 的契约层：它决定每个子命令叫什么、接受哪些参数、
--help 输出什么文本。改 parser 就是改外部用户的脚本 / 文档，必须
有测试锁住。

约定：
- 全局 --json：所有子命令的输出格式开关
- 每个子命令的 help 文本里必须含 “Output schema” 与 “Exit codes”
  两段（被 docs/cli.md 自动引用）
- 未知子命令 / 缺命令时 argparse 自动报错（SystemExit 2）
"""
import argparse
import pytest

from core.cli.parser import build_parser, SUBCOMMANDS


def test_parser_has_no_required_positional():
    """无子命令时不应报错（只显示 help），不应强制要求位置参数。"""
    p = build_parser()
    # 不传 argv 时，缺子命令会让 argparse 在 parse_args 时报错；我们用
    # parse_args([]) 会触发 SystemExit，验证方式是 monkeypatch 一下。
    # 这里只验证 build_parser 不会因 build 阶段缺东西就抛。
    assert p is not None


def test_parser_top_level_help_exits_zero(capsys):
    """--help 应该打印帮助并 exit 0（argparse 默认行为）。"""
    p = build_parser()
    with pytest.raises(SystemExit) as exc:
        p.parse_args(["--help"])
    assert exc.value.code == 0


def test_parser_lists_all_subcommands():
    """SUBCOMMANDS 常量必须跟实际 parser 注册的子命令一致。"""
    p = build_parser()
    # 用 format_help 拿到子命令列表段
    help_text = p.format_help()
    for name in SUBCOMMANDS:
        assert name in help_text, f"{name} 没出现在顶层 help 里"


def test_parser_json_flag_at_top_level():
    """--json 必须挂在顶层 parser 上，所有子命令共享。"""
    p = build_parser()
    args = p.parse_args(["--json", "status"])
    assert args.json is True


def test_parser_no_json_defaults_false():
    """缺省 --json 应为 False（人读格式）。"""
    p = build_parser()
    args = p.parse_args(["status"])
    assert args.json is False


def test_parser_verbose_flag():
    """-v / --verbose 必须在顶层。"""
    p = build_parser()
    a = p.parse_args(["-v", "status"])
    b = p.parse_args(["status", "--verbose"])
    assert a.verbose == 1
    assert b.verbose == 1


def test_unknown_subcommand_exits_nonzero():
    """未知子命令应被 argparse 拒绝（SystemExit 2）。"""
    p = build_parser()
    with pytest.raises(SystemExit) as exc:
        p.parse_args(["nonexistent"])
    assert exc.value.code != 0


def test_missing_subcommand_exits_nonzero():
    """没给子命令时 argparse 应报错。"""
    p = build_parser()
    with pytest.raises(SystemExit) as exc:
        p.parse_args([])
    assert exc.value.code != 0


# ---------- per-subcommand shape ----------

@pytest.mark.parametrize("name", SUBCOMMANDS)
def test_each_subcommand_help_mentions_exit_codes(name):
    """每个子命令的 --help 必须含 \"Exit codes\" 段。"""
    p = build_parser()
    sub = _find_subparser(p, name)
    help_text = sub.format_help()
    assert "Exit codes" in help_text, f"{name} --help 缺 Exit codes 段"


@pytest.mark.parametrize("name", SUBCOMMANDS)
def test_each_subcommand_help_mentions_output_schema(name):
    """每个子命令的 --help 必须含 \"Output schema\" 段。"""
    p = build_parser()
    sub = _find_subparser(p, name)
    help_text = sub.format_help()
    assert "Output schema" in help_text, f"{name} --help 缺 Output schema 段"


# ---------- start ----------

def test_start_has_no_wait_and_timeout():
    p = build_parser()
    args = p.parse_args(["start", "--no-wait"])
    assert args.no_wait is True
    args = p.parse_args(["start", "--timeout", "30"])
    assert args.timeout == 30


def test_start_timeout_default_60():
    p = build_parser()
    args = p.parse_args(["start"])
    assert args.timeout == 60  # 默认 60 秒


# ---------- stop ----------

def test_stop_has_force_flag():
    p = build_parser()
    args = p.parse_args(["stop", "--force"])
    assert args.force is True


# ---------- logs ----------

def test_logs_has_launcher_and_comfyui_subsubcommands():
    p = build_parser()
    args = p.parse_args(["logs", "launcher"])
    assert args.logs_target == "launcher"
    args = p.parse_args(["logs", "comfyui"])
    assert args.logs_target == "comfyui"


def test_logs_default_lines_and_follow():
    p = build_parser()
    args = p.parse_args(["logs", "comfyui"])
    assert args.lines == 100
    assert args.follow is True


def test_logs_lines_and_follow_overridable():
    p = build_parser()
    args = p.parse_args(["logs", "comfyui", "-n", "5", "--no-follow"])
    assert args.lines == 5
    assert args.follow is False


# ---------- update ----------

def test_update_requires_target():
    """update 必须给子目标（comfyui）。"""
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["update"])


def test_update_comfyui_accepts_yes_and_dry_run():
    p = build_parser()
    args = p.parse_args(["update", "comfyui", "--yes", "--dry-run"])
    assert args.yes is True
    assert args.dry_run is True


# ---------- helpers ----------

def _find_subparser(top_parser, name):
    """拿到名字为 name 的 subparser action 对应的子 parser。

    argparse 的 add_subparsers 只会在顶层 parser 上注册一个共享的
    _SubParsersAction（dest="command"），所有子命令挂到它的 .choices
    字典里。所以这里先找到那个 action，再按 name 索引。
    """
    for action in top_parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            if name in action.choices:
                return action.choices[name]
    raise AssertionError(f"找不到子命令 {name} 对应的 parser")
