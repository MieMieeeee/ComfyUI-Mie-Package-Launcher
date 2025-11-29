import os
from pathlib import Path
from tkinter import messagebox
from utils import paths as PATHS

def open_dir(app, path: Path):
    try:
        app.logger.info("打开目录: %s", str(path))
    except Exception:
        pass
    path.mkdir(parents=True, exist_ok=True)
    if path.exists():
        os.startfile(str(path))
    else:
        messagebox.showwarning("警告", f"目录不存在: {path}")

def open_file(app, path: Path):
    try:
        app.logger.info("打开文件: %s", str(path))
    except Exception:
        pass
    if path.exists():
        os.startfile(str(path))
    else:
        messagebox.showwarning("警告", f"文件不存在: {path}")

def open_root_dir(app):
    root = PATHS.get_comfy_root(app.config.get("paths", {}))
    open_dir(app, root)

def open_logs_file(app):
    root = PATHS.get_comfy_root(app.config.get("paths", {}))
    open_file(app, PATHS.logs_file(root))

def open_input_dir(app):
    root = PATHS.get_comfy_root(app.config.get("paths", {}))
    open_dir(app, PATHS.input_dir(root))

def open_output_dir(app):
    root = PATHS.get_comfy_root(app.config.get("paths", {}))
    open_dir(app, PATHS.output_dir(root))

def open_plugins_dir(app):
    root = PATHS.get_comfy_root(app.config.get("paths", {}))
    open_dir(app, PATHS.plugins_dir(root))

def open_workflows_dir(app):
    base = PATHS.get_comfy_root(app.config.get("paths", {}))
    wf = PATHS.workflows_dir(base)
    try:
        app.logger.info("打开工作流目录: %s", str(wf))
    except Exception:
        pass
    if wf.exists():
        os.startfile(str(wf))
    else:
        messagebox.showwarning("提示", "工作流文件夹尚未创建，需要保存至少一个工作流")
def open_web(app):
    url = f"http://127.0.0.1:{app.custom_port.get() or '8188'}"
    try:
        app.logger.info("打开网页: %s", url)
    except Exception:
        pass
    import webbrowser
    mode = "default"
    try:
        mode = (app.browser_open_mode.get() or "default").strip()
    except Exception:
        try:
            mode = (app.config.get("launch_options", {}).get("browser_open_mode") or "default").strip()
        except Exception:
            mode = "default"
    if mode == "none":
        return
    if mode == "custom":
        path = ""
        try:
            path = (app.custom_browser_path.get() or "").strip()
        except Exception:
            try:
                path = (app.config.get("launch_options", {}).get("custom_browser_path") or "").strip()
            except Exception:
                path = ""
        if path:
            try:
                webbrowser.register("custom-browser", None, webbrowser.BackgroundBrowser(path))
                b = webbrowser.get("custom-browser")
                b.open(url)
                return
            except Exception:
                pass
        try:
            messagebox.showwarning("提示", "未设置或无法使用自定义浏览器，使用默认浏览器打开")
        except Exception:
            pass
    webbrowser.open(url)