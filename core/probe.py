import os
import locale
import shutil
import re
import time
from pathlib import Path
from utils.common import run_hidden
from urllib.request import urlopen, Request, build_opener, ProxyHandler

try:
    import psutil
except ImportError:
    psutil = None

# is_http_reachable 用的绕代理 opener（懒初始化）
_NO_PROXY_OPENER = None

# 端口 → 占用 pid 的短缓存。Windows 上没有 psutil（或 net_connections 因权限
# 失败）时会退到 spawn `netstat -ano` —— 那是几百毫秒的同步子进程。一次状态
# 查询里常常要查好几个端口/好几次（收养 + 端口就绪复核），同端口短时间内的
# 结果直接复用，别把 netstat 跑成串。
_PORT_PID_CACHE: dict = {}
_PORT_PID_CACHE_TTL = 3.0


def _port_cache_get(port: str):
    try:
        hit = _PORT_PID_CACHE.get(str(port))
        if not hit:
            return None
        ts, pids = hit
        if (time.monotonic() - ts) > _PORT_PID_CACHE_TTL:
            _PORT_PID_CACHE.pop(str(port), None)
            return None
        return list(pids)
    except Exception:
        return None


def _port_cache_put(port: str, pids):
    try:
        _PORT_PID_CACHE[str(port)] = (time.monotonic(), list(pids or []))
    except Exception:
        pass


def clear_port_pid_cache():
    """清空端口→pid 缓存（测试隔离 / 端口状态剧变时用）。"""
    try:
        _PORT_PID_CACHE.clear()
    except Exception:
        pass


def find_pids_by_port_safe(port: str):
    cached = _port_cache_get(port)
    if cached is not None:
        return cached
    result = _find_pids_by_port_safe_uncached(port)
    _port_cache_put(port, result)
    return result


def _find_pids_by_port_safe_uncached(port: str):
    try:
        port_int = int(port)
    except (TypeError, ValueError):
        port_int = None
    if psutil and port_int is not None:
        # 快路径：net_connections 一次拿全系统连接表。**Windows 上非管理员进程
        # 会抛 AccessDenied**（psutil 需要 SeDebugPrivilege 才能列出全部连接的
        # 归属进程）—— 这时不要急着退到「逐进程 p.connections() 扫几千个进程」
        # （最慢的一条路，实测几秒），而是先走下面的 netstat（一次拿全表）。
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
    # 第二快：netstat 一次拿全表（不依赖 psutil 权限）。比「逐进程扫几千个
    # p.connections()」快一个数量级 —— 非管理员环境下 psutil.net_connections
    # 抛 AccessDenied 时，这里是首选兜底（2026-11-19 实测：Win11 24H2 非管理员
    # 走 netstat 是几百 ms，走逐进程扫描是几秒）。
    try:
        cmd = ["netstat", "-ano"]
        preferred_enc = locale.getpreferredencoding(False) or "utf-8"
        # timeout 兜底: netstat 在连接表极大时可能慢, 别让调用方无限期等
        r = run_hidden(cmd, capture_output=True, text=True, encoding=preferred_enc,
                      errors="ignore", timeout=10)
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
    # 最慢兜底：逐进程扫 p.connections()（上千个进程，每个都要枚举自己的
    # 连接表）—— 只在上面两条都拿不到时用。实测几秒级。
    if psutil and port_int is not None:
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
    return []

def _cmdline_via_windows_query(app, pid: int) -> str:
    """Windows 下查进程命令行：wmic（老系统）→ PowerShell CIM（兜底的兜底）。

    背景（2026-11-07 V9 机器事故）：身份门 is_comfyui_pid 依赖 psutil，而
    psutil 曾被注释出 requirements 没进 exe；Windows 11 24H2+ 又移除了
    wmic——两条路全断后身份校验恒 False，进程收养形同虚设，stop 沦为
    「候选集全杀」危险兜底 + 人工 taskkill。CIM（Get-CimInstance
    Win32_Process）是 wmic 的官方继任，PowerShell ≥3.0 的 Windows 都有；
    单次查询 ~0.5s，只在身份校验冷路径（端口被占 / 收养 / 停止兜底）触发，
    正常启动（端口空闲）不走这里。

    返回命令行文本（可能多行 / 空串）；查不到返回 ""。
    """
    try:
        if getattr(app, "_wmic_available", None) is None:
            app._wmic_available = bool(shutil.which("wmic"))
    except Exception:
        try:
            app._wmic_available = False
        except Exception:
            pass
    preferred_enc = locale.getpreferredencoding(False) or "utf-8"
    if app._wmic_available:
        try:
            r = run_hidden(
                ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/format:list"],
                capture_output=True, text=True, encoding=preferred_enc, errors="ignore",
                timeout=8,
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout
            # wmic 在场但查询失败（策略禁用 / 输出为空）→ 落到 CIM
        except FileNotFoundError:
            try:
                app._wmic_available = False
            except Exception:
                pass
        except Exception:
            pass
    # CIM 兜底：wmic 缺席（Win11 24H2+ 移除）或查询失败时
    ps_script = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"
    try:
        r = run_hidden(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", ps_script],
            capture_output=True, text=True, encoding=preferred_enc, errors="ignore",
            timeout=8,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except Exception:
        pass
    return ""


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
        # 自 PID 排除（与 psutil 分支同语义）：launcher exe 路径本身含
        # 「...\ComfyUI启动器.exe」，comfy_root 子串规则会误命中自己
        try:
            if pid == os.getpid():
                return False
        except Exception:
            pass
        # 多环境支持：读激活环境的 comfyui_root
        try:
            paths = app.get_active_paths() if hasattr(app, "get_active_paths") \
                else app.config.get("paths", {})
            base = Path(paths.get("comfyui_root") or ".").resolve()
            comfy_root = str((base / "ComfyUI").resolve()).lower()
        except Exception:
            comfy_root = None
        out = _cmdline_via_windows_query(app, pid)
        if out:
            lowered = out.lower()
            if ("main.py" in lowered and "comfyui" in lowered) or (comfy_root and comfy_root in lowered):
                return True
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
