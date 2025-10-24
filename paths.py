from pathlib import Path
import sys
import os


def get_comfy_root(paths_cfg: dict) -> Path:
    """Resolve ComfyUI root from config paths.
    Fallback to 'ComfyUI' relative directory if missing.
    """
    try:
        raw = (paths_cfg or {}).get("comfyui_path", "ComfyUI")
    except Exception:
        raw = "ComfyUI"
    p = Path(raw)
    try:
        return p.resolve()
    except Exception:
        return p


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

# ---------- 新增：根目录与 Python 解析 ----------

def resolve_base_root() -> Path:
    """选择合适的项目根目录，优先包含 ComfyUI/main.py 的候选。
    候选来源：launcher 上级、PyInstaller _MEIPASS、exe 所在目录、当前工作目录。
    """
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parent)
        # launcher 上级（项目根）
        candidates.append(Path(__file__).resolve().parent.parent)
    except Exception:
        pass
    try:
        from sys import _MEIPASS  # type: ignore
        if _MEIPASS:
            candidates.append(Path(_MEIPASS))
    except Exception:
        pass
    try:
        candidates.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    candidates.append(Path.cwd())

    # 第一轮：优先包含 ComfyUI/main.py
    for cand in candidates:
        try:
            if cand and cand.exists() and (cand / "ComfyUI" / "main.py").exists():
                return cand
        except Exception:
            pass
    # 第二轮：返回第一个存在的路径
    for cand in candidates:
        try:
            if cand and cand.exists():
                return cand
        except Exception:
            pass
    return Path.cwd()


def resolve_python_exec(comfy_root: Path, configured_path: str) -> Path:
    """根据 ComfyUI 路径与配置解析 Python 可执行文件。
    优先顺序：绝对路径、当前工作目录相对、launcher 上级、ComfyUI 同级便携 Python、默认配置值。
    """
    cfg_path = Path(configured_path or ("python_embeded/python.exe" if os.name == 'nt' else "python_embeded/python"))
    candidates: list[Path] = []
    if cfg_path.is_absolute():
        candidates.append(cfg_path)
    candidates.append(Path.cwd() / cfg_path)
    # launcher 上级常见位置
    try:
        app_root = Path(__file__).resolve().parent.parent
        candidates.append(app_root / cfg_path)
        candidates.append(app_root / "python_embeded" / ("python.exe" if os.name == 'nt' else "python"))
    except Exception:
        pass
    # ComfyUI 同级便携 Python
    try:
        candidates.append(comfy_root.resolve().parent / "python_embeded" / ("python.exe" if os.name == 'nt' else "python"))
    except Exception:
        pass
    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:
            pass
    return cfg_path


def validate_comfy_root(path: Path) -> bool:
    try:
        p = Path(path)
        return p.exists() and ((p / "main.py").exists() or (p / ".git").exists())
    except Exception:
        return False