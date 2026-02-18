import os
import threading
import subprocess

def start(app, pm, cmd, env, run_cwd):
    app.big_btn.set_state("starting")
    app.big_btn.set_text("启动中…")
    app._launching = True

    def worker():
        try:
            try:
                app.logger.info("启动工作目录(cwd): %s", run_cwd)
            except Exception:
                pass
            if os.name == 'nt':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 1
                pm.comfyui_process = subprocess.Popen(
                    cmd, env=env, cwd=run_cwd,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    startupinfo=si,
                )
            else:
                pm.comfyui_process = subprocess.Popen(cmd, env=env, cwd=run_cwd)
            threading.Event().wait(2)
            if pm.comfyui_process.poll() is None:
                app.ui_post(pm.on_start_success)
            else:
                app.ui_post(lambda: pm.on_start_failed("进程退出"))
        except Exception as e:
            msg = str(e)
            app.ui_post(lambda m=msg: pm.on_start_failed(m))

    threading.Thread(target=worker, daemon=True).start()
