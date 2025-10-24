import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont
import subprocess, threading, json, os, sys, webbrowser, tempfile, atexit, shutil
import ctypes
import shlex
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image, ImageTk
from version_manager import VersionManager
import paths as PATHS
import assets as ASSETS
import pip_utils as PIPUTILS
import net_utils as NETUTILS
from config_manager import ConfigManager
from utils import run_hidden, have_git, is_git_repo, SingletonLock
from logger_setup import install_logging
import locale
import logging
from ui import theme as THEME
from ui import version_panel as VERSION
from ui import quick_links_panel as QUICK
from ui import launch_controls_panel as LAUNCH
from ui import network_panel as NETWORK
from ui import about_tab as ABOUT
from ui import comfyui_tab as COMFY
from ui import start_button_panel as START
from ui import launcher_about_tab as LAUNCHER_ABOUT
from ui.custom_widges import BigLaunchButton, RoundedButton, SectionCard
from process_manager import ProcessManager

# ================== 单实例锁 ==================
try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None


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
        # 缓存 Windows wmic 可用性，避免重复尝试
        try:
            self._wmic_available = None
        except Exception:
            pass
        # 初始化界面配色，确保后续布局阶段可用，即使样式创建失败
        try:
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
            try:
                self.root.configure(bg=self.COLORS.get("BG", "#FFFFFF"))
            except Exception:
                pass
        except Exception:
            try:
                self.root.configure(bg="#FFFFFF")
            except Exception:
                pass
        # 统一工作目录为项目根目录（优先选择包含 ComfyUI/main.py 的目录），并在该根目录同级创建 launcher 日志目录
        try:
            base_root = PATHS.resolve_base_root()
            # 缓存根目录，并切换工作目录
            try:
                self._base_root = base_root
            except Exception:
                pass
            os.chdir(base_root)
            # 在确定根目录后再安装日志，确保日志始终写入 ComfyUI 同级的 launcher 目录
            try:
                self.logger = install_logging(log_root=base_root)
                try:
                    self.logger.info("启动器初始化")
                    self.logger.info("工作目录: %s", str(base_root))
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

        # 初始化窗口外观
        self.setup_window()

        # 基础配置与变量需尽早初始化，避免后续保护性路径检查时出现属性缺失
        try:
            config_file = (Path.cwd() / "launcher" / "config.json").resolve()
        except Exception:
            config_file = Path("launcher/config.json")
        self.config_manager = ConfigManager(config_file, self.logger)
        self.config = self.config_manager.load_config()
        # 根据配置或文件开关切换调试模式与日志级别（优先使用 launcher/is_debug 文件）
        try:
            dbg_cfg = False
            try:
                dbg_cfg = bool(self.config.get("advanced", {}).get("show_debug_info", False))
            except Exception:
                dbg_cfg = False
            is_debug_path = Path.cwd() / "launcher" / "is_debug"
            dbg_file = False
            try:
                dbg_file = is_debug_path.exists()
            except Exception:
                dbg_file = False
            # 如果配置要求调试，确保文件存在（不强制删除用户手动创建的调试标记）
            if dbg_cfg:
                try:
                    is_debug_path.parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
                try:
                    is_debug_path.write_text("debug\n", encoding="utf-8")
                except Exception:
                    pass
                dbg_file = True
            dbg_any = bool(dbg_cfg or dbg_file)
            try:
                self.logger.setLevel(logging.DEBUG if dbg_any else logging.INFO)
            except Exception:
                pass
        except Exception:
            pass
        self.setup_variables()

        # 允许在任意目录运行：如果未检测到有效的 ComfyUI 路径，则提示用户选择
        def is_valid_comfy_path(p: Path) -> bool:
            try:
                return PATHS.validate_comfy_root(p)
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
        py_exec = PATHS.resolve_python_exec(comfy_path, self.config["paths"].get("python_path", "python_embeded/python.exe"))
        self.python_exec = str(py_exec)
        # 将解析后的绝对路径写回配置，后续运行更稳健
        try:
            self.config["paths"]["python_path"] = self.python_exec
            json.dump(self.config, open(self.config_file, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
        except Exception:
            pass

        # 载入其他设置
        self.load_settings()

        # 初始化版本管理器（需要 comfyui_path 与 python_path 已解析）
        self.version_manager = VersionManager(
            self,
            self.config["paths"]["comfyui_path"],
            self.config["paths"]["python_path"]
        )

        # 初始化进程管理器
        self.process_manager = ProcessManager(self)

        # 构建界面、启动监控线程并设置关闭事件
        self.build_layout()
        threading.Thread(target=self.process_manager.monitor_process, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def apply_pip_proxy_settings(self):
        """根据当前 PyPI 代理设置更新 python_embeded/pip.ini。"""
        try:
            mode = self.pypi_proxy_mode.get() if hasattr(self.pypi_proxy_mode, 'get') else 'none'
            url = (self.pypi_proxy_url.get() or '').strip() if hasattr(self.pypi_proxy_url, 'get') else ''
            pip_proxy = (self.pip_proxy_url.get() or '').strip() if hasattr(self, 'pip_proxy_url') and hasattr(self.pip_proxy_url, 'get') else (
                (self.config.get('proxy_settings', {}) or {}).get('pip_proxy_url', '')
            )
            
            NETUTILS.apply_pip_proxy_settings(self.python_exec, mode, url, pip_proxy, getattr(self, 'logger', None))
        except Exception:
            try:
                self.logger.exception("应用 PyPI 代理到 pip.ini 时出错")
            except Exception:
                pass

    # ---------- 样式 ----------
    def setup_window(self):
        try:
            try:
                self.logger.info("开始设置窗口样式")
            except Exception:
                pass
            self.root.title("ComfyUI启动器 - 黎黎原上咩")
            self.root.geometry("1250x820")
            self.root.minsize(1100, 700)
            # Windows: 设置 AppUserModelID，改善任务栏图标与分组一致性
            try:
                if os.name == 'nt':
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ComfyUILauncher")
            except Exception:
                pass
            # 窗口图标设置委托到 assets 统一处理
            try:
                ASSETS.apply_window_icons(self.root, getattr(self, 'logger', None))
            except Exception:
                pass

            # 安全创建样式并选择可用主题（抽离到 THEME 模块）
            self.style = THEME.create_style(logger=self.logger)
            if not self.style:
                return

            THEME.apply_theme(self.style, logger=self.logger)

            # 隐藏辅助 Notebook 标签布局（若支持）
            try:
                try:
                    self.logger.info("样式阶段: 设置 Hidden.TNotebook.Tab 布局为空")
                except Exception:
                    pass
                self.style.layout('Hidden.TNotebook.Tab', [])
                try:
                    self.logger.info("样式阶段: Hidden.TNotebook.Tab 布局设置完成")
                except Exception:
                    pass
            except Exception:
                pass

            try:
                self.root.configure(bg=self.COLORS.get("BG", "#FFFFFF"))
            except Exception:
                pass
            THEME.configure_default_font(self.root, logger=self.logger)
            THEME.configure_styles(self.style, self.COLORS, logger=self.logger)
        except Exception:
            # 兜底：记录异常但不要让启动器崩溃
            try:
                self.logger.exception("setup_window 阶段发生异常，继续使用默认外观")
            except Exception:
                pass

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

        # 变更时持久化并自动应用到 pip.ini
        self.pypi_proxy_mode.trace_add("write", lambda *a: (self.save_config(), self.apply_pip_proxy_settings()))
        self.pypi_proxy_url.trace_add("write", lambda *a: (self.save_config(), self.apply_pip_proxy_settings()))

        # 启动选项变更时持久化
        self.compute_mode.trace_add("write", lambda *a: self.save_config())
        self.use_fast_mode.trace_add("write", lambda *a: self.save_config())
        self.enable_cors.trace_add("write", lambda *a: self.save_config())
        self.listen_all.trace_add("write", lambda *a: self.save_config())
        self.custom_port.trace_add("write", lambda *a: self.save_config())
        self.extra_launch_args.trace_add("write", lambda *a: self.save_config())

        # HF 镜像 URL
        default_hf_url = proxy_cfg.get("hf_mirror_url", "https://hf-mirror.com")
        self.hf_mirror_url = tk.StringVar(value=default_hf_url)
        self.selected_hf_mirror.trace_add("write", lambda *a: self.save_config())
        self.hf_mirror_url.trace_add("write", lambda *a: self.save_config())

    # 保护性获取 StringVar，确保界面构建阶段不会因变量未初始化而崩溃
    def _ensure_stringvar(self, attr_name: str, default: str = "获取中…"):
        v = getattr(self, attr_name, None)
        if isinstance(v, tk.StringVar):
            return v
        v = tk.StringVar(value=default)
        setattr(self, attr_name, v)
        return v

    def load_config(self):
        """加载配置 - 委托给 ConfigManager"""
        self.config = self.config_manager.load_config()

    def save_config(self):
        """保存配置 - 委托给 ConfigManager"""
        # 保护性获取变量，避免在初始化早期因为变量不存在而报错
        def _get(var, default):
            try:
                return var.get()
            except Exception:
                return default

        # 更新配置数据
        self.config_manager.update_launch_options(
            default_compute_mode=_get(self.compute_mode, "gpu"),
            default_port=_get(self.custom_port, "8188"),
            enable_fast_mode=_get(self.use_fast_mode, False),
            enable_cors=_get(self.enable_cors, True),
            listen_all=_get(self.listen_all, True),
            extra_args=_get(self.extra_launch_args, "")
        )
        
        # 记录镜像选项（模式与 URL）
        self.config_manager.set("paths.hf_mirror", _get(self.selected_hf_mirror, "hf-mirror"))
        
        # 保存代理设置
        try:
            self.config_manager.update_proxy_settings(
                pypi_proxy_mode=_get(self.pypi_proxy_mode, "aliyun"),
                pypi_proxy_url=_get(self.pypi_proxy_url, "https://mirrors.aliyun.com/pypi/simple/"),
                hf_mirror_url=_get(self.hf_mirror_url, "https://hf-mirror.com")
            )
        except Exception:
            pass
            
        # 保存到文件
        self.config_manager.save_config()
        # 同步本地配置引用
        self.config = self.config_manager.get_config()

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
        for key, label in [("launch", "🚀 启动与更新"), ("version", "🧬 内核版本管理"), ("about", "👤 关于我"), ("comfyui", "📚 关于ComfyUI"), ("about_launcher", "🧰 关于启动器")]:
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
            "comfyui": tk.Frame(self.notebook, bg=c["BG"]),
            "about": tk.Frame(self.notebook, bg=c["BG"]),
            "about_launcher": tk.Frame(self.notebook, bg=c["BG"]),
        }
        self.notebook.add(self.tab_frames["launch"], text="启动与更新")
        self.notebook.add(self.tab_frames["version"], text="内核版本管理")
        self.notebook.add(self.tab_frames["about"], text="关于我")
        self.notebook.add(self.tab_frames["comfyui"], text="关于 ComfyUI")
        self.notebook.add(self.tab_frames["about_launcher"], text="关于启动器")

        self.build_launch_tab(self.tab_frames["launch"])
        self.build_version_tab(self.tab_frames["version"])
        ABOUT.build_about_tab(self, self.tab_frames["about"])
        LAUNCHER_ABOUT.build_about_launcher(self, self.tab_frames["about_launcher"])
        COMFY.build_about_comfyui(self, self.tab_frames["comfyui"])

        self.notebook.select(self.notebook.tabs()[0])
        self.current_tab_name = "launch"

    def select_tab(self, name):
        tab_order = ["launch", "version", "about", "comfyui", "about_launcher"]
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

        LAUNCH.build_launch_controls_panel(self, left, RoundedButton)
        START.build_start_button_panel(self, right, BigLaunchButton)

        version_card = SectionCard(parent, "版本与更新", icon="🔄",
                                   border_color=self.CARD_BORDER_COLOR,
                                   bg=self.CARD_BG,
                                   title_font=self.SECTION_TITLE_FONT,
                                   padding=(16, 12, 16, 12))
        version_card.pack(fill=tk.X, pady=(0, 10))
        VERSION.build_version_panel(self, version_card.get_body(), RoundedButton)

        quick_card = SectionCard(parent, "快捷目录", icon="🗂",
                                 border_color=self.CARD_BORDER_COLOR,
                                 bg=self.CARD_BG,
                                 title_font=self.SECTION_TITLE_FONT,
                                 # 轻微压缩顶部留白，并降低内容与标题间距
                                 padding=(14, 8, 14, 10),
                                 inner_gap=10)
        quick_card.pack(fill=tk.X, pady=(0, 10))
        QUICK.build_quick_links_panel(self, quick_card.get_body(), path=self.config["paths"]["comfyui_path"], rounded_button_cls=RoundedButton)

        self.get_version_info()

    

    # ====== 启动控制 ======
    # 已移除历史兼容方法，主文件保持模块化调用

    # ====== 版本与更新 ======
    # 已移除历史兼容方法，主文件保持模块化调用

    # 已移除历史兼容方法，主文件保持模块化调用

    def _truncate_middle(self, text: str, max_chars: int) -> str:
        """以居中省略号的方式截断字符串到指定字符数。"""
        try:
            if not text or max_chars <= 0:
                return ""
            if len(text) <= max_chars:
                return text
            if max_chars <= 3:
                return text[:max_chars]
            keep = max_chars - 1  # 预留一个位置给省略号“…”
            head = keep // 2
            tail = keep - head
            return text[:head] + "…" + text[-tail:]
        except Exception:
            return text

    def _update_path_label_elide(self):
        """根据可用宽度将路径文本进行中间截断，避免顶栏按钮被挤出。"""
        try:
            try:
                from ui import helpers as UIHELP
            except Exception:
                # 兼容未作为包导入的场景
                import ui.helpers as UIHELP  # type: ignore
            elided = UIHELP.compute_elided_path_text(self)
            if hasattr(self, 'path_value_var'):
                self.path_value_var.set(elided)
        except Exception:
            # 回退：不截断
            try:
                if hasattr(self, 'path_value_var'):
                    full = getattr(self, "_path_full_text", None) or (self.path_value_var.get() if hasattr(self, 'path_value_var') else "")
                    self.path_value_var.set(full)
            except Exception:
                pass

    # ---------- 资源解析 ----------
    # 抽离到 assets.py，主文件不再持有解析实现

    # ---------- Version / About ----------
    def build_version_tab(self, parent):
        self.version_container = tk.Frame(parent, bg=self.COLORS["BG"]) 
        self.version_container.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)



    # ---------- 批量状态 ----------
    # 移除未使用的批量状态方法（旧版按钮式批量更新），避免误引用

    # 移除未使用的批量状态方法（旧版按钮式批量更新），避免误引用

    # ---------- 启动逻辑 ----------
    def toggle_comfyui(self):
        # 委托到进程管理器统一处理
        self.process_manager.toggle_comfyui()

    def start_comfyui(self):
        # 委托到进程管理器统一处理
        self.process_manager.start_comfyui()

    def on_start_success(self):
        # 委托到进程管理器统一处理
        self.process_manager.on_start_success()

    def on_start_failed(self, error):
        # 委托到进程管理器统一处理
        self.process_manager.on_start_failed(error)

    def stop_comfyui(self):
        # 委托到进程管理器统一处理
        self.process_manager.stop_comfyui()

    def _find_pids_by_port_safe(self, port_str):
        # 委托到进程管理器统一处理
        return self.process_manager._find_pids_by_port_safe(port_str)

    def _is_comfyui_pid(self, pid: int) -> bool:
        # 委托到进程管理器统一处理
        return self.process_manager._is_comfyui_pid(pid)

    def _kill_pids(self, pids):
        # 委托到进程管理器统一处理
        return self.process_manager._kill_pids(pids)

    def _is_http_reachable(self) -> bool:
        # 委托到进程管理器统一处理
        return self.process_manager._is_http_reachable()

    def _refresh_running_status(self):
        # 委托到进程管理器统一处理
        return self.process_manager._refresh_running_status()

    def monitor_process(self):
        # 委托到进程管理器统一处理
        return self.process_manager.monitor_process()

    def on_process_ended(self):
        # 委托到进程管理器统一处理
        return self.process_manager.on_process_ended()

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

    def open_root_dir(self):
        root = PATHS.get_comfy_root(self.config.get("paths", {}))
        self._open_dir(root)

    def open_logs_dir(self):
        root = PATHS.get_comfy_root(self.config.get("paths", {}))
        self._open_file(PATHS.logs_file(root))

    def open_input_dir(self):
        root = PATHS.get_comfy_root(self.config.get("paths", {}))
        self._open_dir(PATHS.input_dir(root))

    def open_output_dir(self):
        root = PATHS.get_comfy_root(self.config.get("paths", {}))
        self._open_dir(PATHS.output_dir(root))

    def open_plugins_dir(self):
        root = PATHS.get_comfy_root(self.config.get("paths", {}))
        self._open_dir(PATHS.plugins_dir(root))

    def open_workflows_dir(self):
        # 工作流目录：ComfyUI/user/default/workflows
        base = PATHS.get_comfy_root(self.config.get("paths", {}))
        wf = PATHS.workflows_dir(base)
        try:
            self.logger.info("打开工作流目录: %s", str(wf))
        except Exception:
            pass
        if wf.exists():
            os.startfile(str(wf))
        else:
            messagebox.showwarning("提示", "工作流文件夹尚未创建，需要保存至少一个工作流")

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
            # 恢复 HF 镜像为预设，并同步默认 URL 与输入框可见性
            try:
                self.selected_hf_mirror.set("hf-mirror")
                self.hf_mirror_url.set("https://hf-mirror.com")
                try:
                    # 触发一次可见性更新，隐藏自定义输入框
                    self.on_hf_mirror_selected()
                except Exception:
                    # 兜底：直接隐藏并禁用输入框
                    try:
                        self.hf_mirror_entry.grid_remove()
                        self.hf_mirror_entry.configure(state='disabled')
                    except Exception:
                        pass
            except Exception:
                pass
            # 恢复默认：PyPI 使用阿里云
            try:
                if hasattr(self, 'pypi_proxy_mode_ui'):
                    self.pypi_proxy_mode_ui.set("阿里云")
                if hasattr(self, 'pypi_proxy_mode'):
                    self.pypi_proxy_mode.set("aliyun")
                if hasattr(self, 'pypi_proxy_url'):
                    self.pypi_proxy_url.set("https://mirrors.aliyun.com/pypi/simple/")
                # 隐藏并禁用自定义输入框
                try:
                    if hasattr(self, 'pypi_proxy_url_entry') and self.pypi_proxy_url_entry:
                        self.pypi_proxy_url_entry.grid_remove()
                        self.pypi_proxy_url_entry.configure(state='disabled')
                except Exception:
                    pass
                # 立即应用到 pip.ini
                try:
                    self.apply_pip_proxy_settings()
                except Exception:
                    pass
                try:
                    self.logger.info("恢复默认设置：PyPI=阿里云，已更新 pip.ini")
                except Exception:
                    pass
            except Exception:
                pass
            # 恢复默认：GitHub 代理使用 gh-proxy
            try:
                vm = getattr(self, 'version_manager', None)
                if vm:
                    try:
                        # 更新下拉框显示与内部模式
                        vm.proxy_mode_ui_var.set('gh-proxy')
                        vm.proxy_mode_var.set('gh-proxy')
                        vm.proxy_url_var.set('https://gh-proxy.com/')
                        vm.save_proxy_settings()
                    except Exception:
                        pass
                # 隐藏并禁用自定义 URL 输入框
                try:
                    if hasattr(self, 'github_proxy_url_entry') and self.github_proxy_url_entry:
                        self.github_proxy_url_entry.grid_remove()
                        self.github_proxy_url_entry.configure(state='disabled')
                except Exception:
                    pass
                try:
                    self.logger.info("恢复默认设置：GitHub代理=gh-proxy")
                except Exception:
                    pass
            except Exception:
                pass
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
            # 旧版本兼容：若仍存在单一标签
            if hasattr(self, 'path_label') and self.path_label.winfo_exists():
                self.path_label.config(text=f"路径: {new_path}")
        except Exception:
            pass
        try:
            # 新版样式：更新完整路径并进行截断显示
            if hasattr(self, 'path_value_var'):
                self._path_full_text = str(new_path)
                try:
                    self._update_path_label_elide()
                except Exception:
                    # 若截断失败则回退为完整显示
                    self.path_value_var.set(self._path_full_text)
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
        elif scope == "core_only":
            try:
                self.comfyui_version.set("获取中…")
            except Exception:
                pass
        elif scope == "front_only":
            try:
                self.frontend_version.set("获取中…")
            except Exception:
                pass
        elif scope == "template_only":
            try:
                self.template_version.set("获取中…")
            except Exception:
                pass
        elif scope == "selected":
            # 仅将被选中的项目置为“获取中…”，避免误认为全部更新
            try:
                if self.update_core_var.get():
                    self.comfyui_version.set("获取中…")
                if self.update_frontend_var.get():
                    self.frontend_version.set("获取中…")
                if self.update_template_var.get():
                    self.template_version.set("获取中…")
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

                # 标记是否需要刷新内核版本信息（仅当 scope 要求或被选中）
                core_needed = (scope == "all") or (scope == "core_only") or (scope == "selected" and self.update_core_var.get())

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

                # 前端版本仅在需要时查询：'all' 或显式前端
                if scope == "all" or scope == "front_only" or (scope == "selected" and self.update_frontend_var.get()):
                    try:
                        ver = PIPUTILS.get_package_version(self.python_exec, "comfyui-frontend-package", logger=self.logger)
                        if ver:
                            self.root.after(0, lambda v=ver: self.frontend_version.set(v))
                        else:
                            self.root.after(0, lambda: self.frontend_version.set("未安装"))
                    except Exception:
                        self.root.after(0, lambda: self.frontend_version.set("获取失败"))

                # 模板库版本仅在需要时查询：'all' 或显式模板库
                if scope == "all" or scope == "template_only" or (scope == "selected" and self.update_template_var.get()):
                    try:
                        ver = PIPUTILS.get_package_version(self.python_exec, "comfyui-workflow-templates", logger=self.logger)
                        if ver:
                            self.root.after(0, lambda v=ver: self.template_version.set(v))
                        else:
                            self.root.after(0, lambda: self.template_version.set("未安装"))
                    except Exception:
                        self.root.after(0, lambda: self.template_version.set("获取失败"))

                # 最后刷新内核版本：内核较慢，置于末尾以提升整体响应
                if core_needed and root.exists() and self.git_path:
                    try:
                        # 先尝试同步远端标签，确保本地 `describe` 能拿到最新版本标签
                        try:
                            target_url = None
                            try:
                                origin_url = self.version_manager.get_remote_url()
                                target_url = self.version_manager.compute_proxied_url(origin_url) or origin_url
                            except Exception:
                                target_url = None
                            fetch_args = [self.git_path, "fetch", "--tags"]
                            if target_url:
                                fetch_args.append(target_url)
                            r_fetch_tags = run_hidden(fetch_args, cwd=str(root), capture_output=True, text=True, timeout=15)
                            if r_fetch_tags and r_fetch_tags.returncode == 0:
                                try:
                                    self.logger.info("版本诊断: fetch tags 成功 url=%s", target_url or "origin")
                                except Exception:
                                    pass
                            else:
                                try:
                                    self.logger.warning("版本诊断: fetch tags 失败 rc=%s stderr=%s", getattr(r_fetch_tags, 'returncode', 'N/A'), getattr(r_fetch_tags, 'stderr', ''))
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        r = run_hidden([self.git_path, "describe", "--tags", "--abbrev=0"],
                                           cwd=str(root), capture_output=True, text=True, timeout=10)
                        if r.returncode == 0:
                            tag = r.stdout.strip()
                            r2 = run_hidden([self.git_path, "rev-parse", "--short", "HEAD"],
                                                cwd=str(root), capture_output=True, text=True, timeout=10)
                            commit = r2.stdout.strip() if r2.returncode == 0 else ""
                            # 追加诊断日志：记录本地标签与提交
                            try:
                                self.logger.info("版本诊断: local_tag=%s local_commit=%s path=%s", tag, commit, str(root))
                            except Exception:
                                pass
                            # 追加诊断日志：列出本地最近的若干标签
                            try:
                                r_tags_local = run_hidden([self.git_path, "tag", "--list"],
                                                          cwd=str(root), capture_output=True, text=True, timeout=10)
                                if r_tags_local and r_tags_local.returncode == 0:
                                    tags_all = [t.strip() for t in r_tags_local.stdout.splitlines() if t.strip()]
                                    recent_local = ", ".join(tags_all[-5:]) if tags_all else "<none>"
                                    self.logger.info("版本诊断: local_tags_recent=%s (count=%d)", recent_local, len(tags_all))
                            except Exception:
                                pass
                            # 追加诊断日志：对比远端标签（经代理）
                            try:
                                target_url = None
                                try:
                                    origin_url = self.version_manager.get_remote_url()
                                    target_url = self.version_manager.compute_proxied_url(origin_url) or origin_url
                                except Exception:
                                    target_url = None
                                if target_url:
                                    r_tags_remote = run_hidden([self.git_path, "ls-remote", "--tags", target_url],
                                                                cwd=str(root), capture_output=True, text=True, timeout=15)
                                    if r_tags_remote and r_tags_remote.returncode == 0:
                                        # 取最后若干行（通常为最新标签）
                                        lines = [ln for ln in r_tags_remote.stdout.splitlines() if ln.strip()]
                                        recent_remote = ", ".join([ln.split("\t")[-1] for ln in lines[-5:]]) if lines else "<none>"
                                        self.logger.info("版本诊断: remote_tags_recent=%s url=%s", recent_remote, target_url)
                                    else:
                                        self.logger.warning("版本诊断: 远端标签查询失败 rc=%s stderr=%s", getattr(r_tags_remote, 'returncode', 'N/A'), getattr(r_tags_remote, 'stderr', ''))
                            except Exception:
                                pass
                            self.root.after(0, lambda t=tag, c=commit: self.comfyui_version.set(f"{t} ({c})"))
                        else:
                            self.root.after(0, lambda: self.comfyui_version.set("未找到"))
                    except:
                        self.root.after(0, lambda: self.comfyui_version.set("未找到"))
                elif core_needed:
                    self.root.after(0, lambda: self.comfyui_version.set("ComfyUI未找到"))
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
                if isinstance(self.batch_update_btn, (BigLaunchButton, RoundedButton)):
                    self.batch_update_btn.set_text("更新中…")
                    self.batch_update_btn.set_state('starting')
                else:
                    self.batch_update_btn.config(text="更新中...", cursor='watch')
            except Exception:
                pass

        def worker():
            try:
                # 统计勾选数量，若为多模块更新则抑制单独弹窗并汇总结果
                selected_count = int(bool(self.update_core_var.get())) + int(bool(self.update_frontend_var.get())) + int(bool(self.update_template_var.get()))
                multi_mode = selected_count > 1
                results = []
                if self.update_core_var.get():
                    try:
                        # 使用 VersionManager 的更新逻辑（支持 GitHub 代理、分支解析与错误提示），批量更新时跳过确认并同步执行
                        core_res = self.version_manager.update_to_latest(confirm=False, notify=not multi_mode)
                        if core_res:
                            results.append(core_res)
                    except:
                        pass
                if self.update_frontend_var.get():
                    try:
                        fr_res = self.update_frontend(notify=not multi_mode)
                        if fr_res:
                            results.append(fr_res)
                    except:
                        pass
                if self.update_template_var.get():
                    try:
                        tpl_res = self.update_template_library(notify=not multi_mode)
                        if tpl_res:
                            results.append(tpl_res)
                    except:
                        pass
                try:
                    # 根据勾选项选择性刷新版本信息，避免全部内容刷新
                    only_core = self.update_core_var.get() and not (self.update_frontend_var.get() or self.update_template_var.get())
                    only_front = self.update_frontend_var.get() and not (self.update_core_var.get() or self.update_template_var.get())
                    only_tpl = self.update_template_var.get() and not (self.update_core_var.get() or self.update_frontend_var.get())
                    if only_core:
                        self.get_version_info(scope="core_only")
                    elif only_front:
                        self.get_version_info(scope="front_only")
                    elif only_tpl:
                        self.get_version_info(scope="template_only")
                    else:
                        # 多选场景：仅刷新被选中的项目
                        self.get_version_info(scope="selected")
                except:
                    pass
                # 如为多模块同时更新，合并为一条最终弹窗
                if multi_mode:
                    from tkinter import messagebox
                    def _notify_summary():
                        lines = []
                        for res in results:
                            comp = res.get("component")
                            if comp == "core":
                                if res.get("error"):
                                    lines.append(f"内核：更新失败（{res.get('error')}）")
                                elif res.get("updated") is True:
                                    lines.append(f"内核：已更新到最新提交（{res.get('branch') or ''}）")
                                elif res.get("updated") is False:
                                    lines.append(f"内核：已是最新，无需更新（{res.get('branch') or ''}）")
                                else:
                                    lines.append("内核：更新流程完成")
                            elif comp == "frontend":
                                ver = res.get("version") or ""
                                if res.get("updated"):
                                    lines.append(f"前端：已更新到最新版本（{ver}）")
                                elif res.get("up_to_date"):
                                    lines.append(f"前端：已是最新，无需更新（{ver}）")
                                else:
                                    lines.append("前端：更新流程完成")
                            elif comp == "templates":
                                ver = res.get("version") or ""
                                if res.get("updated"):
                                    lines.append(f"模板库：已更新到最新版本（{ver}）")
                                elif res.get("up_to_date"):
                                    lines.append(f"模板库：已是最新，无需更新（{ver}）")
                                else:
                                    lines.append("模板库：更新流程完成")
                        messagebox.showinfo("完成", "\n".join(lines))
                    self.root.after(0, _notify_summary)
            finally:
                def _reset_btn():
                    self.batch_updating = False
                    if hasattr(self, 'batch_update_btn'):
                        try:
                            if isinstance(self.batch_update_btn, (BigLaunchButton, RoundedButton)):
                                self.batch_update_btn.set_text("更新")
                                self.batch_update_btn.set_state('idle')
                            else:
                                self.batch_update_btn.config(text="更新", cursor='')
                        except Exception:
                            pass
                self.root.after(0, _reset_btn)

        threading.Thread(target=worker, daemon=True).start()

    def update_frontend(self, notify: bool = True):
        """使用 pip_utils 更新前端包 comfyui-frontend-package"""
        try:
            # 获取 PyPI 镜像配置
            idx = None
            mode = self.pypi_proxy_mode.get()
            if mode == 'aliyun':
                idx = 'https://mirrors.aliyun.com/pypi/simple/'
            elif mode == 'custom':
                u = (self.pypi_proxy_url.get() or '').strip()
                if u:
                    idx = u
            
            # 使用 pip_utils 进行安装/更新
            result = PIPUTILS.install_or_update_package(
                "comfyui-frontend-package",
                self.python_exec,
                index_url=idx,
                upgrade=True,
                logger=self.logger
            )
            
            if notify and result["success"]:
                def _notify():
                    try:
                        if result["updated"]:
                            version_text = f"（v{result['version']}）" if result['version'] else ""
                            messagebox.showinfo("完成", f"前端已更新到最新版本{version_text}")
                        elif result["up_to_date"]:
                            version_text = f"（v{result['version']}）" if result['version'] else ""
                            messagebox.showinfo("完成", f"前端已是最新，无需更新{version_text}")
                        else:
                            messagebox.showinfo("完成", "前端更新流程完成（请查看日志确认是否发生变更）")
                    except Exception:
                        pass
                self.root.after(0, _notify)
            
            return {
                "component": "frontend", 
                "updated": result["updated"], 
                "up_to_date": result["up_to_date"], 
                "version": f"v{result['version']}" if result['version'] else None
            }
            
        except Exception as e:
            try:
                self.logger.error(f"前端更新失败: {e}")
            except Exception:
                pass

    def update_template_library(self, notify: bool = True):
        """使用 pip_utils 更新模板库 comfyui-workflow-templates"""
        try:
            # 获取 PyPI 镜像配置
            idx = None
            mode = self.pypi_proxy_mode.get()
            if mode == 'aliyun':
                idx = 'https://mirrors.aliyun.com/pypi/simple/'
            elif mode == 'custom':
                u = (self.pypi_proxy_url.get() or '').strip()
                if u:
                    idx = u
            
            # 使用 pip_utils 进行安装/更新
            result = PIPUTILS.install_or_update_package(
                "comfyui-workflow-templates",
                self.python_exec,
                index_url=idx,
                upgrade=True,
                logger=self.logger
            )
            
            if notify and result["success"]:
                def _notify():
                    try:
                        if result["updated"]:
                            version_text = f"（v{result['version']}）" if result['version'] else ""
                            messagebox.showinfo("完成", f"模板库已更新到最新版本{version_text}")
                        elif result["up_to_date"]:
                            version_text = f"（v{result['version']}）" if result['version'] else ""
                            messagebox.showinfo("完成", f"模板库已是最新，无需更新{version_text}")
                        else:
                            messagebox.showinfo("完成", "模板库更新流程完成（请查看日志确认是否发生变更）")
                    except Exception:
                        pass
                self.root.after(0, _notify)
            
            return {
                "component": "templates", 
                "updated": result["updated"], 
                "up_to_date": result["up_to_date"], 
                "version": f"v{result['version']}" if result['version'] else None
            }
            
        except Exception as e:
            try:
                self.logger.error(f"模板库更新失败: {e}")
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
                        # 检测到便携版 Git：尝试写入 ComfyUI-Manager 的 config.ini
                        try:
                            self._apply_manager_git_exe(self.git_path)
                        except Exception:
                            try:
                                self.logger.exception("应用便携Git到 ComfyUI-Manager 配置失败")
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

    def _apply_manager_git_exe(self, git_path: str):
        """当解析到便携版 Git 时，将其写入 ComfyUI-Manager 的 config.ini 的 git_exe。
        并在 launcher/config.json 中记录已应用，以避免重复设置。
        """
        try:
            if not git_path or git_path == "git":
                return
            # 解析 ComfyUI 根目录
            comfy_root = None
            try:
                comfy_root = Path(self.config["paths"].get("comfyui_path", "")).resolve()
            except Exception:
                comfy_root = None
            if not (comfy_root and comfy_root.exists()):
                try:
                    self.logger.warning("应用便携Git到 Manager 跳过: ComfyUI 路径无效")
                except Exception:
                    pass
                return

            ini_path = comfy_root / "user" / "default" / "ComfyUI-Manager" / "config.ini"
            # 读取并检查配置标记，避免重复设置
            try:
                integrations = self.config.setdefault("integrations", {})
            except Exception:
                integrations = {}
                try:
                    self.config["integrations"] = integrations
                except Exception:
                    pass
            last_path = integrations.get("comfyui_manager_git_path")
            if last_path == git_path and ini_path.exists():
                try:
                    self.logger.info("便携Git已应用到 ComfyUI-Manager，跳过重复设置: path=%s", git_path)
                except Exception:
                    pass
                return

            # 确保目录存在
            try:
                ini_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            # 读取现有内容
            try:
                content = ini_path.read_text(encoding="utf-8", errors="ignore") if ini_path.exists() else ""
            except Exception:
                content = ""
            lines = content.splitlines()
            updated = False
            new_lines = []
            for line in lines:
                if line.strip().lower().startswith("git_exe"):
                    new_lines.append(f"git_exe = {git_path}")
                    updated = True
                else:
                    new_lines.append(line)
            if not updated:
                new_lines.append(f"git_exe = {git_path}")

            try:
                ini_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
            except Exception:
                # 回退到二进制写入
                try:
                    with open(ini_path, "wb") as f:
                        f.write(("\n".join(new_lines) + ("\n" if new_lines else "")).encode("utf-8", errors="ignore"))
                except Exception:
                    raise

            # 在 launcher 配置里记录成功应用
            try:
                integrations["comfyui_manager_git_set"] = True
                integrations["comfyui_manager_git_path"] = git_path
                json.dump(self.config, open(self.config_file, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
            except Exception:
                pass
            try:
                self.logger.info("已将便携Git写入 ComfyUI-Manager 配置: %s", str(ini_path))
            except Exception:
                pass
        except Exception:
            try:
                self.logger.exception("写入 ComfyUI-Manager git_exe 失败")
            except Exception:
                pass

    # ---------- 运行 ----------
    def run(self):
        # 如果启动阶段已经判定为致命错误，则直接安全退出
        if getattr(self, "_fatal_startup_error", False):
            try:
                self.root.destroy()
            except Exception:
                pass
            return
        # 正常路径：进入消息循环（版本信息在界面构建后加载）
        try:
            if hasattr(self, 'comfyui_version'):
                self.get_version_info()
        except Exception:
            pass
        self.root.mainloop()

    def on_hf_mirror_selected(self, _=None):
        try:
            sel = self.selected_hf_mirror.get()
            # 自定义时显示并可编辑；其他模式隐藏并禁用
            if sel == "自定义":
                try:
                    if not self.hf_mirror_entry.winfo_ismapped():
                        # 统一改为 grid 布局
                        self.hf_mirror_entry.grid(row=0, column=2, sticky='w', padx=(8, 0))
                except Exception:
                    pass
                self.hf_mirror_entry.configure(state='normal')
            else:
                if sel == "hf-mirror":
                    # 选择预设镜像时填充默认 URL
                    self.hf_mirror_url.set("https://hf-mirror.com")
                self.hf_mirror_entry.configure(state='disabled')
                try:
                    # 统一隐藏为 grid_remove
                    self.hf_mirror_entry.grid_remove()
                except Exception:
                    pass
            self.save_config()
        except Exception:
            pass

    def on_closing(self):
        # 统一处理关闭时的 ComfyUI 清理：即使不是由本启动器启动，也尝试关闭
        try:
            pm_proc = getattr(self.process_manager, "comfyui_process", None)
            running_tracked = pm_proc is not None and pm_proc.poll() is None
        except Exception:
            running_tracked = False
        # 端口可达则说明存在运行中的 ComfyUI（可能不是我们启动的）
        externally_running = False
        try:
            externally_running = self._is_http_reachable()
        except Exception:
            pass

        if running_tracked or externally_running:
            # 与“停止”按钮一致：直接尝试停止端口上的所有相关进程后退出
            try:
                self.stop_comfyui()
            except Exception:
                pass
            finally:
                try:
                    self.root.destroy()
                except Exception:
                    pass
        else:
            # 未检测到运行中的 ComfyUI，直接退出
            try:
                self.root.destroy()
            except Exception:
                pass

    def stop_all_comfyui_instances(self) -> bool:
        # 委托到进程管理器统一处理
        return self.process_manager.stop_all_comfyui_instances()


if __name__ == "__main__":
    lock = SingletonLock("comfyui_launcher_section_card_with_divider.lock")
    if not lock.acquire():
        # 当检测到已有实例或锁未释放时，给出清晰提示并记录日志
        try:
            from logger_setup import install_logging
            _logger = install_logging()
            _logger.warning("启动器二次启动被阻止：检测到已有实例或锁未释放")
        except Exception:
            pass
        try:
            # 弹出友好提示（为保证在无主窗口时可用，创建临时隐藏 root）
            import tkinter as _tk
            from tkinter import messagebox as _msg
            _tmp = _tk.Tk()
            _tmp.withdraw()
            _msg.showwarning(
                "启动器已在运行",
                "检测到已有启动器实例或锁未释放。\n\n"
                "- 如果窗口已打开，请切换到已运行的窗口。\n"
                "- 如果没有窗口，可能仍在初始化，请等待数秒后再试。\n"
                "- 若问题持续，可重启电脑或稍后重试。"
            )
            _tmp.destroy()
        except Exception:
            pass
        try:
            print("[提示] 启动器已在运行或锁未释放，当前启动请求已忽略。")
        except Exception:
            pass
        sys.exit(0)
    try:
        app = ComfyUILauncherEnhanced()
        app.run()
    finally:
        lock.release()
