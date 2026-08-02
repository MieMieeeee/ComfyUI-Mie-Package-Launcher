# ComfyUI 启动器

> 版本：v1.0.15

PyQt5 GUI + 无窗口 CLI。GUI 管 ComfyUI 启停 / 多环境切换 / 镜像代理等配置；CLI 复用同一套路径，适合服务器 / 自动化 / 开机自启。

## 给 Agent 用

CLI 是 agent 能看见的唯一入口；以 CLI 为准。

```bash
python __main__.py status --json  # 健康检查（退出码 0=在跑 / 3=未跑 / 1=异常）
python __main__.py start          # 启动（阻塞到 /system_stats 就绪）
python __main__.py stop           # 停止
python __main__.py update comfyui # 内核 + 前端 + 模板库 + 依赖
```

原则：默认跑 GUI 当前激活的环境和端口，不自行加 `--env` 或改 `config.json` 绕过 GUI。完整操作指南见 [AGENTS.md](AGENTS.md)；CLI 契约见 [cli.md](cli.md)。

## 给 CLI 用

```bash
python __main__.py start                  # 启动（阻塞到 /system_stats 就绪）
python __main__.py stop                   # 幂等，未跑也返回 0；--force 直接 taskkill /F
python __main__.py status                 # 退出码 0=在跑 / 3=未跑 / 1=异常
python __main__.py info --json            # 当前生效配置
python __main__.py logs comfyui -n 100 --no-follow  # tail 日志（务必 --no-follow）
python __main__.py update comfyui         # 内核 + 前端 + 模板库 + 依赖同步
python __main__.py help [command]         # 完整帮助
```

所有子命令支持 `--json`（单行 JSON）与稳定退出码契约（0/1/2/3/4），适合 systemd / NSSM / cron / GitHub Actions。完整 flag / Exit codes / Output schema 见 [cli.md](cli.md)。

## 常见问题

- [启动后无法运行工作流，`dev_utils_execute() takes 10 positional arguments but 11 were given`](#faq-1)
- [端口 8188 被占用 / 想换端口](#faq-2)
- [想换 HuggingFace / PyPI / GitHub 镜像源](#faq-3)
- [多套 ComfyUI 环境怎么切换](#faq-4)
- [CLI `update comfyui` 不工作](#faq-5)
- [日志视图看不到 tqdm 进度条刷新](#faq-6)
- [启动器版本落后了，怎么更新](#faq-7)
- [怎么改源码 / 编译新的 exe](#faq-8)
- [模型库放在外置硬盘上怎么接进来](#faq-9)

[完整 FAQ 文档](https://dcn8q5lcfe3s.feishu.cn/wiki/ELY2wwPgciIA56kS3eBciY4RnPd)

## 功能特性

### 核心功能
- **多模式启动**: 支持多种启动配置（CPU、GPU、镜像源等）
- **版本信息**: 显示 ComfyUI、前端、模板库、Python、Torch 版本
- **批量更新**: 一键选择并更新内核/前端/模板库
- **配置管理**: 保存和管理启动参数配置
- **路径配置**: 支持自定义 ComfyUI 根目录与 Python 解释器路径
- **CLI 模式**: 无 GUI 后台启动/停止/状态查询，适合服务器与自动化场景

### 版本与更新
- 获取并展示版本信息
- 选择更新项目并执行批量更新
- 支持快速刷新状态
- 升级策略：可选择仅更新到稳定版（依据 GitHub Releases 标签）
- 依赖一致性：可选"模板库与前端版本遵循内核需求"，按 ComfyUI `requirements*.txt` 指定版本进行更新
- GitHub 代理：在内核版本管理中支持 gh-proxy 或自定义代理地址以加速拉取与标签刷新
- **启动器自身更新**（v1.0.8）：检测启动器新版本并引导升级

### 公告系统（v1.0.4）
- 启动时支持远程公告弹窗（JSON/纯文本），默认从内置地址拉取，配置缺失也可用。
- 支持 `index.json` 清单聚合：同时展示多条公告，统一弹窗滚动显示，条目间使用分割线。
- 版本匹配支持数学表达式：`version` 字段可用 `> >= < <= == *`，支持多条件 AND，例如 `">=v1.0.3 <1.2.0"`。
- 两个操作按钮：`知道了`（标记当前公告已读）、`不再弹出`（屏蔽当前公告），持久化到 `launcher/announcement_seen.json` 与 `launcher/announcement_muted.json`。
- 弹窗居中显示、支持长内容滚动；"关于启动器"页新增"查看公告"入口，读取 `launcher/announcement_cache.txt`。
- URL-only 条目支持：清单项仅提供 `url` 即可拉取并展示内容。

### 路径配置（v1.0.5）
- **自定义路径**: 在主界面直接查看和修改 ComfyUI 根目录及 Python 解释器路径。
- **灵活切换**: 支持为 ComfyUI 指定独立的 Python 环境，方便切换不同版本的 Python 或虚拟环境。
- **自动适配**: 修改路径后，启动器会自动刷新版本信息并使用新环境启动 ComfyUI，无需重启启动器。

### CLI 模式（v1.0.8+）
无参数启动即 GUI；带子命令进 headless CLI（复用 GUI 同一套启停路径），适合服务器 / 自动化 / 开机自启。

**CLI = GUI 当前配置的 headless 别名**：默认跑 GUI 当前激活的环境、当前端口、当前路径，不需要也不应自行加 override（`--env` 仅供跨环境自动化脚本用，agent 默认不传）。

| 子命令 | 说明 |
|---|---|
| `start` / `stop` / `restart` | 启动 / 停止 / 重启 ComfyUI |
| `status` | 查询运行状态（退出码区分在跑 / 未跑 / 异常） |
| `info` | 打印当前生效配置 |
| `logs launcher\|comfyui` | tail 日志 |
| `update comfyui` | 更新内核 |
| `help [command]` | 打印帮助 |

所有子命令支持 `--json`（单行 JSON 输出）与稳定的退出码契约。
- agent 操作指南：[AGENTS.md](AGENTS.md)
- 完整 CLI 参考：[cli.md](cli.md)

### v1.0.15 近期更新

- **LogTailer 重构为 VirtualTerminal (VT100)**：与 ComfyUI 前端 xterm.js 行为一致（\r 覆盖当前行、\n 才 finalize）；移除 ProgressCollapseFilter 与"折叠连续进度"checkbox；新增 20 个单测覆盖 VT100 语义（\r\n / tqdm 多帧覆盖 / reset）。
- **退出时日志句柄显式释放**：aboutToQuit 阶段新增 `_shutdown_log_handles`，主动停 LogViewerPage tailer、调 `logging.shutdown()`、显式 close launcher logger 上的 handler；解决 daemon LogTailer 线程被强杀泄漏 ComfyUI 日志 fd 的问题。
- **ComfyUI 子进程强制 UTF-8 模式**：启动时注入 `PYTHONUTF8=1 + -X utf8`，避免中文路径/文件名在 ComfyUI 子进程里乱码。
- **WebUI 工作台（可选服务）**：与 ComfyUI 平级的镜像克隆/启动/依赖安装服务；support gitee / github / custom 镜像切换；退出 launcher 时自动关闭孤儿 WebUI 子进程。
- **多环境支持**：config.json 可存多组 `environments[]`，GUI 下拉切换；CLI 默认跑 GUI 当前激活环境，`--env` 是一次性 override（agent 默认不传）。同时只能跑一个环境，切换前必须先停掉当前服务。

### v1.0.14 近期更新

- **实时日志流**：`PYTHONUNBUFFERED=1` + 后台线程 pump 让 tqdm 进度条实时刷新；日志视图原地渲染 `\r` 回车覆盖行；配套 powershell tail 窗口独立显示。
- **构建时间真实显示**：`info --json` 新增 `build_time` 字段；"关于启动器" 页版本号格式化为 `v1.0.14 (构建于 2026-07-25 17:10:12)`（dev 环境 fallback 到 `sys.executable` mtime，模块见 `core/build_meta.py`）。
- **Headless update 修复**：CLI `update comfyui` 原先在 `services.update_service.perform_batch_update()` 第一行 `update_core_var.get()` AttributeError 崩溃；现补齐 `HeadlessAppContext` 7 个缺失属性 + `services.version` 换真实 `VersionService`，能跑完整 git pull + 前端 + 模板库 + 依赖同步（E2E 验证过）。
- **Release 子目录自动带 3 份 launcher 文档**：`使用说明.md` / `AGENTS.md` / `cli.md` 跟 exe 一起进发布包，用户拿到 release 即可读 CLI / agent 操作说明，无需回仓库。

## 使用说明

### 启动启动器
```bash
# GUI 模式
python comfyui_launcher_pyqt.py

# 或通过 __main__.py（无参 = GUI；带子命令 = CLI）
python __main__.py              # 启动 GUI
python __main__.py status       # 查询运行状态
python __main__.py start        # 启动 ComfyUI（阻塞到就绪）
python __main__.py stop         # 停止 ComfyUI
python __main__.py status --json # JSON 输出，便于脚本解析

# 或直接运行已打包的可执行文件（若已构建）
# 双击 ComfyUI启动器.exe          # 无参 = GUI
# ComfyUI启动器.exe status --json # CLI 子命令
```

### 使用流程
- 启动后，启动器会自动读取 `launcher/config.json`：
  - `paths.comfyui_root`：作为 ComfyUI 根目录；若未配置或无效，会弹窗提示选择 ComfyUI 根目录（包含 `main.py` 或 `.git`）。选择后会保存到配置文件。
  - `paths.python_path`：作为 Python 可执行路径；若未配置或无效，会按常见候选自动解析（如 `python_embeded/python.exe`）。
- **路径配置**：在"启动控制"下方，可点击"重设"按钮来更改 ComfyUI 根目录或 Python 路径。更改后立即生效。
- 在"启动与更新"页配置启动选项（CPU/GPU、端口、CORS、镜像与代理等）。
- 点击"一键启动"，启动器会按配置构造命令并启动 ComfyUI。
- 启动后约 1 秒，若存在可用公告将弹出聚合滚动弹窗。
- 若设置了镜像或代理，会注入相关环境变量（如 `HF_ENDPOINT`、`GITHUB_ENDPOINT`）。
- 检测到便携版 Git（优先在当前目录或打包目录的 `tools/PortableGit/bin/git.exe`）时，会在启动时注入 `GIT_PYTHON_GIT_EXECUTABLE` 并前置其 `bin` 到 `PATH`，无需手动设置系统环境；若未检测到，则回退到系统 Git。
- 若目标端口已被占用，启动器会提示是否直接打开网页而不启动新的实例；默认取消启动。
- 点击"停止"，会直接终止占用当前设置端口（默认 `8188`）的所有相关进程。
- 关闭窗口时，自动执行与"停止"一致的逻辑后退出。

### 快速操作
- 一键启动 ComfyUI
- 打开根/日志/输入/输出/插件目录
- 切换计算模式与网络选项

## 外置模型库管理

- 在"外置模型库管理"页选择外置模型库根路径，扫描并映射子文件夹
- 生成或刷新 `ComfyUI/extra_model_paths.yaml`，自动写入 `base_path` 与各子目录映射，变更前自动备份旧版本
- 映射列表与数量将实时展示，方便核对与维护

### 启动选项
- 计算模式：CPU / GPU
- 选项：快速模式、启用 CORS、监听 `0.0.0.0`
- 端口与额外参数：自定义端口与额外启动参数
- 注意力优化：支持 Split/Quad/PyTorch2.0/Sage/FlashAttention 等选项
- 启动后自动打开：默认浏览器 / 不自动打开 / 自定义浏览器

### 调试模式与日志
- 默认情况下，命令输出日志被严格收敛：每次命令的 `stdout`/`stderr` 最多记录少量行（默认 10 行），`netstat -ano` 仅记录行数摘要，避免日志膨胀。
- 开启调试模式：在 `launcher` 目录创建一个文件 `is_debug`（内容随意，如 `debug`）。存在该文件时，日志级别提升为 `DEBUG`，命令输出将更详细（按字符截断，默认 4000 字）。
- 关闭调试模式：删除 `launcher/is_debug` 文件即可恢复到普通模式。
- 可选高级调节：
  - 非调试模式下的每次输出行数上限可通过环境变量 `COMFYUI_LAUNCHER_LOG_LINES_LIMIT` 设置，例如：`5`。
  - 调试模式下的字符截断长度可通过 `COMFYUI_LAUNCHER_LOG_OUTPUT_LIMIT` 设置，例如：`2000`。
  - 配置文件 `launcher/config.json` 中的 `advanced.show_debug_info` 为 `true` 时，会自动创建 `launcher/is_debug` 文件以便开启调试模式（不会自动删除你手动创建的标记文件）。

## 项目结构

```
ComfyUI-Mie-Package-Launcher/
├── __main__.py                 # PyInstaller 入口（CLI 参数解析 → GUI/CLI 分发）
├── comfyui_launcher_pyqt.py    # GUI 入口（QApplication + 单实例锁 + 启动画面）
├── headless_app.py             # 无 GUI 应用上下文（CLI 模式使用）
├── config/
│   └── manager.py              # 配置管理器（读写 config.json）
├── core/                       # 核心能力层
│   ├── process_manager.py      # 进程生命周期管理
│   ├── process_events.py       # 进程事件（跨线程 UI 通知）
│   ├── app_state.py            # 应用状态机
│   ├── runner_start.py         # 启动逻辑
│   ├── runner_stop.py          # 停止逻辑
│   ├── runner.py               # 运行器入口
│   ├── probe.py                # 端口 / HTTP 可达性探测
│   ├── kill.py                 # 进程终止
│   ├── launcher_cmd.py         # 启动参数构建
│   ├── build_meta.py           # 构建时间 / 版本显示解析
│   ├── version_service.py      # 底层版本信息刷新
│   ├── version_manager.py      # 版本管理器（UI 代理）
│   ├── version_workers.py      # 版本操作工作线程
│   ├── orphan_killer.py        # 退出 launcher 时关闭孤儿 WebUI/ComfyUI 进程
│   ├── webui_dependencies.py   # WebUI 工作台依赖管理
│   ├── webui_installer.py      # WebUI 工作台安装（克隆 + 镜像选择）
│   ├── webui_launcher_cmd.py   # WebUI 工作台启动参数构建
│   ├── webui_process_manager.py # WebUI 工作台进程生命周期管理
│   └── cli_start.py            # CLI 启动逻辑
├── services/                   # 业务服务层（依赖注入）
│   ├── di.py                   # ServiceContainer（统一服务注册）
│   ├── interfaces.py           # Protocol 接口定义
│   ├── process_service.py      # 进程服务
│   ├── version_service.py      # 版本服务（业务编排）
│   ├── update_service.py       # 内核/前端/模板库更新
│   ├── launcher_update_service.py  # 启动器自身更新
│   ├── config_service.py       # 配置服务
│   ├── git_service.py          # Git 解析与配置
│   ├── network_service.py      # PyPI 代理写入
│   ├── runtime_service.py      # 启动前运行时准备
│   ├── startup_service.py      # 预启动流程
│   ├── announcement_service.py # 公告系统
│   ├── log_package_service.py  # 一键打包收集 launcher.log + comfyui.log + config.json
│   ├── model_path_service.py   # 外置模型库管理
│   └── plugin_service.py       # ComfyUI 插件管理（含推荐插件清单 + 判新）
├── ui_qt/                      # PyQt5 界面层
│   ├── qt_app.py               # 主窗口（PyQtLauncher）
│   ├── theme_manager.py        # 主题管理
│   ├── theme_styles.py         # 主题样式定义
│   ├── components/             # 通用组件（导航栏、侧边栏）
│   ├── pages/                  # 页面
│   │   ├── launch_page.py      # 启动页（主页面，组合子模块）
│   │   ├── launch/             # 启动页子模块
│   │   │   ├── version_section.py
│   │   │   ├── launch_controls_section.py
│   │   │   ├── environment_section.py
│   │   │   └── environment_selector.py # 多环境下拉选择器（launch/ 子模块）
│   │   ├── version_page.py     # 版本管理页
│   │   ├── models_page.py      # 外置模型库页
│   │   ├── about_comfyui_page.py
│   │   ├── about_launcher_page.py
│   │   ├── about_me_page.py
│   │   ├── environment_manager_section.py # 多环境管理子模块（顶层页面）
│   │   ├── plugins_page.py        # 插件管理页
│   │   ├── system_settings_page.py # 系统设置页
│   │   └── webui_page.py          # WebUI 工作台页
│   └── widgets/                # 可复用控件
│       ├── buttons.py / inputs.py / cards.py / tables.py
│       ├── announcement_dialog.py
│       ├── update_dialog.py
│       ├── progress_dialog.py
│       ├── custom_confirm_dialog.py
│       └── dialog_helper.py
├── utils/                      # 通用工具
│   ├── common.py               # 通用方法、单实例锁
│   ├── logging.py              # 日志配置
│   ├── paths.py                # 路径解析
│   ├── pip.py                  # pip 安装与查询
│   ├── net.py                  # 网络代理
│   └── ui_actions.py           # UI 辅助操作
├── tests/                      # 测试（pytest）
│   ├── conftest.py             # 公共 fixture
│   ├── unit/                   # 单元测试
│   ├── integration/            # 集成测试
│   ├── ui/                     # UI 测试（pytest-qt）
│   └── utils/                  # 测试工具（app_stub、mock_subprocess 等）
├── pyproject.toml              # 项目配置与 pytest 设置
├── build.py                    # Nuitka + Enigma 一键构建脚本
├── build_parameters.json       # 构建参数（版本号、构建时间）
└── README.md
```

## 架构与数据流

```
View (PyQt5)          Service (DI)           Core              External
┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────┐
│ ui_qt/   │────>│ services/    │────>│ core/        │────>│ Git      │
│ pages/   │     │ di.py 注入   │     │ runner_start │     │ Python   │
│ widgets/ │<────│ 业务编排     │     │ runner_stop  │<────│ ComfyUI  │
│ qt_app.py│     │              │     │ probe        │     │ GitHub   │
└──────────┘     └──────────────┘     └──────────────┘     └──────────┘
      │                  │                    │
      │  UiInvoker       │  config/           │  utils/
      │  信号/槽          │  manager.py        │  paths/pip/net
      └──────────────────┴────────────────────┘
```

### 职责划分
- **View 层**（`ui_qt/`）：PyQt5 页面与控件，通过信号/槽响应用户操作，仅触发 Service 方法，不直接执行系统操作。跨线程 UI 更新通过 `UiInvoker` 信号机制安全调用。
- **Service 层**（`services/`）：通过 `ServiceContainer.from_app(app)` 依赖注入，执行业务流程（更新、代理、配置、运行时准备），调用 Core 与 Utils。
- **Core 层**（`core/`）：执行系统层面操作（子进程、端口探测、版本刷新、进程事件通知），通过回调与事件更新 UI 状态。
- **Config 层**（`config/`）：负责 `launcher/config.json` 的读写与原子更新。

### 关键调用关系
- **入口初始化**：`comfyui_launcher_pyqt.py` 创建 `QApplication` → `PyQtLauncher` → 内部调用 `ServiceContainer.from_app(app)` 注入全部服务。
- **启动流程**：`core/launcher_cmd.build_launch_params` 构造命令 → `core/runner_start.start` 启动 → `core/process_events.py` 发送进程事件 → UI 大按钮状态更新。
- **版本刷新**：`core/version_service.refresh_version_info` 异步查询版本，通过 `UiInvoker` 信号安全更新 UI。
- **CLI 模式**：`__main__.py` 解析参数 → `headless_app.HeadlessAppContext` 提供无 GUI 上下文 → `core/cli_start.cli_start` 启动 ComfyUI。

## 环境要求

- **操作系统**：Windows 10/11
- **Python**：3.8+（推荐 3.10/3.11）
- **依赖**：
  - `PyQt5>=5.15.0`
  - `PyYAML>=6.0`
- **可选依赖**：
  - `psutil`（端口与进程探测更健壮，`core/process_manager.py` 自动回退）
  - `requests`（便捷进行 API 示例调用）

## 打包 EXE

`build.py` 一键完成 Nuitka 编译 + Enigma 封包 + release 子目录打包：

```bash
.venv\Scripts\python.exe build.py             # 正式版
.venv\Scripts\python.exe build.py --test      # 测试通道（dist/ComfyUI启动器_test.dist/）
.venv\Scripts\python.exe build.py --evb-only # 跳过 Nuitka，仅重跑 Enigma 封包
```

参数与排错：见 BUILD.md。

### 构建产物

- `dist/ComfyUI启动器.dist/` — Nuitka + Enigma 中间产物（含 `ComfyUI_Launcher_Internal_boxed.exe`）
- `release/ComfyUI启动器_v<ver>_<YYYYMMDD_HHMM>/` — 最终发布子目录：
  - `ComfyUI启动器.exe` — 纯净名启动器
  - `ComfyUI启动器-CLI.cmd` — 配套 CLI wrapper（agent / 自动化专用，详 AGENTS.md）
  - `使用说明.md` / `AGENTS.md` / `cli.md` — 操作文档随 exe 一起打包，用户拿到 release 即可读
- `build_parameters.json` 自动更新版本号与构建时间（dev 环境 fallback 到 `sys.executable` mtime，见 `core/build_meta.py`）

### 说明
- Nuitka 构建产物体积更小、启动更快（`build_parameters.json` 中 `mode: nuitka_release`）。
- 若自定义图标，替换 `assets/rabbit.ico` 即可。
- 调试日志可通过在 `launcher` 目录下创建 `is_debug` 文件开启；打包后的 EXE 同样支持。
- 公告相关文件写入运行目录的 `launcher/` 子目录：`announcement_cache.txt` / `announcement_seen.json` / `announcement_muted.json`。

## 发布到 GitHub Releases

`release.py` 依赖 [GitHub CLI](https://cli.github.com/) (`gh`)，读取 `release/ComfyUI启动器_v<ver>_<YYYYMMDD_HHMM>/` 里已打包好的 subdir，打成 zip 上传到 GitHub Releases。默认上传资产：`ComfyUI启动器_v<ver>_<YYYYMMDD_HHMM>.zip`（含 exe + CLI wrapper + 3 份文档）

运行前需要：

- 安装 `gh` 并认证 (`gh auth login`)
- 已有正确的 repo 写入权限 (默认为 `MieMieeeee/ComfyUI-Mie-Package-Launcher`)
- `release/ComfyUI启动器_v<ver>_<YYYYMMDD_HHMM>/` 里已有最新打包的 exe

```bash
# 默认：取最新一个 subdir，上传
python release.py

# 列出所有产物（subdir + 旧格式残留）
python release.py --list

# 查看 GitHub 上已发布的 release
python release.py --view

# 指定具体 subdir（避免交互选）
python release.py --file "release/ComfyUI启动器_v1.0.15_20260728_1200"

# 发布时标记为 Latest + 推送 git tag 到 origin
python release.py --latest --push-tag

# 已有 release 重跑 (上传会走 upload-only 分支)
python release.py --version v1.0.15

# 不创建 git tag (只发 release)
python release.py --no-tag

# 删除某个 release
python release.py --delete v1.0.14
```

常见场景：

1. **发布正式版本**：先跑 `python build.py` 打包，本地测试 release 子目录里的 exe，然后 `python release.py --latest --push-tag`。
2. **发布测试版本**：先跑 `python build.py --test`，然后 `python release.py`（脚本会自动给 test subdir 的 release 加 `--prerelease`）。
3. **只推送 zip，不重新打包**：上一次打包过的 subdir 里的 exe 是测试过的，直接 `python release.py` 选它，脚本会重打 zip 上传。zip 里包含 exe + CLI wrapper + 3 份文档，用户下载后解压即可。

输出约定：

- `gh` / `git` 命令失败 -> 与错误信息打到 stderr，退出码 1
- release 已存在 -> 跳过创建，直接 `gh release upload --clobber`。上传失败重跑安全
- `--push-tag` 只在本地 `git tag` 创建后才推送到 origin，默认只创建本地 tag

## 测试

测试框架使用 **pytest**，搭配 `pytest-qt` 进行 PyQt5 控件测试。

```bash
# 运行全部测试
pytest

# 仅运行单元测试
pytest tests/unit/

# 运行单个测试文件
pytest tests/unit/test_runner_start.py -v

# 带覆盖率报告
pytest --cov=. --cov-report=html
```

## 测试结构
- `tests/unit/` — 单元测试，覆盖 Service、Core、Utils 层
- `tests/integration/` — 集成测试，验证跨模块协作
- `tests/ui/` — PyQt5 UI 测试（需要 Qt 显示环境）
- `tests/utils/` — 测试工具（`app_stub`、`mock_subprocess`、`path_mocks`）

## 开发说明

### 模块开发规范
- 新增功能先定义 Service 接口（`services/interfaces.py` 中的 Protocol）并编写测试，再在 View 绑定事件。
- 避免在 View 层进行耗时或有副作用的操作（安装/更新/写文件），统一委派给 Service。
- Core 层对外通过稳定函数暴露能力，避免 UI 直接导入内部实现。
- 日志输出遵循现有精简策略（非调试模式仅记录摘要）。

### View 层约束
- 使用 PyQt5 信号/槽机制，跨线程 UI 更新必须通过 `UiInvoker` 信号。
- 事件处理只做参数收集与校验，将执行委派给 Service。

### Service 层约束
- 明确输入/输出契约，失败返回统一结构（`success/updated/up_to_date/version/error`）。
- 调用 Core 与 Utils，避免直接操作 UI 控件或线程调度。

## 常见问题解答

> ⚠️ 本地速查版本；以 [Feishu wiki 完整 FAQ](https://dcn8q5lcfe3s.feishu.cn/wiki/ELY2wwPgciIA56kS3eBciY4RnPd) 为准。

<a id="faq-1"></a>
<details>
<summary><strong>启动后无法运行工作流，dev_utils_execute() 报错</strong></summary>

> 如果启动 ComfyUI 后无法运行工作流，并在日志中看到类似错误：
> `dev_utils_execute() takes 10 positional arguments but 11 were given`
> 大概率是 **ComfyUI-Dev-Utils 插件版本不兼容** 导致的。
> ✅ 解决方法：**禁用或升级 ComfyUI-Dev-Utils 插件**。
> ![升级或禁用ComfyUI-Dev-Utils插件示意图](readme_assets/升级或禁用dev_utils.png)

</details>

<a id="faq-2"></a>
<details>
<summary><strong>端口 8188 被占用 / 想换端口</strong></summary>

- **GUI**：启动控制页直接改端口字段。
- **CLI**：不支持 `--port` flag；改 `launcher/config.json` 的 `launch_options.default_port`。
- **端口被占**：启动器检测到冲突时弹"是否直接打开网页而不启动新实例"，默认取消启动。

</details>

<a id="faq-3"></a>
<details>
<summary><strong>想换 HuggingFace / PyPI / GitHub 镜像源</strong></summary>

- **HF 镜像**：`launcher/config.json` 的 `proxy_settings.hf_mirror_mode` + `hf_mirror_url`，或 GUI 设置页下拉（默认 `hf-mirror.com`）。
- **PyPI 镜像**：`proxy_settings.pypi_proxy_mode`（`aliyun` / `tsinghua` / `huaweicloud` / `custom` / `none`），CLI `update comfyui` 走这个装依赖。
- **GitHub 代理**：`launch_options.git_proxy_mode` + `git_proxy_url`（`gh-proxy` / 自定义），用于内核 git pull。

</details>

<a id="faq-4"></a>
<details>
<summary><strong>多套 ComfyUI 环境怎么切换</strong></summary>

- **GUI 切**：环境下拉 / 设置页管理（持久化到 `config.json` 的 `active_env_id`）。
- **CLI 默认跑 GUI 当前激活的环境**；agent 不主动切。
- **跨 env 自动化**：`--env <id>`（parser 接受但 agent 默认不传，详 AGENTS.md）。

</details>

<a id="faq-5"></a>
<details>
<summary><strong>CLI `update comfyui` 不工作</strong></summary>

- **v1.0.14 之前**会崩在 `HeadlessAppContext object has no attribute update_core_var`。
- **v1.0.14 已修**：`HeadlessAppContext` 补齐 7 个缺失属性 + `services.version` 换真实 `VersionService`，能跑完整 git pull + 前端 + 模板库 + 依赖同步。
- **还报错**：`python __main__.py update comfyui --dry-run --json` 看会跑哪条路径；或 `python __main__.py logs launcher -n 50 --no-follow` 排查。

</details>

<a id="faq-6"></a>
<details>
<summary><strong>日志视图看不到 tqdm 进度条刷新</strong></summary>

- **v1.0.14 起**：`PYTHONUNBUFFERED=1` + 后台线程 pump 让 tqdm 实时刷新。
- 日志视图原地渲染 `回车` 覆盖行（tqdm 进度条形态）。
- 配套 powershell tail 窗口独立显示（`show_console=true` 时启动）。

</details>

<a id="faq-7"></a>
<details>
<summary><strong>启动器版本落后了，怎么更新</strong></summary>

- **GUI 自更**：关于页有"检查更新"按钮（v1.0.8+）。
- **手动**：拉新源码 → `.venv\Scripts\python.exe build.py` 重打 exe。
- 注意：`build_parameters.json` 会自动 bump `built_at` 时间戳。

</details>

<a id="faq-8"></a>
<details>
<summary><strong>怎么改源码 / 编译新的 exe</strong></summary>

- **开发模式**：`python __main__.py <command>` 直接跑源码（热改生效）。
- **打 exe**：`.venv\Scripts\python.exe build.py`，参数详 [BUILD.md](BUILD.md)。
- **构建产物**：`release/ComfyUI启动器_v<ver>_<YYYYMMDD_HHMM>/` 含 exe + CLI wrapper + 3 份文档。
- `build_parameters.json` 自动 bump 时间戳；`version_preferences` 在 config.json 里调。

</details>

<a id="faq-9"></a>
<details>
<summary><strong>模型库放在外置硬盘上怎么接进来</strong></summary>

- **GUI**："外置模型库管理"页 → 添加根路径 → 自动扫描子文件夹 → 生成 `ComfyUI/extra_model_paths.yaml`。
- **多库**（v1.0.14）：可在 `config.json` 的 `models.external_libraries[]` 配多个，每个独立 base_path + enabled 开关。
- 变更前自动备份旧 yaml。

</details>


## 文档
- Agent 操作指南：[AGENTS.md](AGENTS.md)
- CLI 完整参考：[cli.md](cli.md)
- 接口契约：[docs/ServiceInterfaces.md](docs/ServiceInterfaces.md)
- 自动更新设计：[docs/auto-update.md](docs/auto-update.md)
- 进程事件设计：[docs/process_events_design.md](docs/process_events_design.md)
- 启动页拆分说明：[docs/launch_page_decomposition.md](docs/launch_page_decomposition.md)
