import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont
import subprocess, threading, json, os, sys, webbrowser, tempfile, atexit
import shlex
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image, ImageTk
from version_manager import VersionManager
from utils import run_hidden, have_git, is_git_repo
from logger_setup import install_logging
import locale
import logging

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

# ================== 小号圆角按钮（与一键启动风格一致） ==================
class RoundedButton(tk.Frame):
    def __init__(self, parent, text="按钮", width=120, height=36,
                 color="#2F6EF6", hover="#2760DB", active="#1F52BE",
                 radius=10, command=None,
                 font=("Microsoft YaHei", 11, "bold")):
        super().__init__(parent, width=width, height=height, bg=parent.cget("bg"))
        self.w = width
        self.h = height
        self.radius = radius
        self.color = color
        self.hover = hover
        self.active = active
        self.command = command
        self.state = "idle"
        self.canvas = tk.Canvas(self, width=width, height=height, bd=0, highlightthickness=0,
                                bg=parent.cget("bg"))
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.label = tk.Label(self.canvas, text=text, bg=color, fg="#FFF",
                              font=font)
        self._draw(color)
        self._place()
        for w in (self.canvas, self.label):
            w.bind("<Enter>", lambda e: self._on_hover())
            w.bind("<Leave>", lambda e: self._refresh())
            w.bind("<ButtonPress-1>", lambda e: self._on_press())
            w.bind("<ButtonRelease-1>", lambda e: self._on_release())

    def _draw(self, fill):
        c = self.canvas
        w, h, r = self.w, self.h, self.radius
        c.delete("bg")
        # 中心矩形与四边
        c.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill, tags="bg")
        c.create_rectangle(0, r, w, h - r, fill=fill, outline=fill, tags="bg")
        # 四角圆弧
        for (x0, y0) in [(0, 0), (w - 2 * r, 0), (0, h - 2 * r), (w - 2 * r, h - 2 * r)]:
            c.create_oval(x0, y0, x0 + 2 * r, y0 + 2 * r, fill=fill, outline=fill, tags="bg")

    def _place(self):
        self.canvas.create_window(self.w / 2, self.h / 2, window=self.label, anchor="center", tags="lbl")

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
        # 统一工作目录为项目根目录（优先选择包含 ComfyUI/main.py 的目录），并在该根目录同级创建 launcher 日志目录
        try:
            base_root_candidates = []
            # 源码环境：launcher 上级目录
            try:
                base_root_candidates.append(Path(__file__).resolve().parent.parent)
            except Exception:
                pass
            # PyInstaller 环境资源目录
            try:
                from sys import _MEIPASS  # type: ignore
                if _MEIPASS:
                    base_root_candidates.append(Path(_MEIPASS))
            except Exception:
                pass
            # EXE 所在目录
            try:
                base_root_candidates.append(Path(sys.executable).resolve().parent)
            except Exception:
                pass
            # 当前工作目录作为兜底
            base_root_candidates.append(Path.cwd())
            base_root = None
            # 第一轮：优先选择包含 ComfyUI/main.py 的候选
            for cand in base_root_candidates:
                try:
                    if cand and cand.exists() and (cand / "ComfyUI" / "main.py").exists():
                        base_root = cand
                        break
                except Exception:
                    pass
            # 第二轮：没有命中则选择第一个存在的目录
            if base_root is None:
                for cand in base_root_candidates:
                    try:
                        if cand and cand.exists():
                            base_root = cand
                            break
                    except Exception:
                        pass
            base_root = base_root or Path.cwd()
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
            self.config_file = (Path.cwd() / "launcher" / "config.json").resolve()
        except Exception:
            self.config_file = Path("launcher/config.json")
        self.load_config()
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

        # 载入其他设置
        self.load_settings()

        # 初始化版本管理器（需要 comfyui_path 与 python_path 已解析）
        self.version_manager = VersionManager(
            self,
            self.config["paths"]["comfyui_path"],
            self.config["paths"]["python_path"]
        )

        # 构建界面、启动监控线程并设置关闭事件
        self.build_layout()
        threading.Thread(target=self.monitor_process, daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def apply_pip_proxy_settings(self):
        """根据当前 PyPI 代理设置更新 python_embeded/pip.ini。
        - aliyun/custom: 写入 [global]、index-url、trusted-host
        - none: 移除 index-url/trusted-host/proxy（若文件仅余空配置则删除）
        """
        try:
            py_path = Path(self.python_exec).resolve()
            # pip.ini 位于嵌入式 python.exe 的所在目录
            py_root = py_path.parent if py_path.exists() else Path('python_embeded')
            pip_ini = py_root / 'pip.ini'

            mode = self.pypi_proxy_mode.get() if hasattr(self.pypi_proxy_mode, 'get') else 'none'
            url = (self.pypi_proxy_url.get() or '').strip() if hasattr(self.pypi_proxy_url, 'get') else ''
            pip_proxy = (self.pip_proxy_url.get() or '').strip() if hasattr(self, 'pip_proxy_url') and hasattr(self.pip_proxy_url, 'get') else (
                (self.config.get('proxy_settings', {}) or {}).get('pip_proxy_url', '')
            )

            if mode == 'none':
                if pip_ini.exists():
                    try:
                        content = pip_ini.read_text(encoding='utf-8', errors='ignore')
                        lines = [ln for ln in content.splitlines() if ln.strip()]
                        filtered = []
                        for ln in lines:
                            low = ln.strip().lower()
                            if low.startswith('index-url') or low.startswith('trusted-host') or low.startswith('proxy'):
                                continue
                            filtered.append(ln)
                        non_comment = [ln for ln in filtered if ln.strip() and not ln.strip().startswith('#')]
                        if not non_comment or (len(non_comment) == 1 and non_comment[0].strip().lower() == '[global]'):
                            pip_ini.unlink(missing_ok=True)
                        else:
                            pip_ini.write_text('\n'.join(filtered) + '\n', encoding='utf-8')
                    except Exception:
                        try:
                            pip_ini.unlink(missing_ok=True)
                        except Exception:
                            pass
                return

            if mode == 'aliyun':
                index_url = 'https://mirrors.aliyun.com/pypi/simple/'
                trusted_host = 'mirrors.aliyun.com'
            else:
                index_url = url or ''
                try:
                    parsed = urlparse(index_url)
                    trusted_host = parsed.hostname or ''
                except Exception:
                    trusted_host = ''

            if not index_url:
                return

            lines = ['[global]', f'index-url = {index_url}']
            if trusted_host:
                lines.append(f'trusted-host = {trusted_host}')
            if pip_proxy:
                lines.append(f'proxy = {pip_proxy}')
            try:
                pip_ini.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            try:
                pip_ini.write_text('\n'.join(lines) + '\n', encoding='utf-8')
                try:
                    self.logger.info("已更新 pip.ini: mode=%s url=%s host=%s proxy=%s", mode, index_url, trusted_host, pip_proxy or '-')
                except Exception:
                    pass
            except Exception:
                try:
                    self.logger.warning("写入 pip.ini 失败: %s", str(pip_ini))
                except Exception:
                    pass
        except Exception:
            try:
                self.logger.exception("应用 PyPI 代理到 pip.ini 时出错")
            except Exception:
                pass

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

        # 变更时持久化并自动应用到 pip.ini
        self.pypi_proxy_mode.trace_add("write", lambda *a: (self.save_config(), self.apply_pip_proxy_settings()))
        self.pypi_proxy_url.trace_add("write", lambda *a: (self.save_config(), self.apply_pip_proxy_settings()))

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
        # 确保配置目录存在
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
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
            # 在无配置文件时，若根目录存在 ComfyUI 且包含 main.py，则自动设置为 ComfyUI 路径
            try:
                app_root = getattr(self, "_base_root", Path(__file__).resolve().parent.parent)
            except Exception:
                app_root = Path.cwd()
            auto_comfy = app_root / "ComfyUI"
            try:
                if auto_comfy.exists() and (auto_comfy / "main.py").exists():
                    self.config["paths"]["comfyui_path"] = str(auto_comfy.resolve())
                    try:
                        self.logger.info("检测到本地 ComfyUI 目录，已自动设置路径: %s", str(auto_comfy.resolve()))
                    except Exception:
                        pass
            except Exception:
                pass
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
        tk.Checkbutton(checks, text="快速模式",
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
        tk.Label(checks, text="额外选项:", bg=self.CARD_BG, fg=c["TEXT"]) \
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
            .pack(side=tk.LEFT)

        # —— 网络配置（HF 镜像、GitHub 代理、PyPI 代理） ——
        tk.Label(form, text="网络配置:", bg=self.CARD_BG, fg=c["TEXT"],
                 font=HEAD_LABEL_FONT) \
            .grid(row=3, column=0, sticky="nw", padx=(0, 14), pady=(0, ROW_GAP))

        net_frame = tk.Frame(form, bg=self.CARD_BG)
        # 让网络配置区域横向填充，从而可将按钮推到更靠右
        net_frame.grid(row=3, column=1, sticky="we", pady=(0, ROW_GAP))
        # 右侧动作区：用于放置“恢复默认设置”按钮
        try:
            # 作为弹性占位列，腾出右侧空间
            net_frame.grid_columnconfigure(3, weight=1)
        except Exception:
            pass
        # HF 镜像
        tk.Label(net_frame, text="HF 镜像:", bg=self.CARD_BG, fg=c["TEXT"], font=BODY_FONT) \
            .grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.hf_mirror_combobox = ttk.Combobox(
            net_frame,
            textvariable=self.selected_hf_mirror,
            values=["不使用镜像", "hf-mirror", "自定义"],
            state="readonly",
            width=12
        )
        self.hf_mirror_combobox.grid(row=0, column=1, sticky='w')
        self.hf_mirror_entry = ttk.Entry(net_frame, textvariable=self.hf_mirror_url, width=26)
        self.hf_mirror_entry.grid(row=0, column=2, sticky='w', padx=(8, 0))
        self.hf_mirror_combobox.bind("<<ComboboxSelected>>", self.on_hf_mirror_selected)
        try:
            self.on_hf_mirror_selected()
        except Exception:
            pass

        # GitHub 代理（品牌大小写）
        tk.Label(net_frame, text="GitHub 代理:", bg=self.CARD_BG, fg=c["TEXT"], font=BODY_FONT).grid(
            row=1, column=0, sticky='w', padx=(0, 8), pady=(6, 0)
        )
        self.github_proxy_mode_combo = ttk.Combobox(
            net_frame,
            textvariable=self.version_manager.proxy_mode_ui_var,
            values=["不使用", "gh-proxy", "自定义"],
            state='readonly',
            width=12
        )
        self.github_proxy_mode_combo.grid(row=1, column=1, sticky='w', padx=(0, 8), pady=(6, 0))
        self.github_proxy_url_entry = ttk.Entry(
            net_frame,
            textvariable=self.version_manager.proxy_url_var,
            width=24
        )
        # 自定义 URL 与下拉框之间拉开距离（与 HF 镜像一致）
        self.github_proxy_url_entry.grid(row=1, column=2, sticky='w', padx=(8, 0), pady=(6, 0))

        def _set_github_entry_visibility():
            try:
                mode = self.version_manager.proxy_mode_var.get()
                if mode == 'custom':
                    if not self.github_proxy_url_entry.winfo_ismapped():
                        self.github_proxy_url_entry.grid(row=1, column=2, sticky='w', padx=(8, 0), pady=(6, 0))
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

        # PyPI 代理（品牌大小写）
        tk.Label(net_frame, text="PyPI 代理:", bg=self.CARD_BG, fg=c["TEXT"], font=BODY_FONT).grid(
            row=2, column=0, sticky='w', padx=(0, 8), pady=(6, 0)
        )
        self.pypi_proxy_mode_combo = ttk.Combobox(
            net_frame,
            textvariable=self.pypi_proxy_mode_ui,
            values=["不使用", "阿里云", "自定义"],
            state='readonly',
            width=12
        )
        self.pypi_proxy_mode_combo.grid(row=2, column=1, sticky='w', padx=(0, 8), pady=(6, 0))
        self.pypi_proxy_url_entry = ttk.Entry(
            net_frame,
            textvariable=self.pypi_proxy_url,
            width=24
        )
        # 自定义 URL 与下拉框之间拉开距离（与 HF 镜像一致）
        self.pypi_proxy_url_entry.grid(row=2, column=2, sticky='w', padx=(8, 0), pady=(6, 0))

        # 在网络配置的右侧空白处放置“恢复默认设置”按钮，使用蓝色强调样式
        right_actions = tk.Frame(net_frame, bg=self.CARD_BG)
        # 把按钮放到更靠右的第4列，并靠右对齐
        right_actions.grid(row=0, column=4, rowspan=3, sticky='e', padx=(16, 0), pady=(0, 0))
        # 使用圆角矩形按钮（小号）
        self.restore_defaults_btn = RoundedButton(
            right_actions,
            text="恢复默认设置",
            width=132,
            height=36,
            color=self.COLORS["ACCENT"],
            hover=self.COLORS["ACCENT_HOVER"],
            active=self.COLORS["ACCENT_ACTIVE"],
            radius=10,
            font=("Microsoft YaHei", 11),
            command=self.reset_settings,
        )
        self.restore_defaults_btn.pack(anchor='e')

        def _set_pypi_entry_visibility():
            try:
                mode = self.pypi_proxy_mode.get()
                if mode == 'custom':
                    if not self.pypi_proxy_url_entry.winfo_ismapped():
                        self.pypi_proxy_url_entry.grid(row=2, column=2, sticky='w', padx=(8, 0), pady=(6, 0))
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
                self.apply_pip_proxy_settings()
            except Exception:
                pass

        try:
            self.pypi_proxy_mode_combo.bind('<<ComboboxSelected>>', _on_pypi_mode_change)
            _set_pypi_entry_visibility()
        except Exception:
            pass

        # 原先的“恢复默认设置”按钮已移动到网络配置右侧并改为蓝色

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

        # 表单与按钮并排：左侧为统一表单（复选），右侧为更新按钮
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

        #（已将 GitHub / PyPI 代理迁移到“启动控制 > 网络配置”）

        # 右侧小号“更新”按钮（仿照一键启动样式）
        update_btn_container = tk.Frame(proxy_area, bg=self.CARD_BG)
        update_btn_container.pack(side=tk.RIGHT, padx=(48, 0))
        # 使用圆角矩形样式的小号按钮
        self.batch_update_btn = RoundedButton(
            update_btn_container,
            text="更新",
            width=96,
            height=36,
            color=self.COLORS["ACCENT"],
            hover=self.COLORS["ACCENT_HOVER"],
            active=self.COLORS["ACCENT_ACTIVE"],
            radius=10,
            font=("Microsoft YaHei", 11),
            command=self.perform_batch_update,
        )
        self.batch_update_btn.pack()
        self.frontend_update_btn = self.batch_update_btn
        self.template_update_btn = self.batch_update_btn
        self.batch_updating = False

    def _build_quick_links(self, container, path=None):
        c = self.COLORS
        # 顶部一排：左侧路径，右侧“重设ComfyUI根目录”按钮
        top_bar = tk.Frame(container, bg=self.CARD_BG)
        top_bar.pack(fill=tk.X, padx=(4, 0), pady=(0, 6))
        if path:
            # 左侧：路径标题与值并排，标题样式与“批量更新”一致，值样式与“快速模式”一致
            left_path = tk.Frame(top_bar, bg=self.CARD_BG)
            left_path.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.path_label_title = tk.Label(
                left_path,
                text="路径:",
                bg=self.CARD_BG, fg=c["TEXT"],
                font=self.INTERNAL_HEAD_LABEL_FONT
            )
            self.path_label_title.pack(side=tk.LEFT, padx=(0, 8))
            try:
                path_resolved = str(Path(path).resolve())
            except Exception:
                path_resolved = str(path)
            # 保存完整路径用于后续截断显示
            self._path_full_text = path_resolved
            self.path_value_var = tk.StringVar(value=path_resolved)
            self.path_value_label = tk.Label(
                left_path,
                textvariable=self.path_value_var,
                bg=self.CARD_BG, fg=c["TEXT"]
                # 不指定字体，使用系统默认，与“快速模式”一致
            )
            self.path_value_label.pack(side=tk.LEFT)

            # 记录布局引用，便于根据可用宽度动态截断
            self._path_top_bar = top_bar
            try:
                self._path_label_font = tkfont.nametofont(self.path_value_label.cget("font"))
            except Exception:
                try:
                    self._path_label_font = tkfont.nametofont("TkDefaultFont")
                except Exception:
                    self._path_label_font = None

            # 将“重设ComfyUI根目录”按钮紧随具体路径值右侧
            self.reset_root_btn = RoundedButton(
                left_path,
                text="重设ComfyUI根目录",
                width=160,
                height=36,
                color=self.COLORS["ACCENT"],
                hover=self.COLORS["ACCENT_HOVER"],
                active=self.COLORS["ACCENT_ACTIVE"],
                radius=10,
                font=("Microsoft YaHei", 11),
                command=self.reset_comfyui_path,
            )
            self.reset_root_btn.pack(side=tk.LEFT, padx=(12, 0))

            # 绑定尺寸变化事件以动态更新截断文本，避免按钮被挤出
            def _on_resize(_evt=None):
                try:
                    self._update_path_label_elide()
                except Exception:
                    pass
            top_bar.bind('<Configure>', _on_resize)
            self.root.after(0, _on_resize)
        else:
            # 若无路径信息，保持按钮在顶栏右侧作为回退布局
            self.reset_root_btn = RoundedButton(
                top_bar,
                text="重设ComfyUI根目录",
                width=160,
                height=36,
                color=self.COLORS["ACCENT"],
                hover=self.COLORS["ACCENT_HOVER"],
                active=self.COLORS["ACCENT_ACTIVE"],
                radius=10,
                font=("Microsoft YaHei", 11),
                command=self.reset_comfyui_path,
            )
            self.reset_root_btn.pack(side=tk.RIGHT)

        # 顶栏仅保留“重设ComfyUI根目录”，不再放置“工作流目录”按钮

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
            ("工作流目录", self.open_workflows_dir),
        ]:
            btn = ttk.Button(grid, text=txt, style='Secondary.TButton', command=cmd)
            self.quick_buttons.append(btn)

        def _relayout(_evt=None):
            # 改为单行网格布局（不换行），同时压缩左右与上下间距
            try:
                width = max(0, grid.winfo_width())
            except Exception:
                width = 800
            cols = len(self.quick_buttons)
            for i, btn in enumerate(self.quick_buttons):
                # 全部放在第0行，确保单行显示
                btn.grid(row=0, column=i, padx=4, pady=(2, 6), sticky='nsew')
            for ci in range(cols):
                grid.grid_columnconfigure(ci, weight=1, uniform='quick')

        grid.bind('<Configure>', _relayout)
        self.root.after(0, _relayout)

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
            full = getattr(self, "_path_full_text", None) or (self.path_value_var.get() if hasattr(self, 'path_value_var') else "")
            # 计算可用于显示路径的像素宽度：顶栏总宽度 - 标题宽度 - 按钮宽度 - 余量
            top_w = self._path_top_bar.winfo_width() if hasattr(self, '_path_top_bar') else 0
            title_w = self.path_label_title.winfo_width() if hasattr(self, 'path_label_title') else 0
            btn_w = self.reset_root_btn.winfo_width() if hasattr(self, 'reset_root_btn') else 0
            # 预留边距与间距（标题右侧8px，按钮左侧12px等），综合设置为 40px
            available_px = max(60, top_w - title_w - btn_w - 40)
            # 根据字体估算最大字符数（使用“M”作宽度参考）
            font_obj = getattr(self, '_path_label_font', None)
            if font_obj:
                m_w = max(7, int(font_obj.measure("M")))
            else:
                m_w = 9
            max_chars = max(10, available_px // m_w)
            self.path_value_var.set(self._truncate_middle(full, max_chars))
        except Exception:
            # 回退：不截断
            try:
                if hasattr(self, 'path_value_var'):
                    self.path_value_var.set(full)
            except Exception:
                pass

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
        # 判断是否已有运行中的 ComfyUI（包括外部启动的同端口实例）
        running = False
        try:
            if getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is None:
                running = True
            else:
                running = self._is_http_reachable()
        except Exception:
            running = False
        if running:
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
                cmd.extend(["--fast"])
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
            # 若设置了 GitHub 代理，则注入 GITHUB_ENDPOINT 环境变量
            try:
                vm = getattr(self, 'version_manager', None)
                if vm and vm.proxy_mode_var.get() in ('gh-proxy', 'custom'):
                    base = (vm.proxy_url_var.get() or '').strip()
                    if base:
                        if not base.endswith('/'):
                            base += '/'
                        env["GITHUB_ENDPOINT"] = f"{base}https://github.com"
            except Exception:
                pass
            try:
                self.logger.info("环境变量(GITHUB_ENDPOINT): %s", env.get("GITHUB_ENDPOINT", ""))
            except Exception:
                pass
            self.big_btn.set_state("starting")
            self.big_btn.set_text("启动中…")

            def worker():
                try:
                    if os.name == 'nt':
                        # 始终显示控制台窗口
                        self.comfyui_process = subprocess.Popen(
                            cmd, env=env, cwd=os.getcwd(),
                            creationflags=subprocess.CREATE_NEW_CONSOLE,
                        )
                    else:
                        self.comfyui_process = subprocess.Popen(
                            cmd, env=env, cwd=os.getcwd()
                        )
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
        killed = False
        # 1) 优先停止当前已跟踪的进程
        if getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is None:
            try:
                self.comfyui_process.terminate()
                self.comfyui_process.wait(timeout=5)
                killed = True
            except subprocess.TimeoutExpired:
                try:
                    self.comfyui_process.kill()
                    killed = True
                except Exception as e:
                    messagebox.showerror("错误", f"停止失败: {e}")
            except Exception as e:
                messagebox.showerror("错误", f"停止失败: {e}")
        else:
            # 2) 未跟踪到句柄：根据端口查找并强制终止对应进程
            port = (self.custom_port.get() or "8188").strip()
            pids = self._find_pids_by_port_safe(port)
            if pids:
                # 仅筛选识别为 ComfyUI 的进程，避免误杀其它程序
                comfy_pids = [pid for pid in pids if self._is_comfyui_pid(pid)]
                if comfy_pids:
                    try:
                        self._kill_pids(comfy_pids)
                        killed = True
                    except Exception as e:
                        messagebox.showerror("错误", f"强制停止失败: {e}")
                else:
                    messagebox.showwarning(
                        "警告",
                        "检测到端口占用，但未识别为 ComfyUI 进程，已取消强制停止。\n\n"
                        "如端口被其它程序占用，请修改 ComfyUI 端口或手动关闭该程序。"
                    )
            else:
                messagebox.showwarning("警告", f"未找到端口 {port} 上运行的进程")

        # 根据结果刷新按钮
        if killed:
            self.big_btn.set_state("idle")
            self.big_btn.set_text("一键启动")
            self.comfyui_process = None
        else:
            # 若仍被判定为运行中，保持“停止”以避免误导
            try:
                if self._is_http_reachable():
                    self.big_btn.set_state("running")
                    self.big_btn.set_text("停止")
                else:
                    self.big_btn.set_state("idle")
                    self.big_btn.set_text("一键启动")
            except Exception:
                self.big_btn.set_state("idle")
                self.big_btn.set_text("一键启动")

    def _find_pids_by_port_safe(self, port_str):
        # 解析端口并通过 psutil 或 netstat 查找 PID 列表
        try:
            port = int(port_str)
        except Exception:
            return []
        # 优先使用 psutil
        try:
            import psutil  # type: ignore
            pids = set()
            try:
                for conn in psutil.net_connections(kind='inet'):
                    try:
                        if conn.laddr and conn.laddr.port == port:
                            if conn.status in ('LISTEN', 'ESTABLISHED'):  # 监听或连接中
                                if conn.pid:
                                    pids.add(conn.pid)
                    except Exception:
                        pass
            except Exception:
                pass
            if pids:
                return list(pids)
        except Exception:
            pass
        # 回退到 netstat 解析（Windows）
        try:
            import subprocess
            import re
            cmd = ["netstat", "-ano"]
            # 使用系统首选编码并忽略解码错误，且隐藏子进程窗口
            preferred_enc = locale.getpreferredencoding(False) or "utf-8"
            r = run_hidden(
                cmd,
                capture_output=True,
                text=True,
                encoding=preferred_enc,
                errors="ignore",
            )
            if r.returncode == 0 and r.stdout:
                pids = set()
                pattern = re.compile(rf"^\s*TCP\s+[^:]+:{port}\s+.*?\s+(\d+)\s*$", re.IGNORECASE)
                for line in r.stdout.splitlines():
                    m = pattern.match(line)
                    if m:
                        try:
                            pids.add(int(m.group(1)))
                        except Exception:
                            pass
                # 也匹配 UDP（少见，但兜底）
                pattern_udp = re.compile(rf"^\s*UDP\s+[^:]+:{port}\s+.*?\s+(\d+)\s*$", re.IGNORECASE)
                for line in r.stdout.splitlines():
                    m = pattern_udp.match(line)
                    if m:
                        try:
                            pids.add(int(m.group(1)))
                        except Exception:
                            pass
                return list(pids)
        except Exception:
            pass
        return []

    def _is_comfyui_pid(self, pid: int) -> bool:
        # 通过 cmdline/exe/cwd 多重特征判断是否为 ComfyUI 相关进程
        try:
            import psutil  # type: ignore
            comfy_root = str(Path(self.config["paths"]["comfyui_path"]).resolve()).lower()
            try:
                p = psutil.Process(pid)
                cmdline = " ".join(p.cmdline()).lower()
            except Exception:
                cmdline = ""
            try:
                exe = (p.exe() or "").lower()
            except Exception:
                exe = ""
            try:
                cwd = (p.cwd() or "").lower()
            except Exception:
                cwd = ""

            # 关键特征：main.py、comfyui 字样、路径命中 ComfyUI 根目录
            if comfy_root and (comfy_root in cmdline or comfy_root in exe or comfy_root in cwd):
                return True
            if ("main.py" in cmdline and ("comfyui" in cmdline or "windows-standalone-build" in cmdline)):
                return True
            if ("comfyui" in cmdline or "comfyui" in exe or "comfyui" in cwd):
                return True
        except Exception:
            pass

        # 回退：使用 wmic 获取命令行（在部分 Windows 环境可用）
        if os.name == 'nt':
            try:
                import subprocess
                comfy_root = str(Path(self.config["paths"]["comfyui_path"]).resolve()).lower()
                preferred_enc = locale.getpreferredencoding(False) or "utf-8"
                r = run_hidden([
                    "wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/format:list"
                ], capture_output=True, text=True, encoding=preferred_enc, errors="ignore")
                if r.returncode == 0 and r.stdout:
                    out = r.stdout.lower()
                    if ("comfyui" in out) or ("main.py" in out) or (comfy_root and comfy_root in out):
                        return True
            except Exception:
                pass

        return False

    def _kill_pids(self, pids):
        # 优先使用 psutil 优雅终止，失败则回退到 taskkill
        killed_any = False
        try:
            import psutil  # type: ignore
            for pid in pids:
                try:
                    p = psutil.Process(pid)
                    p.terminate()
                except Exception:
                    pass
            try:
                psutil.wait_procs([psutil.Process(pid) for pid in pids], timeout=3)
                killed_any = True
            except Exception:
                pass
        except Exception:
            pass
        # 对未结束的进程使用 taskkill 强制终止（Windows）
        if os.name == 'nt':
            try:
                for pid in pids:
                    run_hidden(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
                killed_any = True
            except Exception:
                pass
        if not killed_any:
            raise RuntimeError("无法终止目标进程")

    def _is_http_reachable(self) -> bool:
        """非侵入式运行探测：不发起实际 HTTP 请求，改用端口与 PID 映射判断。

        原实现会向后端发起请求，可能导致后端在特定平台/事件循环下出现连接关闭的异常日志。
        为避免干扰后端，这里通过系统连接表与进程特征识别来判断 ComfyUI 是否在运行。
        """
        try:
            port = (self.custom_port.get() or "8188").strip()
            pids = self._find_pids_by_port_safe(port)
            if not pids:
                return False
            # 仅当检测到与 ComfyUI 特征匹配的进程时，认为运行中
            for pid in pids:
                try:
                    if self._is_comfyui_pid(pid):
                        return True
                except Exception:
                    pass
            return False
        except Exception:
            return False

    def _refresh_running_status(self):
        # 根据进程与端口探测结果统一刷新按钮状态
        try:
            running = False
            if getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is None:
                running = True
            else:
                running = self._is_http_reachable()
            if running:
                self.big_btn.set_state("running")
                self.big_btn.set_text("停止")
            else:
                self.big_btn.set_state("idle")
                self.big_btn.set_text("一键启动")
        except Exception:
            pass

    def monitor_process(self):
        while True:
            try:
                # 若处于关闭流程，则停止监控循环，避免销毁窗口前的 UI 冲突
                if getattr(self, "_shutting_down", False):
                    break
                # 进程结束时，置空句柄并根据端口探测决定按钮显示
                if getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is not None:
                    self.comfyui_process = None
                self.root.after(0, self._refresh_running_status)
                threading.Event().wait(2)
            except:
                break

    def on_process_ended(self):
        try:
            self.logger.info("ComfyUI 进程结束")
        except Exception:
            pass
        self.comfyui_process = None
        # 根据端口探测决定显示“停止”或“一键启动”
        try:
            if self._is_http_reachable():
                self.big_btn.set_state("running")
                self.big_btn.set_text("停止")
            else:
                self.big_btn.set_state("idle")
                self.big_btn.set_text("一键启动")
        except Exception:
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

    def open_workflows_dir(self):
        # 工作流目录：ComfyUI/user/default/workflows
        base = Path(self.config["paths"]["comfyui_path"]).resolve()
        wf = base / "user" / "default" / "workflows"
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
            self.selected_hf_mirror.set("hf-mirror")
            # 恢复默认：PyPI 使用阿里云
            try:
                if hasattr(self, 'pypi_proxy_mode_ui'):
                    self.pypi_proxy_mode_ui.set("阿里云")
                if hasattr(self, 'pypi_proxy_mode'):
                    self.pypi_proxy_mode.set("aliyun")
                if hasattr(self, 'pypi_proxy_url'):
                    self.pypi_proxy_url.set("https://mirrors.aliyun.com/pypi/simple/")
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
                        # 优先使用 python -m pip
                        try:
                            self.logger.info("操作pip: 仅查询 comfyui-frontend-package 版本（不会安装/更新；python -m pip）")
                        except Exception:
                            pass
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
                                    try:
                                        self.logger.info("操作pip: 仅查询 comfyui-frontend-package 版本（不会安装/更新；pip.exe）")
                                    except Exception:
                                        pass
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

                # 模板库版本仅在需要时查询：'all' 或显式模板库
                if scope == "all" or scope == "template_only" or (scope == "selected" and self.update_template_var.get()):
                    try:
                        try:
                            self.logger.info("操作pip: 仅查询 comfyui-workflow-templates 版本（不会安装/更新；python -m pip）")
                        except Exception:
                            pass
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
                                    try:
                                        self.logger.info("操作pip: 仅查询 comfyui-workflow-templates 版本（不会安装/更新；pip.exe）")
                                    except Exception:
                                        pass
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
            try:
                self.logger.info("操作pip: 安装/更新 comfyui-frontend-package，index=%s，cmd=%s", idx or '-', " ".join(cmd))
            except Exception:
                pass
            r = run_hidden(cmd, capture_output=True, text=True)
            # 根据 pip 输出判断是否发生了实际更新，并给出提醒
            try:
                out = getattr(r, 'stdout', '') or ''
                updated = ("Successfully installed" in out) or ("Installing collected packages" in out) or ("Successfully upgraded" in out)
                up_to_date = ("Requirement already satisfied" in out) and not updated
                # 查询安装后的版本号用于提示
                installed_ver = None
                try:
                    r_show = run_hidden([str(pip_exe if pip_exe.exists() else self.python_exec), "-m", "pip", "show", "comfyui-frontend-package"], capture_output=True, text=True, timeout=10)
                    if r_show.returncode == 0:
                        for line in (getattr(r_show, 'stdout', '') or '').splitlines():
                            if line.startswith("Version:"):
                                installed_ver = line.split(":", 1)[1].strip()
                                break
                except Exception:
                    pass
                if notify:
                    def _notify():
                        try:
                            if updated:
                                messagebox.showinfo("完成", f"前端已更新到最新版本{f'（v{installed_ver}）' if installed_ver else ''}")
                            elif up_to_date:
                                messagebox.showinfo("完成", f"前端已是最新，无需更新{f'（v{installed_ver}）' if installed_ver else ''}")
                            else:
                                messagebox.showinfo("完成", "前端更新流程完成（请查看日志确认是否发生变更）")
                        except Exception:
                            pass
                    self.root.after(0, _notify)
                return {"component": "frontend", "updated": bool(updated), "up_to_date": bool(up_to_date), "version": (f"v{installed_ver}" if installed_ver else None)}
            except Exception:
                pass
            try:
                self.logger.info("操作pip: 前端包更新完成")
            except Exception:
                pass
        except Exception:
            pass

    def update_template_library(self, notify: bool = True):
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
            try:
                self.logger.info("操作pip: 安装/更新 comfyui-workflow-templates，index=%s，cmd=%s", idx or '-', " ".join(cmd))
            except Exception:
                pass
            r = run_hidden(cmd, capture_output=True, text=True)
            # 根据 pip 输出判断是否发生了实际更新，并给出提醒
            try:
                out = getattr(r, 'stdout', '') or ''
                updated = ("Successfully installed" in out) or ("Installing collected packages" in out) or ("Successfully upgraded" in out)
                up_to_date = ("Requirement already satisfied" in out) and not updated
                # 查询安装后的版本号用于提示
                installed_ver = None
                try:
                    r_show = run_hidden([str(pip_exe if pip_exe.exists() else self.python_exec), "-m", "pip", "show", "comfyui-workflow-templates"], capture_output=True, text=True, timeout=10)
                    if r_show.returncode == 0:
                        for line in (getattr(r_show, 'stdout', '') or '').splitlines():
                            if line.startswith("Version:"):
                                installed_ver = line.split(":", 1)[1].strip()
                                break
                except Exception:
                    pass
                if notify:
                    def _notify():
                        try:
                            if updated:
                                messagebox.showinfo("完成", f"模板库已更新到最新版本{f'（v{installed_ver}）' if installed_ver else ''}")
                            elif up_to_date:
                                messagebox.showinfo("完成", f"模板库已是最新，无需更新{f'（v{installed_ver}）' if installed_ver else ''}")
                            else:
                                messagebox.showinfo("完成", "模板库更新流程完成（请查看日志确认是否发生变更）")
                        except Exception:
                            pass
                    self.root.after(0, _notify)
                return {"component": "templates", "updated": bool(updated), "up_to_date": bool(up_to_date), "version": (f"v{installed_ver}" if installed_ver else None)}
            except Exception:
                pass
            try:
                self.logger.info("操作pip: 模板库更新完成")
            except Exception:
                pass
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
            running_tracked = getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is None
        except Exception:
            running_tracked = False
        # 端口可达则说明存在运行中的 ComfyUI（可能不是我们启动的）
        externally_running = False
        try:
            externally_running = self._is_http_reachable()
        except Exception:
            pass

        if running_tracked or externally_running:
            # 加强提示：可选择关闭所有 ComfyUI 实例（包括外部启动的）
            if messagebox.askyesno("确认", "检测到 ComfyUI 正在运行。是否关闭所有 ComfyUI 实例并退出？\n\n提示：即使不是由本启动器启动的 ComfyUI，也会尝试关闭。"):
                try:
                    # 优先正常停止当前跟踪的进程
                    self.stop_comfyui()
                    # 进一步扫描并尝试关闭其它可能的 ComfyUI 进程
                    self.stop_all_comfyui_instances()
                except Exception:
                    pass
                finally:
                    try:
                        self.root.destroy()
                    except Exception:
                        pass
            else:
                # 用户选择不关闭，直接退出窗口
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
        """尝试关闭所有检测到的 ComfyUI 实例（包括非本启动器启动的）。

        返回 True 表示至少成功终止一个进程。
        """
        killed = False
        pids = set()
        # 1) 通过端口查找（当前自定义端口）
        try:
            port = (self.custom_port.get() or "8188").strip()
            for pid in self._find_pids_by_port_safe(port):
                try:
                    if self._is_comfyui_pid(pid):
                        pids.add(pid)
                except Exception:
                    pass
        except Exception:
            pass
        # 2) 通过进程枚举查找（可能是不同端口或手动启动）
        try:
            import psutil  # type: ignore
            for p in psutil.process_iter(attrs=["pid"]):
                pid = p.info.get("pid")
                if not pid:
                    continue
                try:
                    if self._is_comfyui_pid(int(pid)):
                        pids.add(int(pid))
                except Exception:
                    pass
        except Exception:
            # 若无 psutil，可忽略此步骤（已有端口方法与回退的 taskkill）
            pass
        # 移除自身跟踪的句柄，避免重复
        try:
            if getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is None:
                pids.discard(self.comfyui_process.pid)
        except Exception:
            pass
        # 统一终止
        if pids:
            try:
                self._kill_pids(list(pids))
                killed = True
            except Exception:
                # 继续尝试逐个终止以提升成功率
                for pid in list(pids):
                    try:
                        self._kill_pids([pid])
                        killed = True
                    except Exception:
                        pass
        return killed


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

    # 注意：resolve_git 已移动到 ComfyUILauncherEnhanced 类中