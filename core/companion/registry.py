"""伴生服务注册表查询: 可用性 / root 解析 / 端口读取.

- root 解析复用 config.migrations 的多环境解析 (resolve_paths_for_env),
  与 webui 的 resolve_active_paths_for_webui 同一血统, 不自造.
- 「可用」= 包根下 root 目录存在且 entry_markers 全部存在. 不做端口/进程探测
  (那是 status 的事), 这层只看文件系统, 足够便宜, 可在 GUI env 切换时调用.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from core.companion.spec import BUILTIN_SERVICES, ServiceSpec


def get(service_id: str) -> ServiceSpec:
    """按 id 取 spec. 未知 id 抛 KeyError (调用方转 CLI 报错)."""
    return BUILTIN_SERVICES[service_id]


def all_specs() -> tuple:
    """全部内置服务, 按 id 排序 (list 输出稳定)."""
    return tuple(BUILTIN_SERVICES[k] for k in sorted(BUILTIN_SERVICES))


def resolve_pkg_root(app_config: Any, env_id: Optional[str] = None) -> Optional[Path]:
    """解析环境包根 (= comfyui_root) 为绝对路径. **伴生服务族唯一的包根解析入口**.

    相对 comfyui_root (如包内 config 的 ".") 的锚定采用**多候选**:
      1. stable_project_root() 锚定 (与 utils.paths.get_comfy_root 同惯例,
         exe 目录 → 源码根 → cwd, 优先含 ComfyUI/main.py 的候选);
      2. Path.cwd() 锚定 (与 utils.paths.webui_path_from_config 同惯例).
    返回第一个候选**目录存在**的锚定结果; 都不存在回落候选 1 (availability
    据实报 missing). 双候选是 2026-10-31 真机验证的教训: 单一 stable 锚定在
    「repo 代码 + cwd 在整合包」等运行模式下会解析到错误目录, 页面误报未安装.
    """
    try:
        from config.migrations import resolve_paths_for_env
        cfg = app_config if isinstance(app_config, dict) else {}
        paths = resolve_paths_for_env(cfg, env_id) if env_id else _resolve_active(cfg)
        root_str = (paths or {}).get("comfyui_root")
        if not root_str:
            return None
        p = Path(root_str)
        if p.is_absolute():
            return p.resolve()
        from utils.paths import stable_project_root
        cands = [stable_project_root() / p, Path.cwd() / p]
        for c in cands:
            if c.exists():
                return c.resolve()
        return cands[0].resolve()
    except Exception:
        return None


def resolve_root(app: Any, spec: ServiceSpec, env_id: Optional[str] = None) -> Optional[Path]:
    """服务 root 的绝对路径: <包根>/<spec.root>. 包根 = 环境 comfyui_root.

    解析不到 (config 缺 / env 不存在回落激活环境仍缺) 返回 None, 调用方按未安装处理.

    注意这里 resolve() 了 (junction/软链指向真实目录) —— 用于「存在性判定」是对的
    (junction 目标的 marker 同样存在). 但**命令行走 raw 形态** (见 resolve_root_raw):
    命令行里带各环境自己的路径, 身份门才能把两个指向同一 junction 目标的环境分开.
    """
    pkg = resolve_pkg_root(getattr(app, "config", None), env_id=env_id)
    if pkg is None:
        return None
    return (pkg / spec.root).resolve()


def resolve_root_raw(app: Any, spec: ServiceSpec, env_id: Optional[str] = None) -> Optional[Path]:
    """服务 root 的**未 resolve** 路径: <包根>/<spec.root>.

    与 resolve_root 的差别只在 junction/软链那一层: 这里保留 <包根>/ComfyUI/
    custom_nodes/<插件名> 这种**带环境信息**的写法, 拼进命令行后身份门 (script_rel)
    才能把「两个环境指向同一份 junction 目标」区分开.
    包根本身是 resolve 过的 (resolve_pkg_root 保证), 所以这里的 raw 只影响末级目录.
    """
    pkg = resolve_pkg_root(getattr(app, "config", None), env_id=env_id)
    if pkg is None:
        return None
    return pkg / spec.root


def _resolve_active(cfg: Any) -> Dict[str, str]:
    from config.migrations import resolve_active_paths
    return resolve_active_paths(cfg if isinstance(cfg, dict) else {}) or {}


def availability(app: Any, spec: ServiceSpec, env_id: Optional[str] = None) -> Dict[str, Any]:
    """服务在 (env 指定的) 环境下是否可用.

    返 {available: bool, root: str|None, missing_markers: [str]}.
    root 目录都不存在时 missing_markers 为 ["<root 整体>"].
    """
    root = resolve_root(app, spec, env_id=env_id)
    if root is None or not root.exists():
        return {"available": False, "root": str(root) if root else None,
                "missing_markers": [spec.root + "/ (目录不存在)"]}
    missing = [m for m in spec.entry_markers if not (root / m).exists()]
    return {"available": not missing, "root": str(root), "missing_markers": missing}


def read_port(app: Any, spec: ServiceSpec, binding) -> int:
    """读 binding.config_key 指向的用户覆盖端口, 缺省回落 default_port.

    config_key 是点路径 ("services.openjutsu.proxy_port"), 逐层下钻;
    任何一层缺失 / 类型不对 / 值非法都回落默认, 不抛.
    """
    cfg = getattr(app, "config", None)
    node: Any = cfg if isinstance(cfg, dict) else {}
    try:
        for part in binding.config_key.split("."):
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(part)
        if node is not None:
            return int(node)
    except Exception:
        pass
    return int(binding.default_port)


def resolved_ports(app: Any, spec: ServiceSpec) -> Dict[str, int]:
    """role -> 生效端口 (全部 PortBinding 应用用户覆盖后)."""
    return {b.role: read_port(app, spec, b) for b in spec.ports}
