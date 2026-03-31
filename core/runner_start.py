import os
import threading
import subprocess


def _post_to_ui(app, fn):
    try:
        app.ui_post(fn)
    except Exception:
        try:
            app.root.after(0, fn)
        except Exception:
            pass


def _spawn_process(pm, cmd, env, run_cwd):
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 1
        pm.comfyui_process = subprocess.Popen(
            cmd,
            env=env,
            cwd=run_cwd,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            startupinfo=si,
        )
    else:
        pm.comfyui_process = subprocess.Popen(cmd, env=env, cwd=run_cwd)


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

            _spawn_process(pm, cmd, env, run_cwd)

            threading.Event().wait(2)
            if pm.comfyui_process.poll() is None:
                _post_to_ui(app, pm.on_start_success)
            else:
                _post_to_ui(app, lambda: pm.on_start_failed("进程退出"))
        except Exception as e:
            msg = str(e)
            _post_to_ui(app, lambda m=msg: pm.on_start_failed(m))

    threading.Thread(target=worker, daemon=True).start()
