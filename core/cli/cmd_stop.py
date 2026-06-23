"""stop 子命令：等价于 GUI 停止按钮。"""
from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli.output import format_human, format_json
from core.cli.runner import stop_service

__all__ = ["run", "stop_service"]


def run(args, app) -> int:
    timeout = int(getattr(args, "timeout", 10))
    force = bool(getattr(args, "force", False))
    data = stop_service(app, timeout=timeout, force=force)

    if getattr(args, "json", False):
        print(format_json(data))
    else:
        print(format_human(data))

    # stop 的 no-op 情况（未跑）也是 EXIT_OK，约定 stop 不会失败
    return EXIT_OK
