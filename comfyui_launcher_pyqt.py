import os
import re
import sys
import warnings

# Suppress sipPyTypeDict deprecation warning
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*sipPyTypeDict.*")

# 抑制 Qt DirectWrite 字体警告。
# Windows 高 DPI(如 150% 缩放)下 Qt 枚举系统字体时会反复尝试解析 Fixedsys /
# Modern / MS Sans Serif / MS Serif / Roman / Script 这些旧位图字体,DirectWrite
# 无法处理,每次刷一行 "CreateFontFaceFromHDC() failed" 警告。这些警告无害
# (字体最终会回退到正常字体),纯粹是噪音,通过 logging rule 关掉。
# 必须在 import PyQt5 之前设置。用无条件赋值覆盖用户 shell 里可能已设的其他值。
# DirectWrite 负载失败在 Qt5 不同版本不同 category,多击击都覆盖上:
#   qt.qpa.fonts     字体枚举阶段的警告
#   qt.text.font     Qt5.9+ 的字体加载路径上下文
#   qt.text.fonts    部分 patch 版本使用这个名称
#   qt.text          全局文本模块下的警告全部抑制
# 多个规则以 ";" 分隔。这一层为首选防线(过滤掉大多数警告);
# 下面会加 qInstallMessageHandler 作为二层防线(抓住漏网的任何警告)。
# 阶段性拦截: import PyQt5 之前包装 sys.stderr,
# 过滤 DirectWrite 字体警告。该警告是 Qt DLL 在 import 阶段就输出的,
# 比 qInstallMessageHandler 要装上更早, 所以 logging rule + message handler 都装太晚。
# Python 层的 sys.stderr 包装可以接住所有走 stderr 的输出
# (包括 Qt 内部 qWarning 走 stderr 那部分)。


class _DirectWriteNoiseFilter:
    """stderr 过滤器:
    - 丢掉含 DirectWrite: CreateFontFaceFromHDC 的行 (Qt 字体警告)
    - 从其他行中剥除 ANSI SGR 转义串 (Python logging 输出的 [1m[31m[ERROR][0m 类)。"""

    _NEEDLE = "DirectWrite: CreateFontFaceFromHDC"
    # ANSI SGR: ESC [ <参数> m。参数以 ; 分隔的数字 (颜色 / 加粗 / 背景色 / reset 等)。
    # 不包括光标移动 / 清屏等 (H, J, K 等), 那些不在 PowerShell 能反应的范围内。
    _SGR_RE = re.compile(r"\x1b\[[\d;]*m")

    @classmethod
    def _strip_sgr(cls, s: str) -> str:
        return cls._SGR_RE.sub("", s)

    def __init__(self, real):
        self._real = real
        self._buf = ""

    def write(self, s):
        if not s:
            return
        if not isinstance(s, str):
            try:
                s = s.decode("utf-8", errors="replace")
            except Exception:
                return self._real.write(s)
        # 以\n为分隔索引拼接完整行, 避免一行被切两半
        # 出现"半行是警告, 半行正常" 这种 bug。
        data = self._buf + s
        out = []
        last_split = 0
        for i, ch in enumerate(data):
            if ch == "\n":
                line = data[last_split:i]
                last_split = i + 1
                if self._NEEDLE in line:
                    # 该行丢弃, 不加到 out
                    continue
                # 不含 DirectWrite 的行: 剥除 ANSI SGR 后转发
                out.append(self._strip_sgr(line) + "\n")
        self._buf = data[last_split:]
        if out:
            self._real.write("".join(out))

    def flush(self):
        if self._buf and self._NEEDLE not in self._buf:
            self._real.write(self._strip_sgr(self._buf))
        self._buf = ""
        try:
            self._real.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        # 其他属性(isatty/fileno/...) 全部转发到原始 stream,
        # 避免 colorama 等三方包调用 .isatty 报错。
        return getattr(self._real, name)


sys.stderr = _DirectWriteNoiseFilter(sys.stderr)


os.environ["QT_LOGGING_RULES"] = (
    "qt.qpa.fonts.warning=false;"
    "qt.text.font.warning=false;"
    "qt.text.fonts.warning=false;"
    "qt.text.warning=false"
)

from PyQt5 import QtWidgets, QtCore, QtGui

# 二层防线：装 message handler 拦截 Qt 消息。过滤:
# 1) DirectWrite 字体负载失败 ("CreateFontFaceFromHDC() failed" 类)——无害,仅为警告;
# 2) qt.qpa.fonts / qt.text.* category 下的任何 message（以防 logging rule 漏网）。
# 其他消息全部放行。这个 handler 覆盖默认 handler,但只在本脚本进程内生效。
_DIRECTWRITE_NOISE = (
    "CreateFontFaceFromHDC",  # DirectWrite 负载失败的关键字符串
)


def _qt_message_handler(mode, ctx, msg):
    """拦截 Qt 内部消息。对装中误以 DirectWrite 字体负载失败为默认抛弃。

    参数 ctx 可能为 None（部分路径调用 handler 时不传 ctx）,以及不同 Qt 版本字段不同,所以做防御性访问。
    """
    try:
        if msg and any(needle in msg for needle in _DIRECTWRITE_NOISE):
            return  # 丢弃该条警告
        cat = getattr(ctx, "category", "") if ctx is not None else ""
        if cat and (
            cat.startswith("qt.qpa.fonts")
            or cat.startswith("qt.text")
            and ("font" in cat or "Font" in cat)
        ):
            return
    except Exception:
        pass
    # 其他消息走默认 handler（输出到 stderr、调试器等）
    sys.stderr.write(f"{msg}\n")


QtCore.qInstallMessageHandler(_qt_message_handler)

# -----------------------------------------------------------------------------
# Fix for PyQt5 plugins + DLL path in PyInstaller onedir + Enigma Virtual Box
# -----------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
    print(f"[DEBUG PyQt5 Fix] Base dir (virtual exe dir): {base_dir}")

    # PyQt5 典型 onedir 结构：_internal/PyQt5/Qt/plugins 或 _internal/PyQt5/Qt5/plugins
    possible_plugin_roots = [
        os.path.join(base_dir, '_internal', 'PyQt5', 'Qt', 'plugins'),
        os.path.join(base_dir, '_internal', 'PyQt5', 'Qt5', 'plugins'),
        os.path.join(base_dir, '_internal', 'PyQt5', 'plugins'),
        os.path.join(base_dir, 'PyQt5', 'Qt', 'plugins'),
        os.path.join(base_dir, 'PyQt5', 'Qt5', 'plugins'),
    ]

    target_plugin_path = None
    for p in possible_plugin_roots:
        if os.path.exists(os.path.join(p, 'platforms', 'qwindows.dll')):  # 关键检查：必须有 qwindows.dll
            target_plugin_path = p
            print(f"[DEBUG] Found valid PyQt5 plugins path: {target_plugin_path}")
            break

    if target_plugin_path:
        os.environ['QT_PLUGIN_PATH'] = target_plugin_path
        platform_path = os.path.join(target_plugin_path, 'platforms')
        os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = platform_path
        print(f"[DEBUG] Set QT_PLUGIN_PATH: {target_plugin_path}")
        print(f"[DEBUG] Set QT_QPA_PLATFORM_PLUGIN_PATH: {platform_path}")
    else:
        print("[WARNING] No valid PyQt5 plugins/platforms/qwindows.dll found! Qt will fail.")

    # 额外：把 PyQt5 的 bin 加到 PATH（QtCore/QtGui/QtWidgets.dll 等依赖搜索）
    qt_bin_path = os.path.join(base_dir, '_internal', 'PyQt5', 'Qt', 'bin')
    if not os.path.exists(qt_bin_path):
        qt_bin_path = os.path.join(base_dir, '_internal', 'PyQt5', 'Qt5', 'bin')

    if os.path.exists(qt_bin_path):
        # 1. Update PATH (Traditional method)
        os.environ['PATH'] = qt_bin_path + os.pathsep + os.environ.get('PATH', '')
        print(f"[DEBUG] Added Qt bin to PATH: {qt_bin_path}")

        # 2. Use add_dll_directory for Python 3.8+ (Modern method, often required)
        if hasattr(os, 'add_dll_directory'):
            try:
                os.add_dll_directory(qt_bin_path)
                print(f"[DEBUG] os.add_dll_directory({qt_bin_path}) called")
            except Exception as e:
                print(f"[WARNING] os.add_dll_directory failed: {e}")

        # 3. Pre-load Qt DLLs (Critical for Enigma Virtual Box)
        # Enigma virtualization sometimes fails to resolve dependencies implicitly via PATH
        try:
            import ctypes
            # Order matters: Core -> Gui -> Widgets
            # Also load d3dcompiler_47.dll if present (often needed by Qt5Gui)
            qt_dlls = ['Qt5Core.dll', 'd3dcompiler_47.dll', 'Qt5Gui.dll', 'Qt5Widgets.dll']
            for dll_name in qt_dlls:
                dll_full_path = os.path.join(qt_bin_path, dll_name)
                if os.path.exists(dll_full_path):
                    print(f"[DEBUG] Pre-loading {dll_name} from {dll_full_path}...")
                    try:
                        ctypes.CDLL(dll_full_path)
                    except Exception as dll_err:
                         print(f"[WARNING] Failed to load {dll_name}: {dll_err}")
                else:
                    if dll_name not in ['d3dcompiler_47.dll']: # Optional ones
                        print(f"[WARNING] {dll_name} not found in {qt_bin_path}")
        except Exception as e:
            print(f"[ERROR] Failed to pre-load Qt DLLs: {e}")


def _configure_qt_highdpi():
    """在 ``QApplication`` 构造**之前**设置 Qt 高分屏属性。

    三件事，全部幂等、全部用 ``hasattr`` 守老版本 PyQt5：
      1. ``AA_EnableHighDpiScaling`` —— 让 Qt 自动按系统缩放系数放大坐标。
      2. ``AA_UseHighDpiPixmaps``    —— 让 QIcon/QPixmap 走物理像素渲染。
      3. ``setHighDpiScaleFactorRoundingPolicy(PassThrough)`` —— 显式锁定
         取整策略为 PassThrough。这点很关键：默认策略随 Qt 版本变化
         （Qt <5.14 不存在该枚举；5.14~5.15 某些构建默认 Floor，会把
         Windows 150% 缩放截断成 100%），导致同样的代码在不同 PyQt5
         版本下行为不一致。显式设成 PassThrough + ``hasattr`` 守护，
         新版本锁行为、老版本优雅跳过。

    原 launch_gui / _show_single_instance_dialog 各写一份重复的 try/setAttribute
    块（review 标的脆弱重复），收敛到这里一处。
    """
    try:
        if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
            QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
        if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
            QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
        # Qt 5.14+ 才有此枚举；hasattr 守护，老版本 PyQt5 直接跳过。
        if hasattr(QtCore.Qt, 'HighDpiScaleFactorRoundingPolicy'):
            QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
                QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
    except Exception:
        pass


def _show_single_instance_dialog():
    """显示单实例提示弹窗"""
    try:
        from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog

        # 设置高分屏支持（必须在 QApplication 创建之前）
        app = QtWidgets.QApplication.instance()
        if app is None:
            _configure_qt_highdpi()
            app = QtWidgets.QApplication(sys.argv)

        dialog = CustomConfirmDialog(
            parent=None,
            title="程序已运行",
            content="ComfyUI 启动器已在运行中。\n\n请检查任务栏或系统托盘。",
            buttons=[{"text": "确定", "role": "primary"}],
            default_index=0,
            theme_manager=None  # 使用默认深色主题
        )
        dialog.exec_()
    except Exception as e:
        # 如果弹窗失败，打印到控制台
        print(f"[单实例] 程序已运行: {e}")


class SplashScreen(QtWidgets.QWidget):
    """简单的启动画面"""

    def __init__(self):
        super().__init__()
        # Safe-UI 下用原生标题栏（不设 FramelessWindowHint + 不透明背景），
        # 避免 WA_TranslucentBackground 在部分核显驱动上闪退。
        import core.render_guard as _rg
        self._safe_ui = _rg.is_safe_ui()

        if self._safe_ui:
            self.setWindowFlags(
                QtCore.Qt.WindowStaysOnTopHint |
                QtCore.Qt.Tool
            )
        else:
            self.setWindowFlags(
                QtCore.Qt.FramelessWindowHint |
                QtCore.Qt.WindowStaysOnTopHint |
                QtCore.Qt.Tool
            )
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFixedSize(280, 160)

        # 主容器
        container = QtWidgets.QFrame(self)
        container.setObjectName("splashContainer")
        container.setGeometry(0, 0, 280, 160)
        if self._safe_ui:
            container.setStyleSheet("""
                QFrame#splashContainer {
                    background-color: #1F2937;
                    border: 1px solid #374151;
                    border-radius: 0px;
                }
                QLabel {
                    background: transparent;
                }
            """)
        else:
            container.setStyleSheet("""
                QFrame#splashContainer {
                    background-color: #1F2937;
                    border: 1px solid #374151;
                    border-radius: 12px;
                }
                QLabel {
                    background: transparent;
                }
            """)

        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(20, 25, 20, 20)
        layout.setSpacing(12)
        layout.setAlignment(QtCore.Qt.AlignCenter)

        # Logo - 使用项目图标
        logo_label = QtWidgets.QLabel()
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        logo_label.setFixedHeight(48)
        # 尝试加载图标文件
        try:
            from ui.assets_helper import resolve_asset
            icon_path = resolve_asset('rabbit.png')
            if icon_path.exists():
                pixmap = QtGui.QPixmap(str(icon_path))
                if not pixmap.isNull():
                    # 缩放图片，保持宽高比，高度固定48
                    scaled = pixmap.scaledToHeight(48, QtCore.Qt.SmoothTransformation)
                    logo_label.setPixmap(scaled)
                else:
                    logo_label.setText("🐰")
                    logo_label.setStyleSheet("font-size: 48px;")
            else:
                logo_label.setText("🐰")
                logo_label.setStyleSheet("font-size: 48px;")
        except Exception:
            logo_label.setText("🐰")
            logo_label.setStyleSheet("font-size: 48px;")
        layout.addWidget(logo_label, 0, QtCore.Qt.AlignHCenter)

        # 标题
        title_label = QtWidgets.QLabel("ComfyUI 启动器")
        title_label.setStyleSheet("font: bold 14pt 'Microsoft YaHei UI'; color: #F3F4F6;")
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title_label)

        # 加载提示
        self.status_label = QtWidgets.QLabel("正在加载...")
        self.status_label.setStyleSheet("font: 10pt 'Microsoft YaHei UI'; color: #9CA3AF;")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # 居中显示
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width() - self.width()) // 2,
                geo.y() + (geo.height() - self.height()) // 2
            )

    def set_status(self, text):
        self.status_label.setText(text)
        QtWidgets.QApplication.processEvents()


# -----------------------------------------------------------------------------

# 你的原 import 继续
from utils.common import SingletonLock
from ui_qt.qt_app import PyQtLauncher
from utils.logging import install_crash_reporting
import core.render_guard as render_guard

def launch_gui():
    """Launch the GUI application."""
    # 最早：崩溃留痕（包括锁竞争失败路径也要管）
    install_crash_reporting()

    lock = SingletonLock("comfyui_launcher_pyqt.lock")
    if not lock.acquire():
        # 单实例弹窗之前先让 safe-UI env 生效（弹窗继承 FramelessDraggableDialog，
        # 其 init 中会读 render_guard.is_safe_ui()）
        render_guard.prepare()
        _show_single_instance_dialog()
        sys.exit(0)

    # 拿到互斥：读 state + 可能升级 + 写 running 标记。
    # 必须在 _configure_qt_highdpi() 之前（QT_OPENGL 要在 Qt 初始化前设好）。
    # **不包在 try 块里**：让源码 AST 里 begin 和 highdpi 是两条独立顶层 stmt，
    # 避免被单 try 合并后 AST stmt 索引重合导致顺序判断失效（功能不变）。
    render_guard.begin()

    try:
        # 设置高分屏支持（必须在 QApplication 创建之前）
        _configure_qt_highdpi()

        # 创建 QApplication
        app = QtWidgets.QApplication(sys.argv)

        # 显示启动画面
        splash = SplashScreen()
        splash.show()
        QtWidgets.QApplication.processEvents()

        # 创建主窗口
        splash.set_status("正在初始化...")
        window = PyQtLauncher()

        # 关闭启动画面并显示主窗口
        splash.close()
        window.run()

        # 仅在 run() 正常返回后：清标记 / 写 clean 哨兵。
        # 放 try 内、finally 之外：构造抛异常时不调用，保留升级信号。
        render_guard.finish()

    finally:
        lock.release()


if __name__ == "__main__":
    launch_gui()