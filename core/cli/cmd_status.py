"""status 子命令：打印运行状态，按 --json 切格式。

Exit codes:
  0  service is running (HTTP reachable)
  3  service is not running
  1  probe / config 异常
"""
from typing import Any

from core.cli.exitcodes import EXIT_OK, EXIT_NOT_RUNNING, EXIT_ERROR
from core.cli.output import format_human, format_json
from core.cli.runner import service_status

__all__ = ["run", "service_status"]


def run(args, app) -> int:
    """实现 `cli status [--json]` 的入口。返回进程退出码。"""
    try:
        data = service_status(app)
    except Exception as e:
        print(f"status failed: {e}")
        return EXIT_ERROR

    if getattr(args, "json", False):
        print(format_json(data))
    else:
        print(format_human(data))

    return EXIT_OK if data.get("running") else EXIT_NOT_RUNNING
