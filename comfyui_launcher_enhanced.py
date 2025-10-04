import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import font as tkfont
import subprocess, threading, json, os, sys, webbrowser, tempfile, atexit
from pathlib import Path
from PIL import Image, ImageTk
from version_manager import VersionManager

# ================== 单实例锁 ==================
try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None

class SingletonLock:
    def __init__(self, lock_file_name):
        self.lock_file_path = os.path.join(tempfile.gettempdir(), lock_file_name)
        self.lock_file = None

    def acquire(self):
        try:
            self.lock_file = open(self.lock_file_path, 'w')
            if os.name == 'nt' and msvcrt:
                try:
                    msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    self.lock_file.close()
                    self.lock_file = None
                    return False
            elif fcntl:
                try:
                    fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    self.lock_file.close()
                    self.lock_file = None
                    return False
            else:
                if os.path.exists(self.lock_file_path):
                    self.lock_file.close()
                    self.lock_file = None
                    return False
                else:
                    self.lock_file.write(str(os.getpid()))
                    self.lock_file.flush()
            atexit.register(self.release)
            return True
        except Exception:
            if self.lock_file:
                try:
                    self.lock_file.close()
                except:
                    pass
            self.lock_file = None
            return False

    def release(self):
        if self.lock_file:
            try:
                self.lock_file.close()
                os.unlink(self.lock_file_path)
            except Exception:
                pass
            self.lock_file = None

def run_hidden(cmd, **kwargs):
    import sys
    import subprocess
    if sys.platform.startswith("win"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
    return subprocess.run(cmd, **kwargs)

# ================== 大启动按钮 ==================
class BigLaunchButton(tk.Frame):
    def __init__(self, parent, text="一键启动", size=180,
                 color="#2F6EF6", hover="#2760DB", active="#1F52BE",
                 radius=30, command=None):
        super().__init__(parent, width=size, height=size, bg=parent.cget("bg"))
        self.size = size
        self.radius = radius
        self.color = color
        self.hover = hover
        self.active = active
        self.command = command
        self.state = "idle"
        self.canvas = tk.Canvas(self, width=size, height=size, bd=0, highlightthickness=0,
                                bg=parent.cget("bg"))
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.label = tk.Label(self.canvas, text=text, bg=color, fg="#FFF",
                              font=("Microsoft YaHei", 18, "bold"))
        self._draw(color)
        self._place()
        for w in (self.canvas, self.label):
            w.bind("<Enter>", lambda e: self._on_hover())
            w.bind("<Leave>", lambda e: self._refresh())
            w.bind("<ButtonPress-1>", lambda e: self._on_press())
            w.bind("<ButtonRelease-1>", lambda e: self._on_release())

    def _draw(self, fill):
        c = self.canvas
        s = self.size
        r = self.radius
        c.delete("bg")
        c.create_rectangle(r, 0, s - r, s, fill=fill, outline=fill, tags="bg")
        c.create_rectangle(0, r, s, s - r, fill=fill, outline=fill, tags="bg")
        for (x0, y0) in [(0, 0), (s - 2 * r, 0), (0, s - 2 * r), (s - 2 * r, s - 2 * r)]:
            c.create_oval(x0, y0, x0 + 2 * r, y0 + 2 * r, fill=fill, outline=fill, tags="bg")

    def _place(self):
        self.canvas.create_window(self.size / 2, self.size / 2, window=self.label, anchor="center", tags="lbl")

    def _on_hover(self):
        if self.state == "idle":
            self._draw(self.hover)
            self.label.config(bg=self.hover)

    def _on_press(self):
        self._draw(self.active)
        self.label.config(bg=self.active)

    def _on_release(self):
        if self.command:
            self.command()
        self._refresh()

    def _refresh(self):
        base = self.color if self.state == "idle" else (self.active if self.state == "starting" else self.hover)
        self._draw(base)
        self.label.config(bg=base)

    def set_state(self, st):
        self.state = st
        self._refresh()

    def set_text(self, txt):
        self.label.config(text=txt)

# ================== Section 卡片（图标与标题基线对齐版本） ==================
class SectionCard(tk.Frame):
    def __init__(self, parent,
                 title: str,
                 icon: str = None,
                 border_color: str = "#E3E7EB",
                 bg: str = "#FFFFFF",
                 title_fg: str = "#1F2328",
                 title_font=("Microsoft YaHei", 18, "bold"),
                 icon_font=("Segoe UI Emoji", 18),
                 padding=(20, 18, 20, 20),  # left, top, right, bottom
                 inner_gap=14,
                 icon_width=36,
                 default_icon_offset=2):
        super().__init__(parent,
                         bg=bg,
                         highlightthickness=1,
                         highlightbackground=border_color,
                         bd=0)
        self.pad_l, self.pad_t, self.pad_r, self.pad_b = padding

        ICON_ADJUST_MAP = {
            "⚙": 2,
            "🔄": 1,
            "🗂": 2,
            "🧩": 2,
        }
        icon_y_offset = ICON_ADJUST_MAP.get(icon, default_icon_offset) if icon else 0

        header = tk.Frame(self, bg=bg)
        header.pack(fill=tk.X, padx=(self.pad_l, self.pad_r), pady=(self.pad_t, 0))

        if icon:
            icon_box = tk.Frame(header, width=icon_width, bg=bg)
            icon_box.grid(row=0, column=0, sticky="w")
            icon_box.grid_propagate(False)

            icon_label = tk.Label(icon_box,
                                  text=icon,
                                  font=icon_font,
                                  bg=bg,
                                  fg=title_fg)
            icon_label.pack(anchor="w", pady=(icon_y_offset, 0))

            title_label = tk.Label(header,
                                   text=title,
                                   bg=bg,
                                   fg=title_fg,
                                   font=title_font)
            title_label.grid(row=0, column=1, sticky="w")
            header.columnconfigure(1, weight=1)
        else:
            tk.Label(header, text=title, bg=bg, fg=title_fg,
                     font=title_font).pack(anchor='w')

        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill=tk.BOTH, expand=True,
                       padx=(self.pad_l, self.pad_r),
                       pady=(inner_gap, self.pad_b))

    def get_body(self):
        return self.body

# ================== 主启动器 ==================
class ComfyUILauncherEnhanced:
    _instance = None
    _initialized = False

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    LAUNCH_BUTTON_CENTER = True
    CARD_BORDER_COLOR = "#E3E7EB"
    CARD_BG = "#FFFFFF"
    SEPARATOR_COLOR = "#E3E7EB"
    LEFT_RIGHT_GAP = 56
    MAX_CONTENT_WIDTH = 1320

    SHOW_SIDEBAR_DIVIDER = True
    SIDEBAR_DIVIDER_COLOR = "#E2E5E9"
    SIDEBAR_DIVIDER_SHADOW = True
    SHADOW_WIDTH = 6

    SECTION_TITLE_FONT = ("Microsoft YaHei", 18, "bold")
    INTERNAL_HEAD_LABEL_FONT = ("Microsoft YaHei", 14, "bold")
    BODY_FONT = ("Microsoft YaHei", 10)

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.root = tk.Tk()
        self.setup_window()

        self.config_file = Path("launcher/config.json")
        if not Path("ComfyUI").exists():
            messagebox.showerror("错误", "请在 ComfyUI 根目录下运行此程序")
            self.root.destroy()
            return

        self.load_config()
        self.setup_variables()
        self.load_settings()

        self.version_manager = VersionManager(
            self.root,
            self.config["paths"]["comfyui_path"],
            self.config["paths"]["python_path"]
        )

        self.build_layout()
        threading.Thread(target=self.monitor_process, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ---------- 样式 ----------
    def setup_window(self):
        self.root.title("ComfyUI启动器 - 黎黎原上咩")
        self.root.geometry("1250x760")
        self.root.minsize(1100, 660)
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.layout('Hidden.TNotebook.Tab', [])
        try:
            self.style.theme_use('clam')
        except:
            pass
        self.COLORS = {
            "BG": "#FFFFFF",
            "SIDEBAR_BG": "#20252B",
            "SIDEBAR_ACTIVE": "#2D343C",
            "TEXT": "#1F2328",
            "TEXT_MUTED": "#5F6870",
            "ACCENT": "#2F6EF6",
            "ACCENT_HOVER": "#2760DB",
            "ACCENT_ACTIVE": "#1F52BE",
            "BORDER": "#D0D5DB"
        }
        self.root.configure(bg=self.COLORS["BG"])
        try:
            base = tkfont.nametofont("TkDefaultFont")
            base.configure(family="Microsoft YaHei", size=11)
            self.root.option_add("*Font", "TkDefaultFont")
        except:
            pass
        s = self.style
        c = self.COLORS
        s.configure(".", background=c["BG"], foreground=c["TEXT"])
        s.configure('TEntry', fieldbackground=c["BG"], bordercolor=c["BORDER"], lightcolor=c["ACCENT"])
        s.map('TEntry', bordercolor=[('focus', c["ACCENT"])])
        s.configure('TCombobox', fieldbackground=c["BG"], bordercolor=c["BORDER"])
        s.map('TCombobox', bordercolor=[('focus', c["ACCENT"])])

        s.configure('Secondary.TButton',
                    background=c["BG"], foreground=c["TEXT"],
                    padding=(8, 4),
                    borderwidth=1,
                    bordercolor=c["BORDER"],
                    font=("Microsoft YaHei", 10))
        s.map('Secondary.TButton',
              background=[('active', '#F4F6F8'), ('pressed', '#EDF0F3')],
              bordercolor=[('focus', c["ACCENT"])])

        s.configure('Accent.TButton',
                    background=c["ACCENT"],
                    foreground="#FFFFFF",
                    padding=(10, 6),
                    borderwidth=0,
                    font=("Microsoft YaHei", 11, 'bold'))
        s.map('Accent.TButton',
              background=[('active', c["ACCENT_HOVER"]), ('pressed', c["ACCENT_ACTIVE"])],
              foreground=[('disabled', '#FFFFFFAA')])

        s.configure('Nav.TButton', background=c["SIDEBAR_BG"], foreground="#FFFFFF",
                    padding=(14, 10), anchor='w', borderwidth=0, font=("Microsoft YaHei", 11))
        s.map('Nav.TButton', background=[('active', c["SIDEBAR_ACTIVE"])])
        s.configure('NavSelected.TButton', background=c["SIDEBAR_ACTIVE"],
                    foreground="#FFFFFF", padding=(14, 10), anchor='w',
                    borderwidth=0, font=("Microsoft YaHei", 11, 'bold'))

    # ---------- 变量 ----------
    def setup_variables(self):
        self.compute_mode = tk.StringVar(value="gpu")
        self.use_fast_mode = tk.BooleanVar()
        self.enable_cors = tk.BooleanVar(value=True)
        self.listen_all = tk.BooleanVar(value=True)
        self.custom_port = tk.StringVar(value="8188")
        self.hf_mirror_options = {"不使用镜像": "", "hf-mirror": "https://hf-mirror.com"}
        self.selected_hf_mirror = tk.StringVar(value="hf-mirror")
        self.comfyui_version = tk.StringVar(value="获取中…")
        self.frontend_version = tk.StringVar(value="获取中…")
        self.template_version = tk.StringVar(value="获取中…")
        self.python_version = tk.StringVar(value="获取中…")
        self.torch_version = tk.StringVar(value="获取中…")
        self.update_core_var = tk.BooleanVar(value=True)
        self.update_frontend_var = tk.BooleanVar(value=True)
        self.update_template_var = tk.BooleanVar(value=True)

        self.compute_mode.trace_add("write", lambda *a: self.save_config())
        self.use_fast_mode.trace_add("write", lambda *a: self.save_config())
        self.enable_cors.trace_add("write", lambda *a: self.save_config())
        self.listen_all.trace_add("write", lambda *a: self.save_config())
        self.custom_port.trace_add("write", lambda *a: self.save_config())
        self.selected_hf_mirror.trace_add("write", lambda *a: self.save_config())

    def load_config(self):
        default = {
            "paths": {"comfyui_path": "ComfyUI", "python_path": "python_embeded/python.exe"},
            "launch_options": {"default_compute_mode": "gpu", "default_port": "8188",
                               "enable_fast_mode": False, "enable_cors": False, "listen_all": False}
        }
        self.config_file.parent.mkdir(exist_ok=True)
        if self.config_file.exists():
            try:
                self.config = json.load(open(self.config_file, 'r', encoding='utf-8'))
            except:
                self.config = default
        else:
            self.config = default
            self.save_config()

    def save_config(self):
        self.config["launch_options"] = {
            "default_compute_mode": self.compute_mode.get(),
            "default_port": self.custom_port.get(),
            "enable_fast_mode": self.use_fast_mode.get(),
            "enable_cors": self.enable_cors.get(),
            "listen_all": self.listen_all.get(),
        }
        # 记录镜像选项
        self.config["paths"]["hf_mirror"] = self.selected_hf_mirror.get()
        json.dump(self.config, open(self.config_file, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)

    def load_settings(self):
        opt = self.config.get("launch_options", {})
        self.compute_mode.set(opt.get("default_compute_mode", "gpu"))
        self.custom_port.set(opt.get("default_port", "8188"))
        self.use_fast_mode.set(opt.get("enable_fast_mode", False))
        self.enable_cors.set(opt.get("enable_cors", True))
        self.listen_all.set(opt.get("listen_all", True))

    # ---------- 布局 ----------
    def build_layout(self):
        c = self.COLORS
        self.main_container = tk.Frame(self.root, bg=c["BG"])
        self.main_container.pack(fill=tk.BOTH, expand=True)

        self.sidebar = tk.Frame(self.main_container, width=176, bg=c["SIDEBAR_BG"])
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        sidebar_header = tk.Frame(self.sidebar, bg=c["SIDEBAR_BG"])
        sidebar_header.pack(fill=tk.X, pady=(18, 12))

        tk.Label(
            sidebar_header, 
            text="ComfyUI\n启动器", 
            bg=c["SIDEBAR_BG"], 
            fg="#FFFFFF",
            font=("Microsoft YaHei", 18, 'bold'),
            anchor='center', justify='center'
        ).pack(fill=tk.X)
        tk.Label(
            sidebar_header, 
            text="by 黎黎原上咩",
            bg=c["SIDEBAR_BG"], 
            fg=c.get("TEXT_MUTED", "#A0A4AA"), 
            font=("Microsoft YaHei", 11),
            anchor='center', justify='center'
        ).pack(fill=tk.X, pady=(4, 0))
        self.nav_buttons = {}
        for key, label in [("launch", "🚀 启动与更新"), ("version", "🧬 内核版本管理"), ("about", "👤 关于我")]:
            btn = ttk.Button(self.sidebar, text=label, style='Nav.TButton',
                             command=lambda k=key: self.select_tab(k))
            btn.pack(fill=tk.X, padx=8, pady=3)
            self.nav_buttons[key] = btn

        if self.SHOW_SIDEBAR_DIVIDER:
            if self.SIDEBAR_DIVIDER_SHADOW:
                shadow_canvas = tk.Canvas(self.main_container,
                                          width=1 + self.SHADOW_WIDTH,
                                          highlightthickness=0,
                                          bd=0,
                                          bg=c["BG"])
                shadow_canvas.pack(side=tk.LEFT, fill=tk.Y)
                shadow_canvas.create_rectangle(0, 0, 1, 9999, fill=self.SIDEBAR_DIVIDER_COLOR, outline="")
                base_hex = self.SIDEBAR_DIVIDER_COLOR

                def hex_to_rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
                r, g, b = hex_to_rgb(base_hex if base_hex.startswith('#') else '#E2E5E9')
                for i in range(1, self.SHADOW_WIDTH + 1):
                    col = f"#{r:02x}{g:02x}{b:02x}"
                    shadow_canvas.create_rectangle(i, 0, i + 1, 9999,
                                                   fill=col,
                                                   outline="")
            else:
                divider = tk.Frame(self.main_container, width=1, bg=self.SIDEBAR_DIVIDER_COLOR)
                divider.pack(side=tk.LEFT, fill=tk.Y)

        self.content_area = tk.Frame(self.main_container, bg=c["BG"])
        self.content_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ==== 用 ttk.Notebook 实现 tab ====
        self.notebook = ttk.Notebook(self.content_area, style='Hidden.TNotebook')
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.tab_frames = {
            "launch": tk.Frame(self.notebook, bg=c["BG"]),
            "version": tk.Frame(self.notebook, bg=c["BG"]),
            "about": tk.Frame(self.notebook, bg=c["BG"])
        }
        self.notebook.add(self.tab_frames["launch"], text="启动与更新")
        self.notebook.add(self.tab_frames["version"], text="内核版本管理")
        self.notebook.add(self.tab_frames["about"], text="关于我")

        self.build_launch_tab(self.tab_frames["launch"])
        self.build_version_tab(self.tab_frames["version"])
        self.build_about_tab(self.tab_frames["about"])

        self.notebook.select(self.notebook.tabs()[0])
        self.current_tab_name = "launch"

    def select_tab(self, name):
        tab_order = ["launch", "version", "about"]
        idx = tab_order.index(name)
        tabs = self.notebook.tabs()
        if idx < len(tabs):
            self.notebook.select(tabs[idx])
        for k, btn in self.nav_buttons.items():
            btn.configure(style='NavSelected.TButton' if k == name else 'Nav.TButton')
        self.current_tab_name = name
        if name == 'version' and not getattr(self, '_vm_embedded', False):
            self.version_manager.attach_to_container(self.version_container)
            self._vm_embedded = True

    # ---------- Launch Tab ----------
    def build_launch_tab(self, parent):
        c = self.COLORS

        header = tk.Frame(parent, bg=c["BG"])
        header.pack(fill=tk.X, pady=(18, 10))
        tk.Frame(header, height=1, bg=c["BORDER"]).pack(fill=tk.X, padx=2, pady=(8,8))

        launch_card = SectionCard(parent, "启动控制", icon="⚙",
                                  border_color=self.CARD_BORDER_COLOR,
                                  bg=self.CARD_BG,
                                  title_font=self.SECTION_TITLE_FONT,
                                  padding=(20, 16, 20, 18))
        launch_card.pack(fill=tk.X, pady=(0, 16))
        body = launch_card.get_body()

        container = tk.Frame(body, bg=self.CARD_BG)
        container.pack(fill=tk.X)
        container.columnconfigure(0, weight=3)
        container.columnconfigure(1, weight=0)
        container.columnconfigure(2, weight=0)
        if self.LAUNCH_BUTTON_CENTER:
            container.rowconfigure(0, weight=1)

        left = tk.Frame(container, bg=self.CARD_BG)
        left.grid(row=0, column=0, sticky="nsew")

        sep = tk.Frame(container, bg=self.SEPARATOR_COLOR, width=1)
        sep.grid(row=0, column=1, sticky="ns", padx=(self.LEFT_RIGHT_GAP // 2, self.LEFT_RIGHT_GAP // 2))

        right = tk.Frame(container, bg=self.CARD_BG)
        right.grid(row=0, column=2, sticky="n")
        if self.LAUNCH_BUTTON_CENTER:
            right.rowconfigure(0, weight=1)
            right.columnconfigure(0, weight=1)

        self._build_launch_controls(left)
        self._build_start_button(right)

        version_card = SectionCard(parent, "版本与更新", icon="🔄",
                                   border_color=self.CARD_BORDER_COLOR,
                                   bg=self.CARD_BG,
                                   title_font=self.SECTION_TITLE_FONT,
                                   padding=(20, 14, 20, 18))
        version_card.pack(fill=tk.X, pady=(0, 16))
        self._build_version_section(version_card.get_body())

        quick_card = SectionCard(parent, "快捷目录", icon="🗂",
                                 border_color=self.CARD_BORDER_COLOR,
                                 bg=self.CARD_BG,
                                 title_font=self.SECTION_TITLE_FONT,
                                 padding=(20, 14, 20, 18))
        quick_card.pack(fill=tk.X, pady=(0, 24))
        self._build_quick_links(quick_card.get_body(), path=self.config["paths"]["comfyui_path"])

        self.get_version_info()

    def _build_start_button(self, parent):
        self.big_btn = BigLaunchButton(parent,
                                       text="一键启动",
                                       size=190,
                                       color=self.COLORS["ACCENT"],
                                       hover=self.COLORS["ACCENT_HOVER"],
                                       active=self.COLORS["ACCENT_ACTIVE"],
                                       command=self.toggle_comfyui)
        if self.LAUNCH_BUTTON_CENTER:
            self.big_btn.pack(expand=True)
        else:
            self.big_btn.pack(anchor='n', pady=4)

    # ====== 启动控制 ======
    def _build_launch_controls(self, container):
        c = self.COLORS
        HEAD_LABEL_FONT = self.INTERNAL_HEAD_LABEL_FONT
        BODY_FONT = self.BODY_FONT
        ROW_GAP = 10
        INLINE_GAP = 26
        PORT_MIRROR_GAP = 34
        BUTTON_TOP_GAP = 18

        form = tk.Frame(container, bg=self.CARD_BG)
        form.pack(fill=tk.X)
        form.columnconfigure(1, weight=1)

        tk.Label(form, text="模式:", bg=self.CARD_BG, fg=c["TEXT"],
                 font=HEAD_LABEL_FONT) \
            .grid(row=0, column=0, sticky="nw", padx=(0, 14), pady=(0, ROW_GAP))

        mode_frame = tk.Frame(form, bg=self.CARD_BG)
        mode_frame.grid(row=0, column=1, sticky="w", pady=(0, ROW_GAP))
        ttk.Radiobutton(mode_frame, text="CPU模式",
                        variable=self.compute_mode, value="cpu") \
            .pack(side=tk.LEFT, padx=(0, 20))
        ttk.Radiobutton(mode_frame, text="GPU模式",
                        variable=self.compute_mode, value="gpu") \
            .pack(side=tk.LEFT)

        tk.Label(form, text="选项:", bg=self.CARD_BG, fg=c["TEXT"],
                 font=HEAD_LABEL_FONT) \
            .grid(row=1, column=0, sticky="nw", padx=(0, 14), pady=(0, ROW_GAP))

        checks = tk.Frame(form, bg=self.CARD_BG)
        checks.grid(row=1, column=1, sticky="w", pady=(0, ROW_GAP))
        ttk.Checkbutton(checks, text="快速模式 (fp16)",
                        variable=self.use_fast_mode) \
            .pack(side=tk.LEFT, padx=(0, INLINE_GAP))
        ttk.Checkbutton(checks, text="启用 CORS",
                        variable=self.enable_cors) \
            .pack(side=tk.LEFT, padx=(0, INLINE_GAP))
        ttk.Checkbutton(checks, text="监听 0.0.0.0",
                        variable=self.listen_all) \
            .pack(side=tk.LEFT)

        spacer = tk.Frame(form, bg=self.CARD_BG, width=1, height=1)
        spacer.grid(row=2, column=0)
        port_row = tk.Frame(form, bg=self.CARD_BG)
        port_row.grid(row=2, column=1, sticky="w", pady=(0, ROW_GAP))

        tk.Label(port_row, text="端口号:", bg=self.CARD_BG, fg=c["TEXT"], font=BODY_FONT) \
            .pack(side=tk.LEFT, padx=(0, 8))
        ttk.Entry(port_row, textvariable=self.custom_port, width=14) \
            .pack(side=tk.LEFT, padx=(0, PORT_MIRROR_GAP))

        tk.Label(port_row, text="HF 镜像:", bg=self.CARD_BG, fg=c["TEXT"], font=BODY_FONT) \
            .pack(side=tk.LEFT, padx=(0, 8))
        self.hf_mirror_combobox = ttk.Combobox(
            port_row,
            textvariable=self.selected_hf_mirror,
            values=list(self.hf_mirror_options.keys()),
            state="readonly",
            width=16
        )
        self.hf_mirror_combobox.pack(side=tk.LEFT)
        self.hf_mirror_combobox.bind("<<ComboboxSelected>>", self.on_hf_mirror_selected)

        btn_row = tk.Frame(form, bg=self.CARD_BG)
        btn_row.grid(row=3, column=1, sticky="w", pady=(BUTTON_TOP_GAP, 0))
        ttk.Button(btn_row, text="恢复默认设置",
                   style='Secondary.TButton',
                   command=self.reset_settings).pack(side=tk.LEFT)

        tk.Frame(container, bg=self.CARD_BG, height=2).pack(fill=tk.X)

    # ====== 版本与更新 ======
    def _build_version_section(self, container):
        c = self.COLORS
        grid = tk.Frame(container, bg=self.CARD_BG)
        grid.pack(fill=tk.X)
        items = [("内核", self.comfyui_version),
                 ("前端", self.frontend_version),
                 ("模板库", self.template_version),
                 ("Python", self.python_version),
                 ("Torch", self.torch_version)]
        for i, (lbl, var) in enumerate(items):
            col = tk.Frame(grid, bg=self.CARD_BG)
            col.grid(row=0, column=i, padx=8, sticky='w')
            grid.columnconfigure(i, weight=1)
            tk.Label(col, text=f"{lbl}:", bg=self.CARD_BG, fg=c["TEXT_MUTED"],
                     font=self.BODY_FONT).pack(anchor='w')
            tk.Label(col, textvariable=var, bg=self.CARD_BG, fg=c["TEXT"],
                     font=("Consolas", 11)).pack(anchor='w', pady=(2, 0))
        batch = tk.Frame(container, bg=self.CARD_BG)
        batch.pack(fill=tk.X, pady=(12, 0))
        tk.Label(batch, text="批量更新:", bg=self.CARD_BG, fg=c["TEXT"],
                 font=self.INTERNAL_HEAD_LABEL_FONT).pack(side=tk.LEFT, padx=(0, 8))
        self.core_btn = ttk.Button(batch, text="", style='Secondary.TButton', command=lambda: self._toggle_batch('core'))
        self.front_btn = ttk.Button(batch, text="", style='Secondary.TButton', command=lambda: self._toggle_batch('front'))
        self.tpl_btn = ttk.Button(batch, text="", style='Secondary.TButton', command=lambda: self._toggle_batch('tpl'))
        for b in (self.core_btn, self.front_btn, self.tpl_btn):
            b.pack(side=tk.LEFT, padx=5)
        self.batch_update_btn = ttk.Button(batch, text="更新", style='Accent.TButton',
                                           command=self.perform_batch_update)
        self.batch_update_btn.pack(side=tk.RIGHT)
        self.frontend_update_btn = self.batch_update_btn
        self.template_update_btn = self.batch_update_btn
        self._refresh_batch_labels()

    def _build_quick_links(self, container, path=None):
        c = self.COLORS
        if path:
            tk.Label(container,
                    text=f"路径: {Path(path).resolve()}",
                    bg=c["BG"], fg=c["TEXT_MUTED"],
                    font=self.BODY_FONT).pack(anchor='w', padx=(4, 0), pady=(0, 8))

        row = tk.Frame(container, bg=c["BG"])
        row.pack(fill=tk.X)
        for txt, cmd in [
            ("根目录", self.open_root_dir),
            ("日志文件", self.open_logs_dir),
            ("输入目录", self.open_input_dir),
            ("输出目录", self.open_output_dir),
            ("插件目录", self.open_plugins_dir),
        ]:
            ttk.Button(row, text=txt, style='Secondary.TButton', command=cmd).pack(side=tk.LEFT, padx=6)

    # ---------- Version / About ----------
    def build_version_tab(self, parent):
        self.version_container = tk.Frame(parent, bg=self.COLORS["BG"])
        self.version_container.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)


    def build_about_tab(self, parent):
        frame = tk.Frame(parent, bg=self.COLORS["BG"])
        frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)

        # 加载并居中图片
        img_path = os.path.join(os.path.dirname(__file__), "about_me.png")
        try:
            img = Image.open(img_path)
            img = img.resize((96, 96))
            photo = ImageTk.PhotoImage(img)
            img_label = tk.Label(frame, image=photo, bg=self.COLORS["BG"])
            img_label.image = photo
            img_label.pack(pady=(0, 16))
        except Exception as e:
            tk.Label(frame, text=f"[头像加载失败]: {e}", bg=self.COLORS["BG"], fg="red").pack(pady=(0, 16))

        # 昵称
        tk.Label(
            frame, text="黎黎原上咩",
            bg=self.COLORS["BG"], fg=self.COLORS["TEXT"],
            font=("Microsoft YaHei", 22, 'bold'),
            anchor='center', justify='center'
        ).pack(fill=tk.X, pady=(0, 4))

        # 个性签名
        tk.Label(
            frame, text="未觉池塘春草梦，阶前梧叶已秋声",
            bg=self.COLORS["BG"], fg=self.COLORS.get("TEXT_MUTED", "#A0A4AA"),
            font=("Microsoft YaHei", 13, 'italic'),
            anchor='center', justify='center'
        ).pack(fill=tk.X, pady=(0, 12))

        # B站链接
        def open_bilibili(event=None):
            import webbrowser
            webbrowser.open("https://space.bilibili.com/449342345")

        link = tk.Label(
            frame, text="https://space.bilibili.com/449342345",
            bg=self.COLORS["BG"], fg="#2F6EF6",
            font=("Microsoft YaHei", 13, 'underline'),
            cursor="hand2", anchor='center', justify='center'
        )
        link.pack(fill=tk.X)
        link.bind("<Button-1>", open_bilibili)

    # ---------- 批量状态 ----------
    def _refresh_batch_labels(self):
        self.core_btn.config(text="✅ 内核" if self.update_core_var.get() else "□ 内核")
        self.front_btn.config(text="✅ 前端" if self.update_frontend_var.get() else "□ 前端")
        self.tpl_btn.config(text="✅ 模板库" if self.update_template_var.get() else "□ 模板库")

    def _toggle_batch(self, which):
        if which == 'core':
            self.update_core_var.set(not self.update_core_var.get())
        elif which == 'front':
            self.update_frontend_var.set(not self.update_frontend_var.get())
        else:
            self.update_template_var.set(not self.update_template_var.get())
        self._refresh_batch_labels()

    # ---------- 启动逻辑 ----------
    def toggle_comfyui(self):
        if getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is None:
            self.stop_comfyui()
        else:
            self.start_comfyui()

    def start_comfyui(self):
        try:
            py = Path(self.config["paths"]["python_path"])
            main = Path(self.config["paths"]["comfyui_path"]) / "main.py"
            if not py.exists():
                messagebox.showerror("错误", f"Python不存在: {py}")
                return
            if not main.exists():
                messagebox.showerror("错误", f"主文件不存在: {main}")
                return
            cmd = [str(py), "-s", str(main), "--windows-standalone-build"]
            if self.compute_mode.get() == "cpu":
                cmd.append("--cpu")
            if self.use_fast_mode.get():
                cmd.extend(["--fast", "fp16_accumulation"])
            if self.listen_all.get():
                cmd.extend(["--listen", "0.0.0.0"])
            port = self.custom_port.get().strip()
            if port and port != "8188":
                cmd.extend(["--port", port])
            if self.enable_cors.get():
                cmd.extend(["--enable-cors-header", "*"])
            env = os.environ.copy()
            sel = self.selected_hf_mirror.get()
            if sel != "不使用镜像":
                endpoint = self.hf_mirror_options.get(sel, "")
                if endpoint:
                    env["HF_ENDPOINT"] = endpoint
            self.big_btn.set_state("starting")
            self.big_btn.set_text("启动中…")

            def worker():
                try:
                    self.comfyui_process = subprocess.Popen(
                        cmd, env=env, cwd=os.getcwd(),
                        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
                    threading.Event().wait(2)
                    if self.comfyui_process.poll() is None:
                        self.root.after(0, self.on_start_success)
                    else:
                        self.root.after(0, lambda: self.on_start_failed("进程退出"))
                except Exception as e:
                    self.root.after(0, lambda: self.on_start_failed(str(e)))

            threading.Thread(target=worker, daemon=True).start()
        except Exception as e:
            messagebox.showerror("启动失败", str(e))
            self.on_start_failed(str(e))

    def on_start_success(self):
        self.big_btn.set_state("running")
        self.big_btn.set_text("停止")

    def on_start_failed(self, error):
        self.big_btn.set_state("idle")
        self.big_btn.set_text("一键启动")
        self.comfyui_process = None

    def stop_comfyui(self):
        if getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is None:
            try:
                self.comfyui_process.terminate()
                self.comfyui_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.comfyui_process.kill()
            except Exception as e:
                messagebox.showerror("错误", f"停止失败: {e}")
        self.big_btn.set_state("idle")
        self.big_btn.set_text("一键启动")

    def monitor_process(self):
        while True:
            try:
                if getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is not None:
                    self.root.after(0, self.on_process_ended)
                threading.Event().wait(2)
            except:
                break

    def on_process_ended(self):
        self.comfyui_process = None
        self.big_btn.set_state("idle")
        self.big_btn.set_text("一键启动")

    # ---------- 目录 ----------
    def _open_dir(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        if path.exists():
            os.startfile(str(path))
        else:
            messagebox.showwarning("警告", f"目录不存在: {path}")

    # ---------- 文件 ----------
    def _open_file(self, path: Path):
        if path.exists():
            os.startfile(str(path))
        else:
            messagebox.showwarning("警告", f"文件不存在: {path}")

    def open_root_dir(self): self._open_dir(Path(self.config["paths"]["comfyui_path"]).resolve())
    def open_logs_dir(self): self._open_file(Path(self.config["paths"]["comfyui_path"]).resolve() / "user" / "comfyui.log")
    def open_input_dir(self): self._open_dir(Path(self.config["paths"]["comfyui_path"]).resolve() / "input")
    def open_output_dir(self): self._open_dir(Path(self.config["paths"]["comfyui_path"]).resolve() / "output")
    def open_plugins_dir(self): self._open_dir(Path(self.config["paths"]["comfyui_path"]).resolve() / "custom_nodes")

    def open_comfyui_web(self):
        webbrowser.open(f"http://127.0.0.1:{self.custom_port.get() or '8188'}")

    def reset_settings(self):
        if messagebox.askyesno("确认", "确定恢复默认设置?"):
            self.compute_mode.set("gpu")
            self.custom_port.set("8188")
            self.use_fast_mode.set(False)
            self.enable_cors.set(True)
            self.listen_all.set(True)
            self.selected_hf_mirror.set("hf-mirror")
            self.save_config()
            messagebox.showinfo("完成", "已恢复默认设置")

    # ---------- 版本 ----------
    def get_version_info(self):
        if getattr(self, '_version_info_loading', False):
            return
        self._version_info_loading = True
        for v in (self.comfyui_version, self.frontend_version,
                  self.template_version, self.python_version, self.torch_version):
            v.set("获取中…")

        def worker():
            try:
                root = Path(self.config["paths"]["comfyui_path"]).resolve()
                if root.exists():
                    try:
                        r = run_hidden(["git", "describe", "--tags", "--abbrev=0"],
                                           cwd=str(root), capture_output=True, text=True, timeout=10)
                        if r.returncode == 0:
                            tag = r.stdout.strip()
                            r2 = run_hidden(["git", "rev-parse", "--short", "HEAD"],
                                                cwd=str(root), capture_output=True, text=True, timeout=10)
                            commit = r2.stdout.strip() if r2.returncode == 0 else ""
                            self.comfyui_version.set(f"{tag} ({commit})")
                        else:
                            self.comfyui_version.set("未找到")
                    except:
                        self.comfyui_version.set("未找到")
                else:
                    self.comfyui_version.set("ComfyUI未找到")

                try:
                    r = run_hidden([self.config["paths"]["python_path"], "--version"],
                                       capture_output=True, text=True, timeout=10)
                    if r.returncode == 0:
                        self.python_version.set(r.stdout.strip().replace("Python ", ""))
                    else:
                        self.python_version.set("无法获取")
                except:
                    self.python_version.set("获取失败")

                try:
                    r = run_hidden([self.config["paths"]["python_path"], "-c", "import torch;print(torch.__version__)"],
                                       capture_output=True, text=True, timeout=15)
                    if r.returncode == 0:
                        self.torch_version.set(r.stdout.strip())
                    else:
                        self.torch_version.set("未安装")
                except:
                    self.torch_version.set("获取失败")

                try:
                    r = run_hidden([self.config["paths"]["python_path"], "-m", "pip", "show", "comfyui-frontend-package"],
                                       capture_output=True, text=True, timeout=10)
                    if r.returncode == 0:
                        for line in r.stdout.splitlines():
                            if line.startswith("Version:"):
                                self.frontend_version.set("v" + line.split(":")[1].strip())
                                break
                        else:
                            self.frontend_version.set("未安装")
                    else:
                        self.frontend_version.set("未安装")
                except:
                    self.frontend_version.set("获取失败")

                try:
                    r = run_hidden([self.config["paths"]["python_path"], "-m", "pip", "show", "comfyui-workflow-templates"],
                                       capture_output=True, text=True, timeout=10)
                    if r.returncode == 0:
                        for line in r.stdout.splitlines():
                            if line.startswith("Version:"):
                                self.template_version.set("v" + line.split(":")[1].strip())
                                break
                        else:
                            self.template_version.set("未安装")
                    else:
                        self.template_version.set("未安装")
                except:
                    self.template_version.set("获取失败")
            finally:
                self._version_info_loading = False

        threading.Thread(target=worker, daemon=True).start()

    def perform_batch_update(self):
        if hasattr(self, 'batch_update_btn'):
            self.batch_update_btn.config(text="更新中...", state="disabled")

        def worker():
            try:
                if self.update_core_var.get():
                    try:
                        root = Path(self.config["paths"]["comfyui_path"]).resolve()
                        run_hidden(["git", "pull"], cwd=str(root),
                                       capture_output=True, text=True)
                    except:
                        pass
                if self.update_frontend_var.get():
                    try:
                        self.update_frontend()
                    except:
                        pass
                if self.update_template_var.get():
                    try:
                        self.update_template_library()
                    except:
                        pass
                try:
                    self.get_version_info()
                except:
                    pass
            finally:
                self.root.after(0, lambda: self.batch_update_btn.config(text="更新", state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def update_frontend(self):
        pass

    def update_template_library(self):
        pass

    # ---------- 运行 ----------
    def run(self):
        self.get_version_info()
        self.root.mainloop()

    def on_hf_mirror_selected(self, _=None):
        pass

    def on_closing(self):
        if getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is None:
            if messagebox.askyesno("确认", "ComfyUI 正在运行，是否停止并退出？"):
                self.stop_comfyui()
                self.root.destroy()
        else:
            self.root.destroy()


if __name__ == "__main__":
    lock = SingletonLock("comfyui_launcher_section_card_with_divider.lock")
    if not lock.acquire():
        sys.exit(0)
    try:
        app = ComfyUILauncherEnhanced()
        app.run()
    finally:
        lock.release()