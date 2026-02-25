import os
import sys

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

# -----------------------------------------------------------------------------

# 你的原 import 继续
from utils.common import SingletonLock
from ui_qt.qt_app import PyQtLauncher

if __name__ == "__main__":
    lock = SingletonLock("comfyui_launcher_pyqt.lock")
    if not lock.acquire():
        sys.exit(0)
    try:
        app = PyQtLauncher()
        app.run()
    finally:
        lock.release()