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

- **原生 cm-cli 在 Windows 每次调用要 ~5.5 分钟，不要直接跑**：ComfyUI-Manager 的 `is_file_created_within_one_day` 用 `getctime`（Windows=创建时间，NTFS 隧道冻结）+ cm-cli 硬编码 `reload(dont_wait=False)`，导致每次调用同步全量拉取 CNR。启动器的插件操作（`services/plugin_service.py`）已两级分发绕过：ComfyUI 在跑 → Manager HTTP 队列 API（网页同路径）；否则 → `cm_fast` 包装器（`services/_runner_scripts/cm_fast.py`，monkey-patch `mtime` + `dont_wait=True`，运行时物化到 `launcher/plugins/cm_fast.py`），仅 install(CNR) 缓存缺失时 exit 3 → 原生 cm-cli 兜底建缓存。改插件操作逻辑请走 `PluginService` 公开方法，别自己拼 cm-cli 命令。
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

## 深入

- 完整 CLI 参考（每命令 flag / Exit codes / Output schema / systemd / NSSM / cron 示例）：[`cli.md`](cli.md)
- 服务接口契约：[`docs/ServiceInterfaces.md`](docs/ServiceInterfaces.md)
