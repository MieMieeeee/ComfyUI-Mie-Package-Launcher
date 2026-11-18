"""restart 子命令：stop + start。"""
from core.cli.exitcodes import EXIT_OK, EXIT_ALREADY_RUNNING, EXIT_ERROR
from core.cli.output import format_human, format_json
from core.cli.runner import start_service, stop_service

__all__ = ["run", "start_service", "stop_service"]


def run(args, app) -> int:
    no_wait = bool(getattr(args, "no_wait", False))
    timeout = int(getattr(args, "timeout", 60))
    env_id = getattr(args, "env", None)

    # 先停（无论是否在跑都安全）
    stop_data = stop_service(app, timeout=timeout, force=False)

    # 再启（透传 --env）
    start_data = start_service(app, no_wait=no_wait, timeout=timeout, env_id=env_id)

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
    # 拒绝 / 失败原因必须透传：restart 的调用方（部署脚本 / agent）靠字段分支，
    # 「报成功但没换进程」时吞掉 error 会让旧代码静默服务一整晚（2026-11-05
    # 缺陷报告：stopped:false + started:false + ready:true 拿到 exit 0）。
    if stop_data.get("pid") is not None:
        combined["stopped_pid"] = stop_data.get("pid")
    for key in ("error", "running_env_id", "env_id"):
        if start_data.get(key) is not None:
            combined[key] = start_data[key]

    if getattr(args, "json", False):
        print(format_json(combined))
    else:
        print(format_human(combined))
        # 人类通道补一行结论（--json 是单行 JSON 契约，不能混排）：
        # 「没换成」必须显式说出来，不能让人从 stopped/started 两行里自己猜。
        if not combined["started"] and combined.get("pid") and not combined.get("error"):
            print(
                f"重启未生效：端口 {combined.get('port')} 仍被 pid "
                f"{combined['pid']} 持有，服务未换新（先处理残留实例再 restart）"
            )

    # 退出码语义（与 parser epilog / cli.md 同步）：
    #   0 = 真的重启了且就绪（started && ready）
    #   2 = 没换成——start 拒绝重复（端口上已有实例，多见于 stop 没能杀掉持有者）
    #   1 = 其它失败
    # ready 但 started=false（旧实例在应答探针）绝不能给 0：那正是
    # 「restart 报成功但没换进程」的事故形态。
    if combined["ready"] and combined["started"]:
        return EXIT_OK
    if not combined["started"] and combined.get("pid") and not combined.get("error"):
        return EXIT_ALREADY_RUNNING
    return EXIT_ERROR
