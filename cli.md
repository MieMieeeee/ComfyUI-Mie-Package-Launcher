# ComfyUI 启动器 CLI

`comfyui-launcher` 内置 headless 命令行模式，复用 GUI 启动 / 停止路径，
适合配合 systemd / NSSM / 任务计划程序做开机自启 / 监控 / CI。

agent / 自动化场景推荐用 **ComfyUI启动器-CLI.cmd**（仓库根目录）：

- 行为与 `ComfyUI启动器.exe <cmd>` 完全等价（参数 + 退出码透传）
- 名字带 -CLI，对监控 / NSSM / systemd / GitHub Actions 更友好
- 无参数调用转发到 `help`（不弹 GUI 窗口）
- 必须和 `ComfyUI启动器.exe` 同目录

## 概览

```
usage: comfyui-launcher [-h] [--json] [-v] <command> ...

options:
  -h, --help     show this help message and exit
  --json         以 JSON 格式输出，便于脚本解析
  -v, --verbose  打印更多调试信息（可叠加 -vv）

commands:
  start        启动 ComfyUI（与 GUI 启动按钮行为一致）
  stop         停止 ComfyUI
  status       查询 ComfyUI 运行状态
  restart      先停后启 ComfyUI
  info         打印当前生效的配置
  logs         tail 日志文件（launcher / comfyui 二选一）
  update       更新组件（comfyui 内核 / plugins 全部插件）
  plugins      管理 custom_nodes 插件（list/install/uninstall/disable/enable/check-updates/force-update）
  help         打印帮助（无参 = 顶层；带子命令名 = 该子命令的 help）
```

每个子命令都有自己的 `--help`，会打印 *Exit codes* 与 *Output schema* 两段。
这两段是脚本 / 监控读 CLI 的契约，不要随意改；改了请同步更新本文件。

## 全局约定

- 所有子命令都支持 `--json`，输出紧凑单行 JSON，便于 jq / shell pipeline。
- `-v` / `--verbose` 可叠加（`-vv` 更啰嗦），子命令前后都能放。
- 退出码统一在 `core/cli/exitcodes.py` 集中定义，跨子命令含义稳定：
  - `0` 成功
  - `1` 通用错误（路径缺失、env 异常、IO 失败等）
  - `2` start 拒绝重复启动（已在跑）
  - `3` status 检测到未运行
  - `4` update 检测到已是最新
- **多环境**：配置可存多组环境（`config.json` 的 `environments[]` + `active_env_id`）。CLI 默认跑 `active_env_id` 指向的那一份，**agent / 监控不需要也不应该传 `--env`**——切环境是 GUI 的事。`start` / `restart` / `info` / `logs` / `update` 接受可选的 `--env ENV_ID`（覆盖本次调用的环境，不写回 config），仅在跨环境自动化 / 一次性脚本里用。同一时间只允许一个环境在跑：`start` 发现已有 pidfile 时拒绝并返回 `running_env_id`，要先 `stop` 再换。

PID 跨进程协调走 `<cwd>/launcher/comfyui.pid`（JSON：pid/port/started_at/log_path），
stale（PID 已死）当成不存在。

## 子命令

### start

启动 ComfyUI。默认阻塞直到 `/system_stats` 返回 200 或超时。

```
comfyui-launcher start [--no-wait] [--timeout SEC] [--env ENV_ID]
```

| flag | 默认 | 说明 |
|---|---|---|
| `--no-wait` | off | spawn 后立即返回，不等 `/system_stats` |
| `--timeout` | 60 | 等待就绪的最大秒数 |
| `--env` | (config 的 `active_env_id`) | 一次性指定本次启动使用的环境 ID；不传则用 GUI 当前激活环境 |

**Exit codes:**
- `0` 服务就绪（或 `--no-wait` 且进程 spawn 成功）
- `1` 启动失败（路径不存在、env 异常、进程异常退出、超时）
- `2` 已在跑（pidfile 显示有活进程）

**Output schema (human / `--json`):**
- `started (bool)` 本次调用是否 spawn 了新进程
- `pid (int|null)` ComfyUI PID；未启动时为 null
- `port (int)` HTTP 端口
- `url (str)` `http://127.0.0.1:<port>`
- `ready (bool)` 是否在 `--timeout` 内拿到 200
- `elapsed_sec (float)` 从 spawn 到就绪（或失败）的耗时
- `log_path (str|null)` ComfyUI 日志路径

### stop

按 pidfile + 端口回退链停掉 ComfyUI。未运行是 no-op（也返回 0）。

```
comfyui-launcher stop [--timeout SEC] [--force]
```

| flag | 默认 | 说明 |
|---|---|---|
| `--timeout` | 10 | 等待进程退出的最大秒数 |
| `--force` | off | 跳过优雅终止，直接 `taskkill /F` |

**Exit codes:**
- `0` 成功停掉（或本就没在跑）
- `1` 停止失败

**Output schema:**
- `stopped (bool)` 是否真的 kill 了进程
- `pid (int|null)` 被停掉的 PID；nothing-to-stop 时为 null
- `elapsed_sec (float)` 从请求到确认停止的耗时

### status

读 pidfile + HTTP probe，按退出码区分在跑 / 未跑 / 异常。

```
comfyui-launcher status [--json]
```

**Exit codes:**
- `0` 在跑且 HTTP 可达
- `3` 未跑
- `1` probe 异常（配置缺失、端口格式错误等）

**Output schema:**
- `running (bool)` HTTP 可达
- `pid (int|null)` pidfile 里的 PID；未跑时 null
- `port (int)` HTTP 端口
- `url (str)` `http://127.0.0.1:<port>`
- `http_reachable (bool)` `/system_stats` 是否在超时内返回 200
- `log_path (str|null)` ComfyUI 日志路径
- `since (str|null)` ISO 8601 启动时间

**示例:**
```bash
$ comfyui-launcher status --json
{"running": true, "pid": 1234, "port": 8188, "url": "http://127.0.0.1:8188", "http_reachable": true, "log_path": "C:/ComfyUI-Mie/ComfyUI/user/comfyui.log", "since": "2026-06-23T10:00:00+00:00"}
$ echo $?
0
```

### restart

stop 旧的 + start 新的。若旧实例未在跑则直接 start。

```
comfyui-launcher restart [--no-wait] [--timeout SEC] [--env ENV_ID]
```

| flag | 默认 | 说明 |
|---|---|---|
| `--no-wait` | off | spawn 后立即返回 |
| `--timeout` | 60 | 等待新实例就绪的最大秒数 |
| `--env` | (config 的 `active_env_id`) | 一次性指定本次重启使用的环境 ID；不传则用 GUI 当前激活环境 |

**Exit codes:**
- `0` 重启后服务就绪
- `1` 重启失败（stop 或 start 步骤失败）

**Output schema:** 合并 stop + start 字段（`stopped`, `started`, `ready`, `pid`, `port`, `url`, `elapsed_sec`）。

### info

读 `launcher/config.json` + `build_parameters.json`，把关键字段整理输出，
**不启动任何东西**。排查"我配了什么"时用。

```
comfyui-launcher info [--json] [--env ENV_ID]
```

| flag | 默认 | 说明 |
|---|---|---|
| `--env` | (config 的 `active_env_id`) | 一次性指定查看哪个环境的配置；不传则查 GUI 当前激活环境 |

**Output schema:**
- `launcher_version (str)` 启动器自报版本
- `comfyui_path (str)` 解析后的 ComfyUI 根目录
- `python_path (str)` 解析后的 python 可执行文件
- `port (int)` 当前生效 HTTP 端口
- `paths.*` config 里的 paths 块
- `launch_options.*` config 里的 launch_options 块
- `proxy_settings.*` config 里的 proxy_settings 块
- `models.external_libraries[]` 外置模型库列表，每项含 `id / name / base_path / enabled / is_default`
- `models.disable_external (bool)` 全局禁用手写外置模型库的旧开关（向后兼容，新逻辑以 `external_libraries[]` 的 `enabled` 为准）

### logs

tail 日志文件。

```
comfyui-launcher logs TARGET [-n N] [-f | --no-follow]
```

`TARGET` ∈ `comfyui` / `launcher`，对应：
- `comfyui` → `<comfyui_root>/user/comfyui.log`
- `launcher` → `<cwd>/launcher/launcher.log`

| flag | 默认 | 说明 |
|---|---|---|
| `-n / --lines` | 100 | 先打印最后 N 行 |
| `-f / --follow` | on | 持续跟踪新内容（`--no-follow` 关闭） |
| `--env` | (config 的 `active_env_id`) | 一次性指定看哪个环境的日志；不传则看 GUI 当前激活环境 |

> **注：** `-f` 模式会永久 hang，不适合监控脚本。监控请用 `status` / 读 pidfile 配合外部日志采集。

**Exit codes:**
- `0` 读到了
- `1` log 文件不存在（且无回退路径）

**Output schema:**
- `target (str)` `"launcher"` / `"comfyui"`
- `log_path (str)` 解析到的日志路径
- `lines (int)` 实际打印的行数
- `following (bool)` `-f` 模式是否生效

### update

走 `services.update_service.UpdateService` 的批量更新路径，等价于
GUI 的"更新内核"按钮。支持两个 target：

- `comfyui`：内核更新（git + 前端/模板库同步）
- `plugins`：调 ComfyUI-Manager 的 cm-cli `update all`，更新全部 custom_nodes
  插件（含每个插件的 pip 依赖修复）。需要 ComfyUI-Manager 已装在
  `custom_nodes/ComfyUI-Manager`。

```
comfyui-launcher update TARGET [--yes] [--dry-run] [--json]
```

`TARGET` 取 `comfyui` 或 `plugins`。

| flag | 默认 | 说明 |
|---|---|---|
| `--yes` | on | CLI 默认非交互，保留供将来用 |
| `--dry-run` | off | 只打印会做什么，不实际执行 |
| `--env` | (config 的 `active_env_id`) | 一次性指定更新哪个环境；不传则更新 GUI 当前激活环境 |

**Exit codes:**
- `0` 已应用变更
- `4` 已是最新（无变更）
- `1` 更新失败（网络、冲突、dirty tree 等）

**Output schema:**
- `component (str)` `"comfyui"` 或 `"plugins"`
- `updated (bool)` 本次是否真的更新了
- `from_version (str|null)` 更新前版本（plugins target 为 null）
- `to_version (str|null)` 更新后版本（未变时为 null）
- `log (str)` 人类可读的更新摘要

### plugins

管理 custom_nodes 插件，复用 GUI 同一套 `PluginService`（走 ComfyUI-Manager
的 cm-cli / 直接 git）。只读操作（list/check-updates）不改状态；lifecycle
操作（install/uninstall/disable/enable）改状态；force-update 对 dirty 树
插件做 `git stash` + `git pull --ff-only`（绕过 cm-cli）。

```
comfyui-launcher plugins ACTION [NAME] [--json]
```

`ACTION` 取 `list` / `install` / `uninstall` / `disable` / `enable` /
`check-updates` / `force-update`。`NAME` 对 lifecycle/force-update 必填
（插件 dir_name / git URL / CNR id）；`force-update` 省略 NAME 则作用于全部。

| flag | 默认 | 说明 |
|---|---|---|
| `ACTION` | 必填 | 操作类型 |
| `NAME` | 无 | lifecycle/force-update 的目标；省略时 force-update 作用于全部 |

**Exit codes:**
- `0` 成功（list/check-updates 总是 0；lifecycle op 成功；force-update 全部成功或无插件）
- `1` 失败（lifecycle op 失败 / force-update 有插件失败 / 路径错误等）

**Output schema:**
- `list`: `plugins (list)` 每项 `{name, dir_name, is_git, enabled, version, remote_url}`；`count (int)`
- `install/uninstall/disable/enable`: `action (str)` `target (str)` `ok (bool)` `log (str)` `error (str|null)`
- `check-updates`: `outdated (list)` 有更新的 dir_name 列表；`count (int)`
- `force-update`: `results (list)` 每项 `{name, ok, skipped, detail}`；`all_ok (bool)`

> 禁用态：ComfyUI-Manager 通过给目录加 `.disabled` 后缀禁用插件。`list` 输出里
> `enabled=false` 的项即被禁用，`name` 是刻掉后缀的纯名，`dir_name` 带后缀；
> 后续操作一律传 `dir_name`。

**示例:**
```bash
$ comfyui-launcher plugins list --json | jq '.count'
12

$ comfyui-launcher plugins check-updates --json
{"outdated": ["ComfyUI-KJNodes"], "count": 1, "error": null}

$ comfyui-launcher plugins disable ComfyUI-KJNodes
ok: true
log: disabled ComfyUI-KJNodes

$ comfyui-launcher plugins force-update MieNodes
ok: true
log: Already up to date.
```

### help

打印帮助。和 `-h/--help` 等价，但是是可以拼接的：可以看任意子命令的 help。

```
comfyui-launcher help [COMMAND]
```

无参 → 顶层 usage；带子命令名 → 该子命令的 help / Exit codes / Output schema。
未知子命令 → 退 1 + stderr 一行提示。

| flag | 默认 | 说明 |
|---|---|---|
| `--json` | off | 把 help 文本包成 `{"target": ..., "help_text": ...}` 输出 |

**Exit codes:**
- `0` 打印了 help
- `1` 未知子命令名

**Output schema:**
- `target (str|null)` 哪个子命令的 help；null = 顶层
- `help_text (str)` help 内容（human 模式下走 stdout）

**示例:**
```bash
$ comfyui-launcher help start | head -3
usage: comfyui-launcher start [-h] [--json] [-v] [--no-wait] [--timeout SEC]

在后台启动 ComfyUI。默认阻塞直到 HTTP 就绪或超时。

$ comfyui-launcher help unknown_cmd
unknown subcommand: 'unknown_cmd' (available: start, stop, status, restart, info, logs, update, help)
$ echo $?
1
```

## 退出码一览

| 码 | 含义 | 出现在 |
|---|---|---|
| 0 | 成功 | 所有 |
| 1 | 通用错误 | 所有 |
| 2 | start 拒绝重复 | start |
| 3 | 未在跑 | status |
| 4 | 已是最新 | update |

外部脚本（systemd / NSSM / 监控 agent）按这张表判断是否需要重试 / 告警；
值稳定，请勿随意改。

## 监控脚本示例

### 1. systemd oneshot 服务

```ini
# /etc/systemd/system/comfyui.service
[Service]
Type=oneshot
ExecStart=/opt/comfyui-launcher/launcher start --no-wait
ExecStop=/opt/comfyui-launcher/launcher stop
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

### 2. cron 监控存活

```bash
*/5 * * * * /opt/comfyui-launcher/launcher status --json | jq -e ".running" >/dev/null || systemctl restart comfyui
```

### 3. NSSM（Windows）

```cmd
nssm set ComfyUI AppParameters stop
nssm set ComfyUI MonitorAppParameters status --json
```

## 故障排查

| 现象 | 检查 |
|---|---|
| `status` 一直返回 1 | 跑 `info` 看 config 是不是有效；端口是不是被占 |
| `start` 一直返回 1 | `logs comfyui` 看 stdout；确认 python / main.py 路径 |
| `update` 失败 | 跑 `update comfyui --dry-run` 看会做什么；检查 git 树脏 / 网络 |
| GUI 启动时 `__main__.py` 报 access violation | CLI 模式正常，问题是 Qt 那一侧，与 CLI 无关 |
