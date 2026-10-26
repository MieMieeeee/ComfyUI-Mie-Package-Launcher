# AGENTS.md — 给 AI agent 的操作指南

> 本文件是 agent 操作本启动器的入口。完整 CLI 契约见 [`cli.md`](cli.md)。

## 这是什么

ComfyUI 启动器（PyQt5，Windows）。无参数启动 = GUI 图形界面；带子命令 = headless CLI，
复用 GUI 同一套启动/停止路径，适合自动化、监控、开机自启。

**支持多环境**：一个 ComfyUI 根目录 + python 路径的组合 = 一个「环境」，config 里可存多组。
同时只能运行一个环境，切换前必须先停止当前服务（CLI 会拒绝重复 start，GUI 会提示）。

## 怎么调用

**agent / 自动化推荐 `ComfyUI启动器-CLI.cmd`**：和下面 `ComfyUI启动器.exe` 行为完全等价（参数 + 退出码透传），但名字带 -CLI，对监控脚本 / NSSM / systemd / GitHub Actions 更友好。必须和 `ComfyUI启动器.exe` 同目录。

```bash
# 打包版（部署/运维场景，agent 通常用这个）—— exe 会自动切到自身所在目录找配置
ComfyUI启动器.exe <command> [--json] [-v]

# 开发版（从仓库根目录跑）
python __main__.py <command> [--json] [-v]
```

- **无子命令** → `ComfyUI启动器.exe`（裸跑）会启动 GUI；`ComfyUI启动器-CLI.cmd`（裸跑）会转发到 `help`，不弹窗口。
- **未知子命令或仅传 flags**（如 `frobnicate`、`--json` 单独）→ wrapper exit 1 + stderr 一行 `[ComfyUI启动器-CLI] ERROR: ...`，不弹 GUI。
- 所有子命令都支持 `--json`（输出**单行** JSON，便于解析）和 `-v`/`--verbose`（可叠加 `-vv`）。

## 子命令速查（agent 最常用）

| 目的 | 命令 | 判断方式 |
|---|---|---|
| 健康检查 | `status --json` | 退出码 `0`=在跑 / `3`=未跑 / `1`=异常；或解析 `.running` |
| 启动 | `start` | 阻塞到 `/system_stats` 就绪；加 `--no-wait` 立即返回 |
| 停止 | `stop` | 幂等，未跑也退 `0`；加 `--force` 直接 `taskkill /F` |
| 重启 | `restart` | stop 旧 + start 新 |
| 看配置 | `info --json` | `.comfyui_path` `.python_path` `.port` `.launcher_version` `.environments` `.active_env_id` |
| 看日志 | `logs comfyui -n 100 --no-follow` | `comfyui` / `launcher` / `webui` 三选一；**务必带 `--no-follow`** |
| 更新内核 | `update comfyui --dry-run` 然后 `update comfyui` | 先 dry-run 看会做什么 |
| webui 工作台（非核心，可选服务） | `webui status` / `webui start` / `webui info` | 与 ComfyUI 平级的服务；退出码多了 `6`(ComfyUI 未跑) / `7`(未安装) / `8`(依赖缺失)；详见 `webui --help` |
| 整合包更新（v1.1.0+） | `package show <path-or-url> --json` → `package apply <path-or-url> --auto-yes` | 加载 UP 主写的 manifest（本地文件/HTTPS URL），show 看 diff，apply 执行；退出码 `5`(部分失败) / `9`(前置不兼容) / `10`(manifest 无效) / `11`(源不可达)；model 项永远需用户手动下载 |
| 查帮助 | `help` / `help <command>` / `<command> --help` | — |

> **agent 默认不传 `--env`**。`start` / `restart` / `info` / `update` / `logs` 接受可选的 `--env ENV_ID` 覆盖本次调用的环境，仅供跨环境自动化脚本用；`status` / `stop` 不接受 `--env`（作用于「当前在跑的那个」）。切环境是 GUI 的事，agent 不要主动切。

典型自动化节奏：`status --json` 判断在不在跑 → 不在就 `start` → 失败就 `logs comfyui --no-follow` 排查。

## 机器契约（agent 解析依据）

- **`--json` 输出**：每个命令都是单行 JSON，字段 schema 见 `cli.md` 每个子命令的 *Output schema* 段。
- **退出码**（定义在 `core/cli/exitcodes.py`，跨命令稳定）：

  | 码 | 含义 | 出现在 |
  |---|---|---|
  | 0 | 成功 | 所有 |
  | 1 | 通用错误（路径缺失/env/IO/超时） | 所有 |
  | 2 | start 拒绝重复（已在跑） | start |
  | 3 | 未在跑 | status |
  | 4 | 已是最新 | update |
  | 5 | package apply 部分失败（≥1 项 failed） | package |
  | 6 | webui start 时 ComfyUI 未跑（用了 `--with-comfyui`） | webui |
  | 7 | webui 路径未安装（用 `webui install` 拉取） | webui |
  | 8 | webui 依赖缺失（用 `webui setup` 安装） | webui |
  | 9 | package apply 前置不兼容（dirty tree / env 不匹配且未 `--auto-yes`） | package |
  | 10 | package manifest 无效（schema / sha256 / version 超支持范围） | package |
  | 11 | package 源不可达（文件不存在 / URL 失败 / manifest URL 非 HTTPS） | package |

- 推荐用法：**按退出码分支 + 解析 `--json` 字段**，不要正则匹配人类文案。

## 关键路径

| 文件 | 含义 |
|---|---|
| `launcher/config.json` | 配置（端口、路径、环境列表、启动选项）—— **机器本地，含绝对路径，勿提交运行时改动** |
| `launcher/launcher.log` | 启动器自身日志 |
| `<comfyui_root>/user/comfyui.log` | ComfyUI 输出日志（`logs comfyui` 读这个） |
| `launcher/comfyui.pid` | 跨进程 PID 协调（JSON：pid/port/started_at/log_path/env_id），stale 当不存在 |

端口默认 `8188`，来自 `config.json` 的 `launch_options.default_port`。

### `config.json` 的多环境 schema

```json
{
  "environments": [
    {"id": "env_default", "name": "默认环境", "comfyui_root": "...", "python_path": "..."}
  ],
  "active_env_id": "env_default",
  "paths": {"comfyui_root": "...", "python_path": "..."}
}
```

- `environments[]`：环境数组，每项含 `id`（稳定标识，CLI `--env` 用）/ `name` / `comfyui_root`（ComfyUI 安装的**父目录**，launcher 拼 `root/ComfyUI/main.py`）/ `python_path`。
- `active_env_id`：当前激活环境 id。
- `paths`：**老 schema 的兼容回退**。`get_active_paths()` 优先读 `environments[active_env_id]`，为空才回退 `paths`。首次加载时老 `paths` 会自动迁移成 `environments[0]`（`config/migrations.py`）。

### 多环境代码入口（agent 改路径相关逻辑时看这些）

| 文件 | 含义 |
|---|---|
| `config/migrations.py` | 迁移 + 解析纯函数：`migrate_environments` / `resolve_active_paths` / `resolve_paths_for_env` / `find_env` / `update_active_env` |
| `core/launcher_cmd.py` | `build_launch_params(app, env_id=None)` —— 启动命令构建，用激活环境（或 `--env` 指定）的路径 |
| `utils/paths.py` | `comfy_root_from_config(config)` —— 内部已走 `resolve_active_paths`，传完整 config 即自动环境感知 |
| `headless_app.py` / `ui_qt/qt_app.py` | 两个 app 类各实现 `get_active_paths()`（无共同基类，鸭子类型） |

## 多环境机制（背景，agent 默认不切）

- **agent 默认不切换环境**。CLI 跑的就是 GUI 当前激活的环境（`config.json` 的 `active_env_id`）；切环境是 GUI 的事，agent 不要主动切，也不要为单次启动改 config / 加 `--env` 绕过 GUI 当前配置。
- **同时只能跑一个环境**。`start` 时若已有环境在跑（pidfile 有效），拒绝启动并返回当前在跑的 `running_env_id`；要先 `stop` 再启动。
- **`--env` 是一次性的，不持久化**：仅供跨环境自动化 / 一次性脚本用；不传则用 `active_env_id`，不写回 config。要永久切换激活环境，改 config（GUI 的环境下拉 / 设置页管理，或直接写 `active_env_id`）。
- **`--env <不存在的 id>` 报错**：返回 `error: "环境不存在: ..."`，退出码 1。先 `info --json` 拿 `.environments[].id` 确认可用 id。
- **`stop` / `status` 不接受 `--env`**：它们作用于当前在跑的那个环境，跟环境选择无关。
- **pidfile 记录 `env_id`**：`start` 写入时带上当前环境 id，`status` / `start` 的"已在跑"返回里含 `running_env_id`，便于 agent 判断冲突。
- **`launch_options` 是全局的**，不 per-env（端口/GPU/监听所有环境共享，因为同时只跑一个）。
- **有后台任务时禁止切换**：切换前会检查 `app.has_active_background_tasks()`（覆盖 BackgroundTaskRegistry 的活跃任务 + `_update_running` 核心更新标志）。有进行中任务时弹框阻止切换——因为 git/cm-cli 子进程不能安全强杀，中途换环境会操作错误仓库/目录甚至写坏文件。ComfyUI 服务进程则可以停（用户确认后自动 stop 再切）。
- **version worker 竞态防护**：`refresh_after_env_switch` 会自增 `_env_token`，正在跑的旧 worker 回调时发现 token 变了就丢弃结果，避免旧环境的版本号迟到覆盖新环境。

## 坑（agent 易踩）

- **原生 cm-cli 在 Windows 每次调用要 ~5.5 分钟，不要直接跑**：ComfyUI-Manager 的 `is_file_created_within_one_day` 用 `getctime`（Windows=创建时间，NTFS 隧道冻结）+ cm-cli 硬编码 `reload(dont_wait=False)`，导致每次调用同步全量拉取 CNR。启动器的插件操作（`services/plugin_service.py`）分发规则（B5 起）：**uninstall/disable/enable = Manager HTTP 队列 API → 启动器磁盘直连（`_disk_lifecycle`：rmtree / rename 加 `.disabled` 后缀 / 从 `.disabled/` 子目录移回，不走 cm-cli）**——Manager 的 `unified_uninstall`/`unified_disable` 语义本就只是删/移目录（无 pip 卸载），cm-cli 毫无增量还删不动只读 git pack（WinError 5 → 标「重启后删除」）；磁盘执行顺带 chmod 处理只读文件，且操作后 `_lifecycle_effect_ok` 核实终态防 API 假成功（服务端 skip 报 ok 但目录没动）。install/update = **直接 `cm_fast` 包装器，不走 Manager 队列 API**（2026-10 策略调整：队列任务完成后 Manager 网页端会弹「Apply/重启」，用户点击产生 os.execv 换 PID 的重启——启动器 pidfile 跟踪不到；且更新写入的插件依赖被「预约」进启动脚本列表，下次启动 prestartup 消费后触发「Restarting to reapply dependency installation」二次 execv 链，Windows 下不可靠，曾把运行中的 ComfyUI 静默搞死，2026-10-03 事故），仅 install(CNR) 缓存缺失时 exit 3 → 原生 cm-cli 兜底建缓存。**进程收养**：CLI `status`/`start` 在 pidfile 失联但端口被 ComfyUI 进程占用时，用 `find_pids_by_port_safe` + `is_comfyui_pid`（与 GUI 一键启动端口兜底同链）重写 pidfile（`runner.adopt_external_service`），外部重启后 stop/status 不失联。**cm_fast 源缺失退原生会打 `cm_fast: 包装器源缺失` warning**（曾静默退化致用户卸载等 5.5 分钟，2026-08-27 日志事故）。改插件操作逻辑请走 `PluginService` 公开方法，别自己拼 cm-cli 命令。
- **`logs -f` 会永久阻塞**，自动化/脚本里禁用，要 `--no-follow`。
- **无子命令 = GUI**：如果 agent 想跑 CLI 却只执行了 `ComfyUI启动器.exe`（不带子命令），会弹 GUI 而非执行命令。
- `--start` / `--stop` / `--status` 这类**老 flag 已废弃**（旧文档可能还写），现在是子命令：`start` / `stop` / `status`。
- 配置改动会落到 `launcher/config.json`，里面是本机绝对路径——**不要把运行时生成的 config 改动提交进 git**。
- 调试模式：在 `launcher/` 目录下建一个 `is_debug` 文件（内容随意），日志变详细。
- **多环境：不要直接读写 `config["paths"]`**。老 `paths` 段是兼容回退，生产代码应走 `app.get_active_paths()`（GUI/CLI app 对象）或 `resolve_active_paths(config)`（纯 config）。详见上方「多环境代码入口」表。
- **`comfyui_path` 是死字段**：老 config 里的 `paths.comfyui_path` 几乎无人读（实际驱动逻辑的是 `comfyui_root`），多环境迁移时已丢弃，别搬进 environment 对象。
- **agent 不要为单次启动改 `config.json` / 加 `--env` 绕过 GUI**。CLI 就是 GUI 当前配置的 headless 别名——端口、env、paths 全以 GUI 为准。看到端口冲突 / env 不对，应该让用户去 GUI 调整，而不是 agent 自己改配置 / 加 override。
- **`start` / `stop` 只动 pidfile 里那个 PID**：看不到的另一份 launcher 实例（多环境 GUI 各自）可能随时被它自己的 GUI 关掉。如果看到 8188 突然空了，多半是用户手动操作，**别当成 launcher 的副作用去调查**。
- **发布到 GitHub 后 zip 名中 `启动器` 会变成 `_`**：本地 release/里的 zip 叫 `ComfyUI启动器_v<ver>_<ts>.zip`，上传后在 GitHub release 资产里变成 `ComfyUI._v<ver>_<ts>.zip`。这是 `gh release upload` 的 bug（中文字符被替换为 `_`），v1.0.13 也是这样。**zip 内容正确**（解压后子目录名是 `ComfyUI启动器_v<ver>_<ts>/`，里面文件全对），不影响用户下载体验。看到资产名字对不上别质疑 gh 配置问题，是已知 bug，详见 `release.py` 里的注释。如果一天 gh 修了，不要忘了同步 release note 里的下载名描述。
- **窗口默认高度 1350×900 → 1350×960**：环境区多一行设置（本地代理）后行距约 46px，900 会把「快捷目录」那排按钮切掉半截。改的**四处**：模块级常量 `config/migrations.py::DEFAULT_BASE_H`、`qt_app.py:2752` 的 fallback、`system_settings_page.py` 两处硬编码（650/923，「恢复默认」按钮用的是自己那份，**不是** import 常量 —— 只改 migrations 会漏）。存量安装靠 `migrations._bump_legacy_default_height()` 一次性抬：**只有 `window_w/window_h` 恰好等于旧默认 (1350,900) 才动**，用户自己调过的一律不动；幂等（第二次调用返回 `changed=False`）。pin 住旧值 900 的测试要一起改（`test_window_geometry_memory.py` / `test_system_settings_split_ui_and_size.py`）。
- **本地代理（Clash）与镜像源是两回事，别混**：`proxy_settings` 里 `git_proxy_*` / `pypi_proxy_*` / `hf_mirror_*` 是**镜像**（换落地地址），`local_proxy_enabled` + `local_proxy_url` 是**本地正向代理**（换传输路径，issue #109）。两者正交：开了本地代理，hf 镜像 / gh-proxy / 阿里云 pypi 照样生效，只是流量改经代理转发。实现在 `utils/net.py::apply_local_proxy_env()` / `clear_local_proxy_env()`，注入点在 `__main__.main()`（GUI/CLI/dev/打包四条路的唯一公共入口，早于任何出网动作）。**为什么敢直接改 `os.environ`**：`core/launcher_cmd.py:117` 构造 ComfyUI env 是 `os.environ.copy()`，而全项目只有 `ui_qt/pages/launch/environment_manager_section.py` 一处从零构造 env（且与出网无关），所以改一次就覆盖启动器自身 + ComfyUI + git + pip + HF 下载。**必须同时强制写 `NO_PROXY=no_proxy=127.0.0.1,localhost,::1`**（追加不覆盖）：启动器的 Manager API（`plugin_service._http_json` → `127.0.0.1:8188/manager/*`，插件装卸启停全走这条）和健康探测都是裸 `urlopen`，实测没有 NO_PROXY 会被绕进代理直接 WinError 10061 打死。**只接受 http(s)**，socks5 会被拒（urllib 不支持 socks，填了启动器自身 GitHub API/公告静默失联）。改代理地址后正在跑的子进程不继承，需重启；**关掉开关要调 `clear_local_proxy_env()` 真的撤变量**（它只删指向本配置地址的，用户自己 export 过的 HTTP_PROXY 不动；NO_PROXY 保留 —— 没有代理变量时它是惰性的）。**启用「本地代理」必须先走确认弹窗**（`_on_local_proxy_checkbox_toggled`）：先 `check_local_proxy_reachable()` 探端口，再弹 `DialogHelper.show_confirmation` 列出前置条件（代理软件已启动 / 填 HTTP 端口非 SOCKS 7891 / 127.0.0.1 始终绕过 / 中途关掉会断网）与影响面（哪些出网改道、镜像不受影响、不改系统代理、ComfyUI 需重启）；用户点「取消」要把勾选框弹回去且不写 config（`_revert_local_proxy_check` 用 `_lp_guard` 防 stateChanged 递归）。理由：这是全局开关，配错不是坏一处而是到处连不上；端口探测失败只**警告**不硬拦（用户可能想先开好配置再启动代理）。
- **内核更新的 git 必须自己带代理参数**：2026-10-14 事故（docs/core_update_git_proxy.md）——配了 gh-proxy 的用户「更新内核」必然失败，报 `fatal: unable to access 'https://github.com/Comfy-Org/ComfyUI/': Recv failure: Connection was reset`，每次 5~8 秒挂、重试无用。根因：内核的 `fetch`/`pull` 走 `version_service._run_git` / `_run_git_cancellable`，**以前从不读 `config.proxy_settings`**，直连 origin；`GIT_CONFIG_GLOBAL` 那套代理只透给 cm-cli（插件侧，`plugin_service._git_env`），webui 则是改传给 git 的 URL（`core/webui_installer.py`）。现在统一由 `utils/net.py::git_insteadof_args()` 生成 `-c url.<前缀>.insteadOf=`，在 `VersionService._apply_git_path_and_proxy()` 里插到 git 可执行文件之后、子命令之前。**三条硬约束**：(1) `-c` 的值必须是**单独一个 argv 元素、不带引号**——写成 `'url."<前缀>".insteadOf=...'` 会让 git 把引号当字面量，拼出 `"https://gh-proxy.com/https://github.com/"Comfy-Org/ComfyUI.git` 这种坏地址，不报错只是换个方式失败（git 2.55 实测）；(2) 子命令按 `cmd[1:]` 的 token 判（`fetch`/`pull`/`ls-remote`/`clone`），**不能靠 `cmd[0] == "git"`**——`ui_qt/pages/version_page.py` 传的是 `app.git_path` 全路径；(3) `_run_git_cancellable` 自己 `Popen` 且不传 `env`，`-c` 只能进 argv。两个入口都**必须先复制 cmd 再改**（现有 `_run_git` 会原地改 `cmd[0]`，不复制会污染 version_page 持有的 list 并二次叠加 `-c`）。origin 已经是代理地址时 git 前缀匹配不会套第二层，靠的是匹配行为、不是 `apply_git_proxy_to_url` 的幂等。别把代理改回 `GIT_CONFIG_GLOBAL`：那会让用户 `~/.gitconfig` 整个失效（`http.proxy` / `credential.helper`）。
- **更新超时必须调 `request_cancel()`，不是 `future.cancel()`**：`ui_qt/qt_app.py::start_update` 的外层 `future.result(timeout=update_timeout)` 到期后，`future.cancel()` 对**已经在跑**的任务无效，worker 会继续跑完内层 git（30+60+120s），`with ThreadPoolExecutor` 退出时 `shutdown(wait=True)` 让该线程一直阻塞，最终成功的结果也拿不到（`core_res` 早被写成「更新超时」）。正确做法是调 `services.version.request_cancel()` 杀掉 `_run_git_cancellable` 记下的那个 Popen。**注意覆盖范围**：它只杀 `_run_git_cancellable` 记下的进程，`stable_only=True` 路径里的 `git fetch --tags` 走 `subprocess.run`，杀不到。单纯把超时秒数放大盖不住这条。
- **渲染守卫 / render_mode 三态**：`core/render_guard.py` 管理 `auto → compat → safe` 两级阶梯升级（只升不降，两级封顶 safe）。三态语义：`auto` = 原生 Qt OpenGL + 全部阴影/圆角特效；`compat` = `QT_OPENGL=software`（软件渲染，视觉几乎无感，但跳过 GPU 驱动路径）；`safe` = software + 禁用全部 8 处 QGraphicsDropShadowEffect + `FramelessDraggableDialog` 回退到系统原生标题栏（`FramelessWindowHint` / `WA_TranslucentBackground` 都不设）。查询接口全部是纯读 `os.environ`：`is_safe_ui()` / `current_mode()` / `escalated_this_run()` / `escalated_detail() -> (from_mode,to_mode)|None`，不依赖初始化时序。
- **升级机制 + clean 哨兵 (v9 分类器驱动)**：启动入口 `comfyui_launcher_pyqt.py::launch_gui()` 顺序：`install_crash_reporting()` 最前 → `lock.acquire()` → 失败分支仅 `render_guard.prepare()`（只写 env，不碰 state/upgrade，避免单实例竞态）→ 成功分支调 `render_guard.begin()`。`begin()` 三步: (1) **state 门** 读 `launcher/render_state.json`: `state=="clean"` 或不存在 → 跳过分类器（v1 §1.3: 正常关闭的会话段内若含良性 faulthandler 误报不应误升级）; `state=="running"`（taskkill /F / 断电 / 原生崩溃）→ 进分类器。 (2) **分类器** 读 `launcher/crash.log` 段（v3 块排除算法: `[uncaught_exception]` marker 起，到下一个 marker / `[startup]` / `=` 分隔行止整块跳过，块外任何非空非 marker 行 = native crash 证据; 段取「倒数第二 `[startup]` 到最后 `[startup]`」）三态: `graphics_crash` → 升一级; `python_exception` / `clean_or_user` / `unknown` → 不升级（与渲染模式无关或非崩溃）。升级时 atomic 写 config 的 `ui_settings.render_mode`（裸 JSON 校验 verify 后才置 `_escalated=True` + 写 `[render_guard] escalated (mode=...)` audit 行，verify 失败/异常路径保留升级信号）。`PyQtLauncher()` 构造后调 `mark_running()`: `state="starting" → "running"`, 保字段, clean 哨兵不动（保留诊断信息）。正常 `window.run()` 返回后（**放 try 内而非 finally，避免 PyQtLauncher 构造异常时误清升级信号**）调 `render_guard.finish()` 三段: (a) counter 段: 读 `launcher/render_clean_counter.json`（side 文件, 与 state 分离）, `count` 无条件 +1 中间落盘; (b) promotion 段: `count >= 5` 时写 config=auto + 裸 JSON verify, verified 才清零, 去门（已是 auto 也走 no-op promote + 清零）, 失败路径保留 counter 写 audit; (c) 清理段: `os.remove` state.json, PermissionError/OSError 降级 atomic 回写 `{state:"clean", mode/started_at/version 实值, cleaned_at, note}` 哨兵, 不带 pid。外层 `try/except Exception: pass` 包整个 finish, 任何错误不让启动器失败（与 begin 同构「永不抛」教义）。所有 audit 行（`escalated` / `last_exit=<cls>` / `auto_promoted` / `auto_promote_failed_verify` / `auto_promote_failed_exception` 等）必须以 `[render_guard] ` 前缀走 `append_crash_audit()` 包装器（`core/render_guard.py`），字面量永不含前缀，包装器是前缀唯一来源 → tray-resident / taskkill 场景下分类器不被误触的唯一保护。

- **v1 §3.3 C 项 descope（v10 F11）**：升 safe 时用 `CustomConfirmDialog` 让用户「保留安全模式/改回自动」的二次确认弹窗**本轮未落地**——弹窗仍走 `DialogHelper.show_info` 单按钮提示。如果后续用户反馈希望增加二次确认（改回自动会写 config=auto + 清 counter、不删 state），可按 `CustomConfirmDialog` + `get_result()` 模式补齐。详见 `notes/t24_render_guard_fix_plan_v9.md` §9 边界 + `ui_qt/widgets/custom_confirm_dialog.py`。
- **崩溃留痕 crash.log**：`utils/logging.install_crash_reporting(log_root=None)` 最早在 launch_gui 调。写 `launcher/crash.log` >512KB 清空重开，append 模式，`faulthandler.enable(fh, all_threads=True)` + 早期 `sys.excepthook` 写栈。首行含 `[startup] ts=... launcher_version=...`，版本号来自 `core/version.py` 的 `LAUNCHER_VERSION`（唯一事实源，编译期随代码打进 exe；`build_parameters.json` 只留编译脚本自动插入的元数据，**不带 version**——改版本号只改 `core/version.py` 或跑 `python build.py --version vX.Y.Z`）。`render_guard.begin()` 确定最终模式后追加 `[render_guard] mode=... escalated=...` 到 crash.log（解决启动头写模式时序问题）。看到闪退用户的反馈要**附 `launcher/crash.log`**，如果没有 Python 栈就是纯原生驱动崩溃，结合 render_mode 行一起排查。复位 render_mode 不要手动删 state：去 GUI「系统设置 → 界面渲染模式」下拉改回「自动」并重启；或直接删 launcher/render_state.json + 把 config 里 `ui_settings.render_mode` 改回 `auto`。
- **DLL 分发：opengl32sw.dll 在 exe 旁**：`build.py step_nuitka_compile` + `step_finalize_release` 会从 wheel 的 `PyQt5/Qt5/bin` 拷 `opengl32sw.dll` 到 exe 同级（dist flat 布局 + release boxed 子目录）。Windows DLL 搜索 exe 目录优先，无需 Enigma 虚拟化，零改动 EVB。`prepare()/begin()` 会先 `_locate_opengl32sw()`，命中才设 `QT_OPENGL=software`，否则跳过（避免 DLL 缺失的警告框）。`is_debug` 文件（`launcher/is_debug` 存在）会触发 prepare 阶段把 DLL 搜索路径打印到日志。
- **应用内「检查更新」通道（Gitee）暂不可用，别再试图修它**：启动器的自更新读的是 `https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/updates/index.json`（测试频道是 `.../updates/test/index.json`），而 **Gitee 单文件上限 50MB，装不下 120MB 的 exe** —— 除非把 exe 换成一个小的下载器/差分补丁，否则这条通道没有意义。现状：`F:\comfyui-mie-resources` 里只有 2026-04 的 test 通道（v1.0.10），stable 的 `launcher/updates/index.json` 根本不存在 → 线上用户点「检查更新」拿不到版本信息，不会提示更新。**发版走 GitHub Releases**（`release.py`），用户手动下载。`upgrade_exe.py`（传 exe + 改索引 + push Gitee）在 exe 体积降到 50MB 以下之前不要用。
- **ComfyUI 资源系统（Assets）默认要显式关掉**：ComfyUI 0.40 起内置「资源系统」——本地 SQLite 索引（`<user>/comfyui.db`）+ 扫描 `models` / `input` / `output`，前端多一个 Assets 侧边栏面板。ComfyUI 核心默认是**关**的（要 `--enable-assets`），但 `comfy/cli_args.py` 里 `if args.windows_standalone_build: args.enable_assets = True` —— 而启动器给 ComfyUI 的命令行**一直带着 `--windows-standalone-build`**（为了便携版的自动开页面等行为），等于给所有用户默认开了这个 beta 功能。实测代价：NAS / 网络盘模型库首次扫描要几分钟、硬盘狂响；同一安装目录起第二个 ComfyUI 实例会因共用数据库直接退出（`ASSETS_STARTUP_FAILED: in_use`，ComfyUI issue #17103）。所以启动选项里有「启用资源系统」复选框，**默认不勾 = 传 `--disable-assets`**（必须显式关：光「不加参数」没用，`--windows-standalone-build` 已经开着）。实现见 `core/launcher_cmd.py::_assets_flag_for`：**用户自己在「额外启动参数」里写了 `--enable-assets`/`--disable-assets` 就听用户的**（`--disable-assets` 优先级最高，我们再补会盖掉他）；**装的 ComfyUI 不认识这两个参数就不传**（老版本硬塞会让 argparse 报 unrecognized arguments 直接启动失败，靠读 `ComfyUI/comfy/cli_args.py` 里有这两个串来判断）。模型目录没有新要求，`extra_model_paths.yaml` 继续生效。
- **Safe-UI 查询全部纯 env**：8 处阴影消费点（`qt_app.py` ×2、`sidebar.py`、`version_section.py`、`environment_section.py`、`launch_controls_section.py`、`widgets/cards.py`、`widgets/buttons.py`）均在 effect 创建前 `if render_guard.is_safe_ui(): return/raise`，纯读 `os.environ["LAUNCHER_SAFE_UI"]`，无任何依赖初始化时机，随便 import 顺序都正确。不要在 safe 分支下实例化 `QGraphicsDropShadowEffect` / `QGraphicsBlurEffect`，哪怕立即 setGraphicsEffect(None) 都会触发 native paint 路径导致闪退。

## GUI 主题规范（改 ui_qt 页面/弹窗必读）

所有页面/弹窗的配色**必须**走 `theme_manager`，**禁止**硬编码 `#rrggbb`（`webui_page.py` 曾是异类，已整改）。

### 颜色从哪来

| 来源 | 用法 | 文件 |
|---|---|---|
| `theme_manager.colors.get("<token>", default)` | 取单个色 token（标签/背景/输入框等） | `ui_qt/theme_styles.py`（`ThemeColors`，token dict 在此） |
| `theme_manager.styles.<builder>()` | 取整段 QSS（按钮/输入/表格等） | `ui_qt/theme_styles.py`（`ThemeStyles`） |

**关键 token**：`label` / `label_muted` / `label_dim`（文字）/ `content_bg` / `group_bg`（背景）/ `input_bg` / `input_border` / `input_readonly_bg` / `input_readonly_text`（输入框/日志区）/ `accent` / `error` / `warning`（语义色）。每个 token 都有深/浅两版，切换主题时自动取对的版本。

**按钮 builder 一览**（优先用 builder，别自己拼）：
- `primary_button_style()` —— 品牌紫渐变（`#7F56D9`→`#9E77ED`），一级动作（启动/停止/确定）。
- `secondary_button_style()` —— 中性/半透明面，次级动作（打开网页/配置/刷新）。
- `destructive_button_style()` / `destructive_outline_button_style()` —— 红色，高风险（卸载/退出）。
- `link_button_style()` —— 链接样式。

### 每个页面必须实现 `update_theme`

页面继承 `BasePage`（自动注册主题监听）。`BasePage` 的 `update_theme` 只重应用基础 content 样式；**页内额外 `setStyleSheet` 过的控件必须在子类 `update_theme` 里重应用**，否则切深/浅主题时那些控件颜色会冻结。

```python
def _on_theme_changed(self, theme_styles):
    self.update_theme(theme_styles)

def update_theme(self, theme_styles=None):
    super().update_theme(theme_styles)
    styles = theme_styles or self.theme_manager.styles
    self._btn_xxx.setStyleSheet(styles.primary_button_style())
    self._label_yyy.setStyleSheet(f"color: {self.theme_manager.colors.get('label_muted')};")
```

参考实现：`ui_qt/pages/launch_page.py`、`models_page.py`、（整改后的）`webui_page.py`。

### 弹窗走共享设施，禁原生 QMessageBox

| 需求 | 用法 |
|---|---|
| 单按钮提示（信息/警告/错误） | `DialogHelper.show_info(parent, 标题, 内容)` / `show_warning` / `show_error` |
| 是/否确认 | `DialogHelper.show_confirmation(parent, 标题, 内容)` |
| 多按钮 / 自定义 / 带输入框 / 表单 | `CustomConfirmDialog`（继承 `FramelessDraggableDialog`，传 `theme_manager=`），多按钮靠 `get_result()` 拿索引 |

带表单的自定义对话框继承 `FramelessDraggableDialog`，构造接 `theme_manager`，用「默认色兜底 + `theme_manager.colors` 覆盖」模式取色（参考 `ui_qt/widgets/update_dialog.py`、`custom_confirm_dialog.py`）。**不要** `QtWidgets.QMessageBox.xxx(...)`。

### 字体大小

走 `ThemeStyles` 内部的 `_pt()`/`_px()`（跟随全局 UI 缩放）。用 builder 时已自动带上；自己拼 QSS 里若需固定字号，小号（提示/详情）用 `9pt`、正文 `10pt`、标题 `bold 14pt`，**别**用影响布局的大号裸 pt。

## 跑测试（别再用旧的慢姿势）

```bash
# 全量（约 2 分钟，2500+ 用例）
python -m pytest tests/ -q --basetemp=./.pytest_tmp_run

# 日常快速回归（跳过靠真实 sleep / 子进程的慢用例，约 1 分钟）
python -m pytest tests/unit -q -m "not slow" --basetemp=./.pytest_tmp_run

# 单文件
python -m pytest tests/unit/test_xxx.py -q --basetemp=./.pytest_tmp_run
```

- **必须带一个全新的 `--basetemp`**：仓库里残留的 `tests/.pytest_tmp` 目录权限已坏
  （`Permission denied`），复用它会批量 ERROR。
- **标记**：`slow` = 靠真实 sleep/超时等时序的用例（`test_pip_heartbeat` 28s、
  `test_local_proxy` 25s），`e2e` = 会真的拉子进程/打包产物（合计 16s）。
  两个标记都在 `pyproject.toml` 里注册了，`-m "not slow"` / `-m "not e2e"` 可跳过。
- **别在用例里真的等**：worker 轮询 120 秒这种（`core/runner_start.py` 的
  `worker()` 会 `time.sleep(3)` + 最多 120 秒轮询 `/system_stats`）必须把
  `time.sleep` 和就绪探测打桩，否则一个文件就是 20 多分钟。
- **别从非 threading 模块创建的线程里 `join()`**：`Thread.join()` 内部会调
  `threading.current_thread()`，在 Qt 线程池这类线程里调用会让 CPython 永久
  注册一个 `_DummyThread`，之后 `threading.enumerate()` + `join()` 的代码会撞上
  `cannot join a dummy thread`（`test_start_update_threads` 的 11 个用例会因此全挂）。
  要等线程就用 `utils/thread_util.py::wait_thread()`（轮询 `is_alive()`）。
- **本机 `import ui_qt.qt_app` 会段错误**：PyQt5 5.15.7 + PyQt5-sip 12.17 的
  ABI 不兼容，`PyQtLauncher` 类定义那一步直接 access violation（连带整个 pytest
  进程一起死）。`tests/unit/test_close_to_tray.py` 和
  `tests/integration/test_qt_app_extraction.py` 都会先用子进程探针探测，探不通就 skip。
  想在本机真正跑 GUI，先把 sip 降到兼容版本（`pip install "PyQt5-sip==12.13.0"`）。

## 深入

- 完整 CLI 参考（每命令 flag / Exit codes / Output schema / systemd / NSSM / cron 示例）：[`cli.md`](cli.md)
- 服务接口契约：[`docs/ServiceInterfaces.md`](docs/ServiceInterfaces.md)
