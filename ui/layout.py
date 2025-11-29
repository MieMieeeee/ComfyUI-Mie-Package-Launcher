import tkinter as tk
from tkinter import ttk
from pathlib import Path
from ui.custom_widges import BigLaunchButton, RoundedButton, SectionCard
from ui import version_panel as VERSION
from ui import quick_links_panel as QUICK
from ui import launch_controls_panel as LAUNCH
from ui import about_tab as ABOUT
from ui import comfyui_tab as COMFY
from ui import start_button_panel as START
from ui import launcher_about_tab as LAUNCHER_ABOUT
from ui import external_models_tab as EXT_MODELS
from ui.constants import COLORS, LAUNCH_BUTTON_CENTER, SIDEBAR_DIVIDER_SHADOW, SIDEBAR_DIVIDER_COLOR, SHADOW_WIDTH, LEFT_RIGHT_GAP, CARD_BORDER_COLOR, CARD_BG, SECTION_TITLE_FONT

def build_layout(app):
    c = COLORS
    app.main_container = tk.Frame(app.root, bg=c["BG"])
    app.main_container.pack(fill=tk.BOTH, expand=True)
    app.sidebar = tk.Frame(app.main_container, width=176, bg=c["SIDEBAR_BG"])
    app.sidebar.pack(side=tk.LEFT, fill=tk.Y)
    app.sidebar.pack_propagate(False)
    sidebar_header = tk.Frame(app.sidebar, bg=c["SIDEBAR_BG"])
    sidebar_header.pack(fill=tk.X, pady=(18, 12))
    tk.Label(sidebar_header, text="ComfyUI\n启动器", bg=c["SIDEBAR_BG"], fg="#FFFFFF", font=("Microsoft YaHei", 18, 'bold'), anchor='center', justify='center').pack(fill=tk.X)
    tk.Label(sidebar_header, text="by 黎黎原上咩", bg=c["SIDEBAR_BG"], fg=c.get("TEXT_MUTED", "#A0A4AA"), font=("Microsoft YaHei", 11), anchor='center', justify='center').pack(fill=tk.X, pady=(4, 0))
    app.nav_buttons = {}
    for key, label in [("launch", "🚀 启动与更新"), ("version", "🧬 内核版本管理"), ("external_models", "📦 外置模型库管理"), ("about", "👤 关于我"), ("comfyui", "📚 关于ComfyUI"), ("about_launcher", "🧰 关于启动器")]:
        btn = ttk.Button(app.sidebar, text=label, style='Nav.TButton', command=lambda k=key: app.select_tab(k))
        btn.pack(fill=tk.X, padx=8, pady=3)
        app.nav_buttons[key] = btn
    if True:
        if SIDEBAR_DIVIDER_SHADOW:
            shadow_canvas = tk.Canvas(app.main_container, width=1 + SHADOW_WIDTH, highlightthickness=0, bd=0, bg=c["BG"])
            shadow_canvas.pack(side=tk.LEFT, fill=tk.Y)
            shadow_canvas.create_rectangle(0, 0, 1, 9999, fill=SIDEBAR_DIVIDER_COLOR, outline="")
        else:
            divider = tk.Frame(app.main_container, width=1, bg=SIDEBAR_DIVIDER_COLOR)
            divider.pack(side=tk.LEFT, fill=tk.Y)
    app.content_area = tk.Frame(app.main_container, bg=c["BG"])
    app.content_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    app.notebook = ttk.Notebook(app.content_area, style='Hidden.TNotebook')
    app.notebook.pack(fill=tk.BOTH, expand=True)
    app.tab_frames = {
        "launch": tk.Frame(app.notebook, bg=c["BG"]),
        "version": tk.Frame(app.notebook, bg=c["BG"]),
        "external_models": tk.Frame(app.notebook, bg=c["BG"]),
        "comfyui": tk.Frame(app.notebook, bg=c["BG"]),
        "about": tk.Frame(app.notebook, bg=c["BG"]),
        "about_launcher": tk.Frame(app.notebook, bg=c["BG"]),
    }
    app.notebook.add(app.tab_frames["launch"], text="启动与更新")
    app.notebook.add(app.tab_frames["version"], text="内核版本管理")
    app.notebook.add(app.tab_frames["external_models"], text="外置模型库管理")
    app.notebook.add(app.tab_frames["about"], text="关于我")
    app.notebook.add(app.tab_frames["comfyui"], text="关于 ComfyUI")
    app.notebook.add(app.tab_frames["about_launcher"], text="关于启动器")
    build_launch_tab(app, app.tab_frames["launch"])
    build_version_tab(app, app.tab_frames["version"])
    EXT_MODELS.build_external_models_tab(app, app.tab_frames["external_models"])
    ABOUT.build_about_tab(app, app.tab_frames["about"])
    LAUNCHER_ABOUT.build_about_launcher(app, app.tab_frames["about_launcher"])
    COMFY.build_about_comfyui(app, app.tab_frames["comfyui"])
    app.notebook.select(app.notebook.tabs()[0])
    app.current_tab_name = "launch"
    

def build_launch_tab(app, parent):
    c = app.COLORS
    header = tk.Frame(parent, bg=c["BG"]) 
    header.pack(fill=tk.X, pady=(6, 6))
    launch_card = SectionCard(parent, "启动控制", icon="⚙", border_color=CARD_BORDER_COLOR, bg=CARD_BG, title_font=SECTION_TITLE_FONT, padding=(20, 16, 20, 18))
    launch_card.pack(fill=tk.X, pady=(0, 16))
    body = launch_card.get_body()
    container = tk.Frame(body, bg=CARD_BG)
    container.pack(fill=tk.X)
    container.columnconfigure(0, weight=3)
    container.columnconfigure(1, weight=0)
    container.columnconfigure(2, weight=0)
    if LAUNCH_BUTTON_CENTER:
        container.rowconfigure(0, weight=1)
    left = tk.Frame(container, bg=CARD_BG)
    left.grid(row=0, column=0, sticky="nsew")
    sep = tk.Frame(container, bg=SIDEBAR_DIVIDER_COLOR, width=1)
    sep.grid(row=0, column=1, sticky="ns", padx=(LEFT_RIGHT_GAP // 2, LEFT_RIGHT_GAP // 2))
    right = tk.Frame(container, bg=CARD_BG)
    right.grid(row=0, column=2, sticky="n")
    if LAUNCH_BUTTON_CENTER:
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
    LAUNCH.build_launch_controls_panel(app, left, RoundedButton)
    START.build_start_button_panel(app, right, BigLaunchButton)
    version_card = SectionCard(parent, "版本与更新", icon="🔄", border_color=CARD_BORDER_COLOR, bg=CARD_BG, title_font=SECTION_TITLE_FONT, padding=(16, 12, 16, 12))
    version_card.pack(fill=tk.X, pady=(0, 10))
    VERSION.build_version_panel(app, version_card.get_body(), RoundedButton)
    quick_card = SectionCard(parent, "快捷目录", icon="🗂", border_color=CARD_BORDER_COLOR, bg=CARD_BG, title_font=SECTION_TITLE_FONT, padding=(14, 8, 14, 10), inner_gap=10)
    quick_card.pack(fill=tk.X, pady=(0, 10))
    try:
        from utils import paths as PATHS
        _path = str(PATHS.get_comfy_root(app.config.get("paths", {})))
    except Exception:
        _path = str(Path("ComfyUI").resolve())
    QUICK.build_quick_links_panel(app, quick_card.get_body(), path=_path, rounded_button_cls=RoundedButton)
    app.get_version_info()

def build_version_tab(app, parent):
    app.version_container = tk.Frame(parent, bg=app.COLORS["BG"]) 
    app.version_container.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)