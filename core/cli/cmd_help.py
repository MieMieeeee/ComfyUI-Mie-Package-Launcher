"""help 子命令：print top-level usage or a specific subcommand's help.

行为：
- `cli help`              → 顶层 usage
- `cli help <subcommand>` → 该子命令的 usage + Exit codes + Output schema
- `cli help unknown`      → 退 1 + stderr 一行提示

设计：
- 复用 parser 的 build_parser 拿到子 parser，调它的 format_help() 拿 help 字符串
- 始终走 stdout（不影响 --json 全局开关：help 本身是人类契约）
- schema 在 _HELP_EPILOG（parser.py）里和 --help 一致
"""
import argparse
import sys
from typing import Optional

from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli.output import format_human, format_json
from core.cli.parser import build_parser, SUBCOMMANDS

__all__ = ["run"]


def _find_subparser(top_parser: argparse.ArgumentParser, name: str) -> Optional[argparse.ArgumentParser]:
    """从顶层 parser 拿到名字为 name 的 subparser（和 test_cli_parser 的 helper 同源）。"""
    for action in top_parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            if name in action.choices:
                return action.choices[name]
    return None


def run(args, app) -> int:
    target = getattr(args, "help_target", None)
    p = build_parser()

    if target is None:
        # 顶层 help
        help_text = p.format_help()
        if getattr(args, "json", False):
            print(format_json({"target": None, "help_text": help_text}))
        else:
            print(help_text, end="" if help_text.endswith(chr(10)) else chr(10))
        return EXIT_OK

    if target not in SUBCOMMANDS:
        msg = f"unknown subcommand: {target!r} (available: {', '.join(SUBCOMMANDS)})"
        if getattr(args, "json", False):
            print(format_json({"target": target, "help_text": "", "error": msg}))
        else:
            print(msg, file=sys.stderr)
        return EXIT_ERROR

    sub = _find_subparser(p, target)
    if sub is None:
        # 理论上 SUBCOMMANDS 和实际注册的一致
        print(f"internal: subparser {target!r} not found", file=sys.stderr)
        return EXIT_ERROR

    help_text = sub.format_help()
    if getattr(args, "json", False):
        print(format_json({"target": target, "help_text": help_text}))
    else:
        print(help_text, end="" if help_text.endswith(chr(10)) else chr(10))
    return EXIT_OK
