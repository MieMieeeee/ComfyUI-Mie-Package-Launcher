import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading


def _default_log_root(log_root) -> Path:
    """Resolve a log/launcher directory root.

    When ``log_root`` is provided, use it (best-effort resolved). Otherwise
    delegate to ``utils.paths.resolve_runtime_root``, so the crash-reporting,
    render-guard, and regular logging all agree on where ``launcher/``
    lives.
    """
    try:
        if log_root is not None:
            try:
                return Path(log_root).resolve()
            except Exception:
                return Path.cwd()
        from utils.paths import resolve_runtime_root
        return resolve_runtime_root()
    except Exception:
        return Path.cwd()


def install_logging(app_name: str = "comfyui_launcher", log_root=None) -> logging.Logger:
    """Install rotating file logging and global exception hooks.

    - Writes logs to `launcher/launcher.log` under the provided `log_root` if given;
      otherwise resolves a best-effort root and writes there.
    - Installs `sys.excepthook` and `threading.excepthook` (Python 3.8+) to capture uncaught exceptions.
    - Returns the configured logger for optional direct use.
    """
    logger = logging.getLogger(app_name)
    # Set level from env: COMFYUI_LAUNCHER_DEBUG or COMFYUI_LAUNCHER_LOG_LEVEL
    try:
        # Prefer file-based debug toggle under launcher/is_debug
        try:
            if (Path.cwd() / "launcher" / "is_debug").exists():
                logger.setLevel(logging.DEBUG)
            else:
                level_env = (os.environ.get("COMFYUI_LAUNCHER_LOG_LEVEL") or "").strip().upper()
                debug_env = (os.environ.get("COMFYUI_LAUNCHER_DEBUG") or "").strip().lower()
                if level_env:
                    lvl = getattr(logging, level_env, logging.INFO)
                    logger.setLevel(lvl)
                elif debug_env in ("1", "true", "yes", "on", "debug"):
                    logger.setLevel(logging.DEBUG)
                else:
                    logger.setLevel(logging.INFO)
        except Exception:
            logger.setLevel(logging.INFO)
    except Exception:
        logger.setLevel(logging.INFO)

    try:
        root = _default_log_root(log_root)

        launcher_dir = root / "launcher"
        # Ensure launcher directory exists so that log file can be created
        try:
            launcher_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        log_path = launcher_dir / "launcher.log"
        fh = RotatingFileHandler(str(log_path), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        fh.setFormatter(fmt)
        # Avoid duplicating handlers if called multiple times
        if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
            logger.addHandler(fh)
    except Exception:
        # Fallback: write to current working directory launcher.log if possible
        try:
            fallback = Path.cwd() / "launcher.log"
            logging.basicConfig(
                level=logging.INFO,
                filename=str(fallback),
                filemode="a",
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            )
        except Exception:
            # Last resort: console logging
            try:
                logging.basicConfig(level=logging.INFO)
            except Exception:
                pass

    # Global exception hook (main thread)
    def _excepthook(exc_type, exc, tb):
        try:
            logger.error("Uncaught exception", exc_info=(exc_type, exc, tb))
        except Exception:
            pass

    try:
        sys.excepthook = _excepthook
    except Exception:
        pass

    # Thread exception hook (Python 3.8+)
    if hasattr(threading, "excepthook"):
        def _thread_excepthook(args):
            try:
                logger.error(f"Thread exception: {getattr(args.thread, 'name', 'unknown')}",
                             exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            except Exception:
                pass
        try:
            threading.excepthook = _thread_excepthook
        except Exception:
            pass

    return logger


# ---------------------------------------------------------------------------
# crash reporting: faulthandler + early excepthook -> launcher/crash.log
# ---------------------------------------------------------------------------

_crash_fh = None  # module-level, keep file handle alive so faulthandler doesn't GC it


def _read_build_version(root: Path) -> str:
    """Try to read build_parameters.json version, fall back to 'unknown'."""
    import json as _json
    candidates = (
        root / "build_parameters.json",
        root / "launcher" / "build_parameters.json",
    )
    for p in candidates:
        try:
            if p.exists():
                data = _json.loads(p.read_text(encoding="utf-8"))
                v = (data or {}).get("version")
                if v:
                    return str(v)
        except Exception:
            continue
    return "unknown"


def install_crash_reporting(log_root=None):
    """极早阶段的尽力而为崩溃追踪：原生段错误 + 未捕获异常。

    把崩溃栈写到 ``resolve_runtime_root()/launcher/crash.log``（或调用方
    提供的 root）。全程 try/except，任何一步失败都静默不抛异常——这个模块
    必须能在几乎所有其他系统起来之前就 install 成功。

    写入内容：
      - ``faulthandler.enable(all_threads=True)``：抓 Python 栈。对纯原生
        驱动闪退（栈上没有 Python frame）结果是空的，这本身也是有效证据。
      - 启动头：版本号 + 时间戳 + 提示说明。
      - ``sys.excepthook`` 覆盖：写 traceback 到 crash.log。后续
        ``install_logging`` 会再装自己的 hook，两者并存属正常交接。
    """
    global _crash_fh

    try:
        import faulthandler
        import datetime as _dt
        root = _default_log_root(log_root)
        launcher_dir = root / "launcher"
        try:
            launcher_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        crash_path = launcher_dir / "crash.log"

        # 文件 > 512KB 时清空重开，避免无限增长
        try:
            if crash_path.exists() and crash_path.stat().st_size > 512 * 1024:
                try:
                    crash_path.unlink()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            fh = open(str(crash_path), "a", encoding="utf-8", buffering=1)
        except Exception:
            return
        _crash_fh = fh
        try:
            ts = _dt.datetime.now().isoformat(timespec="seconds")
        except Exception:
            ts = "unknown"
        version = _read_build_version(root)
        try:
            fh.write("=" * 60 + "\n")
            fh.write(f"[startup] ts={ts} launcher_version={version}\n")
            fh.write(
                "[hint] 如果以下没有 Python 栈（纯原生闪退），说明是显卡/GPU 驱动崩溃。"
                "请结合随后出现的 [render_guard] render_mode 行一起判断 OpenGL 渲染路径。\n"
            )
            fh.flush()
        except Exception:
            pass

        try:
            faulthandler.enable(fh, all_threads=True)
        except Exception:
            pass

        # 早期 excepthook：装 install_logging 之前的异常（install_logging 随后会
        # 再装自己的 hook，链式共存）
        def _crash_excepthook(exc_type, exc, tb):
            try:
                import traceback as _tb
                fh.write(f"[uncaught_exception] ts={ts}\n")
                _tb.print_exception(exc_type, exc, tb, file=fh)
                fh.flush()
            except Exception:
                pass
            try:
                sys.__excepthook__(exc_type, exc, tb)
            except Exception:
                pass

        try:
            sys.excepthook = _crash_excepthook
        except Exception:
            pass
    except Exception:
        # 任何步骤失败都静默：崩溃追踪失败不能让启动器起不来
        pass


def append_crash_report(line: str) -> None:
    """追加一行到 crash.log 的句柄（若 crash reporting 已安装）。

    render_guard.begin() 用它在模式确定后补写 render_mode 行，解决
    crash.log 启动头里模式尚未确定的时序问题。全程静默失败。
    """
    global _crash_fh
    try:
        if _crash_fh is None:
            return
        _crash_fh.write(line.rstrip("\n") + "\n")
        _crash_fh.flush()
    except Exception:
        pass