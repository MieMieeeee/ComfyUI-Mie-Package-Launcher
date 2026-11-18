# 伴生服务（Companion Services）泛化架构设计

> 2026-10-31 · 对应交接资料 `C:/XX/启动器伴生服务-交接资料-2026-10-31.md` 与包侧回执 `C:/XX/启动器伴生服务-包侧回执-2026-10-31.md`
> 目标：把「WebUI 工作台」泛化为通用伴生服务框架，openjutsu 作为第二个内置实例。
> 现状摸底见本文引用的 file:line（2026-10-31 探索报告）。

## 1. 目标与非目标

**目标**

1. 通用生命周期：服务为单元抽象 `start / ready / stop / status / update`，服务内部一条还是多条命令是实现细节。
2. openjutsu 实例：一键 ComfyUI(未跑则先起) → proxy → app，自动开前端页 (默认 8198)；停止三进程全收、端口无残留。
3. webui 兼容红线：`webui` 老 CLI 命令、`--json` schema、退出码 6/7/8、`webui_options` 配置键**全部原样保留**。
4. 服务 100% 限定在整合包路径（环境 `comfyui_root`）下，不做任意位置的用户自定义服务。

**非目标（本期不做）**

- webui 运行时迁移到新框架（列为 P2，见 §15；本期 webui 五件套原路径不动，回归零风险）。
- 任意用户自定义服务声明（config 里写 services[] 就能注册新服务）——只做代码级内置注册表。
- npm registry 镜像加速（update 链的 npm ci 直连，慢就慢；首启不需要它）。
- WebUI 工作台页面与 openjutsu 页面的 UI 统一（P2）。

## 2. 总体策略：strangler 顺序

新框架 `core/companion/` 先为 openjutsu 服务，webui 暂不动。理由：

- 11-03 护栏下，新功能不能依赖旧模块迁移完成——迁移滑期就砍掉，openjutsu 照发；
- webui 测试面（16 单测 + 2 e2e，含真实 spawn）锁的是行为，等 P2 迁移时正好当验收基线；
- webui 在注册表中**名义上就是第一个内置实例**（`service list` 可见），只是运行时仍走 `WebuiProcessManager` 老路径。

## 3. 服务声明模型（`core/companion/spec.py`）

代码级注册表，不进用户 config：

```python
@dataclass(frozen=True)
class IdentityRule:
    """PID 身份门（防 PID 复用误杀/误报，继承 webui-pid-reuse 教训）。
    对 psutil Process 的 cmdline（join+lower）与 cwd 做子串匹配，
    所有给出的条件必须同时满足。"""
    cmdline_all: tuple[str, ...] = ()
    cmdline_any: tuple[str, ...] = ()
    cwd_any: tuple[str, ...] = ()
    # 2026-11-18 新增: 入口脚本相对 root 的路径. 命令行里必须出现
    # "<root>/<script_rel>" (raw 与 realpath 两种形态都认). 用来把
    # 「多个环境指向同一份 junction 目标」分开 —— 命令行里带的是各环境
    # 自己的路径文本 (启动命令按未 resolve 的 root 拼).
    script_rel: str = ""

@dataclass(frozen=True)
class PortBinding:
    role: str                 # "proxy" / "app"
    default_port: int         # 8197 / 8198
    config_key: str           # "services.openjutsu.proxy_port"
    ready: str = "port"       # "port" | "http"（本期 openjutsu 全部 port，见 §6）

@dataclass(frozen=True)
class ServiceSpec:
    id: str                   # "webui" / "openjutsu" / "h3-engine"（CLI/注册表键）
    name: str                 # GUI 显示名
    root: str                 # 相对包根（= 环境 comfyui_root），如 "openjutsu"
    entry_markers: tuple[str, ...]   # 存在即视为「已安装」，如 ("package.json", "patch_proxy.py")
    ports: tuple[PortBinding, ...]
    identity: dict[str, IdentityRule]   # role -> 身份规则（pidstore/收养/清残用）
    requires_comfyui: bool
    browser_url_role: str | None       # 就绪后打开哪个 role 的端口
    runtime: "openjutsu" | "h3-engine" | "webui-legacy"   # P1 分流：legacy 走老五件套
```

注册表：`BUILTIN_SERVICES: dict[str, ServiceSpec]`，webui 条目 `runtime="webui-legacy"`（`service status webui` 内部转发 `WebuiProcessManager.status()`，输出字段对齐），openjutsu 条目 `runtime="openjutsu"`、h3-engine 条目 `runtime="h3-engine"` 走新框架。

> **2026-11-18 新增 h3-engine**（H3 短剧工作台，第二个跑在新框架上的服务）：
> `root="ComfyUI/custom_nodes/ComfyUI-Mie-H3-Engine"`（root 允许是相对包根的**多级**路径）、
> `entry_markers=("webapp/__main__.py",)`、单端口 role `app` 默认 **8200**（`services.h3-engine.port`）、
> `requires_comfyui=False`（工作台离线也能用）、`browser_url_role="app"`。
> 身份规则用新增的 `IdentityRule.script_rel="webapp/__main__.py"`（见 §8）。

**h3-engine 的声明要点**（步骤构建在 `core/companion/h3_runtime.py`）：

| role | 进程 | 命令 | 身份规则 |
|---|---|---|---|
| app | 长驻 spawn | `<环境 python> -u <插件根>\webapp\__main__.py`（cwd=插件根） | `script_rel="webapp/__main__.py"` + `cwd_under_root` |

- **runtime 分发表**（`manager._RUNTIME_MODULES`）：runtime 字符串 → 模块路径（`openjutsu` / `h3-engine`）。加第三个 runtime 不再往 manager 里加 if。
- **runtime 可提供的钩子**（duck typing，缺省即旧行为）：

  | 钩子 | 作用 |
  |---|---|
  | `build_steps(paths, ports, comfy_port)` | 步骤列表（`{"role","kind":"once"/"long","cmd","env","cwd"}`），可零个一次性步骤；缺省走老的 `build_step_cmd`/`build_proxy_cmd`/`build_app_cmd` 兼容路径 |
  | `ready_probe(paths, ports)` | 语义就绪探针（端口通 ≠ 是我们的服务）；缺省只看端口 |
  | `log_mode()` | `"file"` = 子进程直写日志文件（CLI 退出后仍能写日志）；缺省 `"pipe"`（launcher 进程内 drain 线程） |
  | `health_info(paths, ports)` | 详细健康信息（进 `status` 的 `health` 字段） |

- **H3 的环境变量注入是必填**：`MIE_WEB_PORT` / `MIE_WEB_HOST`（启动器绑 127.0.0.1，引擎默认 0.0.0.0）/ `MIE_COMFYUI_ROOT` / `MIE_COMFYUI_URL` / `MIE_PLUGIN_ROOT` / `MIE_ASSET_LIBRARY` / `MIE_LLM_KEYS_FILE` / `MIE_WEB_SETTINGS`。引擎侧的兜底值原本指向**别的机器的硬编码路径**（已删），但仍要显式注入，免得读到别的环境的资产库。
- **解释器**：必须是该环境 ComfyUI 的 embedded python（mie_* 装在它的 site-packages 里）；相对 `python_path` 按**所选包根**解析（不是 `stable_project_root()`）。
- **设置/任务/快照**统一落在 `<包根>/launcher/h3-engine/settings.json` 所在目录（引擎侧 `webui_node.settings_path()` 同口径），按环境分开。
- **资产库归引擎自己**（2026-11-18 核实）：H3 的代码不依赖 MieNodes 资产包（它要的是 pip 包，requirements.txt 里写明三个 authoring 包版本独立）。归属规则 = 引擎目录里有 `asset_library/` 就归引擎，否则回落同级的 MieNodes 资产包（老布局，用户的 220MB 数据在那儿，不能遮住）。资产位置在 mie_craft 里三级可配：`resolve_library_dir` → 显式参数 → `$MIE_ASSET_LIBRARY` → `<plugin_root>/asset_library` —— 引擎侧只设 `MIE_ASSET_LIBRARY`（`MIE_PLUGIN_ROOT` 是「谁拥有资产库」的全局开关，MieNodes 自己会指向它，引擎抢了会打断它）。

**安装链（2026-11-18，与 WebUI 工作台同构）**：

| action | 做什么 | 实现 |
|---|---|---|
| `install` | `git clone --depth 1` → `<包根>/ComfyUI/custom_nodes/ComfyUI-Mie-H3-Engine`；目标目录已有内容则**跳过**（不删用户数据）；走用户配置的 git 代理 | `installer.clone_service` |
| `setup` | 引擎 `requirements.txt` 逐包容错装进该环境的 embedded python；镜像上没有的新版本自动回退官方 PyPI | `installer.install_requirements` |
| `update` | `git fetch` + `git reset --hard origin/HEAD`；**用户资产与密钥先挪出仓库外暂存、更新完搬回** | `installer.pull_service` + `protect_user_data` |

> **为什么「从索引摘除」不够**：`reset --hard` 会把索引重置成 `origin/HEAD` 的树 —— 远端历史里若含那些路径（用户曾 `git add -f` 提交过），工作树里的文件照样被还原（实测）。所以保护动作必须是「搬出工作树」。正常情况下引擎仓库的 `.gitignore` 已排除 `asset_library/` 与 `mie_llm_keys.json`，未跟踪 + 被忽略的文件不受 reset 影响。

**openjutsu 的声明要点**（步骤构建在 `core/companion/openjutsu_runtime.py`）：

| role | 进程 | 命令 | 身份规则 |
|---|---|---|---|
| build | 一次性 run 步骤 | `<包根>\node\node.exe <包根>\node\node_modules\npm\bin\npm-cli.js run build` | —（非长驻） |
| proxy | 长驻 spawn | `<包根>\python_embeded\python.exe -c "import sys; sys.path.insert(0, r'<root>\.proxy-site'); from comfy_api_proxy.cli import main; main()" run --port <proxy_port> --max-upload-mb 500` | `cmdline_all=("comfy_api_proxy",)` |
| app | 长驻 spawn | `<包根>\node\node.exe ...\npm-cli.js run start` | `cmdline_any=("npm-cli.js","next")` + `cwd_any=(str(root),)` |

> 2026-10-31 包侧重烘后核实：`--port` 参数存在（`.proxy-site/comfy_api_proxy/cli.py:73`，默认 8189），两端口均可配。

- 不调 `npm.cmd` / `comfy-api-proxy.exe`（.cmd 与 pip shim 都有引号/绝对路径坑，进程树也脏）。
- app 子进程 env：`PORT=<app_port>`、`NEXT_TELEMETRY_DISABLED=1`、`PATH` 前置 `<包根>\node`（Next 运行时 spawn 子进程用）。基础 env 取 `os.environ.copy()`——本地代理（issue #109）与 NO_PROXY 自动继承，与 ComfyUI 子进程同一待遇。
- **app↔proxy 端口耦合（2026-10-31 实测发现）**：app 靠 env `COMFY_BASE_URL` 找 proxy（名字叫 COMFY 但指向 8189 的 proxy，见 `.env.local`）；`COMFYUI_URL`（空=8188）才是 app 侧模型选择器用的真 ComfyUI 地址。所以 spawn app 时必须注入：
  - `COMFY_BASE_URL=http://127.0.0.1:<proxy_port>`（改 proxy 端口时保持一致；Next.js 里进程 env 优先于 .env.local，注入即覆盖）
  - `COMFYUI_URL=http://127.0.0.1:<comfyui_port>`（取启动器当前 ComfyUI 端口——用户改过 ComfyUI 端口时防止 app 还去找 8188）
- 两个端口均可配：proxy 走 `--port` 参数，app 走 `PORT` env（Next.js 标准）。

## 4. 运行时模块（`core/companion/`）

| 文件 | 职责 |
|---|---|
| `spec.py` | 上述声明模型 + `BUILTIN_SERVICES` |
| `registry.py` | `available(app, env_id) -> dict`：按环境解析 root（复用 `resolve_paths_for_env`），entry_markers 全存在才算可用；`get(service_id)` |
| `manager.py` | `CompanionServiceManager(app, service_id, *, env_id=None)`：生命周期编排（§5） |
| `pidstore.py` | v2 多进程 pidfile（§7） |
| `proctree.py` | 进程树终止 + 身份门 + 端口清残（§8） |
| `openjutsu_runtime.py` | openjutsu 的步骤/env 构建、依赖闸门、update 链（§10） |
| `h3_runtime.py` | H3 短剧工作台的路径解析/依赖闸门/命令构建/健康探针/**安装链**（2026-11-18） |
| `installer.py` | **通用安装器**（2026-11-18）：`clone_service` / `pull_service` / `protect_user_data` / `install_requirements` —— 从 `core/webui_installer.py` 泛化，webui 之后迁到本框架时直接复用 |
| `core/cli/cmd_service.py` | `service` 命令族（§9） |

不依赖 PyQt5（与 `WebuiProcessManager` 同一约束），CLI/GUI 复用；app 耦合仍走鸭子属性（`app._cwd / app.config / app.logger / app.get_active_paths / app.services`），`HeadlessAppContext` 已全部提供（headless_app.py:121-231），零新增 app 接口。

## 5. start 生命周期（manager）

```
start(timeout=120, no_wait=False):
  1. 幽灵 pidstore 清理（PID 死/身份不符 → 视为未跑，不拦截）
  2. 已在跑短路：pidstore 身份校验通过 → ok=True, already_running=True
  3. available 检查：root/markers 缺 → exit 7 语义（error + exit_code 字段）
  4. 依赖闸门（openjutsu_runtime.check_deps）：node.exe 缺 / .proxy-site 缺或
     comfy_api_proxy 不可导入 / package.json 缺 → exit 8 语义
  5. requires_comfyui 且 ComfyUI 未跑（core.cli.runner.service_status）→ exit 6 语义
     （CLI 不自动起 ComfyUI，与 webui --with-comfyui 的「不强行启动」对齐；自动起是 GUI 的事）
  6. 端口预检：任一绑定端口被占 → abort, port_in_use=True（复用 probe.find_pids_by_port_safe）
  7. 逐步骤执行：
     a. run 步骤（npm run build）：阻塞等退出，超时 kill，输出进服务日志，非零退出 → 失败返回
     b. spawn proxy：CREATE_NO_WINDOW + stdout/stderr PIPE → drain 线程写日志（复刻 webui_drain，:306-336 模式，行前缀 [proxy]）
     c. spawn app：同上，前缀 [app]
     d. 每个 spawn 后立即把 (pid, role) 追加写 pidstore（先落盘再等就绪，崩溃可追溯）
  8. 等就绪：全部 PortBinding 端口监听（端口探测，见 §6），deadline=timeout；
     任一进程先死 → 失败（日志尾部进 error）
  9. 开浏览器（browser_url_role 的端口）
```

`no_wait`：步骤 7 跑完即返回（不等就绪），对齐 webui `--no-wait` 把 timeout 压短的语义。

## 6. 就绪探测（遵守既有拍板）

- **start 路径一律端口探测**（复用 `find_pids_by_port_safe` 的端口侧能力 / 轻量 socket connect），不做 HTTP——冷启动省时，且 proxy 根路径 404 本来就不能按 HTTP 语义判。
- `status` 的四态矩阵沿用 webui 模型（webui_process_manager.py:519-520）：进程在+端口通=就绪；进程在+端口不通=启动中；进程不在+端口通=端口被占（非本服务）；都不=未跑。status 可额外做 HTTP 探活作为展示字段（webui 语义保留），不参与判定。
- `PortBinding.ready="http"` 字段保留但本期无人使用；webui 的 HTTP 就绪在老路径原样不动。

## 7. pidstore v2（多进程）

`launcher/openjutsu.pid`（通用规则 `launcher/<service_id>.pid`）：

```json
{
  "version": 2,
  "service_id": "openjutsu",
  "env_id": "env_default",
  "started_at": "ISO8601(UTC)",
  "processes": [{"pid": 123, "role": "proxy"}, {"pid": 456, "role": "app"}],
  "ports": {"proxy": 8197, "app": 8198},
  "log_path": "C:/.../launcher/openjutsu.log"
}
```

- 原子写（`.tmp` + `os.replace`），实现复刻 `core/cli/webui_pidfile.py` 的写法，参数化 service_id + 多 pid。
- `webui.pid` 的 v1 扁平 schema **不动**（webui 走老路径；`test_webui_pidfile.py` 原样通过）。
- 读侧统一 `read_live(path, spec)`：逐 pid 存活 + 身份校验，全过才算 live；部分死 → 返回 live 子集（status 如实展示，stop 只杀活的）。

## 8. 停止语义：进程树 + 端口复核 + 身份过滤（`proctree.py`）

```
stop(force=False):
  1. pidstore 读 live pids（身份校验过）；幽灵不杀（2026-10-03 Grok Bot 教训）
  2. 对每个根 pid：kill_tree(pid)
     Windows: taskkill /PID <pid> /T /F（一次调用连树收掉 cmd/npm/node 链）
     兜底: psutil children(recursive=True) + terminate→wait→kill；POSIX: killpg
  3. 端口复核：轮询全部绑定端口（≤5s），仍监听 → 清残：
     find_pids_by_port_safe(port) 逐 pid 身份校验，**匹配才杀**
     （修正老 webui 兜底链无身份校验的已知缺口，见摸底报告 §1；老路径本期不动）
  4. 清 pidstore、停 drain 线程
```

幂等（未跑返 ok=True），与 webui stop 契约一致。

## 9. CLI：`service` 命令族（`core/cli/cmd_service.py` + parser.py）

```
service list [--json]                          # 注册表 + 每服务 available/running
service <id> status | start | stop | restart | info | update
  start:  [--json] [--no-wait] [--timeout SEC(120)] [--env ENV_ID]
  stop:   [--json] [--force]
  status: [--json]        # 退出码 0=在跑 / 3=未跑 / 1=异常（对齐全局约定）
  info:   [--json] [--env ENV_ID]
```

- 退出码语义泛化为服务族通用（`exitcodes.py` 加**同值别名**，不改老常量）：
  `EXIT_SERVICE_CORE_NOT_RUNNING=6`（requires_comfyui 且核心未跑）
  `EXIT_SERVICE_NOT_INSTALLED=7`（root/markers 缺，含「当前环境没有该服务」）
  `EXIT_SERVICE_DEPS_MISSING=8`（node/proxy-site 等依赖缺）
  `test_cli_exitcodes.py` 只锁值，加别名是纯增量。
- `webui` 子命令**永久保留**：`service <webui 动作> webui` 时转发 `cmd_webui` 同一实现（P1 只是名义统一，P2 才换运行时）。
- `logs openjutsu`：`LOGS_TARGETS`（parser.py:37）加目标，`_resolve_log_path`（core/cli/runner.py:106-108）读 `launcher/openjutsu.log`。**务必 `--no-follow`** 的既有告诫适用。
- 顺带修一处文档漂移：`_WEBUI_EPILOG` 声称 already_running 退 2，实现是退 0（cmd_webui.py:141）——本期**不改行为**，把 epilog 改准（`service` 的 epilog 直接写对：already_running → 0）。

## 10. openjutsu 专属：依赖闸门与 update 链

**check_deps（start 前置，exit 8）**：

1. `<包根>\node\node.exe` 存在（缺 = 包烘焙缺陷，报错文案指明）；
2. `<root>\.proxy-site\comfy_api_proxy` 可导入（用 python_embeded `-c "import ..."` 探测，带 8s 超时，复刻 `_probe_one` 模式 webui_dependencies.py:28-43）；
3. `<root>\package.json` + `node_modules\next` 存在。

**update 链**（`service update openjutsu`，带 on_progress）：

```
1. git -C <root> fetch <url> --depth 1 + reset --hard origin/main
   （复刻 pull_webui 的 fetch+reset 模式 webui_installer.py:357-384，规避 divergent；
    URL 代理规则同款：仅 github 套 gh-proxy 前缀，且改用 git_insteadof_args 的 -c argv 方式，
    遵守 2026-10-14 内核更新代理事故的三条硬约束。
    分支注意：包侧重烘后 openjutsu 已在 main @ 0b8238f——原 zh 分支并入 main 血统，
    交接资料里写的 "出货分支 zh" 作废）
2. node npm-cli.js ci
3. node npm-cli.js run build
4. python_embeded -m pip install --target <root>\.proxy-site --upgrade comfy-api-proxy==0.1.6
5. python_embeded -c "...runpy.run_path('patch_proxy.py')..."   # find_spec 定位 + 自带幂等
```

> 顺序与包侧回传 §2.2 的要求逐字一致（patch 必须在依赖升级后重跑，幂等无副作用）。

版本展示：`package.json` 的 `version` 字段 + `git describe --tags --always`。

## 11. GUI

**新页面 `ui_qt/pages/openjutsu_page.py`**（复刻 webui_page 骨架，不复刻 webui 特化逻辑）：

- 状态机沿用十态模型（4 稳定 + 6 busy，busy 态不被 5s 轮询覆盖——webui_page.py:58-74 模式）；稳定态映射：未安装(7) / 依赖缺失(8) / 就绪 / 运行中。
- 线程模型照抄：worker `threading.Thread(daemon=True)` + `QMetaObject.invokeMethod` 回主线程；`_run_with_progress` 模式（注册 `_bg_task_registry`）用于 update 长任务——**有活跃后台任务时环境切换被阻止**的既有机制自动覆盖。
- 启动交互：`requires_comfyui` 服务的三选一改为两选一（取消 / 一键启动 ComfyUI+服务）；「同时启动」复用 webui 页验证过的链：后台 `core.cli.runner.start_service` 等 `res["ready"]` → 再 `CompanionServiceManager.start`。
- 日志查看：LogTailer + VirtualTerminal 复用（webui_page.py:1658-1757 模式）。
- 主题合规：全程 `theme_manager` tokens / builders，实现 `update_theme`（AGENTS.md GUI 规范）。
- 侧边栏新入口（qt_app.py:2146 一带 pages dict + NavBtn），env 切换 hook `refresh_after_env_switch`。

**退出链泛化**（qt_app.py:4217-4265）：

```
退出停服顺序：companion 服务（openjutsu）→ webui → ComfyUI（依赖方先走，既有顺序自然延伸）
托盘保留 ComfyUI 退出场景：orphan 判定泛化为「requires_comfyui 的服务，在 ComfyUI 明确未跑时」
→ 停掉（stop_orphan_webui 保留，新增 stop_orphan_companions，同样保守：探测不可信不动）
```

## 12. 配置与迁移

```json
"services": {
  "openjutsu": {"enabled": true, "proxy_port": 8197, "app_port": 8198,
                 "browser_open_mode": "default"}
}
```

- 块缺失 = 全默认，不写不炸；`webui_options` 原样不动（红线）。
- schema 测试新增 `test_companion_config_schema.py`（照 test_webui_config_schema.py 模式）。
- `launcher/config.json` 含本机绝对路径——运行时改动不进 git（既有告诫）。

## 13. 测试计划

| 层 | 内容 |
|---|---|
| 单测 | spec/registry 解析（多环境、root 缺失）；pidstore v2 round-trip/幽灵/部分死；IdentityRule 匹配矩阵；manager 生命周期（fake spawn：python 假进程脚本扮演 proxy/app，参考 test_webui_lifecycle_e2e.py:71-103 的假脚本手法，文件名/内容按身份规则构造）；update 链各步失败分支；CLI dispatch + 退出码 6/7/8/3；config 兜底 |
| e2e | `service` 命令真进程：info/status --json schema、未安装→7、无依赖→8、完整 start→status→stop 端口无残留 |
| 回归 | `python -m pytest tests/ -q --basetemp=./.pytest_tmp_run`（全新 basetemp，既有坑）；webui 16+2 测试必须全绿 |
| 测试床 | 包侧重烘后（11-01 预定）：`C:\XX\work\Package\openjutsu_mie_packaged` 冷启动全链验收（交接资料 §6 五条 + 换角色任务实测 patch 生效） |

测试红线：不打真 sleep / 不真等 120s 轮询（既有 slow 标记规则）；需要真实 node 的用例打 `e2e` 标记 + 环境探测 skip。

## 14. 里程碑（今天 10-31，护栏 11-03）—— 执行状态

| 日 | 内容 | 状态 |
|---|---|---|
| D0 10-31 | 设计评审通过；~~包侧重烘启动~~ **已完成**（当晚回传：node v22.23.4 + .proxy-site 就位、五项自验全绿、便携换路径测试通过 `C:\XX\work\portable_test\`；测试床三件套常驻可联调，纯净首启场景包侧可按需复原） | ✅ |
| D1 11-01 | 框架核心（spec/registry/pidstore/proctree/manager）+ 单测；openjutsu_runtime；CLI `service` 族 + logs 目标 | ✅ 10-31 当天完成（含 40 个新测试；真 spawn e2e 4 例） |
| D2 11-02 | GUI 页 + 退出链/orphan 泛化 + update 链；重烘包到手后测试床联调 | ✅ 代码完成（openjutsu_page + 侧边栏按环境显隐 + 退出链 openjutsu→webui→ComfyUI + stop_orphan_companions）；**测试床真机联调待做** |
| D3 11-03 | 全量回归 + AGENTS.md/cli.md 文档更新 + 发版准备（建议 v1.1.0，feature 级） | ✅ 全量 pytest exit 0 + 文档已更新；**发版（版本号/构建/回归验证）待做** |
| D1 11-01 | 框架核心（spec/registry/pidstore/proctree/manager）+ 单测；openjutsu_runtime；CLI `service` 族 + logs 目标 |
| D2 11-02 | GUI 页 + 退出链/orphan 泛化 + update 链；重烘包到手后测试床联调 |
| D3 11-03 | 全量回归 + AGENTS.md/cli.md 文档更新 + 发版准备（建议 v1.1.0，feature 级） |
| 护栏 | D3 未达 → 整合包带修好的 bat 发布（回执 §4：bat 可用同样依赖重烘），伴生服务随后以启动器更新交付 |

## 15. P2（下个版本，非本期）

1. webui 运行时迁移到 `core/companion/`：`WebuiProcessManager` 变薄壳，`webui.pid` 迁 v2 pidstore（保留一次读 v1 的兼容），五件套退役为 spec + webui_runtime。
2. GUI 两页统一为「伴生服务」页（服务卡片列表）。
3. 顺手修正老 webui stop 兜底链无身份校验的缺口（§8 已在新路径修对）。
4. npm registry 镜像（npmmirror）接入 update 链。

## 16. 风险与未决

| # | 风险 | 缓解 |
|---|---|---|
| 1 | ~~`comfy-api-proxy run` 端口参数名未知~~ | **已解决**（2026-10-31 回传）：`--port` 参数，cli.py:73，默认 8189 |
| 2 | ~~3.13 下 proxy 依赖 wheel 兼容~~ | **已解决**（2026-10-31 回传）：aiohttp 3.14.5 cp313 wheel 实测通过，含 patch 行为级验证（SSE progress×23 + preview×1） |
| 3 | 重烘包 11-01 不到位 | 联调用假进程脚本顶住 e2e；真机验收滑到包到位当日 |
| 4 | `npm start` 的 start 脚本若不止 `next start`（额外参数/预钩子） | 走 `npm-cli.js run start` 保留 npm 语义（不直调 next），树杀覆盖子进程 |
| 5 | GUI 页工期 | 页面砍到最小可用（状态卡+启停+日志+更新），配置项只留端口/开浏览器 |
| 6 | 用户机器同时有系统 node 且版本更老 | PATH **前置**包内 node 目录（不是替换），npm-cli 一律用包内 node 绝对路径调用，不受 PATH 干扰 |
