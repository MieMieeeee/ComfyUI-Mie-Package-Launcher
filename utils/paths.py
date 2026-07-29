from pathlib import Path
import sys
import os


def get_comfy_root(paths_cfg: dict) -> Path:
    """Resolve the ComfyUI root from a simple paths config dict.

    This helper is used in non-app contexts (e.g. headless tools) where only
    a plain mapping is available. It preserves the existing behaviour of
    resolving the base directory first and then appending ``ComfyUI``.
    """
    try:
        base = Path((paths_cfg or {}).get("comfyui_root") or ".").resolve()
    except Exception:
        base = Path(".").resolve()
    return (base / "ComfyUI").resolve()


def logs_file(comfy_root: Path) -> Path:
    return comfy_root / "user" / "comfyui.log"


def input_dir(comfy_root: Path) -> Path:
    return comfy_root / "input"


def output_dir(comfy_root: Path) -> Path:
    return comfy_root / "output"


def plugins_dir(comfy_root: Path) -> Path:
    return comfy_root / "custom_nodes"


def workflows_dir(comfy_root: Path) -> Path:
    return comfy_root / "user" / "default" / "workflows"


def comfy_root_from_config(app_config: dict | None) -> Path:
    """Resolve the ComfyUI root from a full application config.

    多环境支持：优先用 ``resolve_active_paths`` 解析当前激活环境，
    这样所有传完整 config 的调用者（version_workers / update_service /
    plugin_service / process_manager 等）自动变成环境感知的，无需逐个改。

    - 优先级：``environments[active_env_id]`` → 失配退第一个 → 老的
      ``config["paths"]`` → 默认。
    - 解析出 comfyui_root 后，append ``ComfyUI``。
    - 任何异常退回 ``Path(".").resolve() / "ComfyUI"``。
    """
    try:
        from config.migrations import resolve_active_paths
        paths = resolve_active_paths(app_config) if app_config else {}
    except Exception:
        paths = app_config.get("paths", {}) if isinstance(app_config, dict) else {}
    try:
        base = Path(paths.get("comfyui_root") or ".").resolve()
        root = (base / "ComfyUI").resolve()
    except Exception:
        base = Path(".").resolve()
        root = base / "ComfyUI"
    return root


def resolve_base_root() -> Path:
    """解析运行根目录，用于日志与配置放置。
    优先规则：
    1) 当前工作目录（`Path.cwd()`）
    2) 源码相对目录（`Path(__file__).parent.parent` 或 `Path(__file__).parent`）
    3) EXE 所在目录（`Path(sys.executable).parent`）
    4) `_MEIPASS` 仅用于资源，不参与日志与配置根目录选择

    在上述每个候选中，若检测到 `ComfyUI/main.py`，则优先返回该候选（认为是项目根）。
    否则返回第一个存在的候选路径。
    """
    candidates: list[Path] = []
    try:
        candidates.append(Path.cwd())
    except Exception:
        pass
    try:
        candidates.append(Path(__file__).resolve().parent.parent)
        candidates.append(Path(__file__).resolve().parent)
    except Exception:
        pass
    try:
        candidates.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass

    # 第一轮：优先包含 ComfyUI/main.py 的候选
    for cand in candidates:
        try:
            if cand and cand.exists() and (cand / "ComfyUI" / "main.py").exists():
                return cand
        except Exception:
            pass
    # 第二轮：返回第一个存在的候选（优先 CWD 与源码目录，其次 EXE 目录）
    for cand in candidates:
        try:
            if cand and cand.exists():
                return cand
        except Exception:
            pass
    return Path.cwd()


def resolve_python_exec(comfy_root: Path, configured_path: str) -> Path:
    try:
        # 优先尝试使用配置的路径
        if configured_path:
            p = Path(configured_path)
            # 如果是绝对路径且存在，直接使用
            if p.is_absolute() and p.exists() and p.is_file():
                return p.resolve()
            # 尝试相对于 comfy_root 的父目录解析（因为 configured_path 可能是相对路径）
            try:
                base = comfy_root.resolve().parent
                p_rel = base / configured_path
                if p_rel.exists() and p_rel.is_file():
                    return p_rel.resolve()
            except Exception:
                pass
    except Exception:
        pass

    # 回退到默认逻辑
    try:
        base = comfy_root.resolve().parent
    except Exception:
        base = Path(".").resolve()
    py = base / "python_embeded" / ("python.exe" if os.name == "nt" else "python")
    try:
        return py.resolve()
    except Exception:
        return py


def validate_comfy_root(path: Path) -> bool:
    try:
        p = Path(path)
        return p.exists() and ((p / "main.py").exists() or (p / ".git").exists())
    except Exception:
        return False

# 多 WebUI 项目命名约定 (跟 Comfyui-Workbench-Mie 仓库对齐):
# 期望目录名是 Comfyui-Workbench-Mie, 跟 GitHub repo 同名 (混大小写). 改这个
# 常量要同步更新 AGENTS.md / docs/cli.md 跟 GUI 提示文案.
WEBUI_DIR_NAME = "Comfyui-Workbench-Mie"


def webui_path_from_config(app_config: dict | None, env_id: str | None = None) -> Path | None:
    """返回 WebUI 期望安装路径 (<comfyui_root>/Comfyui-Workbench-Mie).

    - 路径是否存在都返回 (用于 "未安装" 状态显示 期望路径).
    - 多环境支持: env_id 非 None 时用 resolve_paths_for_env, 否则走激活环境.
    - 任何异常 / comfyui_root 缺失 -> 返回 None, 调用方按未安装处理.
    """
    try:
        cfg = app_config if isinstance(app_config, dict) else {}
        from config.migrations import resolve_paths_for_env, resolve_active_paths
        if env_id:
            paths = resolve_paths_for_env(cfg, env_id) or {}
        else:
            paths = resolve_active_paths(cfg) or {}
    except Exception:
        paths = {}
    comfy_root = (paths or {}).get("comfyui_root")
    if not comfy_root:
        return None
    try:
        base = Path(comfy_root).resolve()
    except Exception:
        return None
    return base / WEBUI_DIR_NAME
