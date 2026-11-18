"""伴生服务声明模型 + 内置注册表.

设计约束 (用户 2026-10-31 拍板):
  - 服务 100% 限定在整合包路径 (环境 comfyui_root) 下, root 字段是相对包根的目录名,
    不支持绝对路径 / 包外位置.
  - 声明是**代码级注册表**, 不进用户 config; 用户 config 只存覆盖项 (端口等, 见 registry.read_port).
  - 服务是生命周期单元: start/ready/stop 对外原子, 内部一条还是两条命令是 runtime 的事.

webui 条目是名义条目 (runtime="webui-legacy"): `service ... webui` 转发老五件套,
本期不在本框架上跑 (strangler, 见 docs/companion-services-design.md §2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Tuple


@dataclass(frozen=True)
class IdentityRule:
    """PID 身份门规则 (防 PID 复用误报/误杀).

    背景: webui.pid 曾被无关进程 (Grok Bot.exe) 复用, is_running 误报一个多月,
    stop 差点误杀 (2026-10-03 事故). 所以伴生服务的 pidstore 读取 / 端口清残
    全部要求身份校验, 本类就是校验规则的声明形式.

    匹配语义 (proctree.identity_matches 实现):
      - cmdline_all: joined cmdline (lower) 必须包含**每一个**子串
      - cmdline_any: 必须包含**至少一个**子串 (空 tuple = 不检查)
      - cwd_under_root: 进程 cwd 必须在服务 root 目录之下 (动态路径, 匹配时传入)
      - script_rel: 入口脚本相对 root 的路径 (如 "webapp/__main__.py"). 进程命令行里
        必须出现 "<root>/<script_rel>" —— 用来把「同一个包根下的多个入口」和
        「多个环境指向同一份 junction 目标」区分开: 命令行里带的是**该环境自己的**
        路径 (启动时按未 resolve 的 root 拼), 因此两个环境即使指向同一个 junction
        目标, 命令行文本仍然不同. root 的 raw / realpath 两种形态都接受
        (Windows 上 cwd 可能被系统归一化成 realpath).
    所有给出的条件必须同时满足; 任一条件探测失败 (如 psutil 拿不到 cwd) 按**不匹配**处理
    (保守方向: 漏杀好过误杀).
    """

    cmdline_all: Tuple[str, ...] = ()
    cmdline_any: Tuple[str, ...] = ()
    cwd_under_root: bool = False
    script_rel: str = ""


@dataclass(frozen=True)
class PortBinding:
    """服务监听的一个端口.

    role: 语义角色 ("proxy" / "app"), 与 IdentityRule 的 key / pidstore 的
          processes[].role 对齐.
    default_port: 声明默认端口.
    config_key: 用户覆盖用的 config 点路径 ("services.openjutsu.proxy_port"),
                读法见 registry.read_port (缺省 / 块缺失都回落 default_port).
    ready: 就绪判据. 本期全部 "port" (start 路径端口优先不做 HTTP —— 既有拍板,
           且 proxy 根路径返 404 本就不能按 HTTP 语义判). "http" 保留给 P2 的
           webui 迁移 (其老实现是 GET / 返 200-499).
    """

    role: str
    default_port: int
    config_key: str
    ready: str = "port"


@dataclass(frozen=True)
class ServiceSpec:
    id: str
    """稳定标识 (CLI `service <action> <id>` / pidstore service_id)."""

    name: str
    """GUI 显示名."""

    root: str
    """相对包根 (= 环境 comfyui_root) 的服务目录名. 只允许相对, 见模块 docstring."""

    entry_markers: Tuple[str, ...]
    """root 下必须全部存在的文件/目录, 存在才算「已安装」(退出码 7 的判定)."""

    ports: Tuple[PortBinding, ...]
    identity: Mapping[str, IdentityRule] = field(default_factory=dict)
    """role -> 身份规则. key 应覆盖所有长驻进程的 role."""

    requires_comfyui: bool = False
    """True: start 前 ComfyUI 必须在跑 (CLI 退出码 6, 不强启动; 自动起是 GUI 的事)."""

    browser_url_role: str | None = None
    """就绪后浏览器打开哪个 role 的端口 (None = 不开)."""

    runtime: str = "openjutsu"
    """运行时分流: "openjutsu" 走 core/companion/openjutsu_runtime;
    "h3-engine" 走 core/companion/h3_runtime;
    "webui-legacy" 转发老五件套 (本期 webui 的形态)."""

    repo_url: str = ""
    """「下载安装」用的 git 地址 (空 = 该服务不提供下载安装, 未安装就是未安装)."""

    mirrors: Mapping[str, str] = field(default_factory=dict)
    """仓库镜像表 ({"gitee": ..., "github": ...}); 空 = 只有 repo_url 一个源."""

    requirements_file: str = ""
    """依赖清单相对 root 的路径 (如 "requirements.txt"); 空 = 该服务不装 pip 依赖."""

    protected_paths: Tuple[str, ...] = ()
    """root 下**不能被 git 跟踪**的用户数据 (相对 root).

    更新走 fetch + reset --hard, 而 reset --hard 会把**被跟踪**的文件还原回仓库
    版本 —— 用户的资产库 / 密钥若被跟踪, 更新一次就没了. installer.pull_service
    更新前会先体检, 发现被跟踪就自动 `git rm --cached` 摘出索引.
    """


# ---------------- 内置注册表 ----------------

WEBUI_SPEC = ServiceSpec(
    id="webui",
    name="WebUI 工作台",
    root="Comfyui-Workbench-Mie",
    entry_markers=("app/flask_app.py",),
    ports=(PortBinding(role="main", default_port=8199,
                       config_key="webui_options.port", ready="http"),),
    identity={"main": IdentityRule(cmdline_any=("flask_app",))},
    requires_comfyui=False,
    browser_url_role=None,   # webui 老路径自己管浏览器打开 (browser_open_mode)
    runtime="webui-legacy",
)

OPENJUTSU_SPEC = ServiceSpec(
    id="openjutsu",
    name="openjutsu 视频换角色",
    root="openjutsu",
    entry_markers=("package.json", "patch_proxy.py"),
    ports=(
        PortBinding(role="proxy", default_port=8197,
                    config_key="services.openjutsu.proxy_port"),
        # 前端默认 8198 (2026-10-31 真机验证后用户拍板): 与 8188(ComfyUI)/
        # 8197(proxy)/8199(webui) 成族, 且避开 Next.js 惯用的 3000 (易与用户
        # 本机其他 dev server 撞车). PORT env 注入, Next.js 标准可配.
        PortBinding(role="app", default_port=8198,
                    config_key="services.openjutsu.app_port"),
    ),
    identity={
        # proxy: python -c "...from comfy_api_proxy.cli import main..." → cmdline 含 comfy_api_proxy
        "proxy": IdentityRule(cmdline_all=("comfy_api_proxy",)),
        # app: node npm-cli.js run start (npm 再 spawn next start); cmdline/cwd 双条件防误判
        "app": IdentityRule(cmdline_any=("npm-cli.js", "next"), cwd_under_root=True),
    },
    requires_comfyui=True,
    browser_url_role="app",
    runtime="openjutsu",
)

H3_ENGINE_SPEC = ServiceSpec(
    id="h3-engine",
    name="H3 短剧工作台",
    # H3 Engine 是 ComfyUI 的自定义节点, 装在 <包根>/ComfyUI/custom_nodes/ 下.
    # root 允许是相对包根的多级路径 (硬约束只有「相对 + 在包内」).
    root="ComfyUI/custom_nodes/ComfyUI-Mie-H3-Engine",
    entry_markers=("webapp/__main__.py",),
    ports=(
        # 8200 (2026-11-18 引擎侧统一): 与 8188(ComfyUI)/8197/8198(openjutsu)/
        # 8199(WebUI 工作台) 成族, 且避开 H3 引擎旧默认 8199 —— 8199 是启动器
        # 自己的 WebUI 工作台端口, 两边撞端口会让 ComfyUI 侧的节点误判「已在跑」.
        PortBinding(role="app", default_port=8200,
                    config_key="services.h3-engine.port"),
    ),
    identity={
        # 入口是 webapp/__main__.py: 命令行里带「该环境自己的」路径
        # (启动时按未 resolve 的 root 拼) → 多环境指向同一 junction 目标也能分开.
        "app": IdentityRule(script_rel="webapp/__main__.py", cwd_under_root=True),
    },
    # 工作台可在 ComfyUI 离线时管理资产/剧本, 只有提交渲染才需要 ComfyUI
    # → 不要求 ComfyUI 在跑 (也就不会被 orphan_killer 顺手停掉).
    requires_comfyui=False,
    browser_url_role="app",
    runtime="h3-engine",
    # 「下载安装」: clone 引擎本体 + 装它的 pip 依赖 (进该环境的 embedded python).
    # **不装 MieNodes** —— 引擎的资产库归自己 (asset_library), MieNodes 只是
    # 老布局下资产曾经待过的地方.
    repo_url="https://github.com/MieMieeeee/ComfyUI-Mie-H3-Engine.git",
    mirrors={"github": "https://github.com/MieMieeeee/ComfyUI-Mie-H3-Engine.git"},
    requirements_file="requirements.txt",
    # 用户的角色/场景/分镜与 LLM 密钥住在插件目录里 —— 更新时绝不能被覆盖
    protected_paths=("asset_library", "mie_llm_keys.json"),
)

BUILTIN_SERVICES = {
    WEBUI_SPEC.id: WEBUI_SPEC,
    OPENJUTSU_SPEC.id: OPENJUTSU_SPEC,
    H3_ENGINE_SPEC.id: H3_ENGINE_SPEC,
}
"""内置服务注册表. 新增内置服务 = 在此加一个 ServiceSpec + 对应 runtime 实现."""
