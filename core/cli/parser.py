"""argparse 子命令树。

是 CLI 的契约层：
- 子命令名（SUBCOMMANDS）必须稳定，供测试 / docs 引用
- 每个子命令的 epilog 列出 Exit codes 和 Output schema 段，
  --help 自动暴露给用户，cli.md 也按同样结构写

子命令列表：
    start       启动 ComfyUI（走 GUI 同一路径）
    stop        停止 ComfyUI
    status      打印运行状态
    restart     stop + start
    info        打印当前生效配置
    logs        tail 日志（launcher / comfyui 二选一）
    update      更新组件（comfyui 内核 / plugins 全部插件）
    plugins     管理 custom_nodes 插件（list/install/uninstall/disable/enable/check-updates/force-update）
"""
import argparse
from typing import Final, List

# 顶层稳定的子命令清单。供测试 / docs 引用，避免散落 magic string。
SUBCOMMANDS: Final[List[str]] = [
    "start",
    "stop",
    "status",
    "restart",
    "info",
    "logs",
    "update",
    "plugins",
    "help",
]

# logs 子命令的稳定目标清单。
LOGS_TARGETS: Final[List[str]] = ["launcher", "comfyui"]

# update 子命令的稳定目标清单。
UPDATE_TARGETS: Final[List[str]] = ["comfyui", "plugins"]

# plugins 子命令的稳定 action 清单。
PLUGINS_ACTIONS: Final[List[str]] = [
    "list", "install", "uninstall", "disable", "enable",
    "check-updates", "force-update",
]


# 各子命令的 epilog 模板（Exit codes + Output schema）

_START_EPILOG = """\
Exit codes:
  0  service is ready (HTTP reachable, or --no-wait and process spawned)
  1  failed to start (path missing, env error, process exited)
  2  service was already running (refuse to double-start)

Output schema (default human / --json):
  started     (bool)   - whether this invocation launched a new process
  pid         (int)    - PID of the ComfyUI process; null if not launched
  port        (int)    - HTTP port from config
  url         (str)    - http://127.0.0.1:<port>
  ready       (bool)   - whether /system_stats returned 200 within --timeout
  elapsed_sec (float)  - seconds from spawn to ready (or fail)
  log_path    (str)    - path to ComfyUI stdout log; null if unknown
"""

_STOP_EPILOG = """\
Exit codes:
  0  ComfyUI stopped (or was not running)
  1  failed to stop (signal sent but process did not exit within --timeout)

Output schema (default human / --json):
  stopped     (bool)   - whether a process was actually killed
  pid         (int)    - PID that was stopped; null if nothing to stop
  elapsed_sec (float)  - seconds from request to confirmed stop
"""

_STATUS_EPILOG = """\
Exit codes:
  0  service is running (HTTP reachable)
  3  service is not running
  1  probe error (config missing, port malformed, etc.)

Output schema (default human / --json):
  running        (bool)  - ComfyUI is up and HTTP-reachable
  pid            (int)   - tracked process PID; null when not running
  port           (int)   - HTTP port from config
  url            (str)   - http://127.0.0.1:<port>
  http_reachable (bool)  - /system_stats returned 200 within timeout
  log_path       (str)   - path to ComfyUI stdout log
  since          (str)   - ISO 8601 of process start; null if unknown
"""

_RESTART_EPILOG = """\
Exit codes:
  0  restarted and service is ready
  1  failed to restart (start or stop failed)
  2  service was already running and could not be stopped first

Output schema (default human / --json):
  stopped       (bool)  - whether a previous instance was stopped
  started       (bool)  - whether a new instance was launched
  ready         (bool)  - whether the new instance reached /system_stats 200
  elapsed_sec   (float) - total seconds (stop + start)
"""

_INFO_EPILOG = """\
Exit codes:
  0  printed effective configuration

Output schema (default human / --json):
  launcher_version (str)    - launcher self-reported version
  comfyui_path     (str)    - resolved ComfyUI root directory
  python_path      (str)    - resolved python executable
  port             (int)    - effective HTTP port
  paths.*          (object) - all paths.* values from config
  launch_options.* (object) - all launch_options.* values from config
  proxy_settings.* (object) - all proxy_settings.* values from config
"""

_LOGS_EPILOG = """\
Exit codes:
  0  logs read successfully
  1  log file not found (and no fallback available)

Output schema (default human / --json):
  target   (str)   - "launcher" or "comfyui"
  log_path (str)   - resolved path to the log file
  lines    (int)   - number of lines printed
  following (bool) - whether -f tail mode is active
"""

_UPDATE_EPILOG = """\
Exit codes:
  0  update completed
  4  already up-to-date (no changes)
  1  update failed (network, conflict, dirty tree, etc.)

Output schema (default human / --json):
  component    (str)   - "comfyui" (内核) | "plugins" (custom_nodes 插件)
  updated      (bool)  - whether any change was applied
  from_version (str)   - pre-update version; null if unknown
  to_version   (str)   - post-update version; null if unchanged
  log          (str)   - human-readable summary of what happened

Targets:
  comfyui  走 GUI 内核更新流程（git + 前端/模板库同步）
  plugins  调 ComfyUI-Manager 的 cm-cli update all（含每个插件的 pip 依赖修复）；
           需 ComfyUI-Manager 已装在 custom_nodes/ComfyUI-Manager
"""

_PLUGINS_EPILOG = """\
Exit codes:
  0  success (list/check-updates 总是 0；lifecycle op 成功；force-update 全部成功)
  1  failure (lifecycle op 失败 / force-update 有插件失败 / 路径错误等)

Output schema (default human / --json):

  list:
    plugins (list)  - [{name, dir_name, is_git, enabled, version, remote_url}]
    count   (int)   - 插件数

  install / uninstall / disable / enable <NAME>:
    action (str)   - 操作名
    target (str)   - 传入的 NAME（dir_name / git URL / CNR id）
    ok     (bool)  - 是否成功
    log    (str)   - cm-cli 输出
    error  (str)   - 失败原因；成功时 null

  check-updates:
    outdated (list) - 有更新的插件 dir_name 列表
    count    (int)  - 有更新的数量

  force-update [NAME]:
    results (list) - [{name, ok, skipped, detail}] 每插件结果
    all_ok  (bool) - 是否全部成功
"""

_HELP_EPILOG = """\
Exit codes:
  0  printed help
  1  unknown subcommand name

Output schema (default human / --json):
  target    (str|null) - which subcommand's help; null = top-level
  help_text (str)      - the help content (same as stdout in human mode)
"""


def _global_parent() -> argparse.ArgumentParser:
    """仅含全局 flag 的 parent parser。

    每个子 parser 通过 parents=[_global_parent()] 继承 --json / -v --verbose，
    让这些 flag 既可以出现在子命令前（`cli --json status`），也可以出现在
    子命令后（`cli status --verbose`）。

    关键技巧：parent 上的 default 用 argparse.SUPPRESS，意思是子 parser 解析
    时如果用户没传这个 flag，就不调用 setattr，从而保留顶层 parser 写入的
    值（包括顶层 default=False/0）。这样三个场景都正确：
      cli --json status   -> json=True
      cli status --json   -> json=True
      cli status          -> json=False（顶层 default 保留）
    """
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="以 JSON 格式输出，便于脚本解析。",
    )
    p.add_argument(
        "-v", "--verbose",
        action="count",
        default=argparse.SUPPRESS,
        help="打印更多调试信息（可叠加 -vv）。",
    )
    return p


def _make_subparser(sub, name: str, **kwargs) -> argparse.ArgumentParser:
    """统一的子 parser 工厂，统一 description 风格。

    自动挂上 parents=[_global_parent()]，让 --json / --verbose 在子命令
    前后都能用。
    """
    parents = kwargs.pop("parents", None) or []
    parents = list(parents) + [_global_parent()]
    kwargs["parents"] = parents
    return sub.add_parser(name, **kwargs)


# 多环境支持：以下子命令接受 --env <ENV_ID> 覆盖 config 里的激活环境。
# 不放进 _global_parent（那是给 --json/-v 这类输出控制 flag 的），而是按需
# 挂在会读路径的子命令上。stop / status 不挂：它们作用于「当前在跑的那个」，
# 跟环境选择无关。
_ENV_SUBCOMMANDS = {"start", "restart", "info", "logs", "update"}


def _add_env_arg(sp: argparse.ArgumentParser) -> None:
    """给子 parser 挂上 --env <ENV_ID>。"""
    sp.add_argument(
        "--env",
        type=str,
        default=None,
        metavar="ENV_ID",
        help="使用指定环境（覆盖 config 的 active_env_id）；"
             "不传则用激活环境。",
    )


def build_parser() -> argparse.ArgumentParser:
    """构造顶层 argparse。返回的 parser 可直接 parse_args(argv) 使用。"""
    p = argparse.ArgumentParser(
        prog="comfyui-launcher",
        description=(
            "ComfyUI 启动器命令行界面。复用 GUI 启动 / 停止路径，"
            "提供 headless 模式下的服务管理。可配合 systemd / NSSM / 任务计划程序"
            "做开机自启 / 监控。"
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出，便于脚本解析。",
    )
    p.add_argument(
        "-v", "--verbose",
        action="count",
        default=0,
        help="打印更多调试信息（可叠加 -vv）。",
    )

    sub = p.add_subparsers(
        title="commands",
        dest="command",
        required=True,
        metavar="<command>",
    )

    # start
    sp = _make_subparser(
        sub, "start",
        help="启动 ComfyUI（与 GUI 启动按钮行为一致）",
        description="在后台启动 ComfyUI。默认阻塞直到 HTTP 就绪或超时。",
        epilog=_START_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp.add_argument(
        "--no-wait",
        action="store_true",
        help="spawn 后立即返回，不等待 /system_stats 就绪。",
    )
    sp.add_argument(
        "--timeout",
        type=int,
        default=60,
        metavar="SEC",
        help="等待 HTTP 就绪的最大秒数（默认 60）。",
    )
    _add_env_arg(sp)

    # stop
    sp = _make_subparser(
        sub, "stop",
        help="停止 ComfyUI",
        description="按 pidfile / 端口回退链停掉 ComfyUI。",
        epilog=_STOP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp.add_argument(
        "--timeout",
        type=int,
        default=10,
        metavar="SEC",
        help="等待进程退出的最大秒数（默认 10）。",
    )
    sp.add_argument(
        "--force",
        action="store_true",
        help="跳过优雅终止，直接 taskkill /F。",
    )

    # status
    _make_subparser(
        sub, "status",
        help="查询 ComfyUI 运行状态",
        description="检查 HTTP 可达性 + pidfile，按退出码区分在跑 / 未跑 / 异常。",
        epilog=_STATUS_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # restart
    sp = _make_subparser(
        sub, "restart",
        help="先停后启 ComfyUI",
        description="stop 旧的 + start 新的；若旧实例未在跑则直接 start。",
        epilog=_RESTART_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp.add_argument(
        "--no-wait",
        action="store_true",
        help="spawn 后立即返回。",
    )
    sp.add_argument(
        "--timeout",
        type=int,
        default=60,
        metavar="SEC",
        help="等待新实例就绪的最大秒数（默认 60）。",
    )
    _add_env_arg(sp)

    # info
    sp = _make_subparser(
        sub, "info",
        help="打印当前生效的配置",
        description="读取 launcher/config.json 并把关键字段整理输出，不启动任何东西。",
        epilog=_INFO_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_env_arg(sp)

    # logs (有子目标)
    sp = _make_subparser(
        sub, "logs",
        help="tail 日志文件（launcher / comfyui 二选一）",
        description="打印最近 N 行日志，-f 持续跟踪。",
        epilog=_LOGS_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp.add_argument(
        "logs_target",
        choices=LOGS_TARGETS,
        metavar="TARGET",
        help='"launcher" 或 "comfyui"。',
    )
    sp.add_argument(
        "-n", "--lines",
        type=int,
        default=100,
        metavar="N",
        help="先打印最后 N 行（默认 100）。",
    )
    sp.add_argument(
        "-f", "--follow",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="持续跟踪新内容（默认开启，--no-follow 关闭）。",
    )
    _add_env_arg(sp)

    # help
    sp = _make_subparser(
        sub, "help",
        help="打印帮助（无参 = 顶层；带子命令名 = 该子命令的 help）",
        description="cli help 看顶层；cli help <subcommand> 看子命令的 help / Exit codes / Output schema。",
        epilog=_HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp.add_argument(
        "help_target",
        nargs="?",
        default=None,
        metavar="COMMAND",
        help="要查看帮助的子命令名；不传则打印顶层 help。",
    )

    # update
    sp = _make_subparser(
        sub, "update",
        help="更新组件（comfyui 内核 / plugins 插件）",
        description="comfyui: 走 GUI 内核更新流程（git + 前端/模板库同步）；"
                    "plugins: 调 ComfyUI-Manager cm-cli 更新全部 custom_nodes 插件（含 pip 依赖修复）。",
        epilog=_UPDATE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp.add_argument(
        "update_target",
        choices=UPDATE_TARGETS,
        metavar="TARGET",
        help='"comfyui" 或 "plugins"。',
    )
    sp.add_argument(
        "--yes",
        action="store_true",
        help="跳过确认（CLI 默认就要非交互，所以默认 yes；保留供未来用）。",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印会做什么，不实际执行。",
    )
    _add_env_arg(sp)

    # plugins
    sp = _make_subparser(
        sub, "plugins",
        help="管理 custom_nodes 插件（list/install/uninstall/disable/enable/check-updates/force-update）",
        description="复用 GUI 同一套 PluginService（走 ComfyUI-Manager cm-cli / 直接 git）。"
                    "list/check-updates 只读；install/uninstall/disable/enable 改状态；"
                    "force-update 对 dirty 树插件 git stash + pull。",
        epilog=_PLUGINS_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp.add_argument(
        "plugins_action",
        choices=PLUGINS_ACTIONS,
        metavar="ACTION",
        help="list / install / uninstall / disable / enable / check-updates / force-update。",
    )
    sp.add_argument(
        "plugins_name",
        nargs="?",
        default=None,
        metavar="NAME",
        help="install/uninstall/disable/enable/force-update 的目标插件（dir_name / git URL / CNR id）。"
             "force-update 省略则作用于全部。",
    )

    return p
