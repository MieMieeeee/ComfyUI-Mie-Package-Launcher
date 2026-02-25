import os
import sys
import subprocess
from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from utils import paths as PATHS
from utils.logging import install_logging
from config.manager import ConfigManager
from services.di import ServiceContainer
from core.version_service import refresh_version_info
from core.process_manager import ProcessManager
from services.git_service import GitService
from utils import common as COMMON
from ui import assets_helper as ASSETS
from utils import pip as PIPUTILS
from utils.common import run_hidden
from ui_qt.theme_manager import ThemeManager
from ui_qt.theme_styles import ThemeStyles, ThemeColors
from ui_qt.pages.launch_page import LaunchPage
from ui_qt.pages.version_page import VersionPage
from ui_qt.pages.models_page import ModelsPage
from ui_qt.pages.about_me_page import AboutMePage
from ui_qt.pages.about_comfyui_page import AboutComfyUIPage
from ui_qt.pages.about_launcher_page import AboutLauncherPage


class Var:
    def __init__(self, value=""):
        self._v = value
        self._watchers = []
    def get(self):
        return self._v
    def set(self, v):
        self._v = v
        for w in self._watchers:
            try:
                w(v)
            except Exception:
                pass
    def bind(self, fn):
        self._watchers.append(fn)

class BoolVar:
    def __init__(self, value=False):
        self._v = bool(value)
    def get(self):
        return self._v
    def set(self, v):
        self._v = bool(v)

class BigBtnProxy:
    def __init__(self):
        self._btn = None
        self._state = "idle"
        self._text = None
    def attach(self, qbtn):
        self._btn = qbtn
        if self._text is not None:
            try:
                qbtn.setText(self._text)
            except Exception:
                pass
    def set_state(self, s):
        self._state = s
    def set_text(self, t):
        self._text = t
        if self._btn is not None:
            try:
                self._btn.setText(t)
            except Exception:
                pass

class QtRootAdapter:
    def after(self, ms, fn):
        QtCore.QTimer.singleShot(int(ms), fn)
    def after_idle(self, fn):
        QtCore.QTimer.singleShot(0, fn)
class UiInvoker(QtCore.QObject):
    invoke_signal = QtCore.pyqtSignal(object)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.invoke_signal.connect(self._on_invoke)
    def _on_invoke(self, fn):
        try:
            fn()
        except Exception:
            pass
class VersionWorker(QtCore.QThread):
    pythonVersion = QtCore.pyqtSignal(str)
    torchVersion = QtCore.pyqtSignal(str)
    frontendVersion = QtCore.pyqtSignal(str)
    templateVersion = QtCore.pyqtSignal(str)
    coreVersion = QtCore.pyqtSignal(str)
    gitStatus = QtCore.pyqtSignal(str)
    def __init__(self, app, scope="all"):
        super().__init__()
        self.app = app
        self.scope = scope
    def run(self):
        try:
            paths = self.app.config.get("paths", {}) if isinstance(self.app.config, dict) else {}
            base = Path(paths.get("comfyui_root") or ".").resolve()
            root = (base / "ComfyUI").resolve()
        except Exception:
            base = Path(".").resolve()
            root = base / "ComfyUI"
        try:
            self.app.logger.info("UI: 版本线程启动 scope=%s root=%s py=%s", str(self.scope), str(root), str(self.app.python_exec))
        except Exception:
            pass
        try:
            if self.scope in ("all", "python_related"):
                try:
                    r = run_hidden([self.app.python_exec, "--version"], capture_output=True, text=True, timeout=10)
                    val = r.stdout.strip().replace("Python ", "") if r.returncode == 0 else "获取失败"
                    self.pythonVersion.emit(val)
                    self.app.logger.info("UI: Python 版本=%s", val)
                except Exception:
                    self.pythonVersion.emit("获取失败")
                try:
                    v = PIPUTILS.get_package_version("torch", self.app.python_exec, logger=self.app.logger)
                    self.torchVersion.emit(v or "未安装")
                    self.app.logger.info("UI: Torch 版本=%s", v or "未安装")
                except Exception:
                    self.torchVersion.emit("获取失败")
                try:
                    vf = PIPUTILS.get_package_version("comfyui-frontend-package", self.app.python_exec, logger=self.app.logger) or PIPUTILS.get_package_version("comfyui_frontend_package", self.app.python_exec, logger=self.app.logger)
                    self.frontendVersion.emit(vf or "未安装")
                    self.app.logger.info("UI: 前端包版本=%s", vf or "未安装")
                except Exception:
                    self.frontendVersion.emit("获取失败")
                try:
                    vt = PIPUTILS.get_package_version("comfyui-workflow-templates", self.app.python_exec, logger=self.app.logger) or PIPUTILS.get_package_version("comfyui_workflow_templates", self.app.python_exec, logger=self.app.logger)
                    self.templateVersion.emit(vt or "未安装")
                    self.app.logger.info("UI: 模板库版本=%s", vt or "未安装")
                except Exception:
                    self.templateVersion.emit("获取失败")
            if self.scope in ("all", "core_only", "selected"):
                try:
                    git_cmd, git_text = self.app.resolve_git()
                    if git_cmd is None:
                        self.gitStatus.emit("未找到Git命令")
                    elif not root.exists():
                        self.gitStatus.emit("ComfyUI未找到")
                    else:
                        self.gitStatus.emit(git_text or "")
                    if git_cmd and root.exists():
                        r = run_hidden([git_cmd, "describe", "--tags", "--abbrev=0"], cwd=str(root), capture_output=True, text=True, timeout=8)
                        if r.returncode != 0:
                            r2 = run_hidden([git_cmd, "rev-parse", "--short", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=6)
                            c = r2.stdout.strip() if r2.returncode == 0 else ""
                            try:
                                if hasattr(self.app, "comfyui_commit"):
                                    self.app.comfyui_commit.set(c)
                            except Exception:
                                pass
                            self.coreVersion.emit(f"（{c}）" if c else "未找到")
                        else:
                            tag = r.stdout.strip()
                            r2 = run_hidden([git_cmd, "rev-parse", "--short", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=8)
                            c = r2.stdout.strip() if r2.returncode == 0 else ""
                            try:
                                if hasattr(self.app, "comfyui_commit"):
                                    self.app.comfyui_commit.set(c)
                            except Exception:
                                pass
                            self.coreVersion.emit(f"{tag}（{c}）")
                        try:
                            self.app.logger.info("UI: 内核版本标签已生成")
                        except Exception:
                            pass
                except Exception:
                    self.coreVersion.emit("未找到")
        except Exception:
            pass

from ui_qt.widgets.custom import CircleAvatar, NoWheelComboBox

class PyQtLauncher(QtWidgets.QMainWindow):
    def __init__(self):
        # 适配 4K/2K 高分屏：在创建 QApplication 之前启用缩放支持
        try:
            os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
            if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
                QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
            if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
                QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
        except Exception:
            pass

        self.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        super().__init__()
        self._invoker = UiInvoker(self)
        def _qt_msg_handler(msg_type, context, message):
            try:
                if "libpng warning: bKGD: invalid" in (message or ""):
                    if getattr(self, "logger", None):
                        try:
                            self.logger.info("忽略 Qt 消息: %s", message)
                        except Exception:
                            pass
                    return
            except Exception:
                pass
            try:
                sys.stderr.write(str(message) + "\n")
            except Exception:
                pass
        try:
            self._prev_qt_handler = QtCore.qInstallMessageHandler(_qt_msg_handler)
        except Exception:
            self._prev_qt_handler = None
        base_root = PATHS.resolve_base_root()
        self.base_root = base_root
        os.chdir(base_root)
        self.logger = install_logging(log_root=base_root)
        cfg_file = (Path.cwd() / "launcher" / "config.json").resolve()
        self.config_manager = ConfigManager(cfg_file, self.logger)
        self.config = self.config_manager.load_config()
        comfy_base = Path(self.config.get("paths", {}).get("comfyui_root") or ".").resolve()
        comfy_path = (comfy_base / "ComfyUI").resolve()
        py_exec = PATHS.resolve_python_exec(comfy_path, self.config.get("paths", {}).get("python_path", "python_embeded/python.exe"))
        self.python_exec = str(py_exec)
        self.config.setdefault("paths", {})
        self.config["paths"]["python_path"] = self.python_exec
        self.root = QtRootAdapter()
        # 历史上曾有 "directml" 选项，这里统一回退为 "gpu"
        self.compute_mode = Var("gpu")
        # 空字符串表示“交给 ComfyUI 自己决定显存策略”（不加任何 --*vram 启动项）
        self.vram_mode = Var("")
        self.use_fast_mode = BoolVar(False)
        self.enable_cors = BoolVar(True)
        self.listen_all = BoolVar(True)
        self.custom_port = Var("8188")
        self.disable_all_custom_nodes = BoolVar(False)
        self.disable_api_nodes = BoolVar(False)
        self.use_new_manager = BoolVar(False)
        self.extra_launch_args = Var("")
        self.attention_mode = Var("")
        self.browser_open_mode = Var("default")
        self.custom_browser_path = Var("")
        launch_cfg = self.config.get("launch_options", {}) if isinstance(self.config, dict) else {}
        try:
            cm = launch_cfg.get("default_compute_mode", self.compute_mode.get())
            if cm == "directml":
                cm = "gpu"
            self.compute_mode.set(cm)
            self.vram_mode.set(launch_cfg.get("vram_mode", self.vram_mode.get()))
            self.custom_port.set(launch_cfg.get("default_port", self.custom_port.get()))
            self.disable_all_custom_nodes.set(bool(launch_cfg.get("disable_all_custom_nodes", self.disable_all_custom_nodes.get())))
            self.use_fast_mode.set(bool(launch_cfg.get("enable_fast_mode", self.use_fast_mode.get())))
            self.disable_api_nodes.set(bool(launch_cfg.get("disable_api_nodes", self.disable_api_nodes.get())))
            self.use_new_manager.set(bool(launch_cfg.get("use_new_manager", self.use_new_manager.get())))
            self.enable_cors.set(bool(launch_cfg.get("enable_cors", self.enable_cors.get())))
            self.listen_all.set(bool(launch_cfg.get("listen_all", self.listen_all.get())))
            self.extra_launch_args.set(launch_cfg.get("extra_args", self.extra_launch_args.get()))
            self.attention_mode.set(launch_cfg.get("attention_mode", self.attention_mode.get()))
            self.browser_open_mode.set(launch_cfg.get("browser_open_mode", self.browser_open_mode.get()))
            self.custom_browser_path.set(launch_cfg.get("custom_browser_path", self.custom_browser_path.get()))
        except Exception:
            pass
        proxy_cfg = self.config.get("proxy_settings", {}) if isinstance(self.config, dict) else {}
        self.pypi_proxy_mode = Var(proxy_cfg.get("pypi_proxy_mode", "aliyun"))
        self.pypi_proxy_url = Var(proxy_cfg.get("pypi_proxy_url", "https://mirrors.aliyun.com/pypi/simple/"))
        def _pypi_mode_ui_text(mode: str):
            return "阿里云" if mode == "aliyun" else ("自定义" if mode == "custom" else "不使用")
        self.pypi_proxy_mode_ui = Var(_pypi_mode_ui_text(self.pypi_proxy_mode.get()))
        self.hf_mirror_url = Var(proxy_cfg.get("hf_mirror_url", "https://hf-mirror.com"))
        self.selected_hf_mirror = Var(proxy_cfg.get("hf_mirror_mode", "hf-mirror"))
        self.comfyui_version = Var("获取中…")
        self.comfyui_commit = Var("获取中…")
        self.frontend_version = Var("获取中…")
        self.template_version = Var("获取中…")
        self.python_version = Var("获取中…")
        self.torch_version = Var("获取中…")
        self.git_status = Var("检测中…")
        self.update_core_var = BoolVar(True)
        self.update_frontend_var = BoolVar(True)
        self.update_template_var = BoolVar(True)
        self.git_path = None
        vp = self.config.get("version_preferences", {}) if isinstance(self.config, dict) else {}
        try:
            self.stable_only_var = BoolVar(bool(vp.get("stable_only", True)))
        except Exception:
            self.stable_only_var = BoolVar(True)
        try:
            self.auto_update_deps_var = BoolVar(bool(vp.get("auto_update_deps", True)))
        except Exception:
            self.auto_update_deps_var = BoolVar(True)
        class _VMStub:
            def __init__(self, app_):
                self.app = app_
                self.proxy_mode_var = Var((proxy_cfg.get("git_proxy_mode", "none") or "none"))
                ui = "不使用" if self.proxy_mode_var.get() == "none" else ("gh-proxy" if self.proxy_mode_var.get() == "gh-proxy" else "自定义")
                self.proxy_mode_ui_var = Var(ui)
                self.proxy_url_var = Var(proxy_cfg.get("git_proxy_url", ""))
            def get_remote_url(self):
                try:
                    base = Path(self.app.config.get("paths", {}).get("comfyui_root") or ".").resolve()
                    root = (base / "ComfyUI").resolve()
                except Exception:
                    root = Path.cwd()
                r = COMMON.run_hidden([self.app.git_path or "git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=6, cwd=str(root))
                return r.stdout.strip() if r.returncode == 0 else ""
            def compute_proxied_url(self, origin_url: str):
                mode = self.proxy_mode_var.get()
                url = self.proxy_url_var.get().strip()
                if not origin_url:
                    return None
                if mode == "gh-proxy":
                    if "github.com" in origin_url:
                        return "https://gh-proxy.com/" + origin_url.replace("https://", "").replace("http://", "")
                    return None
                if mode == "custom" and url:
                    if not url.endswith("/"):
                        url2 = url + "/"
                    else:
                        url2 = url
                    return url2 + origin_url.replace("https://", "").replace("http://", "")
                return None
            def save_proxy_settings(self):
                try:
                    self.app.services.config.set("proxy_settings.git_proxy_mode", self.proxy_mode_var.get())
                    self.app.services.config.set("proxy_settings.git_proxy_url", self.proxy_url_var.get())
                    self.app.services.config.save(None)
                except Exception:
                    pass
        self.version_manager = _VMStub(self)
        self.big_btn = BigBtnProxy()
        self.process_manager = ProcessManager(self)
        self.services = ServiceContainer.from_app(self)
        self._setup_ui()
    
    def ui_post(self, fn):
        try:
            if not hasattr(self, "_invoker") or (self._invoker is None):
                self._invoker = UiInvoker(self)
            self._invoker.invoke_signal.emit(fn)
        except Exception:
            try:
                QtCore.QTimer.singleShot(0, fn)
            except Exception:
                try:
                    fn()
                except Exception:
                    pass
    @QtCore.pyqtSlot(str)
    def _on_python_version(self, v):
        try:
            if getattr(self, "logger", None):
                self.logger.info("UI: 接收 Python 版本=%s", v)
        except Exception:
            pass
        self.python_version.set(v)
    @QtCore.pyqtSlot(str)
    def _on_torch_version(self, v):
        self.torch_version.set(v)
    @QtCore.pyqtSlot(str)
    def _on_frontend_version(self, v):
        self.frontend_version.set(v)
    @QtCore.pyqtSlot(str)
    def _on_template_version(self, v):
        self.template_version.set(v)
    @QtCore.pyqtSlot(str)
    def _on_core_version(self, v):
        self.comfyui_version.set(v)
    @QtCore.pyqtSlot(str)
    def _on_git_status(self, v):
        self.git_status.set(v)

    def _setup_ui(self):
        self.setWindowTitle("ComfyUI 启动器")

        # Theme setup
        theme_value = (self.config.get("ui_settings", {}).get("theme") or "dark").lower()
        if theme_value not in ("dark", "light"):
            theme_value = "dark"

        # Sidebar collapse setup
        self._sidebar_collapsed = self.config.get("ui_settings", {}).get("sidebar_collapsed", False)
        self._sidebar_expanded_width = 240
        self._sidebar_collapsed_width = 60

        def _apply_theme(theme: str):
            dark = theme == "dark"
            # Use ThemeManager to update theme and notify listeners BEFORE manual style updates
            c = None
            if hasattr(self, "theme_manager") and self.theme_manager:
                try:
                    self.theme_manager.set_theme(dark)
                except Exception:
                    pass
                c = self.theme_manager.colors
            if c is not None:
                palette = {
                    "root_bg": c.get("root_bg"),
                    "sidebar_grad_top": c.get("sidebar_grad_top"),
                    "sidebar_grad_bottom": c.get("sidebar_grad_bottom"),
                    "sidebar_border": c.get("sidebar_border"),
                    "content_bg": c.get("content_bg"),
                    "content_border": c.get("content_border"),
                    "label": c.get("label"),
                    "group_bg": c.get("group_bg"),
                    "group_border": c.get("group_border"),
                    "input_bg": c.get("input_bg"),
                    "input_border": c.get("input_border"),
                    "button_bg": c.get("btn_secondary_bg"),
                    "button_hover": c.get("btn_ghost_bg"),
                    "text": c.get("text"),
                }
            else:
                palette = {
                    "root_bg": "#111827" if dark else "#F8FAFC",
                    "sidebar_grad_top": "#1F2937" if dark else "#F1F5F9",
                    "sidebar_grad_bottom": "#111827" if dark else "#E2E8F0",
                    "sidebar_border": "rgba(255, 255, 255, 0.05)" if dark else "#E5E7EB",
                    "content_bg": "#1F2937" if dark else "#FFFFFF",
                    "content_border": "rgba(255, 255, 255, 0.1)" if dark else "#E5E7EB",
                    "label": "#E5E7EB" if dark else "#0F172A",
                    "group_bg": "rgba(0, 0, 0, 0.2)" if dark else "#F1F5F9",
                    "group_border": "#374151" if dark else "#E5E7EB",
                    "input_bg": "rgba(0, 0, 0, 0.3)" if dark else "#FFFFFF",
                    "input_border": "#4B5563" if dark else "#94A3B8",
                    "button_bg": "#374151" if dark else "#E2E8F0",
                    "button_hover": "#4B5563" if dark else "#CBD5E1",
                    "text": "#E5E7EB" if dark else "#0F172A",
                }

            # Global style
            self.setStyleSheet(f"""
                QWidget#TabPage, QFrame#ContentWrapper {{
                    background-color: transparent;
                }}
                QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget {{
                    background-color: transparent;
                    border: none;
                }}
                QTabWidget::pane {{ border: 0; background: transparent; }}
                QStackedWidget {{ background: transparent; }}
                QWidget#MainContent {{
                    background-color: {palette['content_bg']};
                    border: 1px solid {palette['content_border']};
                    border-radius: 20px;
                }}
            """)

            if hasattr(self, "_root_widget"):
                self._root_widget.setStyleSheet(f"QWidget {{ background: {palette['root_bg']}; }}")
            if hasattr(self, "_sidebar_widget"):
                try:
                    if hasattr(self, "theme_manager") and self.theme_manager:
                        self._sidebar_widget.setStyleSheet(self.theme_manager.styles.sidebar_style())
                    else:
                        self._sidebar_widget.setStyleSheet(f"""
                            QWidget#SideBar {{
                                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {palette['sidebar_grad_top']}, stop:1 {palette['sidebar_grad_bottom']});
                                border: 1px solid {palette['sidebar_border']};
                                border-radius: 20px;
                            }}
                        """)
                except Exception:
                    pass
            if hasattr(self, "_content_widget"):
                if dark:
                    self._content_widget.setStyleSheet(f"""
                        QWidget#MainContent {{
                            background-color: {palette['content_bg']};
                            border-radius: 20px;
                        }}
                        QLabel {{
                            color: {palette['label']};
                            background: transparent;
                            font: 10pt "Microsoft YaHei UI";
                        }}
                        QGroupBox {{
                            background-color: {palette['group_bg']};
                            border: 1px solid {palette['group_border']};
                            border-radius: 10px;
                            margin-top: 10px;
                            padding: 10px;
                            font: bold 10pt "Microsoft YaHei UI";
                        }}
                        QGroupBox::title {{
                            subcontrol-origin: margin;
                            subcontrol-position: top left;
                            padding: 0 4px;
                            color: {palette['label']};
                            background: transparent;
                            font: bold 10pt "Microsoft YaHei UI";
                        }}
                        QPushButton {{
                            background: {palette['button_bg']};
                            color: {palette['text']};
                            border: 1px solid {palette['input_border']};
                            border-radius: 8px;
                            padding: 5px 10px;
                            font: 10pt "Microsoft YaHei UI";
                        }}
                        QPushButton:hover {{
                            background: {palette['button_hover']};
                            color: {palette['text']};
                        }}
                        QLineEdit {{
                            background-color: {palette['input_bg']};
                            color: {palette['text']};
                            border: 1px solid {palette['input_border']};
                            border-radius: 6px;
                            padding: 5px 10px;
                            font: 10pt "Microsoft YaHei UI";
                            selection-background-color: {c.get('accent', '#6366F1') if c else '#6366F1'};
                        }}
                        QLineEdit:hover, QComboBox:hover {{
                            background-color: rgba(255, 255, 255, 0.05);
                            border: 1px solid #6B7280;
                        }}
                        QLineEdit:focus, QComboBox:focus {{
                            background-color: {palette['input_bg']};
                            border: 2px solid {c.get('accent', '#6366F1') if c else '#6366F1'};
                            padding: 4px 9px;
                        }}
                        QComboBox {{
                            background-color: {palette['input_bg']};
                            color: {palette['text']};
                            border: 1px solid {palette['input_border']};
                            border-radius: 6px;
                            padding: 5px 10px;
                            font: 10pt "Microsoft YaHei UI";
                        }}
                        QComboBox QAbstractItemView {{
                            background-color: {palette['content_bg']};
                            selection-background-color: {c.get('accent', '#6366F1') if c else '#6366F1'};
                            selection-color: #FFFFFF;
                            font: 10pt "Microsoft YaHei UI";
                            border: 1px solid {palette['group_border']};
                            outline: none;
                        }}
                        QRadioButton, QCheckBox {{
                            color: {palette['label']};
                            font: 10pt "Microsoft YaHei UI";
                            spacing: 6px;
                        }}
                        QCheckBox::indicator, QRadioButton::indicator {{
                            width: 20px;
                            height: 20px;
                            border: 2px solid #6B7280;
                            border-radius: 4px;
                            background: transparent;
                        }}
                        QRadioButton::indicator {{ border-radius: 9px; }}
                        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
                            background-color: {c.get('accent', '#6366F1') if c else '#6366F1'};
                            border-color: {c.get('accent', '#6366F1') if c else '#6366F1'};
                            image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M2 5.5L4.5 8L10 2.5' stroke='white' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round' fill='none'/%3E%3C/svg%3E");
                        }}
                    """)
                else:
                    self._content_widget.setStyleSheet(f"""
                        QWidget#MainContent {{
                            background-color: {palette['content_bg']};
                            border-radius: 20px;
                        }}
                        QLabel {{
                            color: {palette['label']};
                            background: transparent;
                            font: 10pt "Microsoft YaHei UI";
                        }}
                        QGroupBox {{
                            background-color: {palette['group_bg']};
                            border: 1px solid {palette['group_border']};
                            border-radius: 10px;
                            margin-top: 10px;
                            padding: 10px;
                            font: bold 10pt "Microsoft YaHei UI";
                        }}
                        QGroupBox::title {{
                            subcontrol-origin: margin;
                            subcontrol-position: top left;
                            padding: 0 4px;
                            color: {palette['label']};
                            background: transparent;
                            font: bold 10pt "Microsoft YaHei UI";
                        }}
                        QPushButton {{
                            background: {palette['button_bg']};
                            color: {palette['text']};
                            border: 1px solid {palette['input_border']};
                            border-radius: 8px;
                            padding: 5px 10px;
                            font: 10pt "Microsoft YaHei UI";
                        }}
                        QPushButton:hover {{
                            background: {palette['button_hover']};
                            color: {palette['text']};
                        }}
                        QLineEdit {{
                            background-color: {palette['input_bg']};
                            color: {palette['text']};
                            border: 1px solid {palette['input_border']};
                            border-radius: 6px;
                            padding: 5px 10px;
                            font: 10pt "Microsoft YaHei UI";
                        }}
                        QComboBox {{
                            background-color: {palette['input_bg']};
                            color: {palette['text']};
                            border: 1px solid {palette['input_border']};
                            border-radius: 6px;
                            padding: 5px 10px;
                            font: 10pt "Microsoft YaHei UI";
                        }}
                        QRadioButton, QCheckBox {{
                            color: {palette['text']};
                            font: 10pt "Microsoft YaHei UI";
                            spacing: 6px;
                        }}
                        QCheckBox::indicator, QRadioButton::indicator {{
                            width: 20px;
                            height: 20px;
                            border: 2px solid {palette['input_border']};
                            border-radius: 4px;
                            background: transparent;
                        }}
                        QRadioButton::indicator {{ border-radius: 9px; }}
                        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
                            background-color: {c.get('accent', '#6366F1') if c else '#6366F1'};
                            border-color: {c.get('accent', '#6366F1') if c else '#6366F1'};
                            image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M2 5.5L4.5 8L10 2.5' stroke='white' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round' fill='none'/%3E%3C/svg%3E");
                        }}
                    """)

            # Update nav button style
            if hasattr(self, "_nav_buttons"):
                nav_style = """QPushButton {{
                        color: {text_muted};
                        background-color: transparent;
                        border: 1px solid transparent;
                        border-radius: 12px;
                        padding: 0px 15px;
                        text-align: left;
                        font: 10.5pt "Microsoft YaHei UI";
                        margin: 0px 0px;
                    }}
                    QPushButton:hover {{
                        background-color: {hover_bg};
                        color: {hover_text};
                    }}
                    QPushButton:checked {{
                        background-color: {checked_bg};
                        color: {checked_text};
                        border: 1px solid {checked_border};
                        font-weight: bold;
                    }}"""
                if c is not None:
                    if dark:
                        qss = nav_style.format(
                            text_muted=c.get("sidebar_text_muted"),
                            hover_bg=c.get("btn_ghost_bg"),
                            hover_text=c.get("text"),
                            checked_bg=c.get("text"),
                            checked_text="#333333",
                            checked_border=c.get("label_muted"),
                        )
                    else:
                        qss = nav_style.format(
                            text_muted=c.get("sidebar_text"),
                            hover_bg="rgba(56, 189, 248, 0.12)",
                            hover_text=c.get("text"),
                            checked_bg="#38BDF8",
                            checked_text=c.get("text"),
                            checked_border="#0EA5E9",
                        )
                else:
                    if dark:
                        qss = nav_style.format(
                            text_muted="#999999",
                            hover_bg="rgba(255, 255, 255, 0.1)",
                            hover_text="#FFFFFF",
                            checked_bg="#FFFFFF",
                            checked_text="#333333",
                            checked_border="#E5E7EB",
                        )
                    else:
                        qss = nav_style.format(
                            text_muted="#1F2937",
                            hover_bg="rgba(56, 189, 248, 0.12)",
                            hover_text="#0F172A",
                            checked_bg="#38BDF8",
                            checked_text="#0F172A",
                            checked_border="#0EA5E9",
                        )
                for b in self._nav_buttons:
                    b.setStyleSheet(qss)

            # Update collapse button style based on theme
            if hasattr(self, "_collapse_btn"):
                if hasattr(self, "theme_manager") and self.theme_manager:
                    collapse_style = self.theme_manager.styles.collapse_button_style()
                    self._collapse_btn.setStyleSheet(collapse_style)
                else:
                    if dark:
                        self._collapse_btn.setStyleSheet("""
                            QPushButton#CollapseButton {
                                background: rgba(255, 255, 255, 0.1);
                                border: 1px solid rgba(255, 255, 255, 0.2);
                                color: #E5E7EB;
                                border-radius: 8px;
                                font: 10pt "Microsoft YaHei UI";
                            }
                            QPushButton#CollapseButton:hover {
                                background: rgba(255, 255, 255, 0.2);
                                color: #FFFFFF;
                            }
                        """)
                    else:
                        self._collapse_btn.setStyleSheet("""
                            QPushButton#CollapseButton {
                                background: rgba(0, 0, 0, 0.05);
                                border: 1px solid rgba(0, 0, 0, 0.1);
                                color: #1F2937;
                                border-radius: 8px;
                                font-size: 16px;
                            }
                            QPushButton#CollapseButton:hover {
                                background: rgba(0, 0, 0, 0.1);
                                color: #0F172A;
                            }
                        """)

            # Update expand button style based on theme
            if hasattr(self, "_expand_btn"):
                if hasattr(self, "theme_manager") and self.theme_manager:
                    expand_style = self.theme_manager.styles.expand_button_style()
                    self._expand_btn.setStyleSheet(expand_style)
                else:
                    if dark:
                        self._expand_btn.setStyleSheet("""
                            QPushButton#ExpandButton {
                                background: rgba(255, 255, 255, 0.1);
                                border: 1px solid rgba(255, 255, 255, 0.2);
                                color: #E5E7EB;
                                border-radius: 8px;
                                font-size: 16px;
                            }
                            QPushButton#ExpandButton:hover {
                                background: rgba(255, 255, 255, 0.2);
                                color: #FFFFFF;
                            }
                        """)
                    else:
                        self._expand_btn.setStyleSheet("""
                            QPushButton#ExpandButton {
                                background: rgba(0, 0, 0, 0.05);
                                border: 1px solid rgba(0, 0, 0, 0.1);
                                color: #1F2937;
                                border-radius: 8px;
                                font-size: 16px;
                            }
                            QPushButton#ExpandButton:hover {
                                background: rgba(0, 0, 0, 0.1);
                                color: #0F172A;
                            }
                        """)

            # Update theme buttons style based on ThemeStyles
            if hasattr(self, "_theme_buttons"):
                try:
                    if hasattr(self, "theme_manager") and self.theme_manager:
                        qss = self.theme_manager.styles.theme_button_style()
                    else:
                        qss = ThemeStyles(ThemeColors(dark=dark)).theme_button_style()
                    for btn in self._theme_buttons:
                        btn.setStyleSheet(qss)
                except Exception:
                    pass

            # Update header labels colors (title and author)
            if hasattr(self, "_header_labels"):
                # First label is title, second is author
                if len(self._header_labels) >= 2:
                    if c is not None:
                        # Use theme colors
                        title_color = c.get("text")
                        author_color = c.get("label_muted")
                        self._header_labels[0].setStyleSheet(f"font: bold 18pt \"Microsoft YaHei\"; color: {title_color}; background: transparent;")
                        self._header_labels[1].setStyleSheet(f"color: {author_color}; font: 9pt \"Microsoft YaHei\"; background: transparent;")
                    else:
                        if dark:
                            # Dark theme: white title and gray author
                            self._header_labels[0].setStyleSheet("font: bold 18pt \"Microsoft YaHei\"; color: #FFFFFF; background: transparent;")
                            self._header_labels[1].setStyleSheet("color: #9CA3AF; font: 9pt \"Microsoft YaHei\"; background: transparent;")
                        else:
                            # Light theme: dark title and author
                            self._header_labels[0].setStyleSheet("font: bold 18pt \"Microsoft YaHei\"; color: #1F2937; background: transparent;")
                            self._header_labels[1].setStyleSheet("color: #4B5563; font: 9pt \"Microsoft YaHei\"; background: transparent;")

            # Update version label colors (value labels are even indices, title labels are odd indices)
            if hasattr(self, "_version_label_refs"):
                if c is not None:
                    title_color = c.get("label_dim")
                    value_color = c.get("text")
                else:
                    title_color = "#9CA3AF" if dark else "#475569"
                    value_color = "#E5E7EB" if dark else "#0F172A"
                for i, label in enumerate(self._version_label_refs):
                    # Even indices (0, 2, 4, ...) are value labels
                    # Odd indices (1, 3, 5, ...) are title labels
                    if i % 2 == 0:
                        label.setStyleSheet(f"font: bold 10pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {value_color}; background: transparent;")
                    else:
                        label.setStyleSheet(f"color: {title_color}; font: bold 9pt \"Microsoft YaHei UI\"; background: transparent;")

            # Update version management page labels (当前分支, 当前提交)
            if hasattr(self, "lbl_ver_branch") and hasattr(self, "lbl_ver_commit"):
                val_color_pv = c.get("text") if c is not None else ("#E5E7EB" if dark else "#0F172A")
                self.lbl_ver_branch.setStyleSheet(f"color: {val_color_pv}; font: bold 10pt 'Microsoft YaHei UI';")
                self.lbl_ver_commit.setStyleSheet(f"color: {val_color_pv}; font: bold 10pt 'Microsoft YaHei UI';")

            # Update version settings panel labels (当前分支, 当前提交, GitHub代理, 升级策略)
            if hasattr(self, "_version_settings_labels"):
                # 使用更醒目的颜色，不是 muted
                if c is not None:
                    label_color_pv = c.get("label")
                else:
                    label_color_pv = "#D1D5DB" if dark else "#374151"
                for label in self._version_settings_labels:
                    label.setStyleSheet(f"color: {label_color_pv}; font: 10pt 'Microsoft YaHei UI';")

            # Update page title colors
            if hasattr(self, "_page_title_refs"):
                title_color = self.theme_manager.colors.get("text") if hasattr(self, 'theme_manager') and self.theme_manager else "#1F2937"
                for label in self._page_title_refs:
                    # 只替换 color 属性，保留其他样式
                    import re
                    current_sheet = label.styleSheet()
                    new_sheet = re.sub(r'color:\s*#[0-9A-Fa-f]{6}\s*;', f'color: {title_color};', current_sheet)
                    label.setStyleSheet(new_sheet)
                    new_sheet = new_sheet.replace("color: #1F2937;", f"color: {title_color};")
                    label.setStyleSheet(new_sheet)

            # Update label colors (t1, t2 labels in About Me page)
            if hasattr(self, "_styled_widgets"):
                if c is not None:
                    name_color = c.get("text")
                    quote_color = c.get("label_muted")
                    badge_bg = c.get("badge_bg")
                    badge_color = c.get("badge_text")
                else:
                    name_color = "#FFFFFF" if dark else "#1F2937"
                    quote_color = "#9CA3AF" if dark else "#475569"
                    badge_bg = "rgba(255,255,255,0.1)" if dark else "rgba(0,0,0,0.05)"
                    badge_color = "#A5B4FC" if dark else "#0284C7"
                for widget in self._styled_widgets:
                    style_sheet = widget.styleSheet()
                    if style_sheet:
                        if "color: #FFFFFF;" in style_sheet:
                            widget.setStyleSheet(style_sheet.replace("color: #FFFFFF;", f"color: {name_color};"))
                        elif "color: #9CA3AF;" in style_sheet:
                            widget.setStyleSheet(style_sheet.replace("color: #9CA3AF;", f"color: {quote_color};"))
                    # Handle HTML content labels (lh_desc in About Launcher page)
                    if isinstance(widget, QtWidgets.QLabel) and widget.text():
                        html_content = widget.text()
                        if "color: #FFFFFF" in html_content:
                            widget.setText(html_content.replace("color: #FFFFFF", f"color: {name_color}"))
                        if "color: #9CA3AF" in html_content:
                            widget.setText(html_content.replace("color: #9CA3AF", f"color: {quote_color}"))
                        if "background-color: rgba(255,255,255,0.1)" in html_content:
                            widget.setText(html_content.replace("background-color: rgba(255,255,255,0.1)", f"background-color: {badge_bg}"))
                        if "color: #A5B4FC" in html_content:
                            widget.setText(html_content.replace("color: #A5B4FC", f"color: {badge_color}"))

            # Update table styles (history_table, model_mappings_table, etc.)
            if hasattr(self, "_styled_widgets"):
                # Table colors
                if c is not None:
                    bg_color = c.get("table_bg")
                    alt_bg_color = c.get("table_alt_bg")
                    text_color = c.get("table_text")
                    grid_color = c.get("table_border")
                    header_bg = c.get("table_header_bg")
                    header_border = c.get("table_header_border")
                    scroll_bg = c.get("table_scroll_bg")

                    # Card colors (ProfileCard, HeroCard, etc.)
                    card_bg = c.get("card_bg")
                    card_border = c.get("card_border")

                    # Link button colors
                    link_bg = c.get("link_bg")
                    link_border = c.get("link_border")
                    link_text = c.get("link_text")
                    link_hover_text = "#FFFFFF"
                    link_hover_border = c.get("link_hover_border")
                else:
                    bg_color = "#1F2937" if dark else "#FFFFFF"
                    alt_bg_color = "#27303f" if dark else "#F1F5F9"
                    text_color = "#E5E7EB" if dark else "#0F172A"
                    grid_color = "#374151" if dark else "#E5E7EB"
                    header_bg = "rgba(0,0,0,0.3)" if dark else "rgba(0,0,0,0.05)"
                    header_border = "#6B7280" if dark else "#94A3B8"
                    scroll_bg = "#4B5563" if dark else "#D1D5DB"

                    # Card colors (ProfileCard, HeroCard, etc.)
                    card_bg = "#1F2937" if dark else "#FFFFFF"
                    card_border = "#374151" if dark else "#E5E7EB"

                    # Link button colors
                    link_bg = "rgba(255, 255, 255, 0.05)" if dark else "rgba(0, 0, 0, 0.03)"
                    link_border = "rgba(255, 255, 255, 0.1)" if dark else "rgba(0, 0, 0, 0.1)"
                    link_text = "#A5B4FC" if dark else "#0284C7"
                    link_hover_text = "#FFFFFF"
                    link_hover_border = "#6366F1"

                for widget in self._styled_widgets:
                    style_sheet = widget.styleSheet()
                    # Handle table widget styles
                    if "background-color: #1F2937;" in style_sheet:
                        widget.setStyleSheet(style_sheet
                            .replace("background-color: #1F2937;", f"background-color: {bg_color};")
                            .replace("alternate-background-color: #27303f;", f"alternate-background-color: {alt_bg_color};")
                            .replace("color: #E5E7EB;", f"color: {text_color};")
                            .replace("gridline-color: #374151;", f"gridline-color: {grid_color};")
                            .replace("background-color: rgba(0,0,0,0.3);", f"background-color: {header_bg};")
                            .replace("background-color: rgba(0,0,0,0.05);", f"background-color: {header_bg};")
                            .replace("border-bottom: 2px solid #6B7280;", f"border-bottom: 2px solid {header_border};")
                            .replace("background: #4B5563;", f"background: {scroll_bg};")
                            .replace("background: #6B7280;", f"background: {header_border};"))
                    # Handle card styles (ProfileCard, HeroCard)
                    elif "background-color: #1F2937;" in style_sheet:
                        widget.setStyleSheet(style_sheet
                            .replace("background-color: #1F2937;", f"background-color: {card_bg};")
                            .replace("border: 1px solid #374151;", f"border: 1px solid {card_border};"))
                    # Handle link button styles
                    elif "background-color: rgba(255, 255, 255, 0.05);" in style_sheet:
                        widget.setStyleSheet(style_sheet
                            .replace("background-color: rgba(255, 255, 255, 0.05);", f"background-color: {link_bg};")
                            .replace("border: 1px solid rgba(255, 255, 255, 0.1);", f"border: 1px solid {link_border};")
                            .replace("color: #A5B4FC;", f"color: {link_text};")
                            .replace("background-color: rgba(255, 255, 255, 0.1);", f"background-color: {link_bg};")
                            .replace("border: 1px solid #6366F1;", f"border: 1px solid {link_hover_border};"))

            # Update input style groups (env_group, form_group) - for kernel version and model management pages
            if hasattr(self, "_input_style_groups"):
                # Regenerate common_input_qss based on theme
                new_common_qss = _get_common_input_qss(dark)
                for group in self._input_style_groups:
                    group.setStyleSheet(new_common_qss)

            # Update secondary buttons
            if hasattr(self, "_secondary_buttons"):
                new_secondary_style = _get_secondary_btn_style(dark)
                for btn in self._secondary_buttons:
                    btn.setStyleSheet(new_secondary_style)

            # Update new refactored pages
            if hasattr(self, "_new_pages"):
                # Call update_theme on each new page using current ThemeManager styles
                theme_styles = self.theme_manager.styles if hasattr(self, "theme_manager") else ThemeStyles(ThemeColors(dark=dark))
                for page in self._new_pages.values():
                    if hasattr(page, "update_theme"):
                        page.update_theme(theme_styles)

        self._apply_theme = _apply_theme
        self._theme_value = theme_value

        # 使用主题颜色而不是硬编码颜色
        is_dark = self._theme_value != "light"
        primary_bg = self.theme_manager.colors.get('btn_primary_bg') if hasattr(self, 'theme_manager') and self.theme_manager else '#7F56D9'
        primary_hover = self.theme_manager.colors.get('btn_primary_hover') if hasattr(self, 'theme_manager') and self.theme_manager else '#9E77ED'
        primary_pressed = self.theme_manager.colors.get('btn_primary_pressed') if hasattr(self, 'theme_manager') and self.theme_manager else '#53389E'

        common_btn_style = f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {primary_bg}, stop:1 {primary_hover});
            color: #FFFFFF;
            border: none;
            border-radius: 12px;
            font: bold 10pt "Microsoft YaHei UI";
            padding: 8px 16px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6941C6, stop:1 {primary_bg});
        }}
        QPushButton:pressed {{
            background: {primary_pressed};
            padding-top: 2px;
            padding-left: 2px;
        }}
        """
        self._common_btn_style = common_btn_style

        try:
            from PyQt5.QtGui import QIcon
            icon_path = ASSETS.resolve_asset('rabbit.ico') or ASSETS.resolve_asset('rabbit.png')
            if icon_path and icon_path.exists():
                ic = QIcon(str(icon_path))
                # 同时设置窗口与应用图标，以确保任务栏/Alt-Tab 使用头像
                try:
                    self.qt_app.setWindowIcon(ic)
                except Exception:
                    pass
                try:
                    self.setWindowIcon(ic)
                except Exception:
                    pass
        except Exception:
            pass
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        main = QtWidgets.QHBoxLayout(root)
        self._root_widget = root

        # Color constants definition (Moved out of sidebar block)
        c = {"SIDEBAR_BG": "#1a1c1e", "TEXT": "#1F2937", "TEXT_MUTED": "#4B5563", "ACCENT": "#6366F1", "ACCENT_HOVER": "#5258CF", "ACCENT_ACTIVE": "#3F46B8", "BG": "#F8FAFC", "BORDER": "#E5E7EB", "BTN_BG": "#F1F5F9", "BTN_HOVER_BG": "#E2E8F0", "SIDEBAR_ACTIVE": "#22262C", "SIDEBAR_DIVIDER_COLOR": "#E5E7EB"}
        try:
            from ui.constants import COLORS as _C
            c.update(_C)
        except Exception:
            pass

        # Main Layout Spacing (for rounded corners visibility)
        try:
            main.setSpacing(12)
            main.setContentsMargins(12, 12, 12, 12)
        except Exception:
            pass

        # Sidebar 内层：实际的侧边内容
        sidebar_inner = QtWidgets.QWidget()
        sidebar_inner.setObjectName("SideBar")
        # Enable styled background for sidebar to support radius and bg color
        sidebar_inner.setAttribute(Qt.WA_StyledBackground, True)

        side_layout = QtWidgets.QVBoxLayout(sidebar_inner)
        side_layout.setContentsMargins(8, 8, 8, 8)
        side_layout.setSpacing(10)

        # Sidebar Header Container
        header_frame = QtWidgets.QFrame()
        header_frame.setObjectName("SidebarHeader")
        header_frame.setStyleSheet("""
            #SidebarHeader {
                background-color: transparent;
                border: none;
            }
        """)

        header_layout = QtWidgets.QVBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 10, 0, 10)
        header_layout.setSpacing(8)

        title = QtWidgets.QLabel("ComfyUI\n启动器")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font: bold 18pt \"Microsoft YaHei\"; color: #FFFFFF; background: transparent;")

        # Add glow effect to title
        try:
            glow = QtWidgets.QGraphicsDropShadowEffect(self)
            glow.setBlurRadius(15)
            glow.setColor(QtGui.QColor(158, 119, 237, 150)) # Purple glow
            glow.setOffset(0, 0)
            title.setGraphicsEffect(glow)
        except Exception:
            pass

        try:
            from PyQt5.QtGui import QFont
            tf = title.font()
            tf.setLetterSpacing(QFont.PercentageSpacing, 102)
            title.setFont(tf)
        except Exception:
            pass
        header_layout.addWidget(title)

        author = QtWidgets.QLabel("by 黎黎原上咩")
        author.setAlignment(Qt.AlignCenter)
        author.setStyleSheet(f"color: #6B7280; font: 9pt \"Microsoft YaHei\"; background: transparent;")
        header_layout.addWidget(author)

        # Store header labels reference for collapse/expand
        self._header_labels = [title, author]

        side_layout.addWidget(header_frame)

        side_layout.addSpacing(10)

        nav = QtWidgets.QVBoxLayout()
        nav.setSpacing(12)
        side_layout.addLayout(nav)

        class NavBtn(QtWidgets.QPushButton):
            def __init__(self, text):
                super().__init__(text)
                self.setCursor(Qt.PointingHandCursor)
                self.setCheckable(True)
                self.setMinimumHeight(45)

                # Shadow effect for depth (applied once)
                try:
                    shadow = QtWidgets.QGraphicsDropShadowEffect(self)
                    shadow.setBlurRadius(15)
                    shadow.setOffset(0, 4)
                    shadow.setColor(QtGui.QColor(0, 0, 0, 40))
                    self.setGraphicsEffect(shadow)
                except Exception:
                    pass

        btns = {
            "launch": NavBtn("🚀 启动与更新"),
            "version": NavBtn("🧬 内核版本管理"),
            "models": NavBtn("📂 外置模型库管理"),
            "about": NavBtn("👤 关于我"),
            "comfyui": NavBtn("📚 关于 ComfyUI"),
            "about_launcher": NavBtn("🧰 关于启动器"),
        }
        # 为导航按钮添加工具提示和存储完整文字
        btns["launch"].setToolTip("启动、停止ComfyUI，查看运行状态")
        btns["launch"].setProperty("full_text", "🚀 启动与更新")
        btns["version"].setToolTip("管理ComfyUI内核版本，切换提交")
        btns["version"].setProperty("full_text", "🧬 内核版本管理")
        btns["models"].setToolTip("管理外置模型库路径配置")
        btns["models"].setProperty("full_text", "📂 外置模型库管理")
        btns["about"].setToolTip("作者信息和相关链接")
        btns["about"].setProperty("full_text", "👤 关于我")
        btns["comfyui"].setToolTip("关于ComfyUI的介绍和官方链接")
        btns["comfyui"].setProperty("full_text", "📚 关于 ComfyUI")
        btns["about_launcher"].setToolTip("关于启动器的介绍和相关链接")
        btns["about_launcher"].setProperty("full_text", "🧰 关于启动器")
        self._nav_buttons = list(btns.values())
        for b in btns.values():
            nav.addWidget(b)

        bottom_container = QtWidgets.QWidget()
        bottom_container.setStyleSheet("background: transparent; border: none;")
        bottom_layout = QtWidgets.QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 8, 0, 0)
        bottom_layout.setSpacing(6)

        theme_row = QtWidgets.QWidget()
        theme_row.setStyleSheet("background: transparent; border: none;")
        theme_row_layout = QtWidgets.QHBoxLayout(theme_row)
        theme_row_layout.setContentsMargins(0, 0, 0, 0)
        theme_row_layout.setSpacing(6)

        def _make_theme_btn(icon: str, label: str, value: str):
            btn = QtWidgets.QPushButton(f"{icon}  {label}")
            btn.setObjectName("ThemeBtn")
            btn.setCheckable(True)
            btn.setFixedHeight(36)
            btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("theme_value", value)
            btn.setToolTip(f"切换到{label}主题")
            return btn

        btn_dark = _make_theme_btn("🌙", "深色", "dark")
        btn_light = _make_theme_btn("☀️", "浅色", "light")

        self._theme_buttons = [btn_dark, btn_light]

        initial_theme = self._theme_value or "dark"
        if initial_theme == "light":
            btn_light.setChecked(True)
        else:
            btn_dark.setChecked(True)

        def _on_theme_change(btn):
            theme = btn.property("theme_value")
            prev = getattr(self, "_theme_value", "dark")
            if theme == prev:
                return
            proceed = self._confirm_restart_on_theme_change(theme, prev)
            if not proceed:
                # 恢复按钮选中状态
                for b in self._theme_buttons:
                    b.setChecked(b is btn and False or (b.property("theme_value") == prev))
                return
            self._theme_value = theme
            try:
                self.services.config.set("ui_settings.theme", theme)
                self.services.config.save(None)
                self.config = self.services.config.get_config()
            except Exception:
                pass
            try:
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(200, self._restart_app)
            except Exception:
                self._restart_app()

        btn_dark.clicked.connect(lambda: _on_theme_change(btn_dark))
        btn_light.clicked.connect(lambda: _on_theme_change(btn_light))

        theme_row_layout.addWidget(btn_dark, 1)
        theme_row_layout.addWidget(btn_light, 1)

        bottom_layout.addWidget(theme_row)

        side_layout.addWidget(bottom_container)
        nav.addStretch(1)

        sidebar_container = QtWidgets.QWidget()
        sidebar_container_layout = QtWidgets.QHBoxLayout(sidebar_container)
        sidebar_container_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_container_layout.setSpacing(0)

        sidebar = QtWidgets.QScrollArea()
        sidebar.setWidget(sidebar_inner)
        sidebar.setWidgetResizable(True)
        sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar.setFrameShape(QtWidgets.QFrame.NoFrame)
        sidebar.setFixedWidth(self._sidebar_collapsed_width if self._sidebar_collapsed else self._sidebar_expanded_width)
        # 滚动区域用于控制宽度，内部的 sidebar_inner 负责实际的深色卡片样式
        self._sidebar_scroll = sidebar
        self._sidebar_widget = sidebar_inner

        sidebar_container_layout.addWidget(sidebar)

        collapse_panel = QtWidgets.QWidget()
        collapse_panel_layout = QtWidgets.QVBoxLayout(collapse_panel)
        collapse_panel_layout.setContentsMargins(0, 0, 0, 0)
        collapse_panel_layout.setSpacing(0)
        collapse_panel.setFixedWidth(12)

        collapse_btn = QtWidgets.QPushButton("◀")
        collapse_btn.setObjectName("CollapseButton")
        collapse_btn.setFixedSize(12, 60)
        collapse_btn.setCursor(Qt.PointingHandCursor)
        collapse_btn.setStyleSheet(
            self.theme_manager.styles.collapse_button_style()
            if hasattr(self, "theme_manager") and self.theme_manager
            else ThemeStyles(ThemeColors(dark=(getattr(self, "_theme_value", "dark") != "light"))).collapse_button_style()
        )
        collapse_btn.clicked.connect(self._toggle_sidebar)
        collapse_btn.setToolTip("收起侧边栏")
        self._collapse_btn = collapse_btn

        expand_btn = QtWidgets.QPushButton("▶")
        expand_btn.setObjectName("ExpandButton")
        expand_btn.setFixedSize(12, 60)
        expand_btn.setCursor(Qt.PointingHandCursor)
        expand_btn.setStyleSheet(
            self.theme_manager.styles.expand_button_style()
            if hasattr(self, "theme_manager") and self.theme_manager
            else ThemeStyles(ThemeColors(dark=(getattr(self, "_theme_value", "dark") != "light"))).expand_button_style()
        )
        expand_btn.clicked.connect(self._toggle_sidebar)
        expand_btn.setToolTip("展开侧边栏")
        expand_btn.setVisible(False)
        self._expand_btn = expand_btn

        collapse_panel_layout.addStretch(1)
        collapse_panel_layout.addWidget(collapse_btn, 0, Qt.AlignVCenter)
        collapse_panel_layout.addWidget(expand_btn, 0, Qt.AlignVCenter)
        collapse_panel_layout.addStretch(1)

        sidebar_container_layout.addWidget(collapse_panel)

        self._theme_widgets = [theme_row]

        # Style updates for main window background to support the transparency
        # style is applied via theme

        # Content area
        content = QtWidgets.QStackedWidget()
        content.setObjectName("MainContent")
        # Enable styled background for MainContent to fix background bleed on rounded corners
        content.setAttribute(Qt.WA_StyledBackground, True)
        self._content_widget = content

        content.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        # style is applied via theme
        main.addWidget(sidebar_container)
        # Divider removed for floating style
        main.addWidget(content, 1)

        # Initialize ThemeManager for new pages
        is_dark = self._theme_value != "light"
        self.theme_manager = ThemeManager(dark=is_dark)

        # Re-apply theme now that theme_manager is available
        # This ensures theme buttons and other widgets get proper theme colors
        self._apply_theme(self._theme_value)

        # Create page instances using new refactored pages
        page_launch = LaunchPage(app=self, theme_manager=self.theme_manager)
        try:
            if hasattr(self, "big_btn"):
                self.big_btn.attach(page_launch.btn_toggle)
        except Exception:
            pass
        page_version = VersionPage(app=self, theme_manager=self.theme_manager)
        page_models = ModelsPage(app=self, theme_manager=self.theme_manager)
        page_about_me = AboutMePage(theme_manager=self.theme_manager)
        page_about_comfyui = AboutComfyUIPage(theme_manager=self.theme_manager)
        page_about_launcher = AboutLauncherPage(app=self, theme_manager=self.theme_manager)

        # Store references for theme updates
        self._new_pages = {
            "launch": page_launch,
            "version": page_version,
            "models": page_models,
            "about": page_about_me,
            "comfyui": page_about_comfyui,
            "about_launcher": page_about_launcher,
        }


        def wrap_in_scroll(widget):
            # Ensure the widget inside scroll area is transparent
            widget.setAttribute(Qt.WA_StyledBackground, True)
            widget.setStyleSheet("background-color: transparent;")

            scroll = QtWidgets.QScrollArea()
            scroll.setWidget(widget)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setStyleSheet(f"""
                QScrollArea {{
                    background-color: transparent;
                    border: none;
                }}
                QScrollArea > QWidget > QWidget {{
                    background-color: transparent;
                }}
                QScrollBar:vertical {{
                    border: none;
                    background: transparent;
                    width: 8px;
                    margin: 0px 0px 0px 0px;
                    border-radius: 0px;
                }}
                QScrollBar::handle:vertical {{
                    background: {c.get('ACCENT', '#6366F1')};
                    min-height: 20px;
                    border-radius: 4px;
                }}
                QScrollBar::handle:vertical:hover {{
                    background: {c.get('ACCENT_HOVER', '#5258CF')};
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                    height: 0px;
                    background: none;
                }}
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                    background: transparent;
                }}
                QScrollBar::horizontal {{
                    border: none;
                    background: transparent;
                    height: 8px;
                    margin: 0px 0px 0px 0px;
                    border-radius: 0px;
                }}
                QScrollBar::handle:horizontal {{
                    background: {c.get('ACCENT', '#6366F1')};
                    min-width: 20px;
                    border-radius: 4px;
                }}
                QScrollBar::handle:horizontal:hover {{
                    background: {c.get('ACCENT_HOVER', '#5258CF')};
                }}
                QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                    width: 0px;
                    background: none;
                }}
                QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                    background: transparent;
                }}
            """)
            return scroll

        content.addWidget(wrap_in_scroll(page_launch))
        content.addWidget(wrap_in_scroll(page_version))
        content.addWidget(wrap_in_scroll(page_models))
        content.addWidget(wrap_in_scroll(page_about_me))
        content.addWidget(wrap_in_scroll(page_about_comfyui))
        content.addWidget(wrap_in_scroll(page_about_launcher))
        # Navigation actions
        pages = {
            "launch": page_launch,
            "version": page_version,
            "models": page_models,
            "about": page_about_me,
            "comfyui": page_about_comfyui,
            "about_launcher": page_about_launcher,
        }
        def _select_tab(name):
            idx = list(pages.keys()).index(name)
            content.setCurrentIndex(idx)
            for k, b in btns.items():
                b.setChecked(k == name)
        for key, b in btns.items():
            b.clicked.connect(lambda _, k=key: _select_tab(k))
        _select_tab("launch")
        try:
            self.get_version_info("all")
        except Exception:
            pass

        # Initialize sidebar visibility based on config
        self._update_sidebar_visibility()

        # 在所有内容和滚动区域构建完成后，再根据右侧内容区域设置窗口初始大小
        try:
            primary_screen = QtWidgets.QApplication.primaryScreen()
            avail_geo = primary_screen.availableGeometry()
            s_w, s_h = avail_geo.width(), avail_geo.height()

            # 先让布局把理想大小算出来（此时右侧页面已加入 QScrollArea）
            self.adjustSize()
            hint = self.sizeHint()

            base_w = 1350
            base_h = 870

            final_w = min(max(hint.width(), base_w), s_w - 40)
            final_h = min(max(hint.height(), base_h), s_h - 80)

            self.resize(final_w, final_h)
            self.move(
                avail_geo.x() + (s_w - final_w) // 2,
                avail_geo.y() + (s_h - final_h) // 2
            )
        except Exception:
            pass

    def _confirm_restart_on_theme_change(self, new_theme: str, old_theme: str) -> bool:
        """弹窗确认：切换主题将重启启动器，不影响已启动的 ComfyUI"""
        try:
            from PyQt5 import QtWidgets
            msg = (
                "将切换到“{new}”主题。\n\n"
                "为确保所有页面样式一致，启动器需要重启。\n"
                "已启动的 ComfyUI 服务不会受到影响。\n\n"
                "是否立即重启启动器？"
            ).format(new="浅色" if new_theme == "light" else "深色")
            res = QtWidgets.QMessageBox.question(
                self,
                "切换主题并重启",
                msg,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.Yes,
            )
            return res == QtWidgets.QMessageBox.Yes
        except Exception:
            return True
    def _restart_app(self):
        """重启应用以确保主题完整生效"""
        try:
            if getattr(self, "_restart_in_progress", False):
                return
            self._restart_in_progress = True
        except Exception:
            pass
        try:
            if getattr(self, "logger", None):
                self.logger.info("主题切换：准备重启应用以完整应用样式")
        except Exception:
            pass
        
        try:
            # 清理定时器和日志，释放文件句柄
            try:
                if hasattr(self, "_sync_timer"):
                    self._sync_timer.stop()
            except Exception:
                pass
            try:
                import logging as _L
                _L.shutdown()
            except Exception:
                pass

            import sys
            import subprocess
            from pathlib import Path
            cwd = Path.cwd()
            
            env = dict(os.environ)
            # 移除可能导致问题的环境变量
            for k in list(env.keys()):
                kl = k.upper()
                if kl.startswith("_MEI") or kl.startswith("PYI_"):
                    env.pop(k, None)
            env.pop("PYTHONHOME", None)
            env.pop("PYTHONPATH", None)

            exe = str(Path(sys.executable).resolve())
            
            # 区分开发环境与打包环境的参数构造
            if getattr(sys, 'frozen', False):
                # 打包环境：sys.executable 是 exe 本身，sys.argv[0] 也是 exe 路径
                # 我们只需要 [exe, arg1, arg2...]
                args = [exe] + sys.argv[1:]
            else:
                # 开发环境：sys.executable 是 python.exe，sys.argv[0] 是脚本路径
                # 我们需要 [python.exe, script.py, arg1, arg2...]
                args = [exe] + sys.argv
            
            kwargs = {}
            if os.name == "nt":
                try:
                    creationflags = 0
                    creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
                    creationflags |= subprocess.DETACHED_PROCESS
                    kwargs['creationflags'] = creationflags
                except Exception:
                    pass
            else:
                kwargs['start_new_session'] = True
            
            subprocess.Popen(
                args,
                cwd=str(cwd),
                env=env,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **kwargs
            )
        except Exception:
            pass
        
        try:
            QtWidgets.QApplication.quit()
        except Exception:
            pass
    def resolve_git(self):
        return GitService(self).resolve_git()


    def _toggle_sidebar(self):
        """Toggle sidebar collapse/expand state"""
        self._sidebar_collapsed = not self._sidebar_collapsed
        width = self._sidebar_collapsed_width if self._sidebar_collapsed else self._sidebar_expanded_width
        target = getattr(self, "_sidebar_scroll", None) or getattr(self, "_sidebar_widget", None)
        if target is not None:
            target.setFixedWidth(width)
        self._update_sidebar_visibility()

        # Save configuration
        try:
            self.services.config.set("ui_settings.sidebar_collapsed", self._sidebar_collapsed)
            self.services.config.save(None)
        except Exception:
            pass

    def _update_sidebar_visibility(self):
        """Update sidebar visibility based on collapse state"""
        is_collapsed = self._sidebar_collapsed

        # Update collapse/expand button visibility
        if hasattr(self, "_collapse_btn"):
            self._collapse_btn.setVisible(not is_collapsed)
        if hasattr(self, "_expand_btn"):
            self._expand_btn.setVisible(is_collapsed)

        # Update header title and author visibility
        if hasattr(self, "_header_labels"):
            for label in self._header_labels:
                label.setVisible(not is_collapsed)

        # Update theme selector visibility (hide when collapsed)
        if hasattr(self, "_theme_widgets"):
            for widget in self._theme_widgets:
                widget.setVisible(not is_collapsed)

        # Update navigation button text (emoji only when collapsed)
        for btn in self._nav_buttons:
            full_text = btn.property("full_text")
            if full_text:
                # Extract emoji (first character)
                emoji = full_text.split()[0]
                btn.setText(emoji if is_collapsed else full_text)

    def get_version_info(self, scope="all"):
        try:
            if getattr(self, "logger", None):
                self.logger.info("UI: 触发版本刷新 scope=%s", scope)
        except Exception:
            pass
        try:
            prev = getattr(self, "_ver_worker", None)
            if prev and prev.isRunning():
                try:
                    prev.requestInterruption()
                except Exception:
                    pass
                try:
                    prev.quit()
                except Exception:
                    pass
                try:
                    prev.wait(1500)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            # 根据 scope 仅重置必要的标签，避免全部闪烁
            if scope in ("all", "python_related"):
                for v in (self.python_version, self.torch_version, self.frontend_version, self.template_version):
                    v.set("获取中…")
            if scope in ("all", "core_only", "selected"):
                self.comfyui_version.set("获取中…")
                self.git_status.set("检测中…")
        except Exception:
            pass
        try:
            w = VersionWorker(self, scope)
            w.pythonVersion.connect(self._on_python_version)
            w.torchVersion.connect(self._on_torch_version)
            w.frontendVersion.connect(self._on_frontend_version)
            w.templateVersion.connect(self._on_template_version)
            w.coreVersion.connect(self._on_core_version)
            w.gitStatus.connect(self._on_git_status)
            self._ver_worker = w
            try:
                w.finished.connect(w.deleteLater)
                w.finished.connect(lambda: setattr(self, "_ver_worker", None))
            except Exception:
                pass
            w.start()
        except Exception:
            try:
                refresh_version_info(self, scope)
            except Exception:
                pass

    def save_config(self):
        try:
            self.services.config.update_launch_options(
                default_compute_mode=self.compute_mode.get() or "gpu",
                # 为空时表示不加任何显存参数，由 ComfyUI 自行决定
                vram_mode=self.vram_mode.get() or "",
                default_port=self.custom_port.get() or "8188",
                disable_all_custom_nodes=self.disable_all_custom_nodes.get(),
                enable_fast_mode=self.use_fast_mode.get(),
                disable_api_nodes=self.disable_api_nodes.get(),
                enable_cors=self.enable_cors.get(),
                listen_all=self.listen_all.get(),
                use_new_manager=self.use_new_manager.get(),
                extra_args=self.extra_launch_args.get() or "",
                attention_mode=self.attention_mode.get() or "",
                browser_open_mode=self.browser_open_mode.get() or "default",
                custom_browser_path=self.custom_browser_path.get() or ""
            )
            self.services.config.update_proxy_settings(
                pypi_proxy_mode=self.pypi_proxy_mode.get(),
                pypi_proxy_url=self.pypi_proxy_url.get(),
                hf_mirror_url=self.hf_mirror_url.get(),
                hf_mirror_mode=self.selected_hf_mirror.get()
            )
            self.services.config.set("version_preferences.stable_only", bool(self.stable_only_var.get()))
            self.services.config.set("version_preferences.auto_update_deps", bool(self.auto_update_deps_var.get()))
            self.services.config.save(None)
            self.config = self.services.config.get_config()
        except Exception:
            pass

    def apply_pip_proxy_settings(self):
        try:
            if getattr(self, 'services', None):
                self.services.network.apply_pip_proxy_settings()
        except Exception:
            pass

    def reset_settings(self):
        try:
            self.compute_mode.set("gpu")
            self.vram_mode.set("--normalvram")
            self.use_fast_mode.set(False)
            self.disable_api_nodes.set(False)
            self.enable_cors.set(True)
            self.listen_all.set(True)
            self.custom_port.set("8188")
            self.extra_launch_args.set("")
            self.attention_mode.set("")
            self.browser_open_mode.set("default")
            self.custom_browser_path.set("")
            self.selected_hf_mirror.set("hf-mirror")
            self.hf_mirror_url.set("https://hf-mirror.com")
            self.pypi_proxy_mode.set("aliyun")
            self.pypi_proxy_mode_ui.set("阿里云")
            self.pypi_proxy_url.set("https://mirrors.aliyun.com/pypi/simple/")
            self.version_manager.proxy_mode_var.set("none")
            self.version_manager.proxy_mode_ui_var.set("不使用")
            self.version_manager.proxy_url_var.set("")
            self.save_config()
            self.apply_pip_proxy_settings()
        except Exception:
            pass

    def _upgrade_latest(self, stable_only: bool):
        try:
            self.start_update(stable_only)
        except Exception:
            pass

    def _format_update_summary(self, core_res: dict | None, req_res: dict | None) -> str:
        lines = []
        if isinstance(core_res, dict):
            if core_res.get("error"):
                err = str(core_res.get("error") or "")
                err = err.strip().replace("\r", " ").replace("\n", " ")
                if len(err) > 180:
                    err = err[:180] + "…"
                lines.append(f"内核：更新失败（{err}）" if err else "内核：更新失败")
            else:
                tag = core_res.get("tag") or ""
                br = core_res.get("branch") or ""
                suffix = f"（{tag or br}）" if (tag or br) else ""
                if core_res.get("updated") is True:
                    lines.append(f"内核：已更新{suffix}")
                elif core_res.get("updated") is False:
                    lines.append(f"内核：已是最新{suffix}")
                else:
                    lines.append(f"内核：更新流程完成{suffix}")
        if isinstance(req_res, dict):
            if req_res.get("updated") is True:
                installed = req_res.get("installed") or []
                satisfied = req_res.get("satisfied") or []
                lines.append(f"依赖：已同步（变更{len(installed)}项，已满足{len(satisfied)}项）")
            elif req_res.get("updated") is False:
                pass
        return "\n".join(lines).strip() or "更新流程完成"

    def start_update(self, stable_only: bool, on_done=None):
        try:
            if getattr(self, "_update_running", False):
                return
            self._update_running = True
        except Exception:
            pass
        try:
            import threading
        except Exception:
            threading = None

        def _worker():
            core_res = None
            req_res = None
            try:
                core_res = self.services.version.upgrade_latest(stable_only=stable_only)
            except Exception as e:
                core_res = {"component": "core", "error": str(e)}
            try:
                if hasattr(self, "auto_update_deps_var") and bool(self.auto_update_deps_var.get()):
                    req_res = self.services.update.sync_requirements_files()
            except Exception as e:
                req_res = {"component": "requirements", "error": str(e)}
            try:
                if getattr(self, "logger", None):
                    self.logger.info("更新结果 core=%s requirements=%s", str(core_res), str(req_res))
                    if isinstance(core_res, dict) and core_res.get("error"):
                        self.logger.warning("内核更新失败: %s", str(core_res.get("error")))
            except Exception:
                pass

            def _finish():
                try:
                    summary = self._format_update_summary(core_res, req_res)
                    try:
                        if getattr(self, "logger", None):
                            self.logger.info("更新摘要:\n%s", summary)
                    except Exception:
                        pass
                    try:
                        if isinstance(core_res, dict) and core_res.get("error"):
                            QtWidgets.QMessageBox.warning(self, "更新失败", summary)
                        else:
                            QtWidgets.QMessageBox.information(self, "更新完成", summary)
                    except Exception:
                        pass
                    try:
                        self.get_version_info("all")
                    except Exception:
                        pass
                finally:
                    try:
                        self._update_running = False
                    except Exception:
                        pass
                    if on_done:
                        try:
                            on_done()
                        except Exception:
                            pass

            self.ui_post(_finish)

        try:
            if threading:
                threading.Thread(target=_worker, daemon=True).start()
            else:
                _worker()
        except Exception:
            try:
                self._update_running = False
            except Exception:
                pass
    def _do_batch_update(self):
        try:
            results, summary = self.services.update.perform_batch_update()
            try:
                self.logger.info("更新摘要:\n%s", summary)
            except Exception:
                pass
            try:
                QtWidgets.QMessageBox.information(self, "更新完成", summary or "更新流程完成")
            except Exception:
                pass
            self.get_version_info("core_only")
        except Exception:
            try:
                QtWidgets.QMessageBox.warning(self, "更新失败", "更新过程中发生错误")
            except Exception:
                pass

    def open_root_dir(self):
        from utils.ui_actions import open_root_dir as _a
        _a(self)
    def open_logs_dir(self):
        from utils.ui_actions import open_logs_file as _a
        _a(self)
    def open_launcher_log(self):
        from utils.ui_actions import open_launcher_log as _a
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
        from utils.ui_actions import open_web
        open_web(self)

    def _is_comfyui_running(self) -> bool:
        pm = getattr(self, "process_manager", None)
        try:
            if pm and getattr(pm, "comfyui_process", None) and pm.comfyui_process.poll() is None:
                return True
        except Exception:
            pass
        try:
            if pm and hasattr(pm, "_is_http_reachable"):
                return pm._is_http_reachable()
        except Exception:
            pass
        try:
            from core.probe import is_http_reachable
            return is_http_reachable(self)
        except Exception:
            return False

    def closeEvent(self, event):
        running = False
        try:
            running = self._is_comfyui_running()
        except Exception:
            running = False
        if running:
            try:
                box = QtWidgets.QMessageBox(self)
                box.setWindowTitle("关闭启动器")
                box.setIcon(QtWidgets.QMessageBox.Question)
                box.setText(
                    "检测到 ComfyUI 仍在运行。\n\n"
                    "关闭启动器时，你可以选择：\n"
                    "1. 退出启动器，保持 ComfyUI 继续运行；\n"
                    "2. 停止 ComfyUI 并退出；\n"
                    "3. 取消，返回启动器。"
                )
                btn_exit_only = box.addButton("退出启动器（保持运行）", QtWidgets.QMessageBox.AcceptRole)
                btn_stop_exit = box.addButton("停止 ComfyUI 并退出", QtWidgets.QMessageBox.DestructiveRole)
                btn_cancel = box.addButton("取消", QtWidgets.QMessageBox.RejectRole)
                box.setDefaultButton(btn_stop_exit)
                box.exec_()
                res_btn = box.clickedButton()
            except Exception:
                res_btn = None
            # 取消：不退出
            if res_btn is btn_cancel or res_btn is None:
                try:
                    event.ignore()
                except Exception:
                    pass
                return
            # 停止并退出
            if res_btn is btn_stop_exit:
                try:
                    self._shutting_down = True
                except Exception:
                    pass
                try:
                    pm = getattr(self, "process_manager", None)
                    if pm and hasattr(pm, "stop_comfyui_sync"):
                        pm.stop_comfyui_sync()
                except Exception:
                    pass
            else:
                # 仅退出启动器，保持 ComfyUI 运行
                try:
                    self._shutting_down = True
                except Exception:
                    pass
        else:
            try:
                self._shutting_down = True
            except Exception:
                pass
        try:
            super().closeEvent(event)
        except Exception:
            try:
                event.accept()
            except Exception:
                pass

    def run(self):
        try:
            if getattr(self, "services", None) and getattr(self.services, "startup", None):
                # 启动时只执行公告检查，不做任何 Git / 版本远程访问
                self.services.startup.start_announcements_only()
        except Exception:
            pass
        try:
            import threading
            threading.Thread(target=self.services.process.monitor, daemon=True).start()
        except Exception:
            pass
        try:
            def _sync():
                try:
                    # 强制用主线程重绘，避免早期跨线程 setText 失效
                    labs = list(self._version_label_refs or [])
                    # 必须与 items 列表顺序一致: 内核, 前端, 模板库, Python, Torch, Git
                    vals = [self.comfyui_version.get(), self.frontend_version.get(), self.template_version.get(), self.python_version.get(), self.torch_version.get(), self.git_status.get()]
                    # 只更新值标签（偶数索引），不更新标题标签（奇数索引）
                    for i in range(0, len(vals) * 2, 2):
                        if i < len(labs):
                            try:
                                labs[i].setText(vals[i // 2])
                            except Exception:
                                pass
                except Exception:
                    pass
            self._sync_timer = QtCore.QTimer(self)
            self._sync_timer.timeout.connect(_sync)
            self._sync_timer.start(1000)
        except Exception:
            pass
        self.show()

        # 强制刷新布局以适配 High DPI 缩放
        try:
            self.qt_app.processEvents()
            self.updateGeometry()
            if hasattr(self, "centralWidget") and self.centralWidget():
                self.centralWidget().updateGeometry()
        except Exception:
            pass
        try:
            self.qt_app.aboutToQuit.connect(self._on_app_quit_cleanup)
        except Exception:
            pass
        self.qt_app.exec_()

    def _on_app_quit_cleanup(self):
        try:
            w = getattr(self, "_ver_worker", None)
            if w and w.isRunning():
                try:
                    w.requestInterruption()
                except Exception:
                    pass
                try:
                    w.quit()
                except Exception:
                    pass
                try:
                    w.wait(1500)
                except Exception:
                    pass
        except Exception:
            pass
