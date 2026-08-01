import sys
import os
import subprocess
import logging
from pathlib import Path
import atexit
import tempfile
try:
    import msvcrt
except ImportError:
    msvcrt = None
try:
    import fcntl
except ImportError:
    fcntl = None

# Windows named mutex support for SingletonLock. CreateMutexW on a named
# mutex is the canonical way to enforce a single instance per named object
# across processes on Windows; it cannot be circumvented by the file-truncate
# race that plagues the legacy msvcrt.locking approach.
try:
    import ctypes
    from ctypes import wintypes
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateMutexW = _kernel32.CreateMutexW
    _CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _CreateMutexW.restype = wintypes.HANDLE
    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL
    _GetLastError = _kernel32.GetLastError
    _GetLastError.argtypes = []
    _GetLastError.restype = wintypes.DWORD
    _ERROR_ALREADY_EXISTS = 183
except Exception:
    ctypes = None
    _CreateMutexW = None
    _CloseHandle = None
    _GetLastError = None
    _ERROR_ALREADY_EXISTS = 183

logger = logging.getLogger("comfyui_launcher")
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
    if sys.platform.startswith("win"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        # capture_output 时显式 DEVNULL stdin，避免 GUI 进程 attach console 后
        # 继承到无效句柄，subprocess._get_handles 抛 WinError 6。
        if kwargs.get("capture_output"):
            kwargs.setdefault("stdin", subprocess.DEVNULL)

    # 文本模式编码兜底：调用方只写 text=True 而不指定 encoding 时，Python 默认
    # 用 UTF-8 解码子进程输出。中文 Windows 下 taskkill / wmic / git 等命令的
    # 输出多为 GBK/CP936，非 ASCII 字节（如 0xB2/0xB3）不是合法 UTF-8 起始字节，
    # 会让 subprocess 内部 _readerthread 抛 UnicodeDecodeError（命令实际已执行
    # 成功，rc=0，只是丢了输出）。这里统一注入系统首选编码 + errors=ignore，
    # 与 core/probe.py、core/process_manager.py 已显式指定的写法保持一致。
    # 已显式传 encoding 的调用方不受影响（setdefault 不覆盖）。
    # Force short HTTP timeout on git fetch/pull/clone. Default git
    # http.lowSpeedTime=300 means a flaky proxy / dead DNS hangs the
    # launcher for 5 minutes before failing; users hit this on LAN boxes
    # where gh-proxy is intermittently unreachable. Bumping limit to 15s
    # + 1000 bytes/s means dead links fail out in 15s, and the call
    # surfaces the failure immediately to UI / retry logic.
    if cmd and isinstance(cmd[0], str) and "git" in cmd[0].lower():
        # Token membership rather than substring: substring requires
        # surrounding whitespace which fails when fetch/pull/clone are
        # adjacent to other tokens in the joined cmd line.
        subcmds = {str(c).lower() for c in cmd[1:]}
        if subcmds & {"fetch", "pull", "clone"}:
            env = kwargs.get("env")
            if env is None:
                env = os.environ.copy()
            env.setdefault("GIT_HTTP_LOW_SPEED_TIME", "15")
            env.setdefault("GIT_HTTP_LOW_SPEED_LIMIT", "1000")
            kwargs["env"] = env


    if kwargs.get("text") and "encoding" not in kwargs:
        try:
            import locale as _locale
            kwargs["encoding"] = _locale.getpreferredencoding(False) or "utf-8"
        except Exception:
            kwargs["encoding"] = "utf-8"
        kwargs.setdefault("errors", "ignore")

    global RUNHIDDEN_SEQ
    RUNHIDDEN_SEQ += 1
    cmd_id = RUNHIDDEN_SEQ
    cmd_display = cmd if isinstance(cmd, (str, bytes)) else " ".join(map(str, cmd))
    cwd = kwargs.get("cwd")
    capture_output = kwargs.get("capture_output", False)
    text_mode = kwargs.get("text", False)
    timeout = kwargs.get("timeout")
    try:
        output_limit = int(os.environ.get("COMFYUI_LAUNCHER_LOG_OUTPUT_LIMIT", "4000"))
    except Exception:
        output_limit = 4000
    try:
        output_lines_limit = int(os.environ.get("COMFYUI_LAUNCHER_LOG_LINES_LIMIT", "10"))
    except Exception:
        output_lines_limit = 10
    debug_mode = _is_debug_file_present() or ((os.environ.get("COMFYUI_LAUNCHER_DEBUG") or "").strip().lower() in ("1", "true", "yes", "on", "debug"))
    cmd_lower = (cmd_display if isinstance(cmd_display, str) else str(cmd_display)).lower()
    proxy_hint = ("github.com" in cmd_lower) and ("ghproxy" in cmd_lower or "gh-proxy" in cmd_lower)

    try:
        cmd_low = (cmd_display if isinstance(cmd_display, str) else str(cmd_display)).lower()
        if ("netstat" in cmd_low) and ("-ano" in cmd_low):
            pass
        else:
            logger.info(
                f"run_hidden[{cmd_id}]: executing cmd=`{cmd_display}` cwd=`{cwd}` "
                f"capture_output={capture_output} text={text_mode} timeout={timeout} proxy_hint={proxy_hint}"
            )
    except Exception:
        pass

    try:
        result = subprocess.run(cmd, **kwargs)
        if capture_output:
            stdout = result.stdout
            stderr = result.stderr
            if not text_mode:
                if isinstance(stdout, (bytes, bytearray)):
                    stdout = stdout.decode("utf-8", errors="ignore")
                if isinstance(stderr, (bytes, bytearray)):
                    stderr = stderr.decode("utf-8", errors="ignore")
            try:
                if ("netstat" in cmd_lower) and ("-ano" in cmd_lower):
                    pass
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
        try:
            logger.exception(f"run_hidden[{cmd_id}] failed cmd=`{cmd_display}` cwd=`{cwd}`")
        except Exception:
            pass
        raise


def have_git() -> bool:
    try:
        r = run_hidden(["git", "--version"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def is_git_repo(path: str | Path) -> bool:
    p = Path(path)
    try:
        return (p / ".git").exists()
    except Exception:
        return False


class SingletonLock:
    def __init__(self, lock_file_name):
        self.lock_file_path = os.path.join(tempfile.gettempdir(), lock_file_name)
        self.lock_file = None
        self._mutex_handle = None
        self._mutex_name = "Local\\" + lock_file_name

    def acquire(self):
        # Windows: use a named mutex via CreateMutexW. Two processes
        # calling CreateMutexW with the same name race; the second call returns
        # ERROR_ALREADY_EXISTS, which we treat as acquisition failure.
        if os.name == "nt" and _CreateMutexW is not None:
            try:
                name = self._mutex_name
                handle = _CreateMutexW(None, False, name)
                if not handle:
                    return False
                if _GetLastError() == _ERROR_ALREADY_EXISTS:
                    _CloseHandle(handle)
                    return False
                self._mutex_handle = handle
                atexit.register(self.release)
                return True
            except Exception:
                return False

        # Non-Windows (or ctypes unavailable): use a lock file. The legacy
        # implementation opened with 'w' (truncate) and called msvcrt.locking / fcntl.flock,
        # which has a race when two processes truncate-then-lock. We open with
        # "a+" (append, do not truncate) so an existing holder's file content
        # is preserved and the OS-level lock can fail predictably.
        try:
            self.lock_file = open(self.lock_file_path, "a+")
            if os.name == "nt" and msvcrt:
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
                # Pure fallback: rely on file presence.
                pass
            atexit.register(self.release)
            return True
        except Exception:
            if self.lock_file:
                try:
                    self.lock_file.close()
                except Exception:
                    pass
            self.lock_file = None
            return False

    def release(self):
        if self._mutex_handle is not None:
            try:
                _CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None
        if self.lock_file:
            try:
                self.lock_file.close()
                os.unlink(self.lock_file_path)
            except Exception:
                pass
            self.lock_file = None