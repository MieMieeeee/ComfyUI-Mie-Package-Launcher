import os
from tkinter import ttk
from ui import assets_helper as ASSETS
from ui import theme as THEME
from ui.constants import COLORS

def setup_window(app):
    try:
        app.root.title("ComfyUI启动器 - 黎黎原上咩")
        app.root.geometry("1250x860")
        app.root.minsize(1100, 700)
        try:
            if os.name == 'nt':
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ComfyUILauncher")
        except Exception:
            pass
        try:
            ASSETS.apply_window_icons(app.root, getattr(app, 'logger', None))
        except Exception:
            pass
        app.style = THEME.create_style(logger=getattr(app, 'logger', None))
        if not app.style:
            return
        THEME.apply_theme(app.style, logger=getattr(app, 'logger', None))
        try:
            app.style.layout('Hidden.TNotebook.Tab', [])
        except Exception:
            pass
        try:
            app.root.configure(bg=COLORS.get("BG", "#FFFFFF"))
        except Exception:
            pass
        
        THEME.configure_default_font(app.root, logger=getattr(app, 'logger', None))
        THEME.configure_styles(app.style, COLORS, logger=getattr(app, 'logger', None))
    except Exception:
        try:
            app.logger.exception("setup_window 阶段发生异常，继续使用默认外观")
        except Exception:
            pass