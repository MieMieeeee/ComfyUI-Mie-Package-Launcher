import os
import subprocess
from utils.common import run_hidden

try:
    import psutil
except ImportError:
    psutil = None

def stop(app, pm):
    try:
        app.logger.info("用户点击停止：开始关闭 ComfyUI")
    except Exception:
        pass
    app._launching = False
    killed = False
    if getattr(pm, "comfyui_process", None) and pm.comfyui_process.poll() is None:
        pid_str = str(pm.comfyui_process.pid)
        if os.name == 'nt':
            try:
                r_soft = run_hidden(["taskkill", "/PID", pid_str, "/T"], capture_output=True, text=True)
                try:
                    app.logger.info("停止跟踪进程: taskkill /T rc=%s", getattr(r_soft, 'returncode', 'N/A'))
                except Exception:
                    pass
                if r_soft.returncode == 0:
                    killed = True
                else:
                    r_hard = run_hidden(["taskkill", "/PID", pid_str, "/T", "/F"], capture_output=True, text=True)
                    try:
                        app.logger.info("停止跟踪进程: taskkill /F rc=%s", getattr(r_hard, 'returncode', 'N/A'))
                    except Exception:
                        pass
                    if r_hard.returncode == 0:
                        killed = True
                    else:
                        try:
                            pm.comfyui_process.terminate()
                            pm.comfyui_process.wait(timeout=5)
                            killed = True
                        except subprocess.TimeoutExpired:
                            pm.comfyui_process.kill()
                            killed = True
                        except Exception as e3:
                            try:
                                from PyQt5 import QtWidgets
                                app.root.after(0, lambda: QtWidgets.QMessageBox.critical(None, "错误", f"停止失败: {e3}"))
                            except Exception:
                                pass
            except Exception:
                try:
                    pm.comfyui_process.terminate()
                    pm.comfyui_process.wait(timeout=5)
                    killed = True
                except subprocess.TimeoutExpired:
                    pm.comfyui_process.kill()
                    killed = True
                except Exception as e2:
                    try:
                        from PyQt5 import QtWidgets
                        app.root.after(0, lambda: QtWidgets.QMessageBox.critical(None, "错误", f"停止失败: {e2}"))
                    except Exception:
                        pass
        else:
            try:
                pm.comfyui_process.terminate()
                pm.comfyui_process.wait(timeout=5)
                killed = True
            except subprocess.TimeoutExpired:
                pm.comfyui_process.kill()
                killed = True
            except Exception as e:
                try:
                    from PyQt5 import QtWidgets
                    app.root.after(0, lambda: QtWidgets.QMessageBox.critical(None, "错误", f"停止失败: {e}"))
                except Exception:
                    pass
    if not killed:
        try:
            port = (app.custom_port.get() or "8188").strip()
        except Exception:
            port = "8188"
        try:
            from core.probe import find_pids_by_port_safe, is_comfyui_pid
            from core.kill import kill_pids
            pids = []
            try:
                pids = find_pids_by_port_safe(port)
            except Exception:
                pids = []
            try:
                app.logger.info("端口进程解析: port=%s, candidates=%s", port, ",".join(map(str, pids)) if pids else "<none>")
            except Exception:
                pass
            filtered = [pid for pid in pids if is_comfyui_pid(app, pid)]
            try:
                app.logger.info("判定为 ComfyUI 的 PID: %s", ",".join(map(str, filtered)) if filtered else "<none>")
            except Exception:
                pass
            if not filtered and pids:
                try:
                    app.logger.warning("特征判定为空，回退为端口候选集进行终止")
                except Exception:
                    pass
                filtered = pids
            if filtered:
                try:
                    kill_pids(app, filtered)
                    killed = True
                except Exception:
                    pass
        except Exception:
            pass
    try:
        app.logger.info("停止流程完成: killed=%s", killed)
    except Exception:
        pass
    return killed
