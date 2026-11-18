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
  logs         tail 日志文件（launcher / comfyui / webui / openjutsu / h3-engine 五选一）
  update       更新组件（comfyui 内核 / plugins 全部插件）
  plugins      管理 custom_nodes 插件（list/install/uninstall/disable/enable/check-updates/force-update）
  webui        管理 Comfyui-Workbench-Mie (webui) 服务，与 ComfyUI 平级（详见 `webui --help`）
  service      管理伴生服务（openjutsu / h3-engine；webui 为名义条目转发老实现，详见 `service --help`）
  package      加载整合包更新 manifest，show / diff / apply（详见 `package --help`）
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
- `1` 启动失败（路径不存在、env 异常、进程异常退出、超时、端口被非 ComfyUI 进程占用、就绪校验不过）
- `2` 已在跑（pidfile 显示有活进程，或端口被身份校验过的 ComfyUI 实例占用——收养后按已跑返回）

**Output schema (human / `--json`):**
- `started (bool)` 本次调用是否 spawn 了新进程
- `pid (int|null)` ComfyUI PID；未启动时为 null
- `port (int)` HTTP 端口
- `url (str)` `http://127.0.0.1:<port>`
- `ready (bool)` 是否在 `--timeout` 内拿到 200 **且监听端口的就是本进程**（旧实例占着端口应答探针、新进程 bind 失败秒死的情况会判 false 并带 `error`）
- `elapsed_sec (float)` 从 spawn 到就绪（或失败）的耗时
- `log_path (str|null)` ComfyUI 日志路径
- `error (str)` 仅失败时出现：失败原因（含端口占用者 pid）
- `running_env_id (str)` 仅「已在跑」拒绝时出现：当前在跑的环境 id

### stop

按 pidfile + 端口回退链停掉 ComfyUI。未运行是 no-op（也返回 0）。

pidfile 失联（外部重启 / Manager 网页重启链换了 PID）时，会先按端口**收养**
（`find_pids_by_port_safe` + `is_comfyui_pid` 身份校验，只收校验过的 PID）再停——
端口上没有身份匹配的 ComfyUI 进程才视为「未在跑」no-op。

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
- `pid (int|null)` 被停掉的 PID（含收养来的外部实例）；nothing-to-stop 时为 null
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
- `0` 重启后服务就绪（**必须是本次拉起的新进程在应答**——旧实例占着端口、新进程没换上的情况绝不返回 0）
- `1` 重启失败（stop 或 start 步骤失败、就绪校验不过、端口被非 ComfyUI 进程占用）
- `2` 没换成：start 拒绝重复（端口上已有实例，多见于 stop 没能杀掉持有者；人类通道会打一行「重启未生效：端口 X 仍被 pid Y 持有」）

**Output schema:** 合并 stop + start 字段：
- `stopped (bool)` / `stopped_pid (int)` 旧实例是否被停掉 / 被停的是谁
- `started (bool)` 是否拉起了新进程
- `ready (bool)` 新实例是否就绪（就绪校验含监听者身份，见 start）
- `pid (int|null)` / `port (int)` / `url (str)` / `log_path (str|null)` / `elapsed_sec (float)`
- `error (str)` 仅失败时出现
- `running_env_id (str)` 仅 start 拒绝时出现：当前在跑的环境 id

### info

读 `launcher/config.json` + `core/version.py`（版本号）+ `build_parameters.json`（编译时间），
把关键字段整理输出，**不启动任何东西**。排查"我配了什么"时用。

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

`TARGET` ∈ `comfyui` / `launcher` / `webui` / `openjutsu` / `h3-engine`，对应：
- `comfyui` → `<comfyui_root>/user/comfyui.log`
- `launcher` → `<cwd>/launcher/launcher.log`
- `webui` → `<cwd>/launcher/webui.log`
- `openjutsu` → `<cwd>/launcher/openjutsu.log`
- `h3-engine` → `<cwd>/launcher/h3-engine.log`

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
- `target (str)` `"launcher"` / `"comfyui"` / `"webui"` / `"openjutsu"` / `"h3-engine"`
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
- `error_detail (str)` **仅失败时非空**：cm-cli 原始输出的**尾部**（含 traceback，
  最多 4000 字符）。cm-cli 的报错栈在输出末尾，`log`（头部截断）里看不到 ——
  失败时直接读这个字段定位（GUI 侧同一份内容显示在失败弹窗里）

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
- `install/uninstall/disable/enable`: `action (str)` `target (str)` `ok (bool)` `log (str)` `error_detail (str)` `error (str|null)`
  - `error_detail`：失败时是 cm-cli 原始输出的**尾部**（含 traceback，最多 4000 字符），
    成功时为空串。cm-cli 的报错栈在输出末尾，`log`（头部截断）里看不到。
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

### package

加载 UP 主写的整合包更新 manifest（JSON），展示 / 对照 / 应用 4 类变更（core / plugin /
model / dependency）。manifest 来源：本地文件路径 或 HTTPS URL（`http://` 拒绝）。

```
comfyui-launcher package <ACTION> <PATH-OR-URL> [flags]
```

| action | 用途 |
|---|---|
| `show` | 加载 + 校验 manifest，打印摘要 + 与当前 env 对照的 diff |
| `diff` | 只输出 diff 段（agent 快速判断哪些 item 需要跑） |
| `apply` | 应用 manifest（串行跑 items） |

| flag | 默认 | 说明 |
|---|---|---|
| `--items ID1,ID2,...` | 全部 | apply 时只跑指定 item_id，其它 pending |
| `--dry-run` | off | apply 时校验 + 模拟跑，不实际改文件 |
| `--auto-yes` | off | 跳过所有交互确认（含 env 不匹配弹窗），脚本用 |
| `--manual-yes` | off | model 项视作用户已自行下载 → verify_manual |
| `--manual-skip` | off | 全部 model 项标 skipped |
| `--env ENV_ID` | active | 一次性指定 env（不写回 config） |
| `--json` | off | 单行 JSON 输出 |

**Exit codes**（`package apply`）：0 成功 / 1 通用错 / 5 部分失败 / 9 前置不兼容 /
10 manifest 无效 / 11 源不可达。详见 §退出码一览。

**apply 典型节奏**：先 `package show <url> --json` 看 diff + current_versions →
确认要跑 → `package apply <url> --auto-yes` → 失败查 `package apply` 的 `--json` report。
model 项永远需要用户手动下载（启动器不下载模型，只校验文件存在）；UP 主会在视频描述给链接。

### service

伴生服务（companion services）统一入口。服务是生命周期单元：`start` 阻塞到**全部端口就绪**（端口探测，不做 HTTP），`stop` 是进程树终止 + 端口复核 + **身份过滤**清残。服务 100% 限定在整合包路径（环境 `comfyui_root`）下——当前环境没有该服务时返回退出码 7。

```
comfyui-launcher service list [--json]
comfyui-launcher service <ACTION> <SERVICE_ID> [flags]
```

`ACTION` ∈ `start / stop / status / info / restart / install / setup / update`；`SERVICE_ID` ∈ `webui / openjutsu / h3-engine`（内置注册表 `core/companion/spec.py`）。
`service ... webui` 转发老 `webui` 子命令实现（strangler：webui 运行时本期不在新框架上，行为/退出码一致）。

openjutsu（`requires_comfyui`）：`start` 前 ComfyUI 必须在跑，否则退 6（不强启动，自动起走 GUI 一键启动）；三进程链 `npm build → proxy(8197) → app(8198)`，pidfile 是 v2 多进程格式（`launcher/openjutsu.pid`），日志三路合一（`launcher/openjutsu.log`，`[build]/[proxy]/[app]` 前缀）。

h3-engine（H3 短剧工作台）：ComfyUI-Mie-H3-Engine 自带的 Flask 工作台，单进程（`<环境 python> -u <插件根>/webapp/__main__.py`），端口 8200（覆盖键 `services.h3-engine.port`）。**不要求 ComfyUI 在跑**（工作台离线也能管资产/剧本，只有提交渲染才需要 ComfyUI），所以 `requires_comfyui=false`、也不会被 `stop_orphan_companions` 顺手停掉。就绪判据比端口更严：`GET /api/health` 要回 `status=ok` 且 `app=comfyui-mie-web`。日志直写文件（`launcher/h3-engine.log`），CLI 起完退出后服务照样能写日志。安装链与 WebUI 工作台同构：`install` = clone 引擎（目录已有内容则跳过，**不删用户数据**）；`setup` = 把引擎的 `requirements.txt` 装进该环境的 embedded python；`update` = `git fetch + reset --hard`（**用户的资产库与密钥不会被覆盖**：引擎仓库 .gitignore 已排除它们，更新前还会再体检一次）。

| flag | 默认 | 说明 |
|---|---|---|
| `--env ENV_ID` | 激活环境 | 一次性环境覆盖（同全局约定，agent 默认不传）；`service` 的 stop/status/info **也认**它 |
| `--url URL` | (服务声明的仓库地址) | install 时用这个 git URL 覆盖默认 |
| `--no-wait` | off | start：spawn 完即返，不等端口就绪 |
| `--timeout SEC` | 120 | start 等待端口就绪的最大秒数（openjutsu 含 npm build，别压太低） |
| `--force` | off | stop：跳过优雅终止，直接进程树强杀 |

**Exit codes:** `0` 成功（已在跑也返 0，`already_running=true` 幂等）/ `1` 通用（端口被占、spawn 失败、超时）/ `3` status 未在跑 / `6` ComfyUI 未跑（requires_comfyui 服务）/ `7` 未安装或环境无此服务 / `8` 依赖缺失（openjutsu: node / .proxy-site / node_modules；h3-engine: 入口 / 该环境 python / 资产库目录 / mie_llm·mie_craft·mie_prompt·soundfile·flask 依赖）。

**Output schema（--json 单行，字段见 `service --help` epilog）:**
- `list`：`services: [{id, name, runtime, requires_comfyui, available, running}]`
- `start`：`{ok, exit_code, pids: [{pid, role}], ports: {role: port}, url, already_running, adopted, log_path, error}`
- `status`：`{running, ready, pids, ports: {role: {port, listening}}, url, since, env_id, health}`（`health` 只有提供语义探针的 runtime 才有值）
- `info`：`{installed, root, ports, deps_ok, deps_missing, ...}`（依赖按**所选服务自己的 runtime** 查）
- `update`（openjutsu 五步链 `git fetch+reset → npm ci → build → pip --target → patch`）：`{ok, updated, log, error}`（h3-engine 的 update 会明确拒绝：引擎本体走「插件管理」）

`logs openjutsu` 读 `<cwd>/launcher/openjutsu.log`，`logs h3-engine` 读 `<cwd>/launcher/h3-engine.log`（自动化里**务必 `--no-follow`**）。

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
| 2 | start 拒绝重复；restart 没换成（端口上已有实例，服务没被换新） | start, restart |
| 3 | 未在跑 | status |
| 4 | 已是最新 | update |
| 5 | package apply 部分失败（≥1 项 failed） | package |
| 6 | webui start 时 ComfyUI 未运行（用了 `--with-comfyui`）；service start 的 requires_comfyui 服务（openjutsu）发现 ComfyUI 未跑 | webui, service |
| 7 | webui 路径未安装（用 `webui install` 拉取）；service 的服务未安装 / 当前环境无此服务 | webui, service |
| 8 | webui 依赖缺失（用 `webui setup` 安装）；service 的服务依赖缺失 | webui, service |
| 9 | package apply 前置不兼容（dirty tree / env 不匹配且未 `--auto-yes`） | package |
| 10 | package manifest 无效（schema / sha256 / version 超支持范围） | package |
| 11 | package 源不可达（文件不存在 / URL 失败 / manifest URL 非 HTTPS） | package |

> webui 的退出码（6/7/8）由 `webui` 与 `service` 两个子命令共用（同值同义——service 是
> webui 语义的泛化命名，`service ... webui` 转发老实现，指同一服务时码必须一致）；
> package 的退出码（5/9/10/11）仅 `package` 子命令返回。
> ComfyUI 主服务（start/stop/status/info/logs/update/plugins）只用到 0–4。
> package 刻意避开 6/7/8，让外部监控脚本能按退出码区分子命令来源。

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
