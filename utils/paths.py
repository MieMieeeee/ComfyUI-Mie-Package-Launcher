from pathlib import Path
import sys
import os


def get_comfy_root(paths_cfg: dict) -> Path:
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
    py = base / "python_embeded" / ("python.exe" if os.name == 'nt' else "python")
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
