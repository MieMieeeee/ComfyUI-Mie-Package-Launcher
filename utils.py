import sys
import os
import subprocess
import logging
from pathlib import Path

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
                logger.info(
                    f"run_hidden[{cmd_id}]: rc={result.returncode}\nstdout:\n{_truncate_text(stdout, output_limit)}\nstderr:\n{_truncate_text(stderr, output_limit)}"
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