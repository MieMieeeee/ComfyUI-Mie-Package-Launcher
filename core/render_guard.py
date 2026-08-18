"""渲染模式守卫：检测上次异常退出并自动升级渲染模式。

三态 (render mode values):
  - ``auto``  : 默认，使用 Qt 默认渲染（硬件）。
  - ``compat``: 软件渲染 (``QT_OPENGL=software``，要求 opengl32sw.dll 可定位)
  - ``safe``  : ``compat`` + 禁用阴影/透明效果（``LAUNCHER_SAFE_UI=1``）

两级升级阶梯（只升不降，用户手动复位）:
    auto --异常退出--> compat --异常退出--> safe（封顶）

生命周期拆成两个入口, 规避与单实例锁的竞态:
  - ``prepare()`` 幂等，只读 config + 设 env，不碰 ``render_state.json``
    用在 lock 失败（单实例弹窗）路径，以及开发调试时无需状态文件。
  - ``begin()`` 仅在成功拿到互斥锁后调用：读 state → 升级 → 写标记。
  - ``finish()`` 仅在 ``window.run()`` 正常返回后调用（不得放 finally），
    删除状态或在删除失败时写 ``state="clean"`` 哨兵。

对外查询接口全基于环境变量（不依赖本模块初始化顺序），任何位置都可调用：
  - ``current_mode()`` → str
  - ``is_safe_ui()`` → bool
  - ``escalated_this_run()`` → bool
  - ``escalated_detail()`` -> tuple[str, str] | None

纯 stdlib（加上 ``config.manager.atomic_write_json`` 的轻量复用，不 import Qt）。
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_MODES = {"auto", "compat", "safe"}
_ESCALATION_ORDER = ["auto", "compat", "safe"]


# ---------------------------------------------------------------------------
# DLL locator (module-level cache, so prepare called twice only scans once)
# ---------------------------------------------------------------------------

_dll_cached: bool = False
_dll_path: Optional[Path] = None


def _locate_opengl32sw() -> Optional[Path]:
    """Search opengl32sw.dll in candidate locations, cache result forever.

    Returns
    -------
    Path or None
        Absolute path to opengl32sw.dll if found; else None.

    Search order (matches comfyui_launcher_pyqt.py existing DLL resolution habits):
      1. exe 同级 (打包 / release 目录，Windows DLL 搜索优先)
      2. exe 同级/_internal/PyQt5/Qt5/bin (未来 Nuitka onedir 变体)
      3. 当前运行 python 的 site-packages/PyQt5/Qt5/bin 和 PyQt5/Qt/bin
         (开发模式，通过 importlib.util.find_spec 定位 PyQt5 包，不触发 init)
    """
    global _dll_cached, _dll_path
    if _dll_cached:
        return _dll_path
    _dll_cached = True

    candidates: list[Path] = []

    try:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "opengl32sw.dll")
        candidates.append(exe_dir / "_internal" / "PyQt5" / "Qt5" / "bin" / "opengl32sw.dll")
    except Exception:
        pass

    try:
        import importlib.util
        spec = importlib.util.find_spec("PyQt5")
        if spec is not None and getattr(spec, "origin", None):
            pkg = Path(spec.origin).resolve().parent
            candidates.append(pkg / "Qt5" / "bin" / "opengl32sw.dll")
            candidates.append(pkg / "Qt" / "bin" / "opengl32sw.dll")
    except Exception:
        pass

    for c in candidates:
        try:
            if c.exists() and c.is_file():
                _dll_path = c
                break
        except Exception:
            continue
    return _dll_path


# ---------------------------------------------------------------------------
# Runtime root + file path helpers
# ---------------------------------------------------------------------------

def _runtime_root() -> Path:
    try:
        from utils.paths import resolve_runtime_root
        return resolve_runtime_root()
    except Exception:
        return Path.cwd()


def _launcher_dir() -> Path:
    d = _runtime_root() / "launcher"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _config_path() -> Path:
    return _launcher_dir() / "config.json"


def _state_path() -> Path:
    return _launcher_dir() / "render_state.json"


def _atomic_write(target: Path, payload: dict) -> None:
    """原子写 JSON（优先复用 config.manager.atomic_write_json；fallback 自己实现）。"""
    try:
        from config.manager import atomic_write_json
        atomic_write_json(target, payload)
        return
    except Exception:
        pass
    # Fallback: tempfile + replace (mirrors atomic_write_json implementation)
    import os as _os
    import tempfile as _tf
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = _tf.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            _os.fsync(f.fileno())
        _os.replace(tmp_path, target)
    except Exception:
        try:
            if _os.path.exists(tmp_path):
                _os.unlink(tmp_path)
        except Exception:
            pass
        raise


def _read_json(path: Path) -> Optional[dict]:
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_render_mode_from_config() -> str:
    """读 launcher/config.json → ui_settings.render_mode；任何异常退回 auto。"""
    cfg = _read_json(_config_path()) or {}
    ui = cfg.get("ui_settings") if isinstance(cfg, dict) else None
    mode = ui.get("render_mode") if isinstance(ui, dict) else None
    if mode in _VALID_MODES:
        return mode  # type: ignore[return-value]
    return "auto"


def _write_render_mode_to_config(mode: str) -> None:
    """原子升级 ui_settings.render_mode，其他所有字段一字不动保留。

    破坏 config 中的其他字段（proxy/environments/custom 等）是致命的，
    我们采用「完整读 → 仅改这一个 key → 原子写回」策略。

    如果 config 整个缺失或损坏到 `{}` 程度（原子写正常路径下不会发生），
    跳过持久化，避免把「只有 ui_settings.render_mode 这一个键的空壳文件」
    回写给 ConfigManager，让它自己的损坏保护策略生效。
    """
    if mode not in _VALID_MODES:
        mode = "auto"
    cfg = _read_json(_config_path()) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    if not cfg:
        # 空/损坏 config：只进程内升级，不落盘
        return
    ui = cfg.setdefault("ui_settings", {})
    if not isinstance(ui, dict):
        ui = {}
        cfg["ui_settings"] = ui
    ui["render_mode"] = mode
    _atomic_write(_config_path(), cfg)


# ---------------------------------------------------------------------------
# Mode / env application
# ---------------------------------------------------------------------------

def _apply_mode_env(mode: str) -> None:
    """根据 mode 设置三个环境变量：LAUNCHER_RENDER_MODE / LAUNCHER_SAFE_UI / QT_OPENGL。

    不存在的 mode 一律按 auto 处理。opengl32sw.dll 缺失时 ``QT_OPENGL`` 跳过敏捷。
    """
    if mode not in _VALID_MODES:
        mode = "auto"
    os.environ["LAUNCHER_RENDER_MODE"] = mode

    if mode == "safe":
        os.environ["LAUNCHER_SAFE_UI"] = "1"
    else:
        os.environ.pop("LAUNCHER_SAFE_UI", None)

    # compat/safe：DLL 存在时设 software，缺失时不碰 QT_OPENGL
    if mode in ("compat", "safe"):
        if _locate_opengl32sw() is not None:
            os.environ["QT_OPENGL"] = "software"
        # DLL 缺失时保守策略：保留用户自己的 QT_OPENGL，不自作主张清空
    # auto：完全不动 QT_OPENGL，让用户自己设的值或 Qt 默认行为生效


# ---------------------------------------------------------------------------
# Escalation bookkeeping (module level, accessible by escalated_*() probes)
# ---------------------------------------------------------------------------

_escalated: bool = False
_escalation_detail: Optional[Tuple[str, str]] = None  # (from_mode, to_mode)


def _next_mode(mode: str) -> str:
    """升一级，safe 封顶。非法 mode → 先归一 auto → 再升级。"""
    if mode not in _VALID_MODES:
        mode = "auto"
    idx = _ESCALATION_ORDER.index(mode)
    if idx + 1 < len(_ESCALATION_ORDER):
        return _ESCALATION_ORDER[idx + 1]
    return "safe"


# ---------------------------------------------------------------------------
# Public API: pure env queries (import-order safe)
# ---------------------------------------------------------------------------

def current_mode() -> str:
    m = os.environ.get("LAUNCHER_RENDER_MODE", "auto")
    return m if m in _VALID_MODES else "auto"


def is_safe_ui() -> bool:
    return os.environ.get("LAUNCHER_SAFE_UI", "0") == "1"


def escalated_this_run() -> bool:
    return _escalated


def escalated_detail() -> Optional[Tuple[str, str]]:
    return _escalation_detail if _escalated else None


# ---------------------------------------------------------------------------
# Public API: lifecycle
# ---------------------------------------------------------------------------

def prepare() -> None:
    """读 config 并设置模式对应的环境变量。幂等，不写状态文件。

    用于：
      * lock.acquire() 失败分支（单实例弹窗，提前让弹窗的 safe-UI 判断有效）
      * 开发调试 / 单元测试，无需 begin() 的状态标记
    """
    try:
        mode = _read_render_mode_from_config()
        _apply_mode_env(mode)
    except Exception:
        try:
            _apply_mode_env("auto")
        except Exception:
            pass


def _build_version() -> str:
    try:
        from utils.logging import _read_build_version
        v = _read_build_version(_runtime_root())
        return v
    except Exception:
        return "unknown"


def begin() -> None:
    """拿到互斥锁后调用：升级判断 + 写 running 标记 + crash 记录。

    完整步骤：
      1. prepare() 同款读 config 定基础 mode
      2. 读 render_state.json：
         - 不存在 → 不升级
         - state == "clean" → 上次 finish 删除失败但已写哨兵 → 不升级
         - 其他 (running / 垃圾残留 / 任意) → 视为上次异常退出 → 升一级
      3. 升级时：原子写 config + 重新应用 env
      4. 写 state = running
      5. 向 crash.log 追加 mode/escalated 行（解决「crash.log 头部没模式」的时序问题）
    """
    global _escalated, _escalation_detail
    _escalated = False
    _escalation_detail = None

    try:
        base_mode = _read_render_mode_from_config()
        final_mode = base_mode

        st_path = _state_path()
        file_exists = st_path.exists()
        state_obj = _read_json(st_path) if file_exists else None

        if not file_exists:
            # 文件不存在：上次 finish 正常删除。不升级。
            pass
        elif state_obj is None:
            # 文件存在但解析失败 / 不是 JSON：原子写正常路径下不会出现，
            # 说明上次一定异常退出了 → 升级
            new_mode = _next_mode(base_mode)
            if new_mode != base_mode:
                try:
                    _write_render_mode_to_config(new_mode)
                except Exception:
                    pass
                final_mode = new_mode
                _escalated = True
                _escalation_detail = (base_mode, new_mode)
            else:
                _escalated = True
                _escalation_detail = (base_mode, base_mode)
        elif isinstance(state_obj, dict) and state_obj.get("state") == "clean":
            # clean 哨兵：上次 finish 删除失败但成功写了 state=clean
            # 不升级。重写 running 标记即可。
            pass
        else:
            # 非 clean → 异常退出（崩溃 / 断电 / 任务管理器强制结束） → 升级
            new_mode = _next_mode(base_mode)
            if new_mode != base_mode:
                try:
                    _write_render_mode_to_config(new_mode)
                except Exception:
                    # config 写入失败就只进程内升级模式，不把异常扩散到让启动器起不来
                    pass
                final_mode = new_mode
                _escalated = True
                _escalation_detail = (base_mode, new_mode)
            else:
                # 已经是 safe（封顶），但仍把升级标志置 True，这样弹窗提示用户 "检测到异常"
                _escalated = True
                _escalation_detail = (base_mode, base_mode)

        # 模式确定后：重设 env
        _apply_mode_env(final_mode)

        # 写 running 标记
        try:
            state_payload = {
                "mode": final_mode,
                "pid": os.getpid(),
                "started_at": int(datetime.datetime.now().timestamp()),
                "version": _build_version(),
                "state": "running",
            }
            _atomic_write(st_path, state_payload)
        except Exception:
            pass

        # crash.log 补写 render_guard 一行（crash_reporting 装了才写）
        try:
            from utils.logging import append_crash_report
            line = (
                f"[render_guard] mode={final_mode} escalated={_escalated} "
                f"version={state_payload.get('version', 'unknown')}"
            )
            if _escalation_detail:
                f, t = _escalation_detail
                line += f" escalated_from={f} escalated_to={t}"
            append_crash_report(line)
        except Exception:
            pass
    except Exception:
        # 防御性：无论 render_guard 自身出啥错，不让启动器因此失败
        try:
            _apply_mode_env("auto")
        except Exception:
            pass


def finish() -> None:
    """window.run() 正常返回后调用：删状态文件，失败则原子写 state=clean 哨兵。

    不得放在 finally 里（否则 PyQtLauncher 构造抛异常时会误清标记，下次 begin
    看不到异常信号，自动升级就失效了。）
    """
    try:
        st_path = _state_path()
        if not st_path.exists():
            return
        try:
            os.remove(str(st_path))
            return
        except PermissionError:
            pass
        except Exception:
            # 其他 remove 异常（打开句柄 / AV 锁）统一降级为写 clean
            pass
        # 删除失败 → atomic 改写 state=clean
        try:
            existing = _read_json(st_path) or {}
            clean = {
                "mode": existing.get("mode", current_mode()),
                "started_at": existing.get("started_at"),
                "version": existing.get("version", _build_version()),
                "cleaned_at": int(datetime.datetime.now().timestamp()),
                "state": "clean",
            }
            _atomic_write(st_path, clean)
        except Exception:
            pass
    except Exception:
        pass
