import os
import time
import threading
import subprocess
from urllib.request import urlopen, Request


def _post_to_ui(app, fn):
    """将函数投递到 UI 线程执行（线程安全）"""
    try:
        app.ui_post(fn)
    except Exception:
        try:
            app.root.after(0, fn)
        except Exception:
            pass


def _spawn_process(pm, cmd, env, run_cwd, show_console=True):
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        if show_console:
            si.wShowWindow = 1  # SW_SHOWNORMAL
            pm.comfyui_process = subprocess.Popen(
                cmd,
                env=env,
                cwd=run_cwd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                startupinfo=si,
            )
        else:
            si.wShowWindow = subprocess.SW_HIDE
            pm.comfyui_process = subprocess.Popen(
                cmd,
                env=env,
                cwd=run_cwd,
                creationflags=subprocess.CREATE_NO_WINDOW,
                startupinfo=si,
            )
    else:
        pm.comfyui_process = subprocess.Popen(cmd, env=env, cwd=run_cwd)


def _check_system_stats(port: str, timeout: float = 1.5) -> bool:
    """通过 /system_stats API 检查 ComfyUI 是否完全启动"""
    try:
        url = f"http://127.0.0.1:{port}/system_stats"
        req = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "ComfyUI-Launcher",
        })
        with urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None)
            if code is None:
                try:
                    code = resp.getcode()
                except Exception:
                    code = None
            return code == 200
    except Exception:
        return False


def start(app, pm, cmd, env, run_cwd):
    app.big_btn.set_state("starting")
    app.big_btn.set_display("启动中…", "点击停止")
    app._launching = True

    # 读取是否显示命令行窗口的配置
    show_console = True
    try:
        if hasattr(app, 'show_console'):
            show_console = app.show_console.get()
    except Exception:
        pass

    # 获取端口
    port = "8188"
    try:
        port = (app.custom_port.get() or "8188").strip()
    except Exception:
        pass

    def worker():
        try:
            try:
                app.logger.info("启动工作目录(cwd): %s", run_cwd)
            except Exception:
                pass

            _spawn_process(pm, cmd, env, run_cwd, show_console=show_console)

            # 等待进程初始化，再开始轮询 API
            time.sleep(3)

            # 轮询 /system_stats 直到 ComfyUI 完全启动（最多 120 秒）
            deadline = time.time() + 120.0
            while time.time() < deadline:
                # 进程已退出
                if pm.comfyui_process and pm.comfyui_process.poll() is not None:
                    _post_to_ui(app, lambda: pm.on_start_failed("进程意外退出"))
                    return

                if _check_system_stats(port):
                    try:
                        app.logger.info("ComfyUI /system_stats 就绪，启动完成")
                    except Exception:
                        pass
                    _post_to_ui(app, pm.on_start_success)
                    return

                time.sleep(1.5)

            # 超时，但进程仍在运行 - 视为启动成功
            try:
                if pm.comfyui_process and pm.comfyui_process.poll() is None:
                    app.logger.warning("启动轮询超时，但进程仍在运行，视为启动成功")
                    _post_to_ui(app, pm.on_start_success)
                else:
                    _post_to_ui(app, lambda: pm.on_start_failed("启动超时"))
            except Exception:
                _post_to_ui(app, lambda: pm.on_start_failed("启动超时"))

        except Exception as e:
            msg = str(e)
            _post_to_ui(app, lambda m=msg: pm.on_start_failed(m))

    threading.Thread(target=worker, daemon=True).start()
