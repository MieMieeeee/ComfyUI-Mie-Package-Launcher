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
    logs        tail 日志（launcher / comfyui / webui / openjutsu / h3-engine 五选一）
    update      更新组件（comfyui 内核 / plugins 全部插件）
    plugins     管理 custom_nodes 插件（list/install/uninstall/disable/enable/check-updates/force-update）
    webui       管理 WebUI 工作台（老命令，契约不变）
    service     管理伴生服务（openjutsu 等；webui 为名义条目转发老实现）
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
    "webui",
    "service",
    "package",
    "help",
]

# logs 子命令的稳定目标清单。
LOGS_TARGETS: Final[List[str]] = ["launcher", "comfyui", "webui", "openjutsu", "h3-engine"]

# update 子命令的稳定目标清单。
UPDATE_TARGETS: Final[List[str]] = ["comfyui", "plugins"]

# plugins 子命令的稳定 action 清单。
PLUGINS_ACTIONS: Final[List[str]] = [
    "list", "install", "uninstall", "disable", "enable",
    "check-updates", "force-update",
]

# webui 子命令的稳定 action 清单 (与 cmd_webui.WEBUI_ACTIONS 一致).
WEBUI_ACTIONS: Final[List[str]] = [
    "start", "stop", "status", "info", "restart",
    "install", "setup", "update",
]

# service 子命令的稳定 action 清单 (与 cmd_service.SERVICE_ACTIONS 一致).
SERVICE_ACTIONS: Final[List[str]] = [
    "list", "start", "stop", "status", "info", "restart",
    "install", "setup", "update",
]

# package 子命令的稳定 action 清单（与 cmd_package.py 一致）.
PACKAGE_ACTIONS: Final[List[str]] = ["show", "diff", "apply"]


# 各子命令的 epilog 模板（Exit codes + Output schema）

_START_EPILOG = """\
Exit codes:
  0  service is ready (HTTP reachable, or --no-wait and process spawned)
  1  failed to start (path missing, env error, process exited, port held
                     by a non-ComfyUI process, or ready-listener check failed)
  2  service was already running (refuse to double-start; includes adoption
                     of an externally restarted instance found by port)

Output schema (default human / --json):
  started     (bool)   - whether this invocation launched a new process
  pid         (int)    - PID of the ComfyUI process; null if not launched
  port        (int)    - HTTP port from config
  url         (str)    - http://127.0.0.1:<port>
  ready       (bool)   - /system_stats 200 within --timeout AND the port
                         listener is the spawned process (an old instance
                         answering the probe does not count as ready)
  elapsed_sec (float)  - seconds from spawn to ready (or fail)
  log_path    (str)    - path to ComfyUI stdout log; null if unknown
  error       (str)    - failure reason; only present on failure
  running_env_id (str) - env id of the running instance; only present when
                         start is refused because it is already running
"""

_STOP_EPILOG = """\
Exit codes:
  0  ComfyUI stopped (or was not running)
  1  failed to stop (signal sent but process did not exit within --timeout)

Output schema (default human / --json):
  stopped     (bool)   - whether a process was actually killed
  pid         (int)    - PID that was stopped (adopted external instance
                         included); null if nothing to stop
  elapsed_sec (float)  - seconds from request to confirmed stop

Notes: when the pidfile is stale, stop first adopts the externally restarted
ComfyUI found on the port (find_pids_by_port_safe + is_comfyui_pid identity
check), then kills it. "Not running" no-op only happens when no
identity-verified ComfyUI holds the port.
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
  0  restarted and service is ready (the newly spawned process must be the
     one answering on the port; an old instance answering never yields 0)
  1  failed to restart (start or stop failed, ready-listener check failed,
     or port held by a non-ComfyUI process)
  2  swap did not happen: start refused because an instance is already
     running (usually the stop step could not kill the port holder)

Output schema (default human / --json):
  stopped       (bool)  - whether a previous instance was stopped
  stopped_pid   (int)   - PID that was stopped; present when a stop target existed
  started       (bool)  - whether a new instance was launched
  ready         (bool)  - whether the new instance reached /system_stats 200
                          with the spawned process as the port listener
  elapsed_sec   (float) - total seconds (stop + start)
  pid / port / url / log_path - from the start step
  error         (str)   - failure reason; only present on failure
  running_env_id (str)  - env id of the running instance; only present when
                          start is refused because it is already running
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




_WEBUI_EPILOG = """\
Exit codes:
  0  success (start 时 webui 已在跑也返 0, already_running=true —— 幂等)
  1  general error (path missing / IO / timeout)
  3  status 进程未在跑
  6  webui start 时检测到 ComfyUI 未运行 (用了 --with-comfyui)
  7  webui 路径未安装 (用 install 子动作拉)
  8  webui 依赖缺失 (用 setup 子动作装)

Output schema (default human / --json):
  start / install / setup / update / restart:
    action       (str)   - 子动作名
    ok           (bool)  - 是否成功
    pid          (int)   - 启动后 PID, null 未启动
    port         (int)   - 端口
    url          (str)   - http://127.0.0.1:<port>
    elapsed_sec  (float) - 耗时秒
    env_id       (str)   - 实际生效的 env_id
    error        (str)   - 错误信息, null 时无

  stop:
    ok           (bool)  - 始终 true (未跑也返 0)
    pid          (int)   - 杀的 PID, null 时无
    killed       (bool)  - 是否真的杀到进程

  status:
    running        (bool) - webui 进程是否存在 (pidfile/Popen 活, 含 Flask 启动中)
    pid            (int)  - 跟踪到的 PID, null 时无
    port           (int)  - 端口
    url            (str)  - http://127.0.0.1:<port>
    http_reachable (bool) - HTTP 端口是否已就绪 (启动中时 running=True 但此处 False)
    log_path       (str)  - 启动器日志路径
    since          (str)  - 启动时间 ISO 8601
    env_id         (str)  - 启动时的 env id

  info:
    installed       (bool) - webui 路径 + 入口都在
    available       (bool) - installed + deps_ok
    webui_path      (str)  - 期望安装路径
    python_path     (str)  - 启动 webui 用的 python
    port            (int)  - 端口
    display_host    (str)  - 绑定地址
    deps_ok         (bool) - flask/requests/websockets 都装
    deps_missing    (list) - 缺哪些包
    deps_available  (list) - 已装哪些
    env_id          (str)  - env (透传 --env)

Actions:
  start    启动 webui (与 GUI 启动按钮行为一致)
  stop     停止 webui (幂等, 未跑也返 0)
  status   查询 webui 状态 (按 HTTP 端口活/死 + pidfile)
  info     打印 webui 当前生效配置 (供 agent 解析)
  restart  stop + start (跟 ComfyUI restart 同语义)
  install  拉 webui 仓库 + 装依赖 (无 webui 时)
  setup    仅装依赖 (webui 已 clone 但缺包时)
  update   git pull (webui 已装时)
"""

_SERVICE_EPILOG = """\
伴生服务（companion services）统一入口。服务是生命周期单元：start/ready/stop
对外原子，内部几条命令是实现细节。服务 100% 限定在整合包路径（环境 comfyui_root）下。

内置服务（注册表，见 core/companion/spec.py）:
  webui      WebUI 工作台 —— 名义条目，转发老 webui 子命令实现（行为/退出码一致）
  openjutsu  openjutsu 视频换角色 —— 走伴生服务新框架（proxy 8189 + app 3000）
  h3-engine  H3 短剧工作台（Beta）—— ComfyUI-Mie-H3-Engine 的 Flask 工作台（app 8200）

Actions:
  list      注册表总览（每服务 available / running）
  start     启动服务 (阻塞到全部端口就绪; --no-wait spawn 完即返)
  stop      停止服务 (幂等, 未跑也返 0; 进程树终止 + 端口复核)
  status    查询状态 (running=进程层[身份校验过], ready=加端口层)
  info      当前生效配置 (路径 / 端口 / 依赖 / 安装状态)
  restart   stop + start
  install   下载服务本体 (git clone 到包内; 目录已有内容则跳过, 不删用户数据)
  setup     装服务运行依赖 (pip 装进该环境的 embedded python)
  update    更新链 (openjutsu: git fetch+reset → npm ci → build → pip --target → patch;
            h3-engine: git fetch + reset --hard, 更新前先确保用户的资产库/密钥
            没被 git 跟踪 —— 被跟踪的文件会被 reset 还原掉)

--env <ENV_ID> 覆盖本次调用的环境 (start/stop/status/info/update 都支持)。
  注意 stop 也认 --env: 不带就是「当前激活环境」。

Exit codes (与 webui 子命令同值同义):
  0  success (start 时已在跑也返 0, already_running=true —— 幂等)
  1  general error (端口被占 / spawn 失败 / 超时)
  3  status 进程未在跑
  6  start 时 requires_comfyui 的服务发现 ComfyUI 未跑 (不强启动; 自动起走 GUI)
  7  服务未安装 / 当前环境无此服务
  8  依赖缺失 (openjutsu: node / .proxy-site / node_modules;
             h3-engine: 入口 / 该环境 python / MieNodes 资产库 / mie_* 依赖)

Output schema (--json, 单行):
  list:     {action, services: [{id, name, runtime, requires_comfyui,
             available, running}]}
  start:    {action, service, ok, exit_code, pids: [{pid, role}],
             ports: {role: port}, url, already_running, adopted, log_path, error}
  stop:     {action, service, ok, killed, residual_ports, elapsed_sec}
  status:   {action, service, running, ready, pids, ports: {role: {port, listening}},
             url, log_path, since, env_id, health}
  info:     {action, service, installed, root, ports, deps_ok, deps_missing, ...}
  update:   {action, service, ok, updated, log, error}

logs 目标: logs openjutsu 读 launcher/openjutsu.log, logs h3-engine 读
launcher/h3-engine.log (务必 --no-follow).
"""

_PACKAGE_EPILOG = """\
整合包更新：加载 manifest（本地文件 / HTTPS URL），show / diff / apply。

manifest 来源：http:// / https:// 前缀走 URL（http:// 拒绝，必须 HTTPS）；其它当本地文件。

Actions:
  show     加载 + 校验 + 打印摘要 + 与当前 env 对照的 diff
  diff     只输出 diff 段（agent 快速判断用）
  apply    应用 manifest

Exit codes:
  0   全部 ok / skipped / not_applicable（无 failed）
  1   通用错误
  5   部分失败（≥1 项 failed）—— ok_at_alt_path / not_applicable / manual_required 不算失败
  9   前置不兼容（dirty tree + clean_untracked=false / env 不匹配且未 --auto-yes）
  10  manifest 无效（schema / sha256 / manifest_version 超支持范围）
  11  文件不存在 / URL 不可达 / 解析失败 / manifest URL 非 HTTPS

Output schema (default human / --json):
  show  -> {manifest, valid, validation_error, diff, current_versions}
  diff  -> {items_already_satisfied, items_to_apply, items_manual_required, diff_basis}
  apply -> {manifest_id, run_id, started_at, finished_at, env_id, items[], summary, exit_hint}
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
_ENV_SUBCOMMANDS = {"start", "restart", "info", "logs", "update", "package"}


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
        help="tail 日志文件（launcher / comfyui / webui / openjutsu / h3-engine 五选一）",
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

    # package（整合包更新，v1.1.0 新增）
    sp = _make_subparser(
        sub, "package",
        help="加载整合包更新 manifest，show / diff / apply",
        description="加载 UP 主写的 manifest（本地文件 / HTTPS URL），show 看摘要 + diff，"
                    "apply 执行。manifest 描述 4 类变更：core / plugin / model / dependency。",
        epilog=_PACKAGE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp.add_argument(
        "package_action",
        choices=PACKAGE_ACTIONS,
        metavar="ACTION",
        help="show（摘要+diff）/ diff（仅 diff 段）/ apply（执行）。",
    )
    sp.add_argument(
        "source",
        metavar="PATH-OR-URL",
        help="manifest 的本地文件路径或 HTTPS URL（http:// 拒绝）。",
    )
    _add_env_arg(sp)
    sp.add_argument(
        "--items",
        type=str,
        default=None,
        metavar="ID1,ID2,...",
        help="apply 时只跑指定 item_id，其它 pending。",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="apply 时校验 + 模拟跑，不实际改文件 / pip / git。",
    )
    sp.add_argument(
        "--auto-yes",
        action="store_true",
        help="跳过所有交互确认（含 env 不匹配弹窗），脚本用。",
    )
    sp.add_argument(
        "--manual-yes",
        action="store_true",
        help="model 项视作用户已自行下载 → verify_manual。",
    )
    sp.add_argument(
        "--manual-skip",
        action="store_true",
        help="全部 model 项标 skipped。",
    )

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

    # webui
    sp = _make_subparser(
        sub, "webui",
        help="管理 Comfyui-Workbench-Mie (webui) 服务（与 ComfyUI 平级）",
        description="start / stop / status / info / restart / install / setup / update; 跟 ComfyUI 同一套 pidfile / 进程管理 / 日志设施, 但走 flask app 入口 -m app.flask_app。",
        epilog=_WEBUI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp.add_argument(
        "webui_action",
        choices=WEBUI_ACTIONS,
        metavar="ACTION",
        help="start / stop / status / info / restart / install / setup / update。",
    )
    sp.add_argument(
        "--env",
        type=str,
        default=None,
        metavar="ENV_ID",
        help="使用指定的环境（覆盖 config 的 active_env_id）; 不传则用激活环境。",
    )
    sp.add_argument(
        "--no-wait",
        action="store_true",
        help="spawn 后立即返回, 不等待 HTTP 就绪。",
    )
    sp.add_argument(
        "--timeout",
        type=int,
        default=60,
        metavar="SEC",
        help="等待 HTTP 就绪的最大秒数（默认 60）。",
    )
    sp.add_argument(
        "--with-comfyui",
        action="store_true",
        help="start 时要求 ComfyUI 已在跑; 否则返 exit code 6。仅做检测, 不强启动 ComfyUI。",
    )
    sp.add_argument(
        "--force",
        action="store_true",
        help="stop 时跳过优雅终止, 直接 taskkill /F。",
    )
    sp.add_argument(
        "--url",
        type=str,
        default=None,
        metavar="URL",
        help="install 时用这个 git URL 覆盖默认 (https://github.com/MieMieeeee/Comfyui-Workbench-Mie.git)。",
    )

    # service (伴生服务)
    try:
        from core.companion.spec import BUILTIN_SERVICES as _BUILTIN_SERVICES
        _service_ids_hint = ", ".join(sorted(_BUILTIN_SERVICES))
    except Exception:
        _service_ids_hint = "webui, openjutsu"
    sp = _make_subparser(
        sub, "service",
        help="管理伴生服务 (openjutsu / h3-engine 等, 与 ComfyUI 平级)",
        description="伴生服务统一入口: list / start / stop / status / info / restart /"
                    " install / setup / update."
                    " 服务是生命周期单元, 内部几条命令是实现细节;"
                    " webui 是名义条目, 转发老 webui 子命令实现。",
        epilog=_SERVICE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp.add_argument(
        "service_action",
        choices=SERVICE_ACTIONS,
        metavar="ACTION",
        help="list / start / stop / status / info / restart / install / setup / update。",
    )
    sp.add_argument(
        "service_id",
        nargs="?",
        default=None,
        metavar="SERVICE",
        help=f"服务 id (可选: {_service_ids_hint}); list 可省略。",
    )
    sp.add_argument(
        "--env",
        type=str,
        default=None,
        metavar="ENV_ID",
        help="使用指定的环境（覆盖 config 的 active_env_id）; 不传则用激活环境。",
    )
    sp.add_argument(
        "--url",
        type=str,
        default=None,
        metavar="URL",
        help="install 时用这个 git URL 覆盖默认仓库地址。",
    )
    sp.add_argument(
        "--no-wait",
        action="store_true",
        help="start: spawn 完立即返回, 不等待端口就绪。",
    )
    sp.add_argument(
        "--timeout",
        type=int,
        default=120,
        metavar="SEC",
        help="start 等待端口就绪的最大秒数（默认 120; openjutsu 首启含 npm build）。",
    )
    sp.add_argument(
        "--force",
        action="store_true",
        help="stop 时跳过优雅终止, 直接进程树强杀。",
    )

    return p
