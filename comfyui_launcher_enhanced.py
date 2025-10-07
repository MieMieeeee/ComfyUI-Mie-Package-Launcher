import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont
import subprocess, threading, json, os, sys, webbrowser, tempfile, atexit
import shlex
from pathlib import Path
from PIL import Image, ImageTk
from version_manager import VersionManager
from utils import run_hidden, have_git, is_git_repo
from logger_setup import install_logging

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

# 使用工具模块中的 run_hidden，移除重复定义

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

    LAUNCH_BUTTON_CENTER = False
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
        # 安装日志记录与异常钩子，输出到 logs/launcher.log
        self.logger = install_logging()
        try:
            self.logger.info("启动器初始化")
        except Exception:
            pass
        self.setup_window()

        # 基础配置与变量需尽早初始化，避免后续保护性路径检查时出现属性缺失
        self.config_file = Path("launcher/config.json")
        self.load_config()
        self.setup_variables()

        # 允许在任意目录运行：如果未检测到有效的 ComfyUI 路径，则提示用户选择
        def is_valid_comfy_path(p: Path) -> bool:
            try:
                return p.exists() and (
                    (p / "main.py").exists() or (p / ".git").exists()
                )
            except Exception:
                return False

        # 当前配置中的路径或常见默认路径
        comfy_path = Path(self.config["paths"].get("comfyui_path", "ComfyUI")).resolve()
        if not is_valid_comfy_path(comfy_path):
            # 尝试当前工作目录下的 ComfyUI 子目录
            alt = Path("ComfyUI").resolve()
            if is_valid_comfy_path(alt):
                comfy_path = alt
            else:
                # 弹窗引导用户选择 ComfyUI 根目录
                messagebox.showwarning(
                    "未找到 ComfyUI",
                    "未检测到有效的 ComfyUI 根目录。请手动选择安装目录。"
                )
                selected = filedialog.askdirectory(title="请选择 ComfyUI 根目录")
                if selected:
                    cand = Path(selected).resolve()
                    if is_valid_comfy_path(cand):
                        comfy_path = cand
                    else:
                        messagebox.showerror("错误", "所选目录似乎不是 ComfyUI 根目录（缺少 main.py 或 .git）")
                # 如果仍然无效，则进入安全退出流程
                if not is_valid_comfy_path(comfy_path):
                    # 标记为致命启动失败，后续 run() 将直接退出，避免 AttributeError
                    self._fatal_startup_error = True
                    try:
                        self.root.withdraw()
                    except Exception:
                        pass
                    messagebox.showerror("错误", "未能定位 ComfyUI 根目录，程序将退出")
                    # 不销毁 root，这样 run() 可以安全地返回；交由 run() 做最终退出处理
                    return

        # 写回配置以便后续使用
        self.config["paths"]["comfyui_path"] = str(comfy_path)
        try:
            json.dump(self.config, open(self.config_file, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        except Exception:
            pass

        # 解析并固定 Python 可执行路径，避免相对路径在不同工作目录下失效
        def resolve_python_exec() -> Path:
            cfg_path = Path(self.config["paths"].get("python_path", "python_embeded/python.exe"))
            candidates = []
            # 已是绝对路径
            if cfg_path.is_absolute():
                candidates.append(cfg_path)
            # 相对路径：尝试当前工作目录
            candidates.append(Path.cwd() / cfg_path)
            # 启动器目录（launcher 上级）
            try:
                app_root = Path(__file__).resolve().parent.parent
                candidates.append(app_root / cfg_path)
                candidates.append(app_root / "python_embeded" / "python.exe")
            except Exception:
                pass
            # 以 ComfyUI 路径为基准（ComfyUI 的上级应是根目录）
            try:
                candidates.append(Path(comfy_path).resolve().parent / "python_embeded" / "python.exe")
            except Exception:
                pass
            for c in candidates:
                try:
                    if c.exists():
                        return c
                except Exception:
                    pass
            return cfg_path

        py_exec = resolve_python_exec()
        self.python_exec = str(py_exec)
        # 将解析后的绝对路径写回配置，后续运行更稳健
        try:
            self.config["paths"]["python_path"] = self.python_exec
            json.dump(self.config, open(self.config_file, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        except Exception:
            pass

        self.load_settings()

        # 将父对象传入自身实例而非 Tk root，以便 VersionManager
        # 能访问启动器的 resolve_git() 与 git_path 等方法/属性
        self.version_manager = VersionManager(
            self,
            self.config["paths"]["comfyui_path"],
            self.config["paths"]["python_path"]
        )

        self.build_layout()
        threading.Thread(target=self.monitor_process, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ---------- 样式 ----------
    def setup_window(self):
        self.root.title("ComfyUI启动器 - 黎黎原上咩")
        self.root.geometry("1250x820")
        self.root.minsize(1100, 700)
        # 窗口图标：优先使用 rabbit.ico，适配 PyInstaller (sys._MEIPASS) 环境；失败则回退到 rabbit.png
        try:
            base_paths = []
            # 1) 运行时资源目录（PyInstaller）
            try:
                base_paths.append(Path(getattr(sys, '_MEIPASS', '')))
            except Exception:
                pass
            # 2) 源码所在的 launcher 目录
            try:
                base_paths.append(Path(__file__).resolve().parent)
            except Exception:
                pass
            # 3) 项目根目录下的 launcher 目录
            base_paths.append(Path('launcher').resolve())
            # 4) 可执行文件所在目录
            try:
                base_paths.append(Path(sys.executable).resolve().parent)
            except Exception:
                pass

            icon_candidates = []
            for b in base_paths:
                if b and b.exists():
                    icon_candidates.append(b / 'rabbit.ico')

            icon_set = False
            for p in icon_candidates:
                if p.exists():
                    try:
                        self.root.iconbitmap(str(p))
                        icon_set = True
                        break
                    except:
                        pass
            if not icon_set:
                png_candidates = []
                for b in base_paths:
                    if b and b.exists():
                        png_candidates.append(b / 'rabbit.png')
                for p in png_candidates:
                    if p.exists():
                        try:
                            self._icon_image = ImageTk.PhotoImage(file=str(p))
                            self.root.iconphoto(True, self._icon_image)
                            break
                        except:
                            pass
        except:
            pass
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
        # 额外启动参数（用户自定义，将与其它选项一起拼接到命令）
        self.extra_launch_args = tk.StringVar(value="")
        self.hf_mirror_options = {"不使用镜像": "", "hf-mirror": "https://hf-mirror.com"}
        self.selected_hf_mirror = tk.StringVar(value="hf-mirror")
        self.comfyui_version = tk.StringVar(value="获取中…")
        self.frontend_version = tk.StringVar(value="获取中…")
        self.template_version = tk.StringVar(value="获取中…")
        self.python_version = tk.StringVar(value="获取中…")
        self.torch_version = tk.StringVar(value="获取中…")
        # Git 状态展示（使用系统Git / 使用整合包Git / 未找到Git命令 等）
        self.git_status = tk.StringVar(value="检测中…")
        # 解析后的 Git 命令路径（'git' 或绝对路径；None 表示不可用）
        self.git_path = None
        self.update_core_var = tk.BooleanVar(value=True)
        self.update_frontend_var = tk.BooleanVar(value=True)
        self.update_template_var = tk.BooleanVar(value=True)

        # PyPI 代理设置（用于前端与模板库更新）
        proxy_cfg = self.config.get("proxy_settings", {}) if isinstance(self.config, dict) else {}
        default_pypi_mode = proxy_cfg.get("pypi_proxy_mode", "aliyun")
        default_pypi_url = proxy_cfg.get("pypi_proxy_url", "https://mirrors.aliyun.com/pypi/simple/")
        self.pypi_proxy_mode = tk.StringVar(value=default_pypi_mode)
        self.pypi_proxy_url = tk.StringVar(value=default_pypi_url)
        # UI 展示值（中文）
        def _pypi_mode_ui_text(mode: str):
            return "阿里云" if mode == "aliyun" else ("自定义" if mode == "custom" else "不使用")
        self.pypi_proxy_mode_ui = tk.StringVar(value=_pypi_mode_ui_text(default_pypi_mode))

        # 变更时持久化
        self.pypi_proxy_mode.trace_add("write", lambda *a: self.save_config())
        self.pypi_proxy_url.trace_add("write", lambda *a: self.save_config())

        self.compute_mode.trace_add("write", lambda *a: self.save_config())
        self.use_fast_mode.trace_add("write", lambda *a: self.save_config())
        self.enable_cors.trace_add("write", lambda *a: self.save_config())
        self.listen_all.trace_add("write", lambda *a: self.save_config())
        self.custom_port.trace_add("write", lambda *a: self.save_config())
        self.extra_launch_args.trace_add("write", lambda *a: self.save_config())
        # HF 镜像 URL（新增）
        default_hf_url = proxy_cfg.get("hf_mirror_url", "https://hf-mirror.com")
        self.hf_mirror_url = tk.StringVar(value=default_hf_url)
        self.selected_hf_mirror.trace_add("write", lambda *a: self.save_config())
        self.hf_mirror_url.trace_add("write", lambda *a: self.save_config())

    def load_config(self):
        try:
            self.logger.info("加载配置文件: %s (exists=%s)", str(self.config_file), self.config_file.exists())
        except Exception:
            pass
        default = {
            "launch_options": {
                "default_compute_mode": "gpu",
                "default_port": "8188",
                "enable_fast_mode": False,
                "enable_cors": True,
                "listen_all": True,
                "extra_args": ""
            },
            "ui_settings": {
                "window_width": 800,
                "window_height": 600,
                "theme": "default",
                "font_size": 9,
                "log_max_lines": 1000,
                "window_size": "500x650"
            },
            "paths": {
                "comfyui_root": ".",
                "python_embeded": "python_embeded",
                "custom_nodes": "ComfyUI/custom_nodes",
                "bat_files_directory": ".",
                "comfyui_path": "ComfyUI",
                "python_path": "python_embeded/python.exe",
                "hf_mirror": "hf-mirror"
            },
            "advanced": {
                "check_environment_changes": True,
                "show_debug_info": False,
                "auto_scroll_logs": True,
                "save_logs": False
            },
            "proxy_settings": {
            "git_proxy_mode": "gh-proxy",
            "git_proxy_url": "https://gh-proxy.com/",
            "pypi_proxy_mode": "aliyun",
            "pypi_proxy_url": "https://mirrors.aliyun.com/pypi/simple/",
            "hf_mirror_url": "https://hf-mirror.com"
        }
        }
        self.config_file.parent.mkdir(exist_ok=True)
        if self.config_file.exists():
            try:
                self.config = json.load(open(self.config_file, 'r', encoding='utf-8'))
                try:
                    self.logger.info("配置读取成功")
                except Exception:
                    pass
            except:
                self.config = default
                try:
                    self.logger.warning("配置读取失败，使用默认值")
                except Exception:
                    pass
        else:
            # 直接写入默认配置，避免在变量尚未初始化时调用 save_config
            self.config = default
            try:
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                try:
                    self.logger.info("首次创建配置文件并写入默认值")
                except Exception:
                    pass
            except:
                pass

    def save_config(self):
        try:
            self.logger.info("保存配置到: %s", str(self.config_file))
        except Exception:
            pass
        # 保护性获取变量，避免在初始化早期因为变量不存在而报错
        def _get(var, default):
            try:
                return var.get()
            except Exception:
                return default

        self.config["launch_options"] = {
            "default_compute_mode": _get(self.compute_mode, "gpu"),
            "default_port": _get(self.custom_port, "8188"),
            "enable_fast_mode": _get(self.use_fast_mode, False),
            "enable_cors": _get(self.enable_cors, True),
            "listen_all": _get(self.listen_all, True),
            "extra_args": _get(self.extra_launch_args, ""),
        }
        # 记录镜像选项（模式与 URL）
        self.config["paths"]["hf_mirror"] = _get(self.selected_hf_mirror, "hf-mirror")
        # 保存代理设置
        ps = self.config.setdefault("proxy_settings", {})
        try:
            ps["pypi_proxy_mode"] = _get(self.pypi_proxy_mode, "aliyun")
            ps["pypi_proxy_url"] = _get(self.pypi_proxy_url, "https://mirrors.aliyun.com/pypi/simple/")
            ps["hf_mirror_url"] = _get(self.hf_mirror_url, "https://hf-mirror.com")
        except Exception:
            pass
        json.dump(self.config, open(self.config_file, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        try:
            self.logger.info("配置保存完成")
        except Exception:
            pass

    def load_settings(self):
        opt = self.config.get("launch_options", {})
        self.compute_mode.set(opt.get("default_compute_mode", "gpu"))
        self.custom_port.set(opt.get("default_port", "8188"))
        self.use_fast_mode.set(opt.get("enable_fast_mode", False))
        self.enable_cors.set(opt.get("enable_cors", True))
        self.listen_all.set(opt.get("listen_all", True))
        self.extra_launch_args.set(opt.get("extra_args", ""))

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
            try:
                self.version_manager.attach_to_container(self.version_container)
            except Exception as e:
                # 将异常记录到启动器日志，便于诊断
                try:
                    self.logger.exception(f"切换到内核版本管理出错: {e}")
                except Exception:
                    pass
                # 同时弹出错误提示，避免静默失败
                try:
                    messagebox.showerror("错误", f"切换到内核版本管理失败: {e}")
                except Exception:
                    pass
            self._vm_embedded = True

    # ---------- Launch Tab ----------
    def build_launch_tab(self, parent):
        c = self.COLORS

        header = tk.Frame(parent, bg=c["BG"])
        header.pack(fill=tk.X, pady=(6, 6))

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
                                   padding=(16, 12, 16, 12))
        version_card.pack(fill=tk.X, pady=(0, 10))
        self._build_version_section(version_card.get_body())

        quick_card = SectionCard(parent, "快捷目录", icon="🗂",
                                 border_color=self.CARD_BORDER_COLOR,
                                 bg=self.CARD_BG,
                                 title_font=self.SECTION_TITLE_FONT,
                                 # 轻微压缩顶部留白，并降低内容与标题间距
                                 padding=(14, 8, 14, 10),
                                 inner_gap=10)
        quick_card.pack(fill=tk.X, pady=(0, 10))
        self._build_quick_links(quick_card.get_body(), path=self.config["paths"]["comfyui_path"])

        self.get_version_info()

    def _build_start_button(self, parent):
        self.big_btn = BigLaunchButton(parent,
                                       text="一键启动",
                                       size=170,
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
        # 改用原生 tk.Checkbutton，Windows 下选中为对号，更贴近用户预期
        tk.Checkbutton(checks, text="快速模式 (fp16)",
                       variable=self.use_fast_mode,
                       bg=self.CARD_BG, fg=self.COLORS["TEXT"],
                       activebackground=self.CARD_BG, activeforeground=self.COLORS["TEXT"],
                       selectcolor=self.CARD_BG) \
            .pack(side=tk.LEFT, padx=(0, INLINE_GAP))
        tk.Checkbutton(checks, text="启用 CORS",
                       variable=self.enable_cors,
                       bg=self.CARD_BG, fg=self.COLORS["TEXT"],
                       activebackground=self.CARD_BG, activeforeground=self.COLORS["TEXT"],
                       selectcolor=self.CARD_BG) \
            .pack(side=tk.LEFT, padx=(0, INLINE_GAP))
        tk.Checkbutton(checks, text="监听 0.0.0.0",
                       variable=self.listen_all,
                       bg=self.CARD_BG, fg=self.COLORS["TEXT"],
                       activebackground=self.CARD_BG, activeforeground=self.COLORS["TEXT"],
                       selectcolor=self.CARD_BG) \
            .pack(side=tk.LEFT)
        # 右侧加入额外选项输入
        tk.Frame(checks, bg=self.CARD_BG).pack(side=tk.LEFT, expand=True)  # 弹性占位，使右侧靠齐
        tk.Label(checks, text="额外选项:", bg=self.CARD_BG, fg=c["TEXT"], font=BODY_FONT) \
            .pack(side=tk.LEFT, padx=(INLINE_GAP, 8))
        ttk.Entry(checks, textvariable=self.extra_launch_args, width=36) \
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
        # 增加“自定义”选项并添加输入框
        self.hf_mirror_combobox = ttk.Combobox(
            port_row,
            textvariable=self.selected_hf_mirror,
            values=["不使用镜像", "hf-mirror", "自定义"],
            state="readonly",
            width=12
        )
        self.hf_mirror_combobox.pack(side=tk.LEFT)
        # HF 镜像 URL 输入框（与 GitHub 代理行为一致）
        self.hf_mirror_entry = ttk.Entry(port_row, textvariable=self.hf_mirror_url, width=26)
        self.hf_mirror_entry.pack(side=tk.LEFT, padx=(8, 0))
        self.hf_mirror_combobox.bind("<<ComboboxSelected>>", self.on_hf_mirror_selected)
        # 初始化输入框状态
        try:
            self.on_hf_mirror_selected()
        except Exception:
            pass

        btn_row = tk.Frame(form, bg=self.CARD_BG)
        btn_row.grid(row=3, column=1, sticky="w", pady=(BUTTON_TOP_GAP, 0))
        ttk.Button(btn_row, text="恢复默认设置",
                   style='Secondary.TButton',
                   command=self.reset_settings).pack(side=tk.LEFT)

        tk.Frame(container, bg=self.CARD_BG, height=2).pack(fill=tk.X)

    # ====== 版本与更新 ======
    def _build_version_section(self, container):
        c = self.COLORS
        # —— 当前版本 ——
        tk.Label(container, text="当前版本:", bg=self.CARD_BG, fg=c["TEXT"],
                 font=self.INTERNAL_HEAD_LABEL_FONT).pack(anchor='w')
        current_frame = tk.Frame(container, bg=self.CARD_BG)
        current_frame.pack(fill=tk.X, pady=(6, 0))
        items = [("内核", self.comfyui_version),
                 ("前端", self.frontend_version),
                 ("模板库", self.template_version),
                 ("Python", self.python_version),
                 ("Torch", self.torch_version),
                 ("Git", self.git_status)]
        grid = tk.Frame(current_frame, bg=self.CARD_BG)
        grid.pack(fill=tk.X)
        for i, (lbl, var) in enumerate(items):
            col = tk.Frame(grid, bg=self.CARD_BG)
            col.grid(row=0, column=i, padx=8, sticky='w')
            grid.columnconfigure(i, weight=1)
            tk.Label(col, text=f"{lbl}:", bg=self.CARD_BG, fg=c["TEXT_MUTED"],
                     font=self.BODY_FONT).pack(anchor='w')
            tk.Label(col, textvariable=var, bg=self.CARD_BG, fg=c["TEXT"],
                     font=("Consolas", 11)).pack(anchor='w', pady=(2, 0))

        # —— 批量更新 ——
        batch_card = tk.Frame(container, bg=self.CARD_BG)
        batch_card.pack(fill=tk.X, pady=(16, 0))
        tk.Label(batch_card, text="批量更新:", bg=self.CARD_BG, fg=c["TEXT"],
                 font=self.INTERNAL_HEAD_LABEL_FONT).pack(anchor='w', padx=(0, 8))

        # 表单与按钮并排：左侧为统一表单（复选与代理），右侧为更新按钮
        proxy_area = tk.Frame(batch_card, bg=self.CARD_BG)
        proxy_area.pack(fill=tk.X, pady=(8, 0))

        # 左侧表单区（不超过内容区一半宽度）
        form_frame = tk.Frame(proxy_area, bg=self.CARD_BG)
        form_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        form_frame.grid_columnconfigure(0, weight=0)
        form_frame.grid_columnconfigure(1, weight=0)
        # 缩短输入框并避免过度拉伸：不让第2列随父容器扩展
        form_frame.grid_columnconfigure(2, weight=0)

        # 保持自然宽度布局：不强制限制为 50%，避免子控件被裁剪
        # 如需限制最大宽度，可后续改为在父容器上使用网格两列分布来控制比例

        # 第0行：更新项（复选框）
        # 统一与启动控制中“快速模式”等勾选项的字号：去掉自定义字体，使用系统默认字体
        tk.Label(form_frame, text="更新项:", bg=self.CARD_BG, fg=c["TEXT"]).grid(
            row=0, column=0, sticky='w', padx=(0, 10), pady=(0, 6)
        )
        opts = tk.Frame(form_frame, bg=self.CARD_BG)
        opts.grid(row=0, column=1, columnspan=2, sticky='w', pady=(0, 6))
        self.core_chk = tk.Checkbutton(
            opts, text="内核", variable=self.update_core_var,
            bg=self.CARD_BG, fg=c["TEXT"],
            activebackground=self.CARD_BG, activeforeground=c["TEXT"],
            selectcolor=self.CARD_BG
        )
        self.front_chk = tk.Checkbutton(
            opts, text="前端", variable=self.update_frontend_var,
            bg=self.CARD_BG, fg=c["TEXT"],
            activebackground=self.CARD_BG, activeforeground=c["TEXT"],
            selectcolor=self.CARD_BG
        )
        self.tpl_chk = tk.Checkbutton(
            opts, text="模板库", variable=self.update_template_var,
            bg=self.CARD_BG, fg=c["TEXT"],
            activebackground=self.CARD_BG, activeforeground=c["TEXT"],
            selectcolor=self.CARD_BG
        )
        self.core_chk.pack(side=tk.LEFT, padx=(0, 10))
        self.front_chk.pack(side=tk.LEFT, padx=(0, 10))
        self.tpl_chk.pack(side=tk.LEFT)

        # 第1行：GitHub 代理
        # 与勾选项统一字号，使用系统默认字体
        tk.Label(form_frame, text="GitHub代理:", bg=self.CARD_BG, fg=c["TEXT"]).grid(
            row=1, column=0, sticky='w', padx=(0, 10), pady=(0, 6)
        )
        self.github_proxy_mode_combo = ttk.Combobox(
            form_frame,
            textvariable=self.version_manager.proxy_mode_ui_var,
            values=["不使用", "gh-proxy", "自定义"],
            state='readonly',
            width=12
        )
        self.github_proxy_mode_combo.grid(row=1, column=1, sticky='w', padx=(0, 8), pady=(0, 6))
        self.github_proxy_url_entry = ttk.Entry(
            form_frame,
            textvariable=self.version_manager.proxy_url_var,
            width=24
        )
        # 不随列扩展，保持较短宽度
        self.github_proxy_url_entry.grid(row=1, column=2, sticky='w', padx=(0, 8), pady=(0, 6))

        def _set_github_entry_visibility():
            try:
                mode = self.version_manager.proxy_mode_var.get()
                if mode == 'custom':
                    if not self.github_proxy_url_entry.winfo_ismapped():
                        self.github_proxy_url_entry.grid(row=1, column=2, sticky='w', padx=(0, 8), pady=(0, 6))
                    self.github_proxy_url_entry.configure(state='normal')
                else:
                    self.github_proxy_url_entry.grid_remove()
                    self.github_proxy_url_entry.configure(state='disabled')
            except Exception:
                pass

        def _on_mode_change_local(_evt=None):
            try:
                vm = self.version_manager
                vm.proxy_mode_var.set(vm._get_mode_internal(vm.proxy_mode_ui_var.get()))
                if vm.proxy_mode_var.get() == 'gh-proxy':
                    vm.proxy_url_var.set('https://gh-proxy.com/')
                _set_github_entry_visibility()
                vm.save_proxy_settings()
            except Exception:
                pass

        try:
            self.github_proxy_mode_combo.bind('<<ComboboxSelected>>', _on_mode_change_local)
            _set_github_entry_visibility()
        except Exception:
            pass

        # 第2行：PyPI 代理
        # 与勾选项统一字号，使用系统默认字体
        tk.Label(form_frame, text="PyPI代理:", bg=self.CARD_BG, fg=c["TEXT"]).grid(
            row=2, column=0, sticky='w', padx=(0, 10)
        )
        self.pypi_proxy_mode_combo = ttk.Combobox(
            form_frame,
            textvariable=self.pypi_proxy_mode_ui,
            values=["不使用", "阿里云", "自定义"],
            state='readonly',
            width=12
        )
        self.pypi_proxy_mode_combo.grid(row=2, column=1, sticky='w', padx=(0, 8))
        self.pypi_proxy_url_entry = ttk.Entry(
            form_frame,
            textvariable=self.pypi_proxy_url,
            width=24
        )
        self.pypi_proxy_url_entry.grid(row=2, column=2, sticky='w', padx=(0, 8))

        def _set_pypi_entry_visibility():
            try:
                mode = self.pypi_proxy_mode.get()
                if mode == 'custom':
                    if not self.pypi_proxy_url_entry.winfo_ismapped():
                        self.pypi_proxy_url_entry.grid(row=2, column=2, sticky='w', padx=(0, 8))
                    self.pypi_proxy_url_entry.configure(state='normal')
                else:
                    self.pypi_proxy_url_entry.grid_remove()
                    self.pypi_proxy_url_entry.configure(state='disabled')
            except Exception:
                pass

        def _pypi_mode_internal(ui_text: str) -> str:
            if ui_text == "阿里云":
                return "aliyun"
            if ui_text == "自定义":
                return "custom"
            return "none"

        def _on_pypi_mode_change(_evt=None):
            try:
                self.pypi_proxy_mode.set(_pypi_mode_internal(self.pypi_proxy_mode_ui.get()))
                if self.pypi_proxy_mode.get() == 'aliyun':
                    self.pypi_proxy_url.set('https://mirrors.aliyun.com/pypi/simple/')
                _set_pypi_entry_visibility()
                self.save_config()
            except Exception:
                pass

        try:
            self.pypi_proxy_mode_combo.bind('<<ComboboxSelected>>', _on_pypi_mode_change)
            _set_pypi_entry_visibility()
        except Exception:
            pass

        # 右侧小号“更新”按钮（仿照一键启动样式）
        update_btn_container = tk.Frame(proxy_area, bg=self.CARD_BG)
        update_btn_container.pack(side=tk.RIGHT, padx=(48, 0))
        self.batch_update_btn = BigLaunchButton(update_btn_container, text="更新",
                                                size=110, radius=20,
                                                color="#2F6EF6", hover="#2760DB", active="#1F52BE",
                                                command=self.perform_batch_update)
        self.batch_update_btn.pack()
        self.frontend_update_btn = self.batch_update_btn
        self.template_update_btn = self.batch_update_btn
        self.batch_updating = False

    def _build_quick_links(self, container, path=None):
        c = self.COLORS
        if path:
            self.path_label = tk.Label(
                container,
                text=f"路径: {Path(path).resolve()}",
                bg=self.CARD_BG, fg=c["TEXT_MUTED"],
                font=self.BODY_FONT
            )
            self.path_label.pack(anchor='w', padx=(4, 0), pady=(0, 6))

        # 容器：自然高度的自适应网格（不强制滚动，高度随内容扩展）
        grid = tk.Frame(container, bg=self.CARD_BG)
        grid.pack(fill=tk.X)
        self.quick_grid_frame = grid

        self.quick_buttons = []
        for txt, cmd in [
            ("根目录", self.open_root_dir),
            ("日志文件", self.open_logs_dir),
            ("输入目录", self.open_input_dir),
            ("输出目录", self.open_output_dir),
            ("插件目录", self.open_plugins_dir),
            ("重设ComfyUI目录", self.reset_comfyui_path),
        ]:
            btn_style = 'Accent.TButton' if '重新设置' in txt else 'Secondary.TButton'
            btn = ttk.Button(grid, text=txt, style=btn_style, command=cmd)
            self.quick_buttons.append(btn)

        def _relayout(_evt=None):
            # 计算列数并网格布局（自动换行）
            try:
                width = max(0, grid.winfo_width())
            except Exception:
                width = 800
            min_btn = 120  # 单按钮最小占位宽度（含左右间距）
            cols = max(3, min(6, max(1, width // min_btn)))
            for i, btn in enumerate(self.quick_buttons):
                r, cidx = divmod(i, cols)
                # 进一步压缩垂直间距，并使按钮在单元格内充分扩展
                btn.grid(row=r, column=cidx, padx=6, pady=(4, 6), sticky='nsew')
            for ci in range(cols):
                grid.grid_columnconfigure(ci, weight=1, uniform='quick')

        grid.bind('<Configure>', _relayout)
        self.root.after(0, _relayout)

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
        try:
            self.logger.info("点击一键启动/停止")
        except Exception:
            pass
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
            # 追加自定义额外参数（支持引号与空格）
            extra = (self.extra_launch_args.get() or "").strip()
            if extra:
                try:
                    extra_tokens = shlex.split(extra)
                except Exception:
                    extra_tokens = extra.split()
                cmd.extend(extra_tokens)
            try:
                self.logger.info("启动命令: %s", " ".join(cmd))
                if extra:
                    self.logger.info("附加参数: %s", extra)
            except Exception:
                pass
            env = os.environ.copy()
            sel = self.selected_hf_mirror.get()
            if sel != "不使用镜像":
                # 使用输入框的 URL；当选择“hf-mirror”时已自动填充默认值
                endpoint = (self.hf_mirror_url.get() or "").strip()
                if endpoint:
                    env["HF_ENDPOINT"] = endpoint
            try:
                self.logger.info("环境变量(HF_ENDPOINT): %s", env.get("HF_ENDPOINT", ""))
            except Exception:
                pass
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
                    msg = str(e)
                    # 捕获当前异常信息到默认参数，避免闭包中变量未绑定问题
                    self.root.after(0, lambda m=msg: self.on_start_failed(m))

            threading.Thread(target=worker, daemon=True).start()
        except Exception as e:
            msg = str(e)
            try:
                messagebox.showerror("启动失败", msg)
            except Exception:
                pass
            # 同样使用默认参数绑定，避免在 after 回调中出现自由变量问题
            self.on_start_failed(msg)

    def on_start_success(self):
        try:
            self.logger.info("ComfyUI 启动成功")
        except Exception:
            pass
        self.big_btn.set_state("running")
        self.big_btn.set_text("停止")

    def on_start_failed(self, error):
        try:
            self.logger.error("ComfyUI 启动失败: %s", error)
        except Exception:
            pass
        self.big_btn.set_state("idle")
        self.big_btn.set_text("一键启动")
        self.comfyui_process = None

    def stop_comfyui(self):
        try:
            self.logger.info("尝试停止 ComfyUI 进程")
        except Exception:
            pass
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
        try:
            self.logger.info("ComfyUI 进程结束")
        except Exception:
            pass
        self.comfyui_process = None
        self.big_btn.set_state("idle")
        self.big_btn.set_text("一键启动")

    # ---------- 目录 ----------
    def _open_dir(self, path: Path):
        try:
            self.logger.info("打开目录: %s", str(path))
        except Exception:
            pass
        path.mkdir(parents=True, exist_ok=True)
        if path.exists():
            os.startfile(str(path))
        else:
            messagebox.showwarning("警告", f"目录不存在: {path}")

    # ---------- 文件 ----------
    def _open_file(self, path: Path):
        try:
            self.logger.info("打开文件: %s", str(path))
        except Exception:
            pass
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
        url = f"http://127.0.0.1:{self.custom_port.get() or '8188'}"
        try:
            self.logger.info("打开网页: %s", url)
        except Exception:
            pass
        webbrowser.open(url)

    def reset_settings(self):
        if messagebox.askyesno("确认", "确定恢复默认设置?"):
            self.compute_mode.set("gpu")
            self.custom_port.set("8188")
            self.use_fast_mode.set(False)
            self.enable_cors.set(True)
            self.listen_all.set(True)
            self.selected_hf_mirror.set("hf-mirror")
            # 恢复默认时清空额外选项输入
            try:
                self.extra_launch_args.set("")
            except Exception:
                pass
            self.save_config()
            try:
                self.logger.info("已恢复默认设置")
            except Exception:
                pass
            messagebox.showinfo("完成", "已恢复默认设置")

    def reset_comfyui_path(self):
        # 选择新的 ComfyUI 根目录
        selected = filedialog.askdirectory(title="请选择 ComfyUI 根目录")
        if not selected:
            return
        new_path = Path(selected).resolve()
        try:
            self.logger.info("设置 ComfyUI 路径: %s", str(new_path))
        except Exception:
            pass
        # 校验：存在且包含 main.py 或 .git
        if not (new_path.exists() and ((new_path / "main.py").exists() or (new_path / ".git").exists())):
            messagebox.showerror("错误", "所选目录似乎不是 ComfyUI 根目录（缺少 main.py 或 .git）")
            return

        # 更新配置并保存
        self.config["paths"]["comfyui_path"] = str(new_path)
        try:
            self.save_config()
        except Exception:
            pass

        # 更新路径标签
        try:
            if hasattr(self, 'path_label') and self.path_label.winfo_exists():
                self.path_label.config(text=f"路径: {new_path}")
        except Exception:
            pass

        # 更新 VersionManager 的路径并刷新信息（若已创建）
        try:
            if hasattr(self, 'version_manager') and self.version_manager:
                self.version_manager.comfyui_path = new_path
                # 如果版本页已嵌入或窗口打开，尝试刷新
                try:
                    self.version_manager.refresh_git_info()
                except Exception:
                    pass
        except Exception:
            pass

        # 重新获取版本信息，更新“版本与更新”区域状态
        try:
            try:
                self.logger.info("刷新版本信息（因路径更新）")
            except Exception:
                pass
            self.get_version_info()
        except Exception:
            pass

        messagebox.showinfo("完成", "ComfyUI 目录已更新")

    # ---------- 版本 ----------
    def get_version_info(self, scope: str = "all"):
        try:
            self.logger.info("开始获取版本信息")
        except Exception:
            pass
        if getattr(self, '_version_info_loading', False):
            return
        self._version_info_loading = True
        if scope == "all":
            for v in (self.comfyui_version, self.frontend_version,
                      self.template_version, self.python_version, self.torch_version):
                v.set("获取中…")
        else:
            try:
                self.comfyui_version.set("获取中…")
            except Exception:
                pass

        def worker():
            try:
                root = Path(self.config["paths"]["comfyui_path"]).resolve()
                # 解析 Git 路径与来源（不直接更新 UI）
                git_cmd, git_source_text = self.resolve_git()
                # 目录存在性与仓库状态
                repo_state = ""
                if git_cmd is None:
                    repo_state = "未找到Git命令"
                elif not root.exists():
                    repo_state = "ComfyUI未找到"
                else:
                    try:
                        r_repo = run_hidden([git_cmd, "rev-parse", "--is-inside-work-tree"],
                                            cwd=str(root), capture_output=True, text=True, timeout=5)
                        repo_state = "Git正常" if (r_repo.returncode == 0 and r_repo.stdout.strip() == "true") else "非Git仓库"
                    except Exception:
                        repo_state = "非Git仓库"

                # Git 文案：优先来源文本；遇到异常则显示具体错误
                git_text_to_show = repo_state if repo_state in ("未找到Git命令", "非Git仓库", "ComfyUI未找到") else git_source_text
                self.root.after(0, lambda: self.git_status.set(git_text_to_show))

                # 更新按钮可用性
                def _update_git_controls():
                    status = self.git_status.get()
                    disable = status in ("未安装Git", "非Git仓库", "ComfyUI未找到", "未找到Git命令")
                    try:
                        # 新的复选框控件
                        if hasattr(self, 'core_chk'):
                            self.core_chk.config(state='disabled' if disable else 'normal')
                        if hasattr(self, 'front_chk'):
                            self.front_chk.config(state='disabled' if disable else 'normal')
                        if hasattr(self, 'tpl_chk'):
                            self.tpl_chk.config(state='disabled' if disable else 'normal')
                        if hasattr(self, 'batch_update_btn'):
                            self.batch_update_btn.config(state='disabled' if disable else 'normal')
                    except:
                        pass
                self.root.after(0, _update_git_controls)

                if root.exists() and self.git_path:
                    try:
                        r = run_hidden([self.git_path, "describe", "--tags", "--abbrev=0"],
                                           cwd=str(root), capture_output=True, text=True, timeout=10)
                        if r.returncode == 0:
                            tag = r.stdout.strip()
                            r2 = run_hidden([self.git_path, "rev-parse", "--short", "HEAD"],
                                                cwd=str(root), capture_output=True, text=True, timeout=10)
                            commit = r2.stdout.strip() if r2.returncode == 0 else ""
                            self.root.after(0, lambda t=tag, c=commit: self.comfyui_version.set(f"{t} ({c})"))
                        else:
                            self.root.after(0, lambda: self.comfyui_version.set("未找到"))
                    except:
                        self.root.after(0, lambda: self.comfyui_version.set("未找到"))
                else:
                    self.root.after(0, lambda: self.comfyui_version.set("ComfyUI未找到"))

                if scope == "all":
                    try:
                        r = run_hidden([self.python_exec, "--version"],
                                           capture_output=True, text=True, timeout=10)
                        if r.returncode == 0:
                            self.root.after(0, lambda v=r.stdout.strip().replace("Python ", ""): self.python_version.set(v))
                        else:
                            self.root.after(0, lambda: self.python_version.set("无法获取"))
                    except:
                        self.root.after(0, lambda: self.python_version.set("获取失败"))

                if scope == "all":
                    try:
                        r = run_hidden([self.python_exec, "-c", "import torch;print(torch.__version__)"],
                                           capture_output=True, text=True, timeout=15)
                        if r.returncode == 0:
                            self.root.after(0, lambda v=r.stdout.strip(): self.torch_version.set(v))
                        else:
                            self.root.after(0, lambda: self.torch_version.set("未安装"))
                    except:
                        self.root.after(0, lambda: self.torch_version.set("获取失败"))

                if scope == "all":
                    try:
                        # 优先使用 python -m pip
                        r = run_hidden([self.python_exec, "-m", "pip", "show", "comfyui-frontend-package"],
                                           capture_output=True, text=True, timeout=10)
                        if r.returncode == 0:
                            for line in r.stdout.splitlines():
                                if line.startswith("Version:"):
                                    ver = "v" + line.split(":")[1].strip()
                                    self.root.after(0, lambda v=ver: self.frontend_version.set(v))
                                    break
                            else:
                                self.root.after(0, lambda: self.frontend_version.set("未安装"))
                        else:
                            # 备用：直接调用 Scripts\pip.exe
                            try:
                                pip_exe = Path(self.python_exec).resolve().parent.parent / "Scripts" / "pip.exe"
                                if pip_exe.exists():
                                    r2 = run_hidden([str(pip_exe), "show", "comfyui-frontend-package"],
                                                    capture_output=True, text=True, timeout=10)
                                    if r2.returncode == 0:
                                        for line in r2.stdout.splitlines():
                                            if line.startswith("Version:"):
                                                ver = "v" + line.split(":")[1].strip()
                                                self.root.after(0, lambda v=ver: self.frontend_version.set(v))
                                                break
                                        else:
                                            self.root.after(0, lambda: self.frontend_version.set("未安装"))
                                    else:
                                        self.root.after(0, lambda: self.frontend_version.set("未安装"))
                                else:
                                    self.root.after(0, lambda: self.frontend_version.set("未安装"))
                            except:
                                self.root.after(0, lambda: self.frontend_version.set("未安装"))
                    except:
                        self.root.after(0, lambda: self.frontend_version.set("获取失败"))

                if scope == "all":
                    try:
                        r = run_hidden([self.python_exec, "-m", "pip", "show", "comfyui-workflow-templates"],
                                           capture_output=True, text=True, timeout=10)
                        if r.returncode == 0:
                            for line in r.stdout.splitlines():
                                if line.startswith("Version:"):
                                    ver = "v" + line.split(":")[1].strip()
                                    self.root.after(0, lambda v=ver: self.template_version.set(v))
                                    break
                            else:
                                self.root.after(0, lambda: self.template_version.set("未安装"))
                        else:
                            # 备用：直接调用 Scripts\pip.exe
                            try:
                                pip_exe = Path(self.python_exec).resolve().parent.parent / "Scripts" / "pip.exe"
                                if pip_exe.exists():
                                    r2 = run_hidden([str(pip_exe), "show", "comfyui-workflow-templates"],
                                                    capture_output=True, text=True, timeout=10)
                                    if r2.returncode == 0:
                                        for line in r2.stdout.splitlines():
                                            if line.startswith("Version:"):
                                                ver = "v" + line.split(":")[1].strip()
                                                self.root.after(0, lambda v=ver: self.template_version.set(v))
                                                break
                                        else:
                                            self.root.after(0, lambda: self.template_version.set("未安装"))
                                    else:
                                        self.root.after(0, lambda: self.template_version.set("未安装"))
                                else:
                                    self.root.after(0, lambda: self.template_version.set("未安装"))
                            except:
                                self.root.after(0, lambda: self.template_version.set("未安装"))
                    except:
                        self.root.after(0, lambda: self.template_version.set("获取失败"))
            finally:
                self._version_info_loading = False

        threading.Thread(target=worker, daemon=True).start()

    def perform_batch_update(self):
        # 已在更新中则忽略重复点击
        if getattr(self, 'batch_updating', False):
            return
        self.batch_updating = True
        if hasattr(self, 'batch_update_btn'):
            # 更新按钮视觉为忙碌状态（BigLaunchButton 优先）
            try:
                if isinstance(self.batch_update_btn, BigLaunchButton):
                    self.batch_update_btn.set_text("更新中…")
                    self.batch_update_btn.set_state('starting')
                else:
                    self.batch_update_btn.config(text="更新中...", cursor='watch')
            except Exception:
                pass

        def worker():
            try:
                if self.update_core_var.get():
                    try:
                        # 使用 VersionManager 的更新逻辑（支持 GitHub 代理、分支解析与错误提示）
                        self.version_manager.update_to_latest()
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
                    if self.update_core_var.get() and not (self.update_frontend_var.get() or self.update_template_var.get()):
                        self.get_version_info(scope="core_only")
                    else:
                        self.get_version_info(scope="all")
                except:
                    pass
            finally:
                def _reset_btn():
                    self.batch_updating = False
                    if hasattr(self, 'batch_update_btn'):
                        try:
                            if isinstance(self.batch_update_btn, BigLaunchButton):
                                self.batch_update_btn.set_text("更新")
                                self.batch_update_btn.set_state('idle')
                            else:
                                self.batch_update_btn.config(text="更新", cursor='')
                        except Exception:
                            pass
                self.root.after(0, _reset_btn)

        threading.Thread(target=worker, daemon=True).start()

    def update_frontend(self):
        # 使用 PyPI 代理更新前端包 comfyui-frontend-package
        try:
            idx = None
            mode = self.pypi_proxy_mode.get()
            if mode == 'aliyun':
                idx = 'https://mirrors.aliyun.com/pypi/simple/'
            elif mode == 'custom':
                u = (self.pypi_proxy_url.get() or '').strip()
                if u:
                    idx = u
            # 优先使用嵌入的 pip
            pip_exe = Path(self.python_exec).resolve().parent.parent / "Scripts" / "pip.exe"
            cmd = [str(pip_exe if pip_exe.exists() else self.python_exec), "-m", "pip", "install", "-U", "comfyui-frontend-package"]
            if idx:
                cmd.extend(["-i", idx])
            run_hidden(cmd, capture_output=True, text=True)
        except Exception:
            pass

    def update_template_library(self):
        # 使用 PyPI 代理更新模板库 comfyui-workflow-templates
        try:
            idx = None
            mode = self.pypi_proxy_mode.get()
            if mode == 'aliyun':
                idx = 'https://mirrors.aliyun.com/pypi/simple/'
            elif mode == 'custom':
                u = (self.pypi_proxy_url.get() or '').strip()
                if u:
                    idx = u
            pip_exe = Path(self.python_exec).resolve().parent.parent / "Scripts" / "pip.exe"
            cmd = [str(pip_exe if pip_exe.exists() else self.python_exec), "-m", "pip", "install", "-U", "comfyui-workflow-templates"]
            if idx:
                cmd.extend(["-i", idx])
            run_hidden(cmd, capture_output=True, text=True)
        except Exception:
            pass

    # ---------- Git 解析 ----------
    def resolve_git(self):
        """解析应使用的 Git 可执行文件（线程安全：不直接更新 Tk 变量）。
        返回 (git_cmd_or_none, 来源文本)：来源文本为“使用整合包Git”“使用系统Git”或“未找到Git命令”。
        """
        # 1) 优先尝试便携 Git：tools/PortableGit/bin/git.exe（相对于启动器目录）
        pg_candidates = []
        try:
            pg_candidates.append(Path(sys.executable).resolve().parent / "tools" / "PortableGit" / "bin" / "git.exe")
        except Exception:
            pass
        try:
            # 优先查找启动器同级目录（launcher 的上一级）下的 tools/PortableGit/bin/git.exe
            pg_candidates.append(Path(__file__).resolve().parent.parent / "tools" / "PortableGit" / "bin" / "git.exe")
        except Exception:
            pass
        try:
            # 其次查找当前脚本所在目录下的 tools/PortableGit/bin/git.exe（兼容某些打包结构）
            pg_candidates.append(Path(__file__).resolve().parent / "tools" / "PortableGit" / "bin" / "git.exe")
        except Exception:
            pass
        pg_candidates.append(Path.cwd() / "tools" / "PortableGit" / "bin" / "git.exe")

        for c in pg_candidates:
            try:
                if c.exists():
                    r_pkg = run_hidden([str(c), "--version"], capture_output=True, text=True, timeout=5)
                    if r_pkg.returncode == 0:
                        self.git_path = str(c)
                        try:
                            self.logger.info(f"Git解析: 使用整合包Git path={self.git_path}")
                        except Exception:
                            pass
                        return self.git_path, "使用整合包Git"
            except Exception:
                pass

        # 2) 回退到系统 Git
        try:
            r_sys = run_hidden(["git", "--version"], capture_output=True, text=True, timeout=5)
            if r_sys.returncode == 0:
                self.git_path = "git"
                try:
                    self.logger.info("Git解析: 使用系统Git path=git")
                except Exception:
                    pass
                return self.git_path, "使用系统Git"
        except Exception:
            pass

        # 3) 未找到
        self.git_path = None
        try:
            self.logger.warning("Git解析: 未找到Git命令")
        except Exception:
            pass
        return None, "未找到Git命令"

    # ---------- 运行 ----------
    def run(self):
        # 如果启动阶段已经判定为致命错误，则直接安全退出
        if getattr(self, "_fatal_startup_error", False):
            try:
                self.root.destroy()
            except Exception:
                pass
            return
        # 正常路径：加载版本信息并进入消息循环
        self.get_version_info()
        self.root.mainloop()

    def on_hf_mirror_selected(self, _=None):
        try:
            sel = self.selected_hf_mirror.get()
            # 自定义时显示并可编辑；其他模式隐藏并禁用
            if sel == "自定义":
                try:
                    # 若未显示，则重新显示
                    if not self.hf_mirror_entry.winfo_ismapped():
                        self.hf_mirror_entry.pack(side=tk.LEFT, padx=(8, 0))
                except Exception:
                    pass
                self.hf_mirror_entry.configure(state='normal')
            else:
                if sel == "hf-mirror":
                    # 选择预设镜像时填充默认 URL
                    self.hf_mirror_url.set("https://hf-mirror.com")
                self.hf_mirror_entry.configure(state='disabled')
                try:
                    self.hf_mirror_entry.pack_forget()
                except Exception:
                    pass
            self.save_config()
        except Exception:
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

    # 注意：resolve_git 已移动到 ComfyUILauncherEnhanced 类中