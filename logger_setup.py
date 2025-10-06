import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading


def install_logging(app_name: str = "comfyui_launcher") -> logging.Logger:
    """Install rotating file logging and global exception hooks.

    - Writes logs to `logs/launcher.log` next to the EXE / working directory.
    - Installs `sys.excepthook` and `threading.excepthook` (Python 3.8+) to capture uncaught exceptions.
    - Returns the configured logger for optional direct use.
    """
    logger = logging.getLogger(app_name)
    logger.setLevel(logging.INFO)

    try:
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(str(log_dir / "launcher.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        fh.setFormatter(fmt)
        # Avoid duplicating handlers if called multiple times
        if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
            logger.addHandler(fh)
    except Exception:
        # Fallback to basicConfig if file handler setup fails
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