import sys
import os
import subprocess
import logging
from pathlib import Path
import atexit
import tempfile
# 尝试导入平台特定的文件锁模块
try:
    import msvcrt
except ImportError:
    msvcrt = None
try:
    import fcntl
except ImportError:
    fcntl = None

# Use the unified launcher logger
logger = logging.getLogger("comfyui_launcher")
# Incremental command id for run_hidden calls
RUNHIDDEN_SEQ = 0

def _truncate_text(text, limit: int) -> str:
    if text is None:
        return ""
    try:
        s = str(text)
    except Exception:
        s = ""
    if limit is None or limit <= 0:
        return s
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n...[truncated {len(s) - limit} chars]"


def _truncate_lines(text, max_lines: int) -> str:
    if text is None:
        return ""
    try:
        s = str(text)
    except Exception:
        s = ""
    lines = s.splitlines()
    if max_lines is None or max_lines <= 0:
        return s
    if len(lines) <= max_lines:
        return s
    return "\n".join(lines[:max_lines]) + f"\n...[truncated {len(lines) - max_lines} lines]"

def _is_debug_file_present() -> bool:
    try:
        return (Path.cwd() / "launcher" / "is_debug").exists()
    except Exception:
        return False


def run_hidden(cmd, **kwargs):
    """Run a subprocess with hidden window on Windows, normal elsewhere.

    Parameters mirror subprocess.run. Commonly used args:
    - cwd: working directory
    - capture_output: bool
    - text: bool
    - timeout: int
    """
    # Windows-specific startup info to hide console window
    if sys.platform.startswith("win"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        # Avoid flashing console windows
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW

    # Prepare logging context
    global RUNHIDDEN_SEQ
    RUNHIDDEN_SEQ += 1
    cmd_id = RUNHIDDEN_SEQ
    cmd_display = cmd if isinstance(cmd, (str, bytes)) else " ".join(map(str, cmd))
    cwd = kwargs.get("cwd")
    capture_output = kwargs.get("capture_output", False)
    text_mode = kwargs.get("text", False)
    timeout = kwargs.get("timeout")
    # Output length limit (default 4000 chars), configurable via env
    try:
        output_limit = int(os.environ.get("COMFYUI_LAUNCHER_LOG_OUTPUT_LIMIT", "4000"))
    except Exception:
        output_limit = 4000
    # Lines limit for non-debug mode (default 10 lines), configurable via env
    try:
        output_lines_limit = int(os.environ.get("COMFYUI_LAUNCHER_LOG_LINES_LIMIT", "10"))
    except Exception:
        output_lines_limit = 10
    # Debug mode toggle via env
    # Debug mode: prefer file flag over environment variable
    debug_mode = _is_debug_file_present() or ((os.environ.get("COMFYUI_LAUNCHER_DEBUG") or "").strip().lower() in ("1", "true", "yes", "on", "debug"))
    # Simple proxy hint for GitHub URLs
    cmd_lower = (cmd_display if isinstance(cmd_display, str) else str(cmd_display)).lower()
    proxy_hint = ("github.com" in cmd_lower) and ("ghproxy" in cmd_lower or "gh-proxy" in cmd_lower)

    # Log command before execution
    try:
        logger.info(
            f"run_hidden[{cmd_id}]: executing cmd=`{cmd_display}` cwd=`{cwd}` "
            f"capture_output={capture_output} text={text_mode} timeout={timeout} proxy_hint={proxy_hint}"
        )
    except Exception:
        # Ensure logging issues never block execution
        pass

    try:
        result = subprocess.run(cmd, **kwargs)
        # Log results after execution
        if capture_output:
            stdout = result.stdout
            stderr = result.stderr
            if not text_mode:
                if isinstance(stdout, (bytes, bytearray)):
                    stdout = stdout.decode("utf-8", errors="ignore")
                if isinstance(stderr, (bytes, bytearray)):
                    stderr = stderr.decode("utf-8", errors="ignore")
            try:
                # Suppress extremely verbose output from `netstat -ano`, log summary only
                if " netstat " in cmd_lower and " -ano" in cmd_lower:
                    try:
                        slines = len((stdout or "").splitlines())
                    except Exception:
                        slines = 0
                    try:
                        elines = len((stderr or "").splitlines())
                    except Exception:
                        elines = 0
                    logger.info(
                        f"run_hidden[{cmd_id}]: rc={result.returncode} (netstat -ano output suppressed) "
                        f"stdout_lines={slines} stderr_lines={elines}"
                    )
                # Special handling for pip show to avoid excessively long logs
                elif " pip show " in cmd_lower or cmd_lower.strip().endswith("pip show"):
                    name_val = None
                    ver_val = None
                    try:
                        for line in (stdout or "").splitlines():
                            l = line.strip()
                            if l.lower().startswith("name:"):
                                name_val = l.split(":", 1)[1].strip()
                            elif l.lower().startswith("version:"):
                                ver_val = l.split(":", 1)[1].strip()
                        logger.info(
                            f"run_hidden[{cmd_id}]: rc={result.returncode} pip_show name={name_val} version={ver_val}"
                        )
                    except Exception:
                        logger.info(
                            f"run_hidden[{cmd_id}]: rc={result.returncode} (pip_show)\nstdout:\n{_truncate_text(stdout, 512)}\nstderr:\n{_truncate_text(stderr, 512)}"
                        )
                else:
                    if debug_mode:
                        logger.info(
                            f"run_hidden[{cmd_id}]: rc={result.returncode}\nstdout:\n{_truncate_text(stdout, output_limit)}\nstderr:\n{_truncate_text(stderr, output_limit)}"
                        )
                    else:
                        logger.info(
                            f"run_hidden[{cmd_id}]: rc={result.returncode}\nstdout:\n{_truncate_lines(stdout, output_lines_limit)}\nstderr:\n{_truncate_lines(stderr, output_lines_limit)}"
                        )
            except Exception:
                pass
        else:
            try:
                logger.info(f"run_hidden[{cmd_id}]: rc={result.returncode}")
            except Exception:
                pass
        return result
    except Exception:
        # Log to the launcher logger with context
        try:
            logger.exception(f"run_hidden[{cmd_id}] failed cmd=`{cmd_display}` cwd=`{cwd}`")
        except Exception:
            pass
        raise


def have_git() -> bool:
    """Return True if git executable is available."""
    try:
        r = run_hidden(["git", "--version"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def is_git_repo(path: str | Path) -> bool:
    """Check if given path is a git repository (has .git)."""
    p = Path(path)
    try:
        return (p / ".git").exists()
    except Exception:
        return False


class SingletonLock:
    def __init__(self, lock_file_name):
        self.lock_file_path = os.path.join(tempfile.gettempdir(), lock_file_name)
        self.lock_file = None

    def acquire(self):
        try:
            self.lock_file = open(self.lock_file_path, 'w')
            if os.name == 'nt' and msvcrt:
                try:
                    msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    self.lock_file.close()
                    self.lock_file = None
                    return False
            elif fcntl:
                try:
                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    self.lock_file.close()
                    self.lock_file = None
                    return False
            else:
                if os.path.exists(self.lock_file_path):
                    self.lock_file.close()
                    self.lock_file = None
                    return False
                else:
                    self.lock_file.write(str(os.getpid()))
                    self.lock_file.flush()
            atexit.register(self.release)
            return True
        except Exception:
            if self.lock_file:
                try:
                    self.lock_file.close()
                except:
                    pass
            self.lock_file = None
            return False

    def release(self):
        if self.lock_file:
            try:
                self.lock_file.close()
                os.unlink(self.lock_file_path)
            except Exception:
                pass
            self.lock_file = None