import os
from utils.common import run_hidden

try:
    import psutil
except ImportError:
    psutil = None


def _kill_with_admin(pid):
    """尝试以管理员权限终止进程（弹 UAC 提权窗）"""
    import ctypes
    # ShellExecuteW 的 "runas" 动词会触发 UAC 提权弹窗
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "taskkill", f"/PID {pid} /F", None, 0
    )
    # ShellExecuteW 返回值 > 32 表示成功启动
    return ret > 32


def kill_pids(app, pids):
    killed_any = False
    failed_pids = []
    _log = getattr(app, 'logger', None)

    if psutil:
        try:
            procs_to_wait = []
            for pid in pids:
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                    procs_to_wait.append(p)
                except psutil.AccessDenied:
                    if _log: _log.info("[kill] psutil.terminate PID=%s 权限不足", pid)
                    failed_pids.append(pid)
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
                    except psutil.AccessDenied:
                        if _log: _log.info("[kill] psutil.kill PID=%s 权限不足", p.pid)
                        failed_pids.append(p.pid)
                    except Exception:
                        pass
        except Exception:
            pass

    if os.name == 'nt':
        for pid in pids:
            if pid in failed_pids:
                if _log: _log.info("[kill] PID=%s 已在 failed_pids，跳过普通 taskkill", pid)
                continue
            try:
                r = run_hidden(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
                if r.returncode == 0:
                    killed_any = True
                else:
                    if _log: _log.info("[kill] taskkill PID=%s 失败 rc=%s，加入 failed_pids", pid, r.returncode)
                    failed_pids.append(pid)
            except Exception:
                failed_pids.append(pid)

    # 对权限不足的进程尝试管理员权限
    if failed_pids:
        if _log: _log.info("[kill] 尝试管理员权限终止: PIDs=%s", failed_pids)
        for pid in failed_pids:
            try:
                if _kill_with_admin(pid):
                    killed_any = True
                    if _log: _log.info("[kill] 管理员提权终止 PID=%s 成功", pid)
            except Exception as e:
                if _log: _log.info("[kill] 管理员提权终止 PID=%s 失败: %s", pid, e)

        # 如果管理员权限也没成功，弹窗告知用户
        still_failed = []
        for pid in failed_pids:
            try:
                if psutil and psutil.pid_exists(pid):
                    still_failed.append(pid)
            except Exception:
                still_failed.append(pid)

        if still_failed:
            pid_text = ", ".join(map(str, still_failed))
            try:
                from PyQt5 import QtWidgets
                QtWidgets.QMessageBox.warning(
                    None, "无法关闭进程",
                    f"以下进程无法终止 (PID: {pid_text})，权限不足。\n\n"
                    f"请手动关闭该进程，或以管理员身份运行启动器。"
                )
            except Exception:
                try:
                    app.logger.warning("无法终止进程 (权限不足): PID %s", pid_text)
                except Exception:
                    pass

    if not killed_any:
        raise RuntimeError("无法终止目标进程")