import os
import sys
import warnings

# Suppress sipPyTypeDict deprecation warning
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*sipPyTypeDict.*")

from PyQt5 import QtWidgets, QtCore, QtGui

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


def _show_single_instance_dialog():
    """显示单实例提示弹窗"""
    try:
        from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog

        # 设置高分屏支持（必须在 QApplication 创建之前）
        app = QtWidgets.QApplication.instance()
        if app is None:
            try:
                if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
                    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
                if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
                    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
            except Exception:
                pass
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

if __name__ == "__main__":
    lock = SingletonLock("comfyui_launcher_pyqt.lock")
    if not lock.acquire():
        _show_single_instance_dialog()
        sys.exit(0)

    try:
        # 设置高分屏支持（必须在 QApplication 创建之前）
        try:
            if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
                QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
            if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
                QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
        except Exception:
            pass

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

    finally:
        lock.release()