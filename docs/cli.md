# ComfyUI 启动器 CLI

`comfyui-launcher` 内置 headless 命令行模式，复用 GUI 启动 / 停止路径，
适合配合 systemd / NSSM / 任务计划程序做开机自启 / 监控 / CI。

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
  update       更新组件（当前仅 comfyui）
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

PID 跨进程协调走 `<cwd>/launcher/comfyui.pid`（JSON：pid/port/started_at/log_path），
stale（PID 已死）当成不存在。

## 子命令

### start

启动 ComfyUI。默认阻塞直到 `/system_stats` 返回 200 或超时。

```
comfyui-launcher start [--no-wait] [--timeout SEC]
```

| flag | 默认 | 说明 |
|---|---|---|
| `--no-wait` | off | spawn 后立即返回，不等 `/system_stats` |
| `--timeout` | 60 | 等待就绪的最大秒数 |

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
comfyui-launcher restart [--no-wait] [--timeout SEC]
```

**Exit codes:**
- `0` 重启后服务就绪
- `1` 重启失败（stop 或 start 步骤失败）

**Output schema:** 合并 stop + start 字段（`stopped`, `started`, `ready`, `pid`, `port`, `url`, `elapsed_sec`）。

### info

读 `launcher/config.json` + `build_parameters.json`，把关键字段整理输出，
**不启动任何东西**。排查"我配了什么"时用。

```
comfyui-launcher info [--json]
```

**Output schema:**
- `launcher_version (str)` 启动器自报版本
- `comfyui_path (str)` 解析后的 ComfyUI 根目录
- `python_path (str)` 解析后的 python 可执行文件
- `port (int)` 当前生效 HTTP 端口
- `paths.*` config 里的 paths 块
- `launch_options.*` config 里的 launch_options 块
- `proxy_settings.*` config 里的 proxy_settings 块

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
GUI 的"更新内核"按钮。**当前仅支持 comfyui**；launcher 自更新和
custom-nodes 更新留作 phase 3。

```
comfyui-launcher update TARGET [--yes] [--dry-run] [--json]
```

`TARGET` 当前只能是 `comfyui`。

| flag | 默认 | 说明 |
|---|---|---|
| `--yes` | on | CLI 默认非交互，保留供将来用 |
| `--dry-run` | off | 只打印会做什么，不实际执行 |

**Exit codes:**
- `0` 已应用变更
- `4` 已是最新（无变更）
- `1` 更新失败（网络、冲突、dirty tree 等）

**Output schema:**
- `component (str)` `"comfyui"`
- `updated (bool)` 本次是否真的更新了
- `from_version (str|null)` 更新前版本
- `to_version (str|null)` 更新后版本（未变时为 null）
- `log (str)` 人类可读的更新摘要

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
