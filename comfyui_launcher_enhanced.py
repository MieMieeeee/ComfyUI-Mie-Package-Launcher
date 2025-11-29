import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading, os, sys
import ctypes
from pathlib import Path
from core.version_manager import VersionManager
from utils import paths as PATHS
from ui import assets_helper as ASSETS
from config.manager import ConfigManager
from utils.common import SingletonLock
from utils.logging import install_logging
import logging
from ui import theme as THEME
from ui.constants import COLORS
from ui.window import setup_window as UI_SETUP_WINDOW
from ui.layout import build_layout as UI_BUILD_LAYOUT
from ui.events import select_tab as UI_SELECT_TAB
from core.process_manager import ProcessManager
from services.di import ServiceContainer

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

    # 样式常量已集中在 ui/constants.py

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._initializing = True
        self.root = tk.Tk()
        # 缓存 Windows wmic 可用性，避免重复尝试
        try:
            self._wmic_available = None
        except Exception:
            pass
        # 初始化界面配色（集中在 ui.constants），确保布局阶段可用
        try:
            self.COLORS = COLORS
            try:
                self.root.configure(bg=COLORS.get("BG", "#FFFFFF"))
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
        UI_SETUP_WINDOW(self)

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

        # 当前配置中的根与子目录名
        raw_root = self.config.get("paths", {}).get("comfyui_root")
        comfy_path = (Path(raw_root or ".").resolve() / Path("ComfyUI")).resolve()
        if not is_valid_comfy_path(comfy_path):
            try:
                if comfy_path.exists():
                    # 配置中路径存在则直接接受，避免 EXE 启动时误判
                    is_valid = True
                    comfy_path = comfy_path
                else:
                    is_valid = False
            except Exception:
                is_valid = False
            if is_valid:
                pass
            else:
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
                    # 如果仍然无效，继续使用选择的目录以允许后续界面与服务初始化
                    if not is_valid_comfy_path(comfy_path):
                        try:
                            self.logger.warning("未检测到有效 ComfyUI 根目录，将继续使用所选路径: %s", str(comfy_path))
                        except Exception:
                            pass
                    pass

        # 写回配置为分离的 root + path（路径名）
        self.config.setdefault("paths", {})
        self.config["paths"]["comfyui_root"] = str(comfy_path.parent)
        try:
            self.config_manager.save_config(self.config)
        except Exception:
            pass

        # 解析并固定 Python 可执行路径，避免相对路径在不同工作目录下失效
        py_exec = PATHS.resolve_python_exec(comfy_path, self.config["paths"].get("python_path", "python_embeded/python.exe"))
        self.python_exec = str(py_exec)
        # 将解析后的绝对路径写回配置，后续运行更稳健
        try:
            self.config["paths"]["python_path"] = self.python_exec
            self.config_manager.save_config(self.config)
        except Exception:
            pass

        # 载入其他设置
        self.load_settings()
        try:
            self._initializing = False
        except Exception:
            pass

        # 初始化版本管理器（传入完整的 ComfyUI 目录路径与 Python 路径）
        self.version_manager = VersionManager(
            self,
            str(comfy_path),
            self.config["paths"]["python_path"]
        )

        # 初始化进程管理器
        self.process_manager = ProcessManager(self)
        try:
            self.services = ServiceContainer.from_app(self)
        except Exception:
            self.services = None

        UI_BUILD_LAYOUT(self)
        threading.Thread(target=self.process_manager.monitor_process, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def apply_pip_proxy_settings(self):
        """根据当前 PyPI 代理设置更新 python_embeded/pip.ini（委托 Service 层）。"""
        try:
            if getattr(self, 'services', None):
                self.services.network.apply_pip_proxy_settings()
        except Exception:
            pass

    # ---------- 样式 ----------

    # ---------- 变量 ----------
    def setup_variables(self):
        self.compute_mode = tk.StringVar(value="gpu")
        self.use_fast_mode = tk.BooleanVar()
        self.enable_cors = tk.BooleanVar(value=True)
        self.listen_all = tk.BooleanVar(value=True)
        self.custom_port = tk.StringVar(value="8188")
        self.extra_launch_args = tk.StringVar(value="")
        self.attention_mode = tk.StringVar(value="")
        self.browser_open_mode = tk.StringVar(value="default")
        self.custom_browser_path = tk.StringVar(value="")
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
        # 升级偏好：仅稳定版
        vp = (self.config.get("version_preferences") or {}) if isinstance(self.config, dict) else {}
        self.stable_only_var = tk.BooleanVar(value=bool(vp.get("stable_only", True)))
        self.requirements_sync_var = tk.BooleanVar(value=bool(vp.get("requirements_sync", True)))

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
        self.attention_mode.trace_add("write", lambda *a: self.save_config())
        self.browser_open_mode.trace_add("write", lambda *a: self.save_config())
        self.custom_browser_path.trace_add("write", lambda *a: self.save_config())
        # 版本偏好变更时持久化
        self.stable_only_var.trace_add("write", lambda *a: self.save_config())
        self.requirements_sync_var.trace_add("write", lambda *a: self.save_config())

        # HF 镜像 URL
        default_hf_url = proxy_cfg.get("hf_mirror_url", "https://hf-mirror.com")
        self.hf_mirror_url = tk.StringVar(value=default_hf_url)
        try:
            default_hf_mode = proxy_cfg.get("hf_mirror_mode", "hf-mirror")
            self.selected_hf_mirror.set(default_hf_mode)
        except Exception:
            pass
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
        try:
            if getattr(self, 'services', None):
                self.config = self.services.config.load()
            else:
                self.config = self.config_manager.load_config()
        except Exception:
            pass

    def save_config(self):
        # 保护性获取变量，避免在初始化早期因为变量不存在而报错
        def _get(var, default):
            try:
                return var.get()
            except Exception:
                return default

        try:
            if getattr(self, 'services', None):
                self.services.config.update_launch_options(
                    default_compute_mode=_get(self.compute_mode, "gpu"),
                    default_port=_get(self.custom_port, "8188"),
                    enable_fast_mode=_get(self.use_fast_mode, False),
                    enable_cors=_get(self.enable_cors, True),
                    listen_all=_get(self.listen_all, True),
                    extra_args=(self.config.get("launch_options", {}).get("extra_args", "") if getattr(self, '_initializing', False) else _get(self.extra_launch_args, "")),
                    attention_mode=(self.config.get("launch_options", {}).get("attention_mode", "") if getattr(self, '_initializing', False) else _get(self.attention_mode, "")),
                    browser_open_mode=(self.config.get("launch_options", {}).get("browser_open_mode", "default") if getattr(self, '_initializing', False) else _get(self.browser_open_mode, "default")),
                    custom_browser_path=(self.config.get("launch_options", {}).get("custom_browser_path", "") if getattr(self, '_initializing', False) else _get(self.custom_browser_path, ""))
                )
                self.services.config.set("proxy_settings.hf_mirror_mode", _get(self.selected_hf_mirror, "hf-mirror"))
                try:
                    self.services.config.set("paths.comfyui_root", str(Path(self.config.get("paths", {}).get("comfyui_root") or ".").resolve()))
                except Exception:
                    pass
                self.services.config.update_proxy_settings(
                    pypi_proxy_mode=_get(self.pypi_proxy_mode, "aliyun"),
                    pypi_proxy_url=_get(self.pypi_proxy_url, "https://mirrors.aliyun.com/pypi/simple/"),
                    hf_mirror_url=_get(self.hf_mirror_url, "https://hf-mirror.com")
                )
                self.services.config.set("version_preferences.stable_only", _get(self.stable_only_var, True))
                self.services.config.set("version_preferences.requirements_sync", _get(self.requirements_sync_var, False))
                self.services.config.save(None)
                self.config = self.services.config.get_config()
            else:
                # 回退到原有 ConfigManager
                self.config_manager.update_launch_options(
                    default_compute_mode=_get(self.compute_mode, "gpu"),
                    default_port=_get(self.custom_port, "8188"),
                    enable_fast_mode=_get(self.use_fast_mode, False),
                    enable_cors=_get(self.enable_cors, True),
                    listen_all=_get(self.listen_all, True),
                    extra_args=(self.config.get("launch_options", {}).get("extra_args", "") if getattr(self, '_initializing', False) else _get(self.extra_launch_args, "")),
                    attention_mode=(self.config.get("launch_options", {}).get("attention_mode", "") if getattr(self, '_initializing', False) else _get(self.attention_mode, "")),
                    browser_open_mode=(self.config.get("launch_options", {}).get("browser_open_mode", "default") if getattr(self, '_initializing', False) else _get(self.browser_open_mode, "default")),
                    custom_browser_path=(self.config.get("launch_options", {}).get("custom_browser_path", "") if getattr(self, '_initializing', False) else _get(self.custom_browser_path, ""))
                )
                self.config_manager.set("proxy_settings.hf_mirror_mode", _get(self.selected_hf_mirror, "hf-mirror"))
                try:
                    self.config_manager.set("paths.comfyui_root", str(Path(self.config.get("paths", {}).get("comfyui_root") or ".").resolve()))
                except Exception:
                    pass
                try:
                    self.config_manager.update_proxy_settings(
                        pypi_proxy_mode=_get(self.pypi_proxy_mode, "aliyun"),
                        pypi_proxy_url=_get(self.pypi_proxy_url, "https://mirrors.aliyun.com/pypi/simple/"),
                        hf_mirror_url=_get(self.hf_mirror_url, "https://hf-mirror.com")
                    )
                except Exception:
                    pass
                try:
                    self.config_manager.set("version_preferences.stable_only", _get(self.stable_only_var, True))
                except Exception:
                    pass
                try:
                    self.config_manager.set("version_preferences.requirements_sync", _get(self.requirements_sync_var, False))
                except Exception:
                    pass
                self.config_manager.save_config()
                self.config = self.config_manager.get_config()
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
        try:
            self.attention_mode.set(opt.get("attention_mode", ""))
        except Exception:
            pass
        try:
            self.browser_open_mode.set(opt.get("browser_open_mode", "default"))
        except Exception:
            pass
        try:
            self.custom_browser_path.set(opt.get("custom_browser_path", ""))
        except Exception:
            pass

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
        UI_SELECT_TAB(self, name)

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
        try:
            _path = self.config.get("paths", {}).get("comfyui_path", str(Path.cwd()))
        except Exception:
            _path = str(Path.cwd())
        QUICK.build_quick_links_panel(self, quick_card.get_body(), path=_path, rounded_button_cls=RoundedButton)
        
        self.root.after(0, lambda: self.get_version_info())

    

    # ====== 启动控制 ======
    # 已移除历史兼容方法，主文件保持模块化调用

    # ====== 版本与更新 ======
    # 已移除历史兼容方法，主文件保持模块化调用

    # 已移除历史兼容方法，主文件保持模块化调用


    # ---------- 资源解析 ----------
    # 抽离到 assets.py，主文件不再持有解析实现

    # ---------- Version / About ----------
    def build_version_tab(self, parent):
        pass



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

    def pre_start_up(self):
        try:
            if getattr(self, 'services', None):
                self.services.runtime.pre_start_up()
        except Exception:
            pass

    # 运行时准备迁移至 RuntimeService

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

    # ---------- 目录/文件 ----------（委托 utils.ui_actions）

    def open_root_dir(self):
        from utils.ui_actions import open_root_dir as _a
        _a(self)

    def open_logs_dir(self):
        from utils.ui_actions import open_logs_file as _a
        _a(self)

    def open_input_dir(self):
        from utils.ui_actions import open_input_dir as _a
        _a(self)

    def open_output_dir(self):
        from utils.ui_actions import open_output_dir as _a
        _a(self)

    def open_plugins_dir(self):
        from utils.ui_actions import open_plugins_dir as _a
        _a(self)

    def open_workflows_dir(self):
        from utils.ui_actions import open_workflows_dir as _a
        _a(self)


    def open_comfyui_web(self):
        from utils.ui_actions import open_web as _web
        _web(self)

    def reset_settings(self):
        from ui.events import reset_settings as _reset
        _reset(self)

    def reset_comfyui_path(self):
        from ui.events import reset_comfyui_path as _reset_path
        _reset_path(self)

    # ---------- 版本 ----------
    def get_version_info(self, scope: str = "all"):
        from core.version_service import refresh_version_info
        refresh_version_info(self, scope)

    def perform_batch_update(self):
        if getattr(self, 'batch_updating', False):
            return
        self.batch_updating = True
        if hasattr(self, 'batch_update_btn'):
            try:
                if hasattr(self.batch_update_btn, 'set_text'):
                    try:
                        self.batch_update_btn.set_text("更新中…")
                    except Exception:
                        pass
                    try:
                        self.batch_update_btn.set_state("starting")
                    except Exception:
                        pass
                else:
                    self.batch_update_btn.config(text="更新中…", cursor='watch')
            except Exception:
                pass
        def worker():
            try:
                results, summary = self.services.update.perform_batch_update()
                try:
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
                        self.get_version_info(scope="selected")
                except Exception:
                    pass
                def _notify_summary():
                    try:
                        messagebox.showinfo("完成", summary or "更新流程完成")
                    except Exception:
                        pass
                self.root.after(0, _notify_summary)
            finally:
                def _reset_btn():
                    self.batch_updating = False
                    if hasattr(self, 'batch_update_btn'):
                        try:
                            if hasattr(self.batch_update_btn, 'set_text'):
                                try:
                                    self.batch_update_btn.set_text("更新")
                                except Exception:
                                    pass
                                try:
                                    self.batch_update_btn.set_state("idle")
                                except Exception:
                                    pass
                            else:
                                self.batch_update_btn.config(text="更新", cursor='')
                        except Exception:
                            pass
                self.root.after(0, _reset_btn)
        threading.Thread(target=worker, daemon=True).start()

    def update_frontend(self, notify: bool = True):
        try:
            res = self.services.update.update_frontend(False)
            if notify:
                def _notify():
                    try:
                        if res.get("updated"):
                            vt = f"（v{res.get('version')}）" if res.get('version') else ""
                            messagebox.showinfo("完成", f"前端已更新到最新版本{vt}")
                        elif res.get("up_to_date"):
                            vt = f"（v{res.get('version')}）" if res.get('version') else ""
                            messagebox.showinfo("完成", f"前端已是最新，无需更新{vt}")
                        else:
                            messagebox.showinfo("完成", "前端更新流程完成（请查看日志确认是否发生变更）")
                    except Exception:
                        pass
                self.root.after(0, _notify)
            return res
        except Exception as e:
            try:
                self.logger.error(f"前端更新失败: {e}")
            except Exception:
                pass

    def update_template_library(self, notify: bool = True):
        try:
            res = self.services.update.update_templates(False)
            if notify:
                def _notify():
                    try:
                        if res.get("updated"):
                            vt = f"（v{res.get('version')}）" if res.get('version') else ""
                            messagebox.showinfo("完成", f"模板库已更新到最新版本{vt}")
                        elif res.get("up_to_date"):
                            vt = f"（v{res.get('version')}）" if res.get('version') else ""
                            messagebox.showinfo("完成", f"模板库已是最新，无需更新{vt}")
                        else:
                            messagebox.showinfo("完成", "模板库更新流程完成（请查看日志确认是否发生变更）")
                    except Exception:
                        pass
                self.root.after(0, _notify)
            return res
        except Exception as e:
            try:
                self.logger.error(f"模板库更新失败: {e}")
            except Exception:
                pass

    # ---------- Git 解析 ----------
    def resolve_git(self):
        return self.services.git.resolve_git()

    def _apply_manager_git_exe(self, git_path: str):
        self.services.git.apply_to_manager(git_path)

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
        from ui.events import on_hf_mirror_selected as _hf
        _hf(self, _)

    def on_closing(self):
        try:
            pm_proc = getattr(self.process_manager, "comfyui_process", None)
            running_tracked = pm_proc is not None and pm_proc.poll() is None
        except Exception:
            running_tracked = False
        externally_running = False
        try:
            externally_running = self._is_http_reachable()
        except Exception:
            pass
        if running_tracked or externally_running:
            try:
                proceed = messagebox.askyesno("提示", "检测到 ComfyUI 正在运行，是否退出并关闭 ComfyUI？")
            except Exception:
                proceed = True
            if not proceed:
                return
            ok = False
            try:
                ok = bool(self.process_manager.stop_comfyui_sync())
            except Exception:
                ok = False
            try:
                self.root.destroy()
            except Exception:
                pass
        else:
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
            from utils.logging import install_logging
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
