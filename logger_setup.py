import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading


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
        # Prefer a caller-provided root (e.g., the parent of ComfyUI) for deterministic placement
        if log_root is not None:
            try:
                root = Path(log_root).resolve()
            except Exception:
                root = Path.cwd()
        else:
            # Best-effort root detection when not provided
            root_candidates = []
            try:
                root_candidates.append(Path(__file__).resolve().parent.parent)
            except Exception:
                pass
            try:
                from sys import _MEIPASS  # type: ignore
                if _MEIPASS:
                    root_candidates.append(Path(_MEIPASS))
            except Exception:
                pass
            try:
                root_candidates.append(Path(sys.executable).resolve().parent)
            except Exception:
                pass
            root_candidates.append(Path.cwd())
            root = None
            for cand in root_candidates:
                try:
                    if cand and cand.exists():
                        root = cand
                        break
                except Exception:
                    pass
            root = root or Path.cwd()

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