from pathlib import Path
import sys
import os

def stable_project_root() -> Path:
    """Return a stable project root for resolving relative config paths.

    Why this exists: a relative ``comfyui_root`` like "." historically
    resolved via ``Path(".").resolve()`` which expands against the
    process CWD. When the launcher.exe is started from a different
    cwd (cmd shell, Task Scheduler, file manager with shifted cwd),
    that expansion lands on the wrong directory and the resulting
    python path is bogus -- e.g. ``F:\\python_embeded\\python.exe``
    instead of the bundled ``<launcher_dir>\\python_embeded\\python.exe``.

    Strategy (按优先级):
    1. EXE 目录 (Path(sys.executable).parent) -- PyInstaller 打包后
    2. 源码根目录 (Path(__file__).parent.parent) -- 源码运行
    3. CWD -- 最后兜底
    并优先选第一个含有 ``ComfyUI/main.py`` 的候选 (项目根目录 marker).

    这样即便用户从 cmd shell 启动 (cwd=F:\\), launcher 仍然认 F:\\ComfyUI_Mie_2026_V9.0
    作为它的项目根, "." 这样的相对配置就能正确解析到该目录里的
    python_embeded/.
    """
    try:
        exe = Path(sys.executable).resolve().parent
    except Exception:
        exe = None
    try:
        src = Path(__file__).resolve().parent.parent
    except Exception:
        src = None
    try:
        cwd = Path.cwd()
    except Exception:
        cwd = None
    candidates = [c for c in (exe, src, cwd) if c is not None]
    # First pass: prefer a candidate that has ComfyUI/main.py (项目根 marker)
    for cand in candidates:
        try:
            if cand.exists() and (cand / "ComfyUI" / "main.py").exists():
                return cand
        except Exception:
            pass
    # Fallback: first existing candidate
    for cand in candidates:
        try:
            if cand.exists():
                return cand
        except Exception:
            pass
    return Path.cwd()



def get_comfy_root(paths_cfg: dict) -> Path:
    """Resolve the ComfyUI root from a simple paths config dict.

    Relative ``comfyui_root`` (e.g. ``"."`` or ``"subdir/foo"``) is anchored
    to ``stable_project_root()`` rather than ``Path.cwd()``: launching the
    launcher.exe from a different cwd (cmd shell / Task Scheduler / etc)
    would otherwise make ``"."`` drift to the wrong directory and resolve to
    a nonexistent ``python_embeded/python.exe``. See ``stable_project_root``.
    """
    try:
        comfy_root_str = (paths_cfg or {}).get("comfyui_root") or "."
        cr = Path(comfy_root_str)
        if cr.is_absolute():
            base = cr.resolve()
        else:
            base = (stable_project_root() / comfy_root_str).resolve()
    except Exception:
        base = stable_project_root()
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
        comfy_root_str = paths.get("comfyui_root") or "."
        cr = Path(comfy_root_str)
        if cr.is_absolute():
            base = cr.resolve()
        else:
            # Relative comfyui_root: anchor to launcher project root, not CWD.
            base = (stable_project_root() / comfy_root_str).resolve()
        root = (base / "ComfyUI").resolve()
    except Exception:
        base = stable_project_root()
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
    """返回启动 webui 用的 python.exe 路径.

    优先级 (按顺序, 第一个能用的赢):
    1. configured_path 是绝对路径 + 存在 -> 直接用它.
    2. configured_path 相对 -> 优先按 stable_project_root() 解析 (避免 CWD 漂移);
       若失败再退到 comfy_root.parent (老路径, 跟 v8-migrate 兼容).
    3. 最终 fallback: stable_project_root() / python_embeded/python.exe (launcher
       自带的 python; 不再用 comfy_root.parent, 后者在 comfyui_root="."
       时常因 CWD 错配而崩 -- 例如 fall 到 F:/python_embeded/python.exe 这种不存在的路径,
       而真正的 python 在 launcher 自己目录的 python_embeded/ 里.)
    """
    try:
        if configured_path:
            p = Path(configured_path)
            if p.is_absolute() and p.exists() and p.is_file():
                return p.resolve()
            # 相对路径: 优先按 launcher 的项目根解析.
            try:
                base = stable_project_root()
                p_rel = base / configured_path
                if p_rel.exists() and p_rel.is_file():
                    return p_rel.resolve()
            except Exception:
                pass
            # 兼容老路径: 也试 comfy_root.parent.
            try:
                base = comfy_root.resolve().parent
                p_rel = base / configured_path
                if p_rel.exists() and p_rel.is_file():
                    return p_rel.resolve()
            except Exception:
                pass
    except Exception:
        pass

    # 最终回退: launcher 自带的 python_embeded/python.exe (not comfy_root.parent)
    try:
        base = stable_project_root()
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


def resolve_runtime_root() -> Path:
    """Launcher 自身的运行根目录（用于 crash.log / render_state.json /
    launcher/ 子目录定位。

    与 ``stable_project_root`` / ``resolve_base_root`` 的关键区别：
    **绝对不按 ``ComfyUI/main.py`` marker 选目录。当 launcher 和
    单独安装在 C:\\ 盘而整合包在 D:\\ 盘时，launcher 的配置、日志必须
    跟着 launcher 自身走，不能追着整合包目录漂移。

    候选顺序逐行移植自 ``utils/logging.py`` install_logging(None)`` 的
    48-92 行逻辑，三处一致。保证 logging / render_guard / crash reporting
    对 ``launcher/`` 目录的答案一致。
    """
    candidates: list[Path] = []

    # Nuitka: __compiled__ 存在 → sys.argv[0] 主 exe 目录
    try:
        __compiled__  # type: ignore[has-type]  # noqa: F821
        is_nuitka = True
    except NameError:
        is_nuitka = False
    if is_nuitka:
        try:
            candidates.append(Path(sys.argv[0]).resolve().parent)
        except Exception:
            pass

    # PyInstaller: sys._MEIPASS
    try:
        from sys import _MEIPASS  # type: ignore
        if _MEIPASS:
            candidates.append(Path(_MEIPASS))
    except Exception:
        pass

    # 源码目录（__file__ 父父目录）
    try:
        candidates.append(Path(__file__).resolve().parent.parent)
    except Exception:
        pass

    # 可执行文件目录（PyInstaller 时是 exe，Nuitka 时是 python.exe）
    try:
        candidates.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass

    candidates.append(Path.cwd())

    root: Path | None = None
    for cand in candidates:
        try:
            if cand and cand.exists():
                root = cand
                break
        except Exception:
            pass
    return root or Path.cwd()
