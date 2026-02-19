import os
import sys
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
                            self.coreVersion.emit(f"（{c}）" if c else "未找到")
                        else:
                            tag = r.stdout.strip()
                            r2 = run_hidden([git_cmd, "rev-parse", "--short", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=8)
                            c = r2.stdout.strip() if r2.returncode == 0 else ""
                            self.coreVersion.emit(f"{tag}（{c}）")
                        try:
                            self.app.logger.info("UI: 内核版本标签已生成")
                        except Exception:
                            pass
                except Exception:
                    self.coreVersion.emit("未找到")
        except Exception:
            pass

class CircleAvatar(QtWidgets.QLabel):
    """
    自定义圆形头像控件，解决 QSS border-radius 锯齿及大图裁剪问题
    """
    def __init__(self, pixmap=None, size=80, parent=None):
        super().__init__(parent)
        self._pix = pixmap
        self.setFixedSize(size, size)

    def set_pixmap(self, pix):
        self._pix = pix
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

        if not self._pix or self._pix.isNull():
            # 绘制占位底色
            painter.setBrush(QtGui.QColor("#EEF2F7"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(0, 0, self.width(), self.height())
            return

        path = QtGui.QPainterPath()
        d = min(self.width(), self.height())
        path.addEllipse(0, 0, d, d)
        painter.setClipPath(path)

        # 比例模式填满圆形区域 (类似 CSS object-fit: cover)
        scaled_pixmap = self._pix.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )

        x = (self.width() - scaled_pixmap.width()) // 2
        y = (self.height() - scaled_pixmap.height()) // 2
        painter.drawPixmap(x, y, scaled_pixmap)

class NoWheelComboBox(QtWidgets.QComboBox):
    """
    禁用鼠标滚轮切换内容的下拉框
    """
    def wheelEvent(self, event):
        event.ignore()

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
        self.compute_mode = Var("gpu")
        self.vram_mode = Var("--normalvram")
        self.use_fast_mode = BoolVar(False)
        self.enable_cors = BoolVar(True)
        self.listen_all = BoolVar(True)
        self.custom_port = Var("8188")
        self.disable_all_custom_nodes = BoolVar(False)
        self.disable_api_nodes = BoolVar(False)
        self.extra_launch_args = Var("")
        self.attention_mode = Var("")
        self.browser_open_mode = Var("default")
        self.custom_browser_path = Var("")
        launch_cfg = self.config.get("launch_options", {}) if isinstance(self.config, dict) else {}
        try:
            self.compute_mode.set(launch_cfg.get("default_compute_mode", self.compute_mode.get()))
            self.vram_mode.set(launch_cfg.get("vram_mode", self.vram_mode.get()))
            self.custom_port.set(launch_cfg.get("default_port", self.custom_port.get()))
            self.disable_all_custom_nodes.set(bool(launch_cfg.get("disable_all_custom_nodes", self.disable_all_custom_nodes.get())))
            self.use_fast_mode.set(bool(launch_cfg.get("enable_fast_mode", self.use_fast_mode.get())))
            self.disable_api_nodes.set(bool(launch_cfg.get("disable_api_nodes", self.disable_api_nodes.get())))
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

        try:
            # 获取屏幕可用几何信息（减去任务栏后的区域）
            primary_screen = QtWidgets.QApplication.primaryScreen()
            avail_geo = primary_screen.availableGeometry()
            s_w, s_h = avail_geo.width(), avail_geo.height()

            # 弃用单纯的百分比计算，改用"保底大尺寸"策略
            # 逻辑分析：
            # 4K 150% -> 逻辑分辨率约 2560x1440。设置 1350x950 占用约 53% 屏幕宽度，66% 屏幕高度。
            # 1080P 100% -> 逻辑分辨率 1920x1080。设置 1350x950 占用约 70% 屏幕宽度，88% 屏幕高度。
            # 调整为更紧凑的初始尺寸，适应更广泛的屏幕（特别是 1080P 高缩放笔记本）
            base_w = 1350
            base_h = 1000

            # 使用 adjustSize 让布局管理器告诉我们需要多大
            # 但先给一个较大的初始值，防止布局压缩
            final_w = base_w
            final_h = base_h

            # 依然保留防爆屏逻辑 (针对老旧投影仪等极端情况)
            if final_w > s_w: final_w = s_w - 20
            if final_h > s_h: final_h = s_h - 40

            self.resize(final_w, final_h)

            self.resize(final_w, final_h)

            # 智能居中
            self.move(
                avail_geo.x() + (s_w - final_w) // 2,
                avail_geo.y() + (s_h - final_h) // 2
            )
        except Exception:
            # 如果获取屏幕信息失败，使用一个较大的保守默认值
            self.resize(1280, 900)
            try:
                # 简单居中 fallback
                geo = self.frameGeometry()
                cp = QtWidgets.QDesktopWidget().availableGeometry().center()
                geo.moveCenter(cp)
                self.move(geo.topLeft())
            except Exception:
                pass

        # Theme setup
        theme_value = (self.config.get("ui_settings", {}).get("theme") or "dark").lower()
        if theme_value not in ("dark", "light"):
            theme_value = "dark"

        def _apply_theme(theme: str):
            dark = theme == "dark"
            palette = {
                "root_bg": "#111827" if dark else "#F8FAFC",
                "sidebar_grad_top": "#1F2937" if dark else "#F1F5F9",
                "sidebar_grad_bottom": "#111827" if dark else "#E2E8F0",
                "sidebar_border": "rgba(255, 255, 255, 0.05)" if dark else "#E5E7EB",
                "content_bg": "#1F2937" if dark else "#FFFFFF",
                "content_border": "rgba(255, 255, 255, 0.1)" if dark else "#E5E7EB",
                "label": "#E5E7EB" if dark else "#111827",
                "group_bg": "rgba(0, 0, 0, 0.2)" if dark else "#F1F5F9",
                "group_border": "#374151" if dark else "#E5E7EB",
                "input_bg": "rgba(0, 0, 0, 0.3)" if dark else "#FFFFFF",
                "input_border": "#4B5563" if dark else "#CBD5E1",
                "button_bg": "#374151" if dark else "#E2E8F0",
                "button_hover": "#4B5563" if dark else "#CBD5E1",
                "text": "#E5E7EB" if dark else "#111827",
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
                self._sidebar_widget.setStyleSheet(f"""
                    QWidget#SideBar {{
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {palette['sidebar_grad_top']}, stop:1 {palette['sidebar_grad_bottom']});
                        border: 1px solid {palette['sidebar_border']};
                        border-radius: 20px;
                    }}
                """)
            if hasattr(self, "_content_widget"):
                if dark:
                    self._content_widget.setStyleSheet(f"""
                        QWidget#MainContent {{
                            background-color: #1F2937;
                            border-radius: 20px;
                        }}
                        QLabel {{
                            color: #E5E7EB;
                            background: transparent;
                            font: 10pt "Microsoft YaHei UI";
                        }}
                        QGroupBox {{
                            background-color: rgba(0, 0, 0, 0.2);
                            border: 1px solid #374151;
                            border-radius: 10px;
                            margin-top: 10px;
                            padding: 10px;
                            font: bold 10pt "Microsoft YaHei UI";
                        }}
                        QGroupBox::title {{
                            subcontrol-origin: margin;
                            subcontrol-position: top left;
                            padding: 0 4px;
                            color: #E5E7EB;
                            background: transparent;
                            font: bold 10pt "Microsoft YaHei UI";
                        }}
                        QPushButton {{
                            background: #374151;
                            color: #E5E7EB;
                            border: 1px solid #4B5563;
                            border-radius: 8px;
                            padding: 5px 10px;
                            font: 10pt "Microsoft YaHei UI";
                        }}
                        QPushButton:hover {{
                            background: #4B5563;
                            color: #FFFFFF;
                        }}
                        QLineEdit {{
                            background-color: rgba(0, 0, 0, 0.3);
                            color: #FFFFFF;
                            border: 1px solid #4B5563;
                            border-radius: 6px;
                            padding: 5px 10px;
                            font: 10pt "Microsoft YaHei UI";
                            selection-background-color: {c.get('ACCENT', '#6366F1')};
                        }}
                        QLineEdit:hover, QComboBox:hover {{
                            background-color: rgba(255, 255, 255, 0.05);
                            border: 1px solid #6B7280;
                        }}
                        QLineEdit:focus, QComboBox:focus {{
                            background-color: rgba(0, 0, 0, 0.5);
                            border: 2px solid {c.get('ACCENT', '#6366F1')};
                            padding: 4px 9px;
                        }}
                        QComboBox {{
                            background-color: rgba(0, 0, 0, 0.3);
                            color: #E5E7EB;
                            border: 1px solid #4B5563;
                            border-radius: 6px;
                            padding: 5px 10px;
                            font: 10pt "Microsoft YaHei UI";
                        }}
                        QComboBox QAbstractItemView {{
                            background-color: #1F2937;
                            selection-background-color: {c.get('ACCENT', '#6366F1')};
                            selection-color: #FFFFFF;
                            font: 10pt "Microsoft YaHei UI";
                            border: 1px solid #374151;
                            outline: none;
                        }}
                        QRadioButton, QCheckBox {{
                            color: #E5E7EB;
                            font: 10pt "Microsoft YaHei UI";
                            spacing: 6px;
                        }}
                        QCheckBox::indicator, QRadioButton::indicator {{
                            width: 18px;
                            height: 18px;
                            border: 2px solid #6B7280;
                            border-radius: 4px;
                            background: transparent;
                        }}
                        QRadioButton::indicator {{ border-radius: 9px; }}
                        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
                            background-color: {c.get('ACCENT', '#6366F1')};
                            border-color: {c.get('ACCENT', '#6366F1')};
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
                            width: 18px;
                            height: 18px;
                            border: 2px solid #94A3B8;
                            border-radius: 4px;
                            background: transparent;
                        }}
                        QRadioButton::indicator {{ border-radius: 9px; }}
                        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
                            background-color: #38BDF8;
                            border-color: #0EA5E9;
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
                        text_muted="#475569",
                        hover_bg="rgba(56, 189, 248, 0.12)",
                        hover_text="#0F172A",
                        checked_bg="#38BDF8",
                        checked_text="#0F172A",
                        checked_border="#0EA5E9",
                    )
                for b in self._nav_buttons:
                    b.setStyleSheet(qss)

        self._apply_theme = _apply_theme
        self._theme_value = theme_value

        common_btn_style = """
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7F56D9, stop:1 #9E77ED);
            color: #FFFFFF;
            border: none;
            border-radius: 12px;
            font: bold 10pt "Microsoft YaHei UI";
            padding: 8px 16px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6941C6, stop:1 #7F56D9);
        }
        QPushButton:pressed {
            background: #53389E;
            padding-top: 2px;
            padding-left: 2px;
        }
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

        # Sidebar
        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("SideBar")
        sidebar.setFixedWidth(240)
        # Enable styled background for sidebar to support radius and bg color
        sidebar.setAttribute(Qt.WA_StyledBackground, True)
        self._sidebar_widget = sidebar

        # style is applied via theme

        side_layout = QtWidgets.QVBoxLayout(sidebar)
        side_layout.setContentsMargins(15, 15, 15, 15)
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
        header_layout.setContentsMargins(0, 20, 0, 10)
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

                # Using QSS for the floating card effect - Updated per instructions
                self.setStyleSheet(f"""
                QPushButton {{
                    color: #999999;
                    background-color: transparent;
                    border: 1px solid transparent;
                    border-radius: 12px;
                    padding: 0px 15px;
                    text-align: left;
                    font: 10.5pt "Microsoft YaHei UI";
                    margin: 0px 0px;
                }}
                QPushButton:hover {{
                    background-color: rgba(255, 255, 255, 0.1);
                    color: #FFFFFF;
                }}
                QPushButton:checked {{
                    background-color: #FFFFFF;
                    color: #333333;
                    border: 1px solid #E5E7EB;
                    font-weight: bold;
                }}
                """)

                # Add shadow effect for depth
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
        self._nav_buttons = list(btns.values())
        for b in btns.values():
            nav.addWidget(b)
        nav.addStretch(1)

        # Theme selector (sidebar)
        theme_box = QtWidgets.QHBoxLayout()
        theme_box.setContentsMargins(0, 0, 0, 0)
        lbl_theme = QtWidgets.QLabel("主题")
        lbl_theme.setStyleSheet("color: #9CA3AF; font: 9pt 'Microsoft YaHei UI';")
        theme_combo = NoWheelComboBox()
        theme_combo.addItems(["深色", "浅色"])
        theme_combo.setFixedWidth(90)
        theme_combo.setStyleSheet("padding: 2px 6px;")

        if self._theme_value == "light":
            theme_combo.setCurrentIndex(1)
        else:
            theme_combo.setCurrentIndex(0)

        def _on_theme_change(index: int):
            theme = "light" if index == 1 else "dark"
            self._theme_value = theme
            try:
                self.services.config.set("ui_settings.theme", theme)
                self.services.config.save(None)
                self.config = self.services.config.get_config()
            except Exception:
                pass
            self._apply_theme(theme)

        theme_combo.currentIndexChanged.connect(_on_theme_change)

        theme_box.addWidget(lbl_theme)
        theme_box.addWidget(theme_combo)
        theme_box.addStretch(1)
        side_layout.addLayout(theme_box)

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
        main.addWidget(sidebar)
        # Divider removed for floating style
        main.addWidget(content, 1)

        # Apply current theme
        self._apply_theme(self._theme_value)
        page_launch = QtWidgets.QWidget()
        page_version = QtWidgets.QWidget()
        page_models = QtWidgets.QWidget()
        page_about_me = QtWidgets.QWidget()
        page_about_comfyui = QtWidgets.QWidget()
        page_about_launcher = QtWidgets.QWidget()

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
        # Build launch
        v_layout = QtWidgets.QVBoxLayout(page_launch)
        try:
            v_layout.setContentsMargins(12, 12, 12, 12)
            v_layout.setSpacing(8)
        except Exception:
            pass
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(15)
        v_layout.addLayout(top_row)

        btn_toggle = QtWidgets.QPushButton("🚀 一键启动")
        btn_toggle.setCursor(Qt.PointingHandCursor)
        # Fixed width as requested, letting height expand or be fixed
        btn_toggle.setFixedWidth(120)
        # Using Fixed horizontal and Expanding vertical policy to match form group height
        btn_toggle.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        btn_toggle.setStyleSheet("""
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7F56D9, stop:1 #9E77ED);
            color: #FFFFFF;
            border: none;
            border-radius: 15px;
            font: bold 14pt "Microsoft YaHei UI";
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6941C6, stop:1 #7F56D9);
        }
        QPushButton:pressed {
            background: #53389E;
            padding-top: 2px;
            padding-left: 2px;
        }
        """)
        btn_toggle.clicked.connect(lambda: self.services.process.toggle())
        class BigBtnProxy:
            def __init__(self, qbtn: QtWidgets.QPushButton):
                self._btn = qbtn
                self._state = "idle"
            def set_state(self, s: str):
                self._state = s
            def set_text(self, t: str):
                try:
                    self._btn.setText(t)
                except Exception:
                    pass
        self.big_btn = BigBtnProxy(btn_toggle)

        form_group = QtWidgets.QGroupBox("启动控制")
        form_layout = QtWidgets.QGridLayout(form_group)
        # Revert to dual-column layout
        form_layout.setColumnStretch(1, 1) # Control column
        form_layout.setColumnStretch(3, 1) # Second control column
        form_layout.setColumnMinimumWidth(0, 90)  # Label column minimum width
        form_layout.setHorizontalSpacing(20)
        form_layout.setVerticalSpacing(15)
        # Increased margins
        form_layout.setContentsMargins(18, 18, 18, 18)

        top_row.addWidget(form_group, 1)
        top_row.addWidget(btn_toggle, 0)

        # Apply Shadow to GroupBox
        try:
            shadow1 = QtWidgets.QGraphicsDropShadowEffect(self)
            shadow1.setBlurRadius(18)
            shadow1.setOffset(0, 4)
            shadow1.setColor(QtGui.QColor(0, 0, 0, 30))
            form_group.setGraphicsEffect(shadow1)
        except Exception:
            pass

        def _save():
            try:
                self.save_config()
            except Exception:
                pass

        # 1. 运行模式 (Running Mode) - Radio Buttons
        mode_label = QtWidgets.QLabel("运行模式：")
        mode_container = QtWidgets.QWidget()
        mode_layout = QtWidgets.QHBoxLayout(mode_container)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(15)

        modes = [("GPU", "gpu"), ("CPU", "cpu"), ("DirectML", "directml")]
        for label, val in modes:
            rb = QtWidgets.QRadioButton(label)
            rb.setChecked(self.compute_mode.get() == val)
            rb.toggled.connect(lambda c, v=val: (self.compute_mode.set(v) if c else None, _save()))
            mode_layout.addWidget(rb)
        mode_layout.addStretch(1)

        # 2. 显存策略 (VRAM)
        opt_label = QtWidgets.QLabel("显存策略：")
        opt_widget = NoWheelComboBox()
        opt_widget.addItems(["显存充足 (High)", "默认 (Normal)", "低显存 (Low)", "极低显存 (No)"])
        vram_map_vals = ["--highvram", "--normalvram", "--lowvram", "--novram"]

        cur_vram = self.vram_mode.get()
        if cur_vram in vram_map_vals:
            opt_widget.setCurrentIndex(vram_map_vals.index(cur_vram))
        else:
            opt_widget.setCurrentIndex(1) # Normal

        opt_widget.currentIndexChanged.connect(lambda i: (self.vram_mode.set(vram_map_vals[i]), _save()))

        # 3. 注意力优化 (Attention)
        attn_label = QtWidgets.QLabel("注意力优化：")
        attn_combo = NoWheelComboBox()
        attn_opts = [
            ("默认 (Default)", ""),
            ("PyTorch (SDPA)", "--use-pytorch-cross-attention"),
            ("Flash Attention", "--use-flash-attention"),
            ("Sage Attention", "--use-sage-attention"),
            ("Split Attention", "--use-split-cross-attention"),
            ("Quad Attention", "--use-quad-cross-attention"),
        ]
        for name, val in attn_opts:
            attn_combo.addItem(name, val)

        cur_attn = self.attention_mode.get() or ""
        # Find index
        found_attn = False
        for i, (name, val) in enumerate(attn_opts):
            if val == cur_attn:
                attn_combo.setCurrentIndex(i)
                found_attn = True
                break
        if not found_attn: attn_combo.setCurrentIndex(0)

        attn_combo.currentIndexChanged.connect(lambda i: (self.attention_mode.set(attn_opts[i][1]), _save()))

        # 4. 端口 (Port)
        port_label = QtWidgets.QLabel("端口号：")
        port_edit = QtWidgets.QLineEdit(self.custom_port.get())
        port_edit.setFixedWidth(60)
        port_edit.textChanged.connect(lambda v: (self.custom_port.set(v), _save()))

        # 5. 启动后
        open_label = QtWidgets.QLabel("自动打开浏览器：")
        open_combo = NoWheelComboBox()
        open_opts = [
            ("不自动打开", "disable"),
            ("使用默认浏览器", "default"),
            ("使用指定浏览器", "webbrowser"),
        ]
        for name, val in open_opts:
            open_combo.addItem(name, val)

        cur_open = self.browser_open_mode.get()
        for i, (name, val) in enumerate(open_opts):
             if val == cur_open:
                 open_combo.setCurrentIndex(i)
                 break
        open_combo.currentIndexChanged.connect(lambda i: (self.browser_open_mode.set(open_opts[i][1]), _save()))

        # 6. Checkboxes
        listen_chk = QtWidgets.QCheckBox("允许局域网访问")
        listen_chk.setChecked(self.listen_all.get())
        listen_chk.toggled.connect(lambda v: (self.listen_all.set(v), _save()))

        cb_fast = QtWidgets.QCheckBox("快速FP16累加")
        cb_fast.setChecked(self.use_fast_mode.get())
        cb_fast.toggled.connect(lambda v: (self.use_fast_mode.set(v), _save()))

        cb_api = QtWidgets.QCheckBox("禁用API节点")
        cb_api.setChecked(self.disable_api_nodes.get())
        cb_api.toggled.connect(lambda v: (self.disable_api_nodes.set(v), _save()))

        cb_nodes = QtWidgets.QCheckBox("禁用所有插件(DEBUG)")
        cb_nodes.setChecked(self.disable_all_custom_nodes.get())
        cb_nodes.toggled.connect(lambda v: (self.disable_all_custom_nodes.set(v), _save()))

        # 7. Extra Args
        extra_label = QtWidgets.QLabel("额外选项：")
        extra_edit = QtWidgets.QLineEdit(self.extra_launch_args.get())
        extra_edit.setPlaceholderText("例如: --disable-smart-memory --fp16-vae")
        extra_edit.textChanged.connect(lambda v: (self.extra_launch_args.set(v), _save()))

        # --- Layout Grid Placement ---
        # Splitting into 2 columns roughly

        # Row 0: Mode | Port
        form_layout.addWidget(mode_label, 0, 0)
        form_layout.addWidget(mode_container, 0, 1) # Mode spans a bit?

        hbox_port = QtWidgets.QHBoxLayout()
        hbox_port.setContentsMargins(0, 0, 0, 0)
        hbox_port.setSpacing(15)
        hbox_port.addWidget(port_label)
        hbox_port.addWidget(port_edit)
        hbox_port.addWidget(listen_chk)
        hbox_port.addStretch(1)
        form_layout.addLayout(hbox_port, 0, 2, 1, 2) # Port in second col area

        # Row 1: VRAM Strategy (Left) | Attention (Right)
        form_layout.addWidget(opt_label, 1, 0)
        vram_cont = QtWidgets.QHBoxLayout()
        vram_cont.setContentsMargins(0,0,0,0)
        vram_cont.addWidget(opt_widget)
        # vram_cont.addStretch(1) # Let combo expand? Start with simple widget
        form_layout.addWidget(opt_widget, 1, 1)

        form_layout.addWidget(attn_label, 1, 2)
        form_layout.addWidget(attn_combo, 1, 3)

        # Row 2: After Launch (Left) | Checkboxes (Right mixed)
        form_layout.addWidget(open_label, 2, 0)

        # Custom browser button (conditional, same row as after launch)
        cpath_btn = QtWidgets.QPushButton("选择浏览器...")
        cpath_btn.setCursor(QtCore.Qt.PointingHandCursor)
        cpath_btn.setMinimumWidth(120)

        def _select_browser():
            from PyQt5.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(
                None, "选择浏览器程序", "",
                "可执行文件 (*.exe);;所有文件 (*.*)"
            )
            if file_path:
                self.custom_browser_path.set(file_path)
                cpath_btn.setText("已选择")
                _save()

        cpath_btn.clicked.connect(_select_browser)

        # Container for open_combo + cpath_btn
        row2_container = QtWidgets.QWidget()
        row2_layout = QtWidgets.QHBoxLayout(row2_container)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(15)
        row2_layout.addWidget(open_combo)
        row2_layout.addWidget(cpath_btn)
        row2_layout.addStretch(1)
        form_layout.addWidget(row2_container, 2, 1, 1, 3)

        def _update_cpath_vis():
            is_custom = (open_combo.currentData() == "webbrowser")
            cpath_btn.setVisible(is_custom)
        open_combo.currentIndexChanged.connect(lambda: _update_cpath_vis())
        _update_cpath_vis()

        # Row 3: More Checkboxes & Extra Args
        hbox_opts = QtWidgets.QHBoxLayout()
        hbox_opts.setContentsMargins(0, 0, 0, 0)
        hbox_opts.setSpacing(25)
        hbox_opts.addWidget(cb_fast)
        hbox_opts.addWidget(cb_api)
        hbox_opts.addWidget(cb_nodes)
        hbox_opts.addStretch(1)

        form_layout.addLayout(hbox_opts, 3, 0, 1, 4)

        # Row 4: Extra args
        form_layout.addWidget(extra_label, 4, 0)
        form_layout.addWidget(extra_edit, 4, 1, 1, 3)


        # Environment Config & Other Pages
        # --- 环境配置区块 (合并了网络与路径配置) ---
        env_group = QtWidgets.QGroupBox("环境配置")
        env_main_v = QtWidgets.QVBoxLayout(env_group)
        env_main_v.setContentsMargins(0, 0, 0, 0)
        env_main_v.setSpacing(0)
        v_layout.addWidget(env_group)

        # 头部辅助栏：移除独立的 Header，将按钮移至 Grid 第一行
        # restore_btn_top 定义
        restore_btn_top = QtWidgets.QPushButton("↺ 恢复默认")
        restore_btn_top.setObjectName("RestoreDefault")
        restore_btn_top.setCursor(Qt.PointingHandCursor)
        # Ghost Button Style
        restore_btn_top.setStyleSheet("""
            QPushButton#RestoreDefault {
                background: transparent;
                border: 1px solid #4B5563;
                color: #9CA3AF;
                font: 9pt "Microsoft YaHei UI";
                padding: 4px 10px;
                border-radius: 6px;
            }
            QPushButton#RestoreDefault:hover {
                background: rgba(255, 255, 255, 0.05);
                color: #E5E7EB;
                border: 1px solid #6B7280;
            }
        """)
        restore_btn_top.clicked.connect(self.reset_settings)

        env_layout = QtWidgets.QGridLayout()
        # Columns: [Label (Fixed)] [Control Area (Expanding)]
        env_layout.setColumnMinimumWidth(0, 100)
        env_layout.setColumnStretch(1, 1)
        env_layout.setHorizontalSpacing(15)
        env_layout.setVerticalSpacing(12) # Increased spacing for breathing room
        env_layout.setContentsMargins(15, 15, 15, 15)
        env_main_v.addLayout(env_layout)

        try:
            shadow_env = QtWidgets.QGraphicsDropShadowEffect(self)
            shadow_env.setBlurRadius(18)
            shadow_env.setOffset(0, 4)
            shadow_env.setColor(QtGui.QColor(0, 0, 0, 30))
            env_group.setGraphicsEffect(shadow_env)
        except Exception: pass

        # 统一控件高度样式与标签对齐
        common_input_qss = """
            QComboBox, QLineEdit, QPushButton {
                min-height: 28px;
                border: 1px solid #4B5563;
                border-radius: 6px;
                padding: 2px 8px;
                color: #E5E7EB;  /* Light text color */
                background-color: #374151; /* Dark background */
            }
            QComboBox::drop-down {
                border: none;
                background-color: #374151;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #9CA3AF;
                width: 0;
                height: 0;
                margin-right: 8px; /* Move away from right edge */
            }
            /* Popup list styling */
            QComboBox QAbstractItemView {
                background-color: #374151;
                color: #E5E7EB; 
                border: 1px solid #4B5563;
                selection-background-color: #4B5563;
                selection-color: #FFFFFF;
                outline: none;
            }
            QLineEdit:read-only {
                background-color: #1F2937;
                color: #9CA3AF;
            }
            QLabel {
                font-weight: bold;
                color: #9CA3AF;
            }
        """
        env_group.setStyleSheet(common_input_qss)
        form_group.setStyleSheet(common_input_qss) # Also apply to Launch Control for VRAM dropdown

        def _mk_cfg_label(txt):
            lbl = QtWidgets.QLabel(txt)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setFixedWidth(100) # Fixed width as requested
            return lbl

        # Standard secondary button style (Ghost-ish but valid)
        secondary_btn_style = """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.05);
                color: #E5E7EB;
                border: 1px solid #4B5563;
                border-radius: 6px;
                padding: 5px 15px;
                font: 10pt "Microsoft YaHei UI";
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """

        # Helper to create a composite control row
        def _add_row(row_idx, label_text, widget_list, suffix_widget=None, add_stretch=True, custom_stretch_map=None):
            env_layout.addWidget(_mk_cfg_label(label_text), row_idx, 0)

            container = QtWidgets.QWidget()
            hbox = QtWidgets.QHBoxLayout(container)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(10)

            for i, w in enumerate(widget_list):
                stretch = 0
                if custom_stretch_map and i in custom_stretch_map:
                    stretch = custom_stretch_map[i]
                hbox.addWidget(w, stretch)

            # Add spacer only if requested (default True for short combos)
            if add_stretch:
                hbox.addStretch(1)

            if suffix_widget:
                hbox.addWidget(suffix_widget)

            env_layout.addWidget(container, row_idx, 1)

        # Create a dummy spacer to align rows without button to the row with button
        # Restore button width approx: text + padding. "↺ 恢复默认" is wider than 85px.
        def _get_align_spacer():
            sp = QtWidgets.QWidget()
            sp.setFixedWidth(73) # Increased to match actual button width better
            sp.setStyleSheet("background: transparent;")
            return sp

        # 1. HF 镜像
        env_hf_combo = NoWheelComboBox()
        env_hf_combo.addItems(["不使用", "hf-mirror", "自定义"])
        env_hf_combo.setMinimumWidth(120)
        env_hf_combo.setCurrentText(self.selected_hf_mirror.get() if self.selected_hf_mirror.get() in ["不使用", "hf-mirror", "自定义"] else "hf-mirror")

        env_hf_entry = QtWidgets.QLineEdit(self.hf_mirror_url.get())
        env_hf_entry.setPlaceholderText("请输入镜像地址...")
        env_hf_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        # Add row with Restore Button at the end. Use balanced stretch factor.
        _add_row(0, "HF 镜像源：", [env_hf_combo, env_hf_entry], restore_btn_top, custom_stretch_map={1: 10})

        def _env_hf_change(text):
            is_custom = (text == "自定义")
            is_none = (text == "不使用")

            env_hf_entry.setReadOnly(not is_custom)
            env_hf_entry.setVisible(not is_none)

            if text == "hf-mirror":
                env_hf_entry.setText("https://hf-mirror.com")
            elif is_custom:
                # Clear text box when switching to custom, unless it was already custom
                # Check directly against variable to avoid clearing user's typing during init
                if self.selected_hf_mirror.get() != "自定义":
                     env_hf_entry.setText("")

            self.selected_hf_mirror.set(text)
            if is_custom:
                self.hf_mirror_url.set(env_hf_entry.text())
            elif text == "hf-mirror":
                self.hf_mirror_url.set("https://hf-mirror.com")
            else:
                self.hf_mirror_url.set("")
            self.save_config()

        env_hf_combo.currentTextChanged.connect(_env_hf_change)
        # Init state
        _env_hf_change(env_hf_combo.currentText())
        # Connect text change only for custom editing
        env_hf_entry.textChanged.connect(lambda t: (self.hf_mirror_url.set(t) if env_hf_combo.currentText() == "自定义" else None, self.save_config()))


        # 2. GitHub 代理
        env_gh_combo = NoWheelComboBox()
        env_gh_combo.addItems(["不使用", "gh-proxy", "自定义"])
        env_gh_combo.setMinimumWidth(120)
        env_gh_combo.setCurrentText(self.version_manager.proxy_mode_ui_var.get())

        env_gh_entry = QtWidgets.QLineEdit(self.version_manager.proxy_url_var.get())
        env_gh_entry.setPlaceholderText("请输入代理地址...")
        env_gh_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        # Add Align Spacer to mimic Restore Button width, ensuring consistent text box termination
        _add_row(1, "GitHub 代理：", [env_gh_combo, env_gh_entry], suffix_widget=_get_align_spacer(), custom_stretch_map={1: 10})

        def _env_gh_change(text):
            is_custom = (text == "自定义")
            is_none = (text == "不使用")

            env_gh_entry.setReadOnly(not is_custom)
            env_gh_entry.setVisible(not is_none)

            m = "none" if is_none else ("gh-proxy" if text == "gh-proxy" else "custom")

            if text == "gh-proxy":
                url = "https://gh-proxy.com/"
                env_gh_entry.setText(url)
                self.version_manager.proxy_url_var.set(url)
            elif is_custom:
                if self.version_manager.proxy_mode_ui_var.get() != "自定义":
                    env_gh_entry.setText("")

            self.version_manager.proxy_mode_var.set(m)
            self.version_manager.proxy_mode_ui_var.set(text)

            if is_custom:
                self.version_manager.proxy_url_var.set(env_gh_entry.text())

            self.version_manager.save_proxy_settings()

        env_gh_combo.currentTextChanged.connect(_env_gh_change)
        _env_gh_change(env_gh_combo.currentText())
        env_gh_entry.textChanged.connect(lambda t: (self.version_manager.proxy_url_var.set(t) if env_gh_combo.currentText() == "自定义" else None, self.version_manager.save_proxy_settings()))


        # 3. PyPI 代理
        env_pypi_combo = NoWheelComboBox()
        env_pypi_combo.addItems(["不使用", "阿里云", "自定义"])
        env_pypi_combo.setMinimumWidth(120)
        env_pypi_combo.setCurrentText(self.pypi_proxy_mode_ui.get())

        env_pypi_entry = QtWidgets.QLineEdit(self.pypi_proxy_url.get())
        env_pypi_entry.setPlaceholderText("请输入 PyPI 源地址...")
        env_pypi_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        # Add Align Spacer here too
        _add_row(2, "PyPI 代理：", [env_pypi_combo, env_pypi_entry], suffix_widget=_get_align_spacer(), custom_stretch_map={1: 10})

        def _env_pypi_change(text):
            is_custom = (text == "自定义")
            is_none = (text == "不使用")

            env_pypi_entry.setReadOnly(not is_custom)
            env_pypi_entry.setVisible(not is_none)

            mode = "none" if is_none else ("aliyun" if text == "阿里云" else "custom")

            if text == "阿里云":
                url = "https://mirrors.aliyun.com/pypi/simple/"
                env_pypi_entry.setText(url)
                self.pypi_proxy_url.set(url)
            elif is_custom:
                if self.pypi_proxy_mode_ui.get() != "自定义":
                    env_pypi_entry.setText("")
                self.pypi_proxy_url.set(env_pypi_entry.text())

            self.pypi_proxy_mode.set(mode)
            self.pypi_proxy_mode_ui.set(text)
            self.save_config()
            self.apply_pip_proxy_settings()

        env_pypi_combo.currentTextChanged.connect(_env_pypi_change)
        _env_pypi_change(env_pypi_combo.currentText())
        env_pypi_entry.textChanged.connect(lambda t: (self.pypi_proxy_url.set(t) if env_pypi_combo.currentText() == "自定义" else None, self.save_config()))

        # 逻辑分割线
        div_line = QtWidgets.QFrame()
        div_line.setFrameShape(QtWidgets.QFrame.HLine)
        div_line.setFrameShadow(QtWidgets.QFrame.Plain)
        div_line.setStyleSheet("background-color: #374151; border: none; min-height: 1px; max-height: 1px; margin: 4px 0;")
        env_layout.addWidget(div_line, 3, 0, 1, 2)

        # 4. ComfyUI 根目录
        root_show = QtWidgets.QLineEdit(str((Path(self.config.get('paths', {}).get('comfyui_root') or '.'))))
        root_show.setReadOnly(True)
        root_show.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        root_btn = QtWidgets.QPushButton("选取")
        root_btn.setCursor(Qt.PointingHandCursor)
        root_btn.setStyleSheet(secondary_btn_style)

        # Paths should expand, so no spacer stretch (Revert to previous behavior)
        _add_row(4, "根目录：", [root_show, root_btn], add_stretch=False)

        # 5. Python 経路
        py_show = QtWidgets.QLineEdit(self.python_exec)
        py_show.setReadOnly(True)
        py_show.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        py_btn = QtWidgets.QPushButton("选取")
        py_btn.setCursor(Qt.PointingHandCursor)
        py_btn.setStyleSheet(secondary_btn_style)

        _add_row(5, "Python 路径：", [py_show, py_btn], add_stretch=False)

        def _choose_root():
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择 ComfyUI 根目录", str(Path.cwd()))
            if d:
                root_show.setText(d)
                self.config.setdefault('paths', {})['comfyui_root'] = d
                try:
                    self.services.config.save(self.config)
                except Exception: pass
                try:
                    base = Path(d).resolve()
                    # 检查根目录下是否有 python_embeded 目录
                    python_embeded_dir = base / "python_embeded"
                    python_exe_path = python_embeded_dir / "python.exe"
                    if python_embeded_dir.exists() and python_exe_path.exists():
                        # 如果存在 python_embeded/python.exe，直接使用它
                        self.python_exec = str(python_exe_path.resolve())
                    else:
                        # 否则使用原来的解析逻辑
                        comfy_path = (base / "ComfyUI").resolve()
                        py = PATHS.resolve_python_exec(comfy_path, self.config.get("paths", {}).get("python_path", "python_embeded/python.exe"))
                        self.python_exec = str(py)
                    self.config['paths']['python_path'] = self.python_exec
                    self.services.config.save(self.config)
                    py_show.setText(self.python_exec)
                except Exception: pass
                self.get_version_info("all")

        root_btn.clicked.connect(_choose_root)

        def _choose_python():
            p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 Python 可执行文件", str(Path.cwd()), "可执行文件 (*.exe);;所有文件 (*.*)")
            if p:
                py_show.setText(p)
                self.python_exec = p
                self.config.setdefault('paths', {})['python_path'] = p
                try:
                    self.services.config.save(self.config)
                except Exception: pass
                self.get_version_info("all")

        py_btn.clicked.connect(_choose_python)

        # --- 版本与更新区块 ---
        ver_group = QtWidgets.QGroupBox("版本与更新")
        ver_layout = QtWidgets.QVBoxLayout(ver_group)
        v_layout.addWidget(ver_group)

        # 1. 顶部信息展示区：数据卡片网格
        cur_grid = QtWidgets.QGridLayout()
        cur_grid.setSpacing(15)
        cur_grid.setContentsMargins(10, 5, 10, 10)
        ver_layout.addLayout(cur_grid)

        self._version_label_refs = []

        def _mk_item(title, value_source, icon_str):
            # 卡片容器
            card = QtWidgets.QFrame()
            card.setAttribute(Qt.WA_StyledBackground, True)
            # Remove background and border as requested to let items float on main background
            card.setStyleSheet("""
                QFrame {
                    background: transparent;
                    border: none;
                }
            """)

            # Horizontal Layout for single-line display
            hb = QtWidgets.QHBoxLayout(card)
            hb.setContentsMargins(5, 2, 5, 2)
            hb.setSpacing(8)
            hb.setAlignment(Qt.AlignCenter)

            # 1. Icon
            icon_lbl = QtWidgets.QLabel(icon_str)
            icon_lbl.setStyleSheet("font-size: 14pt; background: transparent;")
            hb.addWidget(icon_lbl)

            # 2. Title
            t = QtWidgets.QLabel(f"{title} :")
            t.setStyleSheet("color: #9CA3AF; font: bold 9pt \"Microsoft YaHei UI\"; background: transparent;")
            hb.addWidget(t)

            # 3. Value
            if hasattr(value_source, "get"):
                v_text = value_source.get()
            else:
                v_text = str(value_source)

            v = QtWidgets.QLabel(v_text)
            v.setStyleSheet("font: bold 10pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: #E5E7EB; background: transparent;")
            hb.addWidget(v)

            if hasattr(value_source, "bind"):
                def _update_v(val, vv=v):
                    vv.setText(str(val))
                value_source.bind(_update_v)
                self._version_label_refs.append(v)

            return card

        items = [
            ("内核", self.comfyui_version, "🧬"),
            ("前端", self.frontend_version, "🎨"),
            ("模板库", self.template_version, "📋"),
            ("Python", self.python_version, "🐍"),
            ("Torch", self.torch_version, "🔥"),
            ("Git", self.git_status, "🐙"),
        ]

        for i, (title, src, ico) in enumerate(items):
            w = _mk_item(title, src, ico)
            r, cidx = divmod(i, 3)
            cur_grid.addWidget(w, r, cidx)

        for col in range(3):
            cur_grid.setColumnStretch(col, 1)

        # 2. 中间交互控制区
        opt_layout = QtWidgets.QVBoxLayout()
        opt_layout.setContentsMargins(10, 5, 10, 5)
        opt_layout.setSpacing(12)
        ver_layout.addLayout(opt_layout)

        # 策略行：水平并排 Checkbox
        policy_row = QtWidgets.QHBoxLayout()
        policy_row.setSpacing(20)
        stable_chk = QtWidgets.QCheckBox(" 仅更新到稳定版")
        clean_chk = QtWidgets.QCheckBox(" 自动更新依赖库")
        policy_row.addWidget(stable_chk)
        policy_row.addWidget(clean_chk)
        policy_row.addStretch(1)
        opt_layout.addLayout(policy_row)

        try:
            stable_chk.setChecked(bool(self.stable_only_var.get()))
            clean_chk.setChecked(bool(self.auto_update_deps_var.get()))
        except Exception: pass

        # 胶囊按钮样式
        capsule_style = """
            QPushButton {
                background-color: #F3F4F6;
                color: #4B5563;
                border: 1px solid #E5E7EB;
                border-radius: 15px;
                padding: 5px 15px;
                font: bold 9.5pt "Microsoft YaHei UI";
            }
            QPushButton:hover {
                background-color: #E5E7EB;
            }
            QPushButton:checked {
                background-color: #EEF2FF;
                color: #6366F1;
                border: 2px solid #6366F1;
            }
        """

        # 更新项行：小胶囊样式
        items_row = QtWidgets.QHBoxLayout()
        items_row.setSpacing(10)
        items_label = QtWidgets.QLabel("更新项：")
        items_label.setStyleSheet("color: #4B5563; font-weight: bold;")
        items_row.addWidget(items_label)

        def _mk_capsule(txt, var):
            btn = QtWidgets.QPushButton(txt)
            btn.setCheckable(True)
            btn.setChecked(var.get())
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(capsule_style)
            btn.toggled.connect(lambda v: var.set(v))
            return btn

        btn_core = _mk_capsule("内核", self.update_core_var)
        btn_front = _mk_capsule("前端", self.update_frontend_var)
        btn_tpl = _mk_capsule("模板库", self.update_template_var)

        items_row.addWidget(btn_core)
        items_row.addWidget(btn_front)
        items_row.addWidget(btn_tpl)
        items_row.addStretch(1)

        # 底部动作按钮
        btn_refresh = QtWidgets.QPushButton(" 🔄 刷新当前版本")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        # 次级按钮风格 (浅紫色背景)
        btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #F4F0FF;
                color: #7F56D9;
                border: 1px solid #D6BBFB;
                border-radius: 10px;
                padding: 6px 15px;
                font: bold 10pt "Microsoft YaHei UI";
            }
            QPushButton:hover { background-color: #EBE4FF; }
        """)

        btn_update = QtWidgets.QPushButton(" 🚀 开始更新")
        btn_update.setCursor(Qt.PointingHandCursor)
        btn_update.setMinimumWidth(120)
        btn_update.setStyleSheet(self._common_btn_style) # 维持紫色实心风格

        items_row.addWidget(btn_refresh)
        items_row.addWidget(btn_update)
        opt_layout.addLayout(items_row)

        # 信号逻辑绑定
        def _pref_save():
            try:
                self.stable_only_var.set(bool(stable_chk.isChecked()))
                self.auto_update_deps_var.set(bool(clean_chk.isChecked()))
                self.services.config.set("version_preferences.stable_only", self.stable_only_var.get())
                self.services.config.set("version_preferences.auto_update_deps", self.auto_update_deps_var.get())
                self.services.config.save(None)
            except Exception: pass

        stable_chk.toggled.connect(lambda _: _pref_save())
        clean_chk.toggled.connect(lambda _: _pref_save())
        btn_refresh.clicked.connect(lambda: self.get_version_info("all"))
        btn_update.clicked.connect(lambda: self._upgrade_latest(stable_chk.isChecked()))

        # --- 快捷目录区块 ---
        quick_group = QtWidgets.QGroupBox("快捷目录")
        quick_layout = QtWidgets.QHBoxLayout(quick_group)
        v_layout.addWidget(quick_group)
        btn_root = QtWidgets.QPushButton("📂 根目录")
        btn_logs = QtWidgets.QPushButton("📝 日志文件")
        btn_launcher_log = QtWidgets.QPushButton("🧰 启动器日志")
        btn_input = QtWidgets.QPushButton("📥 输入目录")
        btn_output = QtWidgets.QPushButton("📤 输出目录")
        btn_plugins = QtWidgets.QPushButton("🔌 插件目录")
        btn_workflows = QtWidgets.QPushButton("🗂️ 工作流目录")
        btn_root.clicked.connect(self.open_root_dir)
        btn_logs.clicked.connect(self.open_logs_dir)
        btn_launcher_log.clicked.connect(self.open_launcher_log)
        btn_input.clicked.connect(self.open_input_dir)
        btn_output.clicked.connect(self.open_output_dir)
        btn_plugins.clicked.connect(self.open_plugins_dir)
        btn_workflows.clicked.connect(self.open_workflows_dir)
        for b in [btn_root, btn_logs, btn_launcher_log, btn_input, btn_output, btn_plugins, btn_workflows]:
            b.setMinimumHeight(34)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(common_btn_style)
            quick_layout.addWidget(b)
        # =========================================================
        # Build Version Management Page (内核版本管理)
        # =========================================================
        pv_layout = QtWidgets.QVBoxLayout(page_version)
        pv_layout.setContentsMargins(25, 25, 25, 25)
        pv_layout.setSpacing(15)

        # 1. Page Title
        pv_title = QtWidgets.QLabel("ComfyUI 内核版本管理")
        pv_title.setStyleSheet("font: bold 16pt 'Microsoft YaHei UI'; color: #FFFFFF; margin-bottom: 5px;")
        pv_layout.addWidget(pv_title)

        # 2. Status Info (Branch & Commit)
        info_widget = QtWidgets.QWidget()
        info_layout = QtWidgets.QFormLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(10)
        info_layout.setLabelAlignment(Qt.AlignLeft)

        self.lbl_ver_branch = QtWidgets.QLabel("检测中...")
        self.lbl_ver_commit = QtWidgets.QLabel("检测中...")

        # 绑定数据显示
        # self.git_status.bind(lambda v: self.lbl_ver_branch.setText(v))
        self.comfyui_version.bind(lambda v: self.lbl_ver_commit.setText(v))

        lbl_style_pv = "color: #9CA3AF; font: 10pt 'Microsoft YaHei UI';"
        val_style_pv = "color: #E5E7EB; font: bold 10pt 'Microsoft YaHei UI';"

        l_br = QtWidgets.QLabel("当前分支:")
        l_br.setStyleSheet(lbl_style_pv)
        self.lbl_ver_branch.setStyleSheet(val_style_pv)

        l_cm = QtWidgets.QLabel("当前提交:")
        l_cm.setStyleSheet(lbl_style_pv)
        self.lbl_ver_commit.setStyleSheet(val_style_pv)

        info_layout.addRow(l_br, self.lbl_ver_branch)
        info_layout.addRow(l_cm, self.lbl_ver_commit)
        pv_layout.addWidget(info_widget)

        # 3. Settings Interface (Proxy & Strategies)
        settings_panel = QtWidgets.QWidget()
        settings_panel.setStyleSheet("background-color: rgba(0, 0, 0, 0.2); border-radius: 8px; padding: 10px;")
        sp_layout = QtWidgets.QVBoxLayout(settings_panel)
        sp_layout.setSpacing(12)

        # Row 1: Proxy Setting
        row_proxy = QtWidgets.QHBoxLayout()
        row_proxy.setContentsMargins(0, 0, 0, 0)
        lbl_gh = QtWidgets.QLabel("GitHub代理:")
        lbl_gh.setStyleSheet(lbl_style_pv)

        pv_proxy_combo = NoWheelComboBox()
        pv_proxy_combo.addItems(["不使用", "gh-proxy", "自定义"])
        pv_proxy_combo.setFixedWidth(140)
        pv_proxy_combo.setStyleSheet(common_input_qss)

        pv_proxy_combo.setCurrentText(self.version_manager.proxy_mode_ui_var.get())

        def _pv_proxy_changed(text):
             m = "none" if text == "不使用" else ("gh-proxy" if text == "gh-proxy" else "custom")
             self.version_manager.proxy_mode_var.set(m)
             self.version_manager.proxy_mode_ui_var.set(text)

             if text == "gh-proxy":
                 self.version_manager.proxy_url_var.set("https://gh-proxy.com/")
             self.version_manager.save_proxy_settings()

        pv_proxy_combo.currentTextChanged.connect(_pv_proxy_changed)

        self.version_manager.proxy_mode_ui_var.bind(
            lambda v: pv_proxy_combo.setCurrentText(v) if pv_proxy_combo.currentText() != v else None
        )

        row_proxy.addWidget(lbl_gh)
        row_proxy.addWidget(pv_proxy_combo)
        row_proxy.addStretch(1)
        sp_layout.addLayout(row_proxy)

        # Row 2: Strategy Checkboxes
        row_strat = QtWidgets.QHBoxLayout()
        row_strat.setContentsMargins(0, 0, 0, 0)
        lbl_st = QtWidgets.QLabel("升级策略:")
        lbl_st.setStyleSheet(lbl_style_pv)

        cb_stable = QtWidgets.QCheckBox("仅更新到稳定版")
        cb_stable.setChecked(self.stable_only_var.get())
        cb_stable.toggled.connect(lambda c: (self.stable_only_var.set(c), self.save_config()))

        cb_deps = QtWidgets.QCheckBox("自动更新依赖库 (包括前端及模板库)")
        cb_deps.setChecked(self.auto_update_deps_var.get())
        cb_deps.toggled.connect(lambda c: (self.auto_update_deps_var.set(c), self.save_config()))

        row_strat.addWidget(lbl_st)
        row_strat.addWidget(cb_stable)
        row_strat.addSpacing(15)
        row_strat.addWidget(cb_deps)
        row_strat.addStretch(1)
        sp_layout.addLayout(row_strat)

        pv_layout.addWidget(settings_panel)

        # 4. Action Buttons
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(12)

        btn_action_style = """
            QPushButton {
                background-color: #374151;
                color: #FFFFFF;
                border: 1px solid #4B5563;
                border-radius: 6px;
                padding: 6px 16px;
                font: 10pt "Microsoft YaHei UI";
            }
            QPushButton:hover { background-color: #4B5563; }
            QPushButton:pressed { background-color: #1F2937; }
        """

        btn_upd = QtWidgets.QPushButton("更 新")
        btn_upd.setCursor(Qt.PointingHandCursor)
        btn_upd.setStyleSheet(btn_action_style)
        btn_upd.clicked.connect(lambda: self._upgrade_latest(self.stable_only_var.get()))

        btn_switch = QtWidgets.QPushButton("切换到所选提交")
        btn_switch.setCursor(Qt.PointingHandCursor)
        btn_switch.setStyleSheet(btn_action_style)

        def _do_checkout_commit():
            row = self.history_table.currentRow()
            if row >= 0:
                item = self.history_table.item(row, 0)
                if item:
                    commit_hash = item.text().strip()
                    if commit_hash:
                         try:
                             if getattr(self, "logger", None):
                                self.logger.info(f"UI: 请求切换到提交 {commit_hash}")
                             base = Path(self.config.get("paths", {}).get("comfyui_root") or ".").resolve()
                             root = (base / "ComfyUI").resolve()
                             COMMON.run_hidden([self.git_path or "git", "checkout", commit_hash], cwd=str(root))
                             self.get_version_info("all")
                             QtWidgets.QMessageBox.information(self, "切换成功", f"已切换到提交 {commit_hash}")
                         except Exception as e:
                             QtWidgets.QMessageBox.warning(self, "切换失败", str(e))

        btn_switch.clicked.connect(_do_checkout_commit)

        btn_refresh = QtWidgets.QPushButton("刷新提交历史 (远端)")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(btn_action_style)

        def _fetch_remote_and_refresh():
            btn_refresh.setEnabled(False)
            btn_refresh.setText("刷新中...")
            try:
                base = Path(self.config.get("paths", {}).get("comfyui_root") or ".").resolve()
                root = (base / "ComfyUI").resolve()
                if not root.exists():
                     return
                # 1. Fetch
                if getattr(self, "logger", None): self.logger.info("UI: 正在执行 git fetch...")
                run_hidden([self.git_path or "git", "fetch"], cwd=str(root))
                # 2. Refresh info (force refresh kernel section which reloads history)
                # We tell _refresh_kernel_section to try loading remote history
                _refresh_kernel_section(force_remote=True)

                # Also trigger version check to update other indicators
                self.get_version_info("core_only")
            except Exception:
                pass
            finally:
                btn_refresh.setEnabled(True)
                btn_refresh.setText("刷新提交历史 (远端)")

        btn_refresh.clicked.connect(_fetch_remote_and_refresh)

        btn_row.addWidget(btn_upd)
        btn_row.addWidget(btn_switch)
        btn_row.addWidget(btn_refresh)
        btn_row.addStretch(1)

        pv_layout.addLayout(btn_row)

        # 5. Commit History Table
        hist_label = QtWidgets.QLabel("提交历史")
        hist_label.setStyleSheet("font: bold 12pt 'Microsoft YaHei UI'; color: #FFFFFF; margin-top: 10px;")
        pv_layout.addWidget(hist_label)

        self.history_table = QtWidgets.QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["提交哈希", "日期", "作者", "提交信息"])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.history_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.history_table.setShowGrid(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        self.history_table.setStyleSheet("""
            QTableWidget {
                border: none;
                background-color: #1F2937;
                alternate-background-color: #27303f;
                color: #E5E7EB;
                gridline-color: #374151;
            }
            QHeaderView::section {
                background-color: rgba(0,0,0,0.3);
                color: #E5E7EB;
                border: none;
                padding: 8px;
                font-weight: bold;
                border-bottom: 2px solid #6B7280;
            }
            QTableWidget::item {
                padding: 4px;
                border: none; /* Removed bottom border to look cleaner with alternate colors */
            }
            QTableWidget::item:selected {
                background-color: rgba(99, 102, 241, 0.4); /* ACCENT semi-transparent */
                color: #FFFFFF;
            }
            QTableWidget::item:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }
            /* Scrollbar styling */
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
            }
            QScrollBar::handle:vertical {
                background: #4B5563;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6B7280;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)

        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)

        pv_layout.addWidget(self.history_table)

        self._version_branch_label = self.lbl_ver_branch
        self._version_commit_label = self.lbl_ver_commit
        self._version_stable_label = QtWidgets.QLabel()
        self._history_table = self.history_table

        def _refresh_kernel_section(force_remote=False):
            try:
                cur = self.services.version.get_current_kernel_version()
                self._version_commit_label.setText(cur.get("commit") or "未知")
                try:
                    base = Path(self.config.get("paths", {}).get("comfyui_root") or ".").resolve()
                    root = (base / "ComfyUI").resolve()
                except Exception:
                    root = Path.cwd()
                r = run_hidden([self.git_path or "git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=6, cwd=str(root))
                self._version_branch_label.setText(r.stdout.strip() if r.returncode == 0 else "unknown")
            except Exception:
                pass
            try:
                _load_commit_history(force_remote)
            except Exception:
                pass

        def _load_commit_history(show_remote=False):
            try:
                base = Path(self.config.get("paths", {}).get("comfyui_root") or ".").resolve()
                root = (base / "ComfyUI").resolve()
            except Exception:
                root = Path.cwd()

            target = "HEAD"
            if show_remote:
                 # Try to find upstream or origin/HEAD
                 r_up = run_hidden([self.git_path or "git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], capture_output=True, text=True, timeout=3, cwd=str(root))
                 if r_up.returncode == 0 and r_up.stdout.strip():
                     target = r_up.stdout.strip()
                 else:
                     target = "origin/HEAD"

            r = run_hidden([self.git_path or "git", "log", "--date=short", "--pretty=format:%h|%ad|%an|%s", "-n", "50", target], capture_output=True, text=True, timeout=8, cwd=str(root))

            rows = []
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.splitlines():
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        rows.append(parts)

            # Fallback to local HEAD if remote failed but was requested
            if (r.returncode != 0 or not rows) and show_remote:
                 r = run_hidden([self.git_path or "git", "log", "--date=short", "--pretty=format:%h|%ad|%an|%s", "-n", "50", "HEAD"], capture_output=True, text=True, timeout=8, cwd=str(root))
                 if r.returncode == 0 and r.stdout:
                    for line in r.stdout.splitlines():
                        parts = line.split("|", 3)
                        if len(parts) == 4:
                            rows.append(parts)

            self.history_table.setRowCount(len(rows))
            try:
                import re as _re
                _kw_fix = _re.compile(r"(?i)\\bfix\\b")
                _kw_ver = _re.compile(r"v\\d+(?:\\.\\d+)*")
            except Exception:
                _kw_fix = None
                _kw_ver = None
            for ri, cols in enumerate(rows):
                for ci, val in enumerate(cols):
                    item = QtWidgets.QTableWidgetItem(val)
                    if ci == 0:
                        f = item.font()
                        f.setFamily("Consolas")
                        item.setFont(f)
                        item.setForeground(QtGui.QBrush(QtGui.QColor("#9CA3AF")))
                    if ci == 3:
                        try:
                            if (_kw_fix and _kw_fix.search(val)) or (_kw_ver and _kw_ver.search(val)):
                                f = item.font()
                                f.setBold(True)
                                item.setFont(f)
                                item.setForeground(QtGui.QBrush(QtGui.QColor("#FFFFFF")))
                            else:
                                item.setForeground(QtGui.QBrush(QtGui.QColor("#D1D5DB")))
                        except Exception:
                            pass
                    self.history_table.setItem(ri, ci, item)

        _refresh_kernel_section(force_remote=False)

        # =========================================================
        # Build External Model Library Page (外置模型库管理)
        # =========================================================
        pm_layout = QtWidgets.QVBoxLayout(page_models)
        pm_layout.setContentsMargins(25, 25, 25, 25)
        pm_layout.setSpacing(15)

        pm_title = QtWidgets.QLabel("外置模型库管理")
        pm_title.setStyleSheet("font: bold 16pt 'Microsoft YaHei UI'; color: #FFFFFF; margin-bottom: 5px;")
        pm_layout.addWidget(pm_title)

        # Config Card
        pm_card = QtWidgets.QGroupBox("配置与映射")
        pm_card_layout = QtWidgets.QVBoxLayout(pm_card)
        pm_card_layout.setSpacing(20)
        pm_card_layout.setContentsMargins(20, 20, 20, 20)
        pm_layout.addWidget(pm_card)

        # 1. Base Path Selection
        bp_row = QtWidgets.QHBoxLayout()
        lbl_bp = QtWidgets.QLabel("模型库根路径:")
        lbl_bp.setFixedWidth(100)
        lbl_bp.setStyleSheet("color: #9CA3AF; font: 10pt 'Microsoft YaHei UI';")

        # Load initial value
        init_base_path = ""
        try:
            if getattr(self, "services", None) and hasattr(self.services, "model_path"):
                init_base_path = self.services.model_path.get_external_path()
        except Exception:
            pass

        self.edit_base_path = QtWidgets.QLineEdit(init_base_path)
        self.edit_base_path.setReadOnly(True)
        self.edit_base_path.setStyleSheet(common_input_qss)

        btn_sel_bp = QtWidgets.QPushButton("选择目录...")
        btn_sel_bp.setCursor(Qt.PointingHandCursor)
        btn_sel_bp.setFixedWidth(100)
        btn_sel_bp.setStyleSheet(self._common_btn_style)

        def _sel_bp():
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择模型库根目录", self.edit_base_path.text() or ".")
            if d:
                self.edit_base_path.setText(str(Path(d).resolve()))
                _refresh_mapping_table()

        btn_sel_bp.clicked.connect(_sel_bp)

        bp_row.addWidget(lbl_bp)
        bp_row.addWidget(self.edit_base_path)
        bp_row.addWidget(btn_sel_bp)
        pm_card_layout.addLayout(bp_row)

        # 2. Count Info
        count_row = QtWidgets.QHBoxLayout()
        # Default mapping count
        map_count = len(self.services.model_path.get_mappings()) if getattr(self, "services", None) and hasattr(self.services, "model_path") else 0

        lbl_info = QtWidgets.QLabel(f"当前已映射子文件夹: {map_count}")
        lbl_info.setStyleSheet("color: #9CA3AF; font: 10pt 'Microsoft YaHei UI';")
        count_row.addWidget(lbl_info)
        count_row.addStretch(1)
        pm_card_layout.addLayout(count_row)

        # 3. Actions Row (Update Button & Open Config Button)
        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(15)

        btn_update_map = QtWidgets.QPushButton("更新映射")
        btn_update_map.setCursor(Qt.PointingHandCursor)
        btn_update_map.setFixedWidth(120)
        btn_update_map.setStyleSheet(self._common_btn_style)

        def _do_update_map():
            path = self.edit_base_path.text().strip()
            if not path:
                QtWidgets.QMessageBox.warning(self, "错误", "请先选择模型库根路径")
                return

            try:
                success = self.services.model_path.update_mapping(path)
                if success:
                    QtWidgets.QMessageBox.information(self, "成功", "外置模型库映射已更新！\n请重启 ComfyUI 生效。")
                    _refresh_mapping_table()
                else:
                    QtWidgets.QMessageBox.warning(self, "失败", "更新映射配置失败，请检查日志。")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "错误", str(e))

        btn_update_map.clicked.connect(_do_update_map)

        btn_open_yaml = QtWidgets.QPushButton("打开配置文件")
        btn_open_yaml.setCursor(Qt.PointingHandCursor)
        btn_open_yaml.setFixedWidth(120)
        # Using secondary style for less prominent action
        btn_open_yaml.setStyleSheet(secondary_btn_style)

        def _do_open_yaml():
            try:
                if getattr(self, "services", None) and hasattr(self.services, "model_path"):
                    yp = self.services.model_path._get_yaml_path()
                    if yp.exists():
                        os.startfile(str(yp))
                    else:
                        QtWidgets.QMessageBox.information(self, "提示", "配置文件 extra_model_paths.yaml 尚未创建。")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "错误", f"无法打开文件: {e}")

        btn_open_yaml.clicked.connect(_do_open_yaml)

        action_row.addWidget(btn_update_map)
        action_row.addWidget(btn_open_yaml)
        action_row.addStretch(1)

        pm_card_layout.addLayout(action_row)

        # 4. Mapping Table
        lbl_table = QtWidgets.QLabel("当前已映射子文件夹")
        lbl_table.setStyleSheet("font: bold 11pt 'Microsoft YaHei UI'; color: #FFFFFF; margin-top: 10px;")
        pm_card_layout.addWidget(lbl_table)

        table = QtWidgets.QTableWidget()
        mappings = self.services.model_path.get_mappings() if getattr(self, "services", None) and hasattr(self.services, "model_path") else []
        table.setRowCount(len(mappings))
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["名称", "路径"])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setShowGrid(True)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)

        # Increase minimum height for better visibility
        table.setMinimumHeight(500)

        # Reuse historical table style
        table.setStyleSheet("""
            QTableWidget {
                border: none;
                background-color: #1F2937;
                alternate-background-color: #27303f;
                color: #E5E7EB;
                gridline-color: #374151;
            }
            QHeaderView::section {
                background-color: rgba(0,0,0,0.3);
                color: #E5E7EB;
                border: none;
                padding: 8px;
                font-weight: bold;
                border-bottom: 2px solid #6B7280;
            }
            QTableWidget::item {
                padding: 6px;
                border: none;
            }
        """)

        def _refresh_mapping_table():
            base_path = self.edit_base_path.text().strip()
            if getattr(self, "services", None) and hasattr(self.services, "model_path"):
                mappings_now = self.services.model_path.get_mappings_for_base(base_path)
            else:
                mappings_now = []
            table.setRowCount(len(mappings_now))
            for i, (k, v) in enumerate(mappings_now):
                item_k = QtWidgets.QTableWidgetItem(k)
                item_v = QtWidgets.QTableWidgetItem(v)
                table.setItem(i, 0, item_k)
                table.setItem(i, 1, item_v)
            try:
                lbl_info.setText(f"当前已映射子文件夹: {len(mappings_now)}")
            except Exception:
                pass

        _refresh_mapping_table()

        pm_card_layout.addWidget(table)

        pm_layout.addStretch(1)

        # Build About Me
        try:
            page_about_me.setObjectName("AboutMePage")
            page_about_me.setStyleSheet(f"""
                #AboutMePage {{
                    background: transparent;
                }}
            """)
        except Exception:
            pass

        about_outer = QtWidgets.QHBoxLayout(page_about_me)
        about_outer.setContentsMargins(0, 0, 0, 0)
        about_outer.addStretch(1)
        about_container = QtWidgets.QFrame()
        about_container.setObjectName("ContentWrapper")
        # Scheme 1: Immersive Full Width - Transparent container
        about_container.setStyleSheet("background: transparent; border: none;")
        try:
            from ui.constants import MAX_CONTENT_WIDTH as _MAXW
            about_container.setMaximumWidth(_MAXW)
        except Exception:
            about_container.setMaximumWidth(980)
        about_layout = QtWidgets.QVBoxLayout(about_container)
        about_layout.setContentsMargins(20, 10, 20, 10)
        about_layout.setSpacing(10)
        img_path = ASSETS.resolve_asset('about_me.jpg')
        if not (img_path and img_path.exists()):
            img_path = ASSETS.resolve_asset('about_me.png')

        avatar_pix = None
        if img_path and img_path.exists():
            try:
                avatar_pix = QtGui.QPixmap(str(img_path))
            except Exception:
                pass

        avatar = CircleAvatar(avatar_pix, size=60)

        t1 = QtWidgets.QLabel("黎黎原上咩")
        t1.setStyleSheet("""
            font: bold 18pt "Microsoft YaHei UI"; 
            color: #FFFFFF;
            background: transparent;
        """)

        t2 = QtWidgets.QLabel("“未觉池塘春草梦，阶前梧叶已秋声”")
        # 使用楷体增强文艺感，严禁使用 italic 以免在 Qt 中渲染模糊
        t2.setStyleSheet("""
            color: #9CA3AF; 
            font: 12pt "KaiTi", "SimKai", "Microsoft YaHei UI";
            background: transparent;
        """)

        profile_card = QtWidgets.QFrame()
        profile_card.setObjectName("ProfileCard")
        profile_card.setMinimumHeight(100)
        profile_card.setAttribute(Qt.WA_StyledBackground, True)
        profile_card.setStyleSheet(f"""
        #ProfileCard {{
            background-color: #1F2937;
            border: 1px solid {c.get('BORDER','#374151')};
            border-radius: 12px;
        }}
        """)

        # 添加阴影效果提升质感
        try:
            glow = QtWidgets.QGraphicsDropShadowEffect(self)
            glow.setBlurRadius(15)
            glow.setOffset(0, 4)
            glow.setColor(QtGui.QColor(0, 0, 0, 30))
            profile_card.setGraphicsEffect(glow)
        except Exception:
            pass

        pc_outer = QtWidgets.QHBoxLayout(profile_card)
        pc_outer.setContentsMargins(20, 10, 20, 10)
        pc_outer.setSpacing(20)

        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(6)
        info_layout.setAlignment(Qt.AlignVCenter)

        info_layout.addWidget(t1)
        info_layout.addWidget(t2)

        pc_outer.addWidget(avatar)
        pc_outer.addLayout(info_layout)
        pc_outer.addStretch(1)

        about_layout.addWidget(profile_card)
        about_layout.addSpacing(5)
        cards_grid = QtWidgets.QGridLayout()
        cards_grid.setHorizontalSpacing(12)
        cards_grid.setVerticalSpacing(12)
        about_layout.addLayout(cards_grid)
        def _make_link(text, url):
            btn = QtWidgets.QPushButton(text)
            btn.setObjectName("LinkButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(38)
            btn.setStyleSheet(f"""
            QPushButton#LinkButton {{
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 10px;
                padding: 0 14px;
                text-align: left;
                color: #A5B4FC; /* Lighter accent for dark bg */
                font: 10.5pt "Microsoft YaHei UI";
            }}
            QPushButton#LinkButton:hover {{
                background-color: rgba(255, 255, 255, 0.1);
                color: #FFFFFF;
                border: 1px solid {c.get('ACCENT','#6366F1')};
            }}
            """)
            def _open():
                QtGui = __import__('PyQt5.QtGui', fromlist=['QDesktopServices'])
                QDesktopServices = getattr(QtGui, 'QDesktopServices')
                QUrl = getattr(__import__('PyQt5.QtCore', fromlist=['QUrl']), 'QUrl')
                QDesktopServices.openUrl(QUrl(url))
            btn.clicked.connect(_open)
            try:
                def _enter(_):
                    eff = QtWidgets.QGraphicsDropShadowEffect(btn)
                    eff.setBlurRadius(15)
                    eff.setOffset(0, 4)
                    eff.setColor(QtGui.QColor(99, 102, 241, 35))
                    btn.setGraphicsEffect(eff)
                def _leave(_):
                    btn.setGraphicsEffect(None)
                btn.enterEvent = _enter
                btn.leaveEvent = _leave
            except Exception:
                pass
            return btn
        def _card(title, items):
            g = QtWidgets.QGroupBox(title)
            g.setAttribute(Qt.WA_StyledBackground, True)
            g.setStyleSheet(f"""
            QGroupBox {{
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 16px;
                margin-top: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 10px;
                margin-left: 8px;
                color: #E5E7EB;
                font: bold 11.5pt "Microsoft YaHei UI";
                background: transparent;
            }}
            """)
            v = QtWidgets.QVBoxLayout(g)
            v.setContentsMargins(15, 22, 15, 12)
            v.setSpacing(8)
            v.setAlignment(Qt.AlignVCenter)

            for txt, u in items:
                v.addWidget(_make_link(txt, u))
            return g
        home_links = [
            ("🎬 哔哩哔哩（@黎黎原上咩）", "https://space.bilibili.com/449342345"),
            ("🎬 YouTube（@SweetValberry）", "https://www.youtube.com/@SweetValberry"),
        ]
        code_links = [
            ("🐙 GitHub（@MieMieeeee）", "https://github.com/MieMieeeee"),
        ]
        bundle_links = [
            ("📁 夸克网盘", "https://pan.quark.cn/s/4b98f758d6d4"),
            ("📁 百度网盘", "https://pan.baidu.com/s/1-shiphL-2RSt51RqyLBzGA?pwd=ukhx"),
        ]
        model_links = [
            ("📁 夸克网盘", "https://pan.quark.cn/s/3be6eb0d7f65"),
            ("📁 百度网盘", "https://pan.baidu.com/s/1tbd2wZ1doOkADB-SaSrGtQ?pwd=x6wh"),
        ]
        workflow_links = [
            ("📁 夸克网盘", "https://pan.quark.cn/s/59bafd8bf39d"),
            ("📁 百度网盘", "https://pan.baidu.com/s/1Ya3XeqPIMU15RQd8Tie9FA?pwd=5r6r"),
        ]
        wiki_links = [
            ("📘 飞书 Wiki", "https://dcn8q5lcfe3s.feishu.cn/wiki/IYHAwFhLviZIHBk7C7XccuJBn3c"),
        ]
        cards_grid.addWidget(_card("主页", home_links), 0, 0)
        cards_grid.addWidget(_card("代码库", code_links), 0, 1)
        cards_grid.addWidget(_card("ComfyUI 整合包", bundle_links), 1, 0)
        cards_grid.addWidget(_card("模型库", model_links), 1, 1)
        cards_grid.addWidget(_card("工作流库", workflow_links), 2, 0)
        cards_grid.addWidget(_card("知识库", wiki_links), 2, 1)
        about_layout.addStretch(1)
        about_outer.addWidget(about_container)
        about_outer.addStretch(1)

        # Build About ComfyUI
        comfy_outer = QtWidgets.QHBoxLayout(page_about_comfyui)
        try:
            page_about_comfyui.setObjectName("AboutComfyPage")
            page_about_comfyui.setStyleSheet(f"""
                #AboutComfyPage {{
                    background: transparent;
                }}
            """)
        except Exception:
            pass
        comfy_outer.setContentsMargins(0, 0, 0, 0)
        comfy_outer.addStretch(1)

        comfy_container = QtWidgets.QFrame()
        comfy_container.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        comfy_container.setStyleSheet("background: transparent; border: none;")
        comfy_container.setMaximumWidth(800)

        comfy_layout = QtWidgets.QVBoxLayout(comfy_container)
        comfy_layout.setContentsMargins(20, 10, 20, 10)
        comfy_layout.setSpacing(10)

        # Hero Card (Cover Card Layout)
        hero_card = QtWidgets.QFrame()
        hero_card.setObjectName("HeroCard")
        hero_card.setAttribute(Qt.WA_StyledBackground, True)
        hero_card.setStyleSheet(f"""
            #HeroCard {{
                background-color: #1F2937;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 16px;
            }}
        """)

        try:
            glow_h = QtWidgets.QGraphicsDropShadowEffect(self)
            glow_h.setBlurRadius(20)
            glow_h.setOffset(0, 8)
            glow_h.setColor(QtGui.QColor(0, 0, 0, 40))
            hero_card.setGraphicsEffect(glow_h)
        except Exception:
            pass

        hero_layout = QtWidgets.QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(0, 40, 0, 30) # Increased vertical padding
        hero_layout.setSpacing(25) # Increased spacing between Logo and Text
        hero_layout.setAlignment(Qt.AlignCenter)

        # Banner Image (Logo as Hero)
        banner_label = QtWidgets.QLabel()
        banner_label.setMinimumHeight(140) # Adequate height for the logo
        banner_label.setAlignment(Qt.AlignCenter)
        banner_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        banner_path = ASSETS.resolve_asset('comfyui.png')
        if banner_path and banner_path.exists():
            p_str = str(banner_path).replace("\\", "/")
            # Use 'image' property, centered, transparent background
            banner_label.setStyleSheet(f"""
                QLabel {{
                    background-color: transparent; 
                    image: url("{p_str}");
                    image-position: center;
                }}
            """)
        else:
             # Fallback placeholder
             banner_label.setText("ComfyUI")
             banner_label.setStyleSheet("""
                font: bold 40px "Microsoft YaHei UI"; color: #FFFFFF; background: transparent;
             """)

        hero_layout.addWidget(banner_label)

        # Text Content (Centered Slogan)
        hero_content = QtWidgets.QWidget()
        hero_content.setStyleSheet("background: transparent;")
        hc_layout = QtWidgets.QVBoxLayout(hero_content)
        hc_layout.setContentsMargins(40, 0, 40, 0)
        hc_layout.setSpacing(10)
        hc_layout.setAlignment(Qt.AlignCenter)

        # Center aligned description with HTML formatting, removed "ComfyUI" title text line
        h_desc = QtWidgets.QLabel(
            "<div style='text-align: center;'>"
            "<p style='font-size: 14px; color: #9CA3AF; line-height: 160%;'>"
            "ComfyUI 以模块化节点为核心，支持灵活的工作流构建与高效的推理执行。<br>"
            "它是目前最流行的 AI 绘画后端之一，拥有丰富的社区生态与可拓展的插件体系。<br>"
            "让创作者与开发者都能快速搭建生成式 AI 应用。"
            "</p>"
            "</div>"
        )
        h_desc.setStyleSheet("background: transparent;")
        h_desc.setWordWrap(True)
        h_desc.setAlignment(Qt.AlignCenter)
        try:
            h_desc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        except Exception:
            pass

        hc_layout.addWidget(h_desc)

        hero_layout.addWidget(hero_content)
        comfy_layout.addWidget(hero_card)

        comfy_layout.addSpacing(15)

        # Links Group
        comfy_links_grid = QtWidgets.QGridLayout()
        comfy_links_grid.setHorizontalSpacing(12)
        comfy_links_grid.setVerticalSpacing(12)
        comfy_layout.addLayout(comfy_links_grid)

        def _make_comfy_link_cell(title, desc, url):
            cell = QtWidgets.QFrame()
            cell.setObjectName("LinkCard")
            cell.setAttribute(Qt.WA_StyledBackground, True)
            cell.setStyleSheet(f"""
                #LinkCard {{
                    background-color: #1F2937;
                    border: 1px solid {c.get('BORDER','#374151')};
                    border-radius: 14px;
                }}
            """)
            vl = QtWidgets.QVBoxLayout(cell)
            vl.setContentsMargins(12, 12, 12, 12)

            btn = _make_link(title, url)
            if url == "internal:announcement":
                def _show_ann():
                    txt = ""
                    try:
                        if getattr(self, 'services', None) and getattr(self.services, 'announcement', None):
                            cache = self.services.announcement._get_cache_file()
                            if cache.exists():
                                txt = cache.read_text(encoding="utf-8", errors="ignore").strip()
                        QtWidgets.QMessageBox.information(self, "公告", txt or "暂无公告")
                    except Exception:
                        QtWidgets.QMessageBox.information(self, "公告", "暂无公告")
                btn.clicked.disconnect()
                btn.clicked.connect(_show_ann)

            vl.addWidget(btn)
            return cell

        ct_links = [
            ("🐙 官方 GitHub", "源码仓库与项目进展", "https://github.com/comfyanonymous/ComfyUI"),
            ("📰 官方博客", "项目动态与技术文章", "https://blog.comfy.org/"),
            ("📘 官方 Wiki", "节点用法与操作指南", "https://comfyui-wiki.com/"),
            ("💡 ComfyUI-Manager", "节点管理与扩展插件", "https://github.com/ltdrdata/ComfyUI-Manager"),
        ]

        for i, (txt, desc, u) in enumerate(ct_links):
            r, col = divmod(i, 2)
            comfy_links_grid.addWidget(_make_comfy_link_cell(txt, desc, u), r, col)

        comfy_layout.addStretch(1)
        comfy_outer.addWidget(comfy_container)
        comfy_outer.addStretch(1)

        # Build About Launcher
        la_outer = QtWidgets.QHBoxLayout(page_about_launcher)
        try:
            page_about_launcher.setObjectName("AboutLauncherPage")
            page_about_launcher.setStyleSheet(f"""
                #AboutLauncherPage {{
                    background: transparent;
                }}
            """)
        except Exception:
            pass
        la_outer.setContentsMargins(0, 0, 0, 0)
        la_outer.addStretch(1)

        la_container = QtWidgets.QFrame()
        la_container.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        la_container.setStyleSheet("background: transparent; border: none;")
        la_container.setMaximumWidth(800)

        la_layout = QtWidgets.QVBoxLayout(la_container)
        la_layout.setContentsMargins(20, 10, 20, 10)
        la_layout.setSpacing(10)

        # Hero Card for Launcher
        la_hero_card = QtWidgets.QFrame()
        la_hero_card.setObjectName("LauncherHeroCard")
        la_hero_card.setAttribute(Qt.WA_StyledBackground, True)
        la_hero_card.setStyleSheet(f"""
            #LauncherHeroCard {{
                background-color: #1F2937;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 16px;
            }}
        """)

        try:
            glow_l = QtWidgets.QGraphicsDropShadowEffect(self)
            glow_l.setBlurRadius(20)
            glow_l.setOffset(0, 8)
            glow_l.setColor(QtGui.QColor(0, 0, 0, 40))
            la_hero_card.setGraphicsEffect(glow_l)
        except Exception:
            pass

        lh_layout = QtWidgets.QVBoxLayout(la_hero_card)
        lh_layout.setContentsMargins(0, 40, 0, 30)
        lh_layout.setSpacing(25)
        lh_layout.setAlignment(Qt.AlignCenter)

        # Launcher Logo (Rabbit)
        rab_logo_label = QtWidgets.QLabel()
        rab_logo_label.setMinimumHeight(140)
        rab_logo_label.setAlignment(Qt.AlignCenter)
        rab_logo_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        rabbit_path = ASSETS.resolve_asset('rabbit.png')
        if rabbit_path and rabbit_path.exists():
            r_str = str(rabbit_path).replace("\\", "/")
            rab_logo_label.setStyleSheet(f"""
                QLabel {{
                    background-color: transparent; 
                    image: url("{r_str}");
                    image-position: center;
                }}
            """)
        else:
             rab_logo_label.setText("Launcher")
             rab_logo_label.setStyleSheet("""
                font: bold 40px "Microsoft YaHei UI"; color: #FFFFFF; background: transparent;
             """)

        lh_layout.addWidget(rab_logo_label)

        # Version Info Helper
        def _get_build_badge_str():
            try:
                from pathlib import Path
                import json, sys
                p_base = Path(getattr(self, "base_root", Path.cwd()))
                candidates = []
                try:
                    candidates.append(Path(getattr(sys, "_MEIPASS", "")) / "build_parameters.json")
                except Exception: pass
                try:
                    candidates.append(Path(sys.executable).resolve().parent / "build_parameters.json")
                except Exception: pass
                try:
                    candidates.append(p_base / "build_parameters.json")
                    candidates.append(p_base / "launcher" / "build_parameters.json")
                    candidates.append(Path(__file__).resolve().parents[1] / "build_parameters.json")
                except Exception: pass
                target = None
                for p in candidates:
                    try:
                        if p and p.exists():
                            target = p
                            break
                    except Exception: pass
                if target and target.exists():
                    with open(target, "r", encoding="utf-8") as f:
                        params = json.load(f) or {}
                    ver = str(params.get("version") or "").strip()
                    suf = str(params.get("suffix") or "").strip()
                    if ver and suf: return f"v{ver} {suf}"
                    if ver: return f"v{ver}"
                    if suf: return suf
            except Exception: pass
            return "Dev Build"

        version_str = _get_build_badge_str()

        # Text Content (Centered Slogan)
        lh_content = QtWidgets.QWidget()
        lh_content.setStyleSheet("background: transparent;")
        lhc_layout = QtWidgets.QVBoxLayout(lh_content)
        lhc_layout.setContentsMargins(40, 0, 40, 0)
        lhc_layout.setSpacing(10)
        lhc_layout.setAlignment(Qt.AlignCenter)

        lh_desc = QtWidgets.QLabel(
            "<div style='text-align: center;'>"
            "<p style='font-size: 20px; font-weight: bold; color: #FFFFFF; margin-bottom: 12px; letter-spacing: 1px;'>"
            "ComfyUI 启动器</p>"
            "<p style='font-size: 14px; color: #9CA3AF; line-height: 160%;'>"
            "专为 ComfyUI 设计的轻巧、友好的桌面管理工具。<br>"
            f"让环境配置、版本管理与日常使用变得简单而优雅。<br><br>"
            f"<span style='background-color: rgba(255,255,255,0.1); border-radius: 4px; padding: 2px 8px; font-size: 12px; color: #A5B4FC;'>{version_str}</span>"
            "</p>"
            "</div>"
        )
        lh_desc.setStyleSheet("background: transparent;")
        lh_desc.setWordWrap(True)
        lh_desc.setAlignment(Qt.AlignCenter)
        try:
            lh_desc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        except Exception:
            pass

        lhc_layout.addWidget(lh_desc)

        lh_layout.addWidget(lh_content)
        la_layout.addWidget(la_hero_card)
        la_layout.addSpacing(15)

        # Quick Actions Grid
        cta_grid = QtWidgets.QGridLayout()
        cta_grid.setHorizontalSpacing(12)
        cta_grid.setVerticalSpacing(12)
        la_layout.addLayout(cta_grid)

        def _make_cta_cell(title, icon_text, url):
            cell = QtWidgets.QFrame()
            cell.setObjectName("CtaCard")
            cell.setAttribute(Qt.WA_StyledBackground, True)
            cell.setStyleSheet(f"""
                #CtaCard {{
                    background-color: #1F2937;
                    border: 1px solid {c.get('BORDER','#374151')};
                    border-radius: 14px;
                }}
            """)
            vl = QtWidgets.QVBoxLayout(cell)
            vl.setContentsMargins(12, 12, 12, 12)

            btn = _make_link(f"{icon_text} {title}", url)
            if url == "internal:announcement":
                def _show_ann():
                    txt = ""
                    try:
                        if getattr(self, 'services', None) and getattr(self.services, 'announcement', None):
                            cache = self.services.announcement._get_cache_file()
                            if cache.exists():
                                txt = cache.read_text(encoding="utf-8", errors="ignore").strip()
                        QtWidgets.QMessageBox.information(self, "公告", txt or "暂无公告")
                    except Exception:
                        QtWidgets.QMessageBox.information(self, "公告", "暂无公告")
                btn.clicked.disconnect()
                btn.clicked.connect(_show_ann)

            vl.addWidget(btn)
            return cell

        cta_links = [
            ("代码仓库 GitHub", "🐙", "https://github.com/MieMieeeee/ComfyUI-Mie-Package-Launcher"),
            ("遇到问题？提个 Issue", "💬", "https://github.com/MieMieeeee/ComfyUI-Mie-Package-Launcher/issues/new"),
            ("展示与反馈", "📢", "https://github.com/MieMieeeee/ComfyUI-Mie-Package-Launcher/discussions"),
            ("查看公告", "🔔", "internal:announcement"),
        ]

        for i, (txt, ico, u) in enumerate(cta_links):
            r, col = divmod(i, 2)
            cta_grid.addWidget(_make_cta_cell(txt, ico, u), r, col)

        la_layout.addStretch(1)
        la_outer.addWidget(la_container)
        la_outer.addStretch(1)

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

    def resolve_git(self):
        return GitService(self).resolve_git()


    def get_version_info(self, scope="all"):
        try:
            if getattr(self, "logger", None):
                self.logger.info("UI: 触发版本刷新 scope=%s", scope)
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
                vram_mode=self.vram_mode.get() or "--normalvram",
                default_port=self.custom_port.get() or "8188",
                disable_all_custom_nodes=self.disable_all_custom_nodes.get(),
                enable_fast_mode=self.use_fast_mode.get(),
                disable_api_nodes=self.disable_api_nodes.get(),
                enable_cors=self.enable_cors.get(),
                listen_all=self.listen_all.get(),
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
            res = self.services.version.upgrade_latest(stable_only=stable_only)
            self.get_version_info("core_only")
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

    def run(self):
        self.get_version_info("all")
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
                    for w, t in zip(labs, vals):
                        try:
                            w.setText(t)
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

        self.qt_app.exec_()
