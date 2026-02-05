import os
import locale
import shutil
import re
from pathlib import Path
from utils.common import run_hidden
from urllib.request import urlopen, Request

try:
    import psutil
except ImportError:
    psutil = None

def find_pids_by_port_safe(port: str):
    if psutil:
        try:
            pids = set()
            for p in psutil.process_iter(attrs=["pid"]):
                try:
                    conns = p.connections(kind='inet')
                    for conn in conns:
                        try:
                            if getattr(conn, 'laddr', None) and getattr(conn.laddr, 'port', None) == int(port):
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
            pattern_tcp = re.compile(rf"^\s*TCP\s+\S+:{port}\s+\S+:\S+\s+(LISTENING|ESTABLISHED)\s+(\d+)\s*$", re.IGNORECASE)
            for line in r.stdout.splitlines():
                m = pattern_tcp.match(line)
                if m:
                    try:
                        pid_val = int(m.group(2))
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
                paths = app.config.get("paths", {})
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

def is_http_reachable(app) -> bool:
    try:
        port = int((app.custom_port.get() or "8188").strip())
    except Exception:
        return False
    try:
        url = f"http://127.0.0.1:{port}/system_stats"
        req = Request(url, headers={"Accept": "application/json", "User-Agent": "ComfyUI-Launcher"})
        with urlopen(req, timeout=0.4) as resp:
            code = getattr(resp, "status", None)
            if code is None:
                try:
                    code = resp.getcode()
                except Exception:
                    code = None
            return code == 200
    except Exception:
        return False
