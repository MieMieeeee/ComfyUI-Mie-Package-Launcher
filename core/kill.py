import os
from utils.common import run_hidden

try:
    import psutil
except ImportError:
    psutil = None

def kill_pids(app, pids):
    killed_any = False
    if psutil:
        try:
            procs_to_wait = []
            for pid in pids:
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                    procs_to_wait.append(p)
                except Exception:
                    pass
            if procs_to_wait:
                gone, alive = psutil.wait_procs(procs_to_wait, timeout=3)
                if gone:
                    killed_any = True
                for p in alive:
                    try:
                        p.kill()
                        killed_any = True
                    except Exception:
                        pass
        except Exception:
            pass
    if os.name == 'nt':
        try:
            for pid in pids:
                # 不使用 /T 参数，避免误杀子进程（如浏览器）
                run_hidden(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
            killed_any = True
        except Exception:
            pass
    if not killed_any:
        raise RuntimeError("无法终止目标进程")