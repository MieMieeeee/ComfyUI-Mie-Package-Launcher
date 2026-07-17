"""start 子命令：等价于 GUI 启动按钮。"""
from core.cli.exitcodes import EXIT_OK, EXIT_ALREADY_RUNNING, EXIT_ERROR
from core.cli.output import format_human, format_json
from core.cli.runner import start_service

__all__ = ["run", "start_service"]


def run(args, app) -> int:
    no_wait = bool(getattr(args, "no_wait", False))
    timeout = int(getattr(args, "timeout", 60))
    env_id = getattr(args, "env", None)
    data = start_service(app, no_wait=no_wait, timeout=timeout, env_id=env_id)

    if getattr(args, "json", False):
        print(format_json(data))
    else:
        print(format_human(data))

    # 退出码：已跑 -> 2; 失败 -> 1; 成功 -> 0
    if not data.get("started") and data.get("pid") and not data.get("error"):
        return EXIT_ALREADY_RUNNING
    if not data.get("ready"):
        return EXIT_ERROR
    return EXIT_OK
