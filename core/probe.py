import os
import locale
import shutil
import re
from pathlib import Path
from utils.common import run_hidden
from urllib.request import urlopen, Request, build_opener, ProxyHandler

try:
    import psutil
except ImportError:
    psutil = None

# is_http_reachable 用的绕代理 opener（懒初始化）
_NO_PROXY_OPENER = None

def find_pids_by_port_safe(port: str):
    try:
        port_int = int(port)
    except (TypeError, ValueError):
        port_int = None
    if psutil and port_int is not None:
        # 快路径：net_connections 一次拿全系统连接表（Windows 上无需管理员即可
        # 拿到 pid）。旧实现逐进程 p.connections()，上千个进程要好几秒且跑在
        # UI 线程（toggle_comfyui 启动前检测），表现为点「一键启动」后按钮卡住。
        try:
            pids = set()
            for conn in psutil.net_connections(kind="inet"):
                if (conn.status == psutil.CONN_LISTEN and conn.laddr
                        and conn.laddr.port == port_int
                        and conn.pid and conn.pid > 0):
                    pids.add(conn.pid)
            if pids:
                return list(pids)
        except Exception:
            pass
        # 兜底：逐进程扫描（部分平台 net_connections 不可用/缺权限时）
        try:
            pids = set()
            for p in psutil.process_iter(attrs=["pid"]):
                try:
                    conns = p.connections(kind='inet')
                    for conn in conns:
                        try:
                            # 只查找 LISTEN 状态的进程，避免误杀连接到该端口的浏览器
                            if (getattr(conn, 'status', None) == 'LISTEN' and
                                getattr(conn, 'laddr', None) and
                                getattr(conn.laddr, 'port', None) == port_int):
                                if p.pid and p.pid > 0:
                                    pids.add(p.pid)
                        except Exception:
                            pass
                except Exception:
                    pass
            if pids:
                return list(pids)
        except Exception:
            pass
    try:
        cmd = ["netstat", "-ano"]
        preferred_enc = locale.getpreferredencoding(False) or "utf-8"
        r = run_hidden(cmd, capture_output=True, text=True, encoding=preferred_enc, errors="ignore")
        if r.returncode == 0 and r.stdout:
            pids = set()
            # 只查找 LISTENING 状态的进程，避免误杀连接到该端口的浏览器
            pattern_tcp = re.compile(rf"^\s*TCP\s+\S+:{port}\s+\S+:\S+\s+LISTENING\s+(\d+)\s*$", re.IGNORECASE)
            for line in r.stdout.splitlines():
                m = pattern_tcp.match(line)
                if m:
                    try:
                        pid_val = int(m.group(1))
                        if pid_val > 0:
                            pids.add(pid_val)
                    except Exception:
                        pass
            return list(pids)
    except Exception:
        pass
    return []

def is_comfyui_pid(app, pid: int) -> bool:
    if psutil:
        try:
            p = psutil.Process(pid)
            try:
                if pid in (os.getpid(), os.getppid()):
                    return False
            except Exception:
                pass
            try:
                cmdline = " ".join(p.cmdline()).lower()
            except Exception:
                cmdline = ""
            try:
                exe = (p.exe() or "").lower()
            except Exception:
                exe = ""
            try:
                cwd = (p.cwd() or "").lower()
            except Exception:
                cwd = ""
            has_segment = (("\\comfyui\\" in cmdline) or ("/comfyui/" in cmdline) or
                           ("\\comfyui\\" in exe) or ("/comfyui/" in exe) or
                           ("\\comfyui\\" in cwd) or ("/comfyui/" in cwd))
            has_main = ("main.py" in cmdline)
            if has_main and (has_segment or ("comfyui" in cmdline) or ("windows-standalone-build" in cmdline)):
                return True
            if has_segment and not ("launcher" in cmdline or "launcher" in exe or "launcher" in cwd):
                return True
        except (Exception):
            pass
    if os.name == 'nt':
        try:
            if getattr(app, "_wmic_available", None) is None:
                app._wmic_available = bool(shutil.which("wmic"))
        except Exception:
            app._wmic_available = False
        if app._wmic_available:
            try:
                # 多环境支持：读激活环境的 comfyui_root
                paths = app.get_active_paths() if hasattr(app, "get_active_paths") \
                    else app.config.get("paths", {})
                base = Path(paths.get("comfyui_root") or ".").resolve()
                comfy_root = str((base / "ComfyUI").resolve()).lower()
            except Exception:
                comfy_root = None
            preferred_enc = locale.getpreferredencoding(False) or "utf-8"
            try:
                r = run_hidden(["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/format:list"], capture_output=True, text=True, encoding=preferred_enc, errors="ignore")
                if r.returncode == 0 and r.stdout:
                    out = r.stdout.lower()
                    if ("main.py" in out and "comfyui" in out) or (comfy_root and comfy_root in out):
                        return True
            except FileNotFoundError:
                app._wmic_available = False
            except Exception:
                pass
    return False

def is_http_reachable(app, _log=False) -> bool:
    """检查 ComfyUI HTTP 服务是否可达"""
    try:
        port = int((app.custom_port.get() or "8188").strip())
    except Exception:
        if _log:
            try:
                app.logger.warning("[probe] is_http_reachable: 端口解析失败")
            except Exception:
                pass
        return False
    # 本机探测必须绕过系统/环境代理：urlopen 默认走 ProxyHandler，若用户配了
    # 系统代理，127.0.0.1 的请求会被发给代理服务器，轻则白等超时（启动前检测
    # 卡在 UI 线程），重则误判不可达。
    global _NO_PROXY_OPENER
    try:
        if _NO_PROXY_OPENER is None:
            _NO_PROXY_OPENER = build_opener(ProxyHandler({}))
        _open = _NO_PROXY_OPENER.open
    except Exception:
        _open = urlopen
    try:
        url = f"http://127.0.0.1:{port}/system_stats"
        req = Request(url, headers={"Accept": "application/json", "User-Agent": "ComfyUI-Launcher"})
        last_err = None
        for timeout in (0.4, 1.5):
            try:
                with _open(req, timeout=timeout) as resp:
                    code = getattr(resp, "status", None)
                    if code is None:
                        try:
                            code = resp.getcode()
                        except Exception:
                            code = None
                    result = code == 200
                    if _log:
                        try:
                            app.logger.info("[probe] is_http_reachable: port=%s, code=%s, result=%s", port, code, result)
                        except Exception:
                            pass
                    return result
            except Exception as e:
                last_err = e
        if _log:
            try:
                reason = getattr(last_err, "reason", None)
                if reason is not None:
                    app.logger.info("[probe] is_http_reachable: port=%s, 失败: %s, reason=%r, msg=%s", port, type(last_err).__name__, reason, str(last_err))
                else:
                    app.logger.info("[probe] is_http_reachable: port=%s, 失败: %s, msg=%s", port, type(last_err).__name__, str(last_err))
            except Exception:
                pass
        return False
    except Exception as e:
        if _log:
            try:
                app.logger.info("[probe] is_http_reachable: port=%s, 失败: %s, msg=%s", port, type(e).__name__, str(e))
            except Exception:
                pass
        return False
