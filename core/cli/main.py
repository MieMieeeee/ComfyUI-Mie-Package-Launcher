"""CLI 入口：解析 argv，分派到各 cmd_*.run，返回退出码。

设计上：
- main() 不直接 sys.exit，把退出码交给 __main__.py 统一 sys.exit
- dispatch(args) 走 switch-like 分派，新增子命令只需在 _DISPATCH 加一行
- _load_app() 负责创建 HeadlessAppContext（找不到配置时返回 None）
- 子命令 run 抛异常会被 dispatch 捕获，stderr 一行 trace，退出 EXIT_ERROR
"""
import sys
import traceback
from typing import Any, Optional

from core.cli import cmd_status, cmd_start, cmd_stop, cmd_restart, cmd_info, cmd_logs, cmd_update, cmd_help
from core.cli.exitcodes import EXIT_OK, EXIT_ERROR

__all__ = ["main", "dispatch", "_load_app", "_DISPATCH"]


# command name -> (module, run_fn_name)
_DISPATCH = {
    "status": cmd_status,
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "info": cmd_info,
    "logs": cmd_logs,
    "update": cmd_update,
    "help": cmd_help,
}


def _load_app() -> Optional[Any]:
    """创建 HeadlessAppContext。找不到 config 时返回 None，不抛。"""
    try:
        from headless_app import get_headless_app
        import os
        cwd = os.getcwd()
        return get_headless_app(cwd)
    except FileNotFoundError as e:
        print(f"config not found: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"failed to load app: {e}", file=sys.stderr)
        return None


def dispatch(args, app=None) -> int:
    """根据 args.command 调对应 cmd_*.run(args, app)。

    app 可以外部传入（方便测试和将来的 GUI 复用）；None 时自动 _load_app。
    """
    command = getattr(args, "command", None)
    if command not in _DISPATCH:
        print(f"unknown command: {command!r}", file=sys.stderr)
        return EXIT_ERROR

    if app is None:
        app = _load_app()
    if app is None:
        return EXIT_ERROR

    module = _DISPATCH[command]
    try:
        return int(module.run(args, app))
    except SystemExit:
        raise
    except Exception as e:
        # 测试可观察的稳定行为：stderr 一行 trace，EXIT_ERROR
        traceback.print_exc(file=sys.stderr)
        print(f"{command} failed: {e}", file=sys.stderr)
        return EXIT_ERROR


def main(argv: Optional[list] = None) -> int:
    """完整 CLI 入口：parse argv + dispatch + return code。

    argv 缺省走 sys.argv[1:]，与 argparse 默认一致。
    """
    from core.cli.parser import build_parser
    p = build_parser()
    args = p.parse_args(argv)
    return dispatch(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
