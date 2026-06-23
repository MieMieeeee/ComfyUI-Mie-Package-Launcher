"""restart 子命令：stop + start。"""
from core.cli.exitcodes import EXIT_OK, EXIT_ERROR
from core.cli.output import format_human, format_json
from core.cli.runner import start_service, stop_service

__all__ = ["run", "start_service", "stop_service"]


def run(args, app) -> int:
    no_wait = bool(getattr(args, "no_wait", False))
    timeout = int(getattr(args, "timeout", 60))

    # 先停（无论是否在跑都安全）
    stop_data = stop_service(app, timeout=timeout, force=False)

    # 再启
    start_data = start_service(app, no_wait=no_wait, timeout=timeout)

    combined = {
        "stopped": stop_data.get("stopped", False),
        "started": start_data.get("started", False),
        "ready": start_data.get("ready", False),
        "elapsed_sec": stop_data.get("elapsed_sec", 0.0) + start_data.get("elapsed_sec", 0.0),
        "pid": start_data.get("pid"),
        "port": start_data.get("port"),
        "url": start_data.get("url"),
        "log_path": start_data.get("log_path"),
    }

    if getattr(args, "json", False):
        print(format_json(combined))
    else:
        print(format_human(combined))

    return EXIT_OK if combined["ready"] else EXIT_ERROR
