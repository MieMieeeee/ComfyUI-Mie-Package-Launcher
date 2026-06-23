"""PyInstaller entry point - parses CLI args before any PyQt imports."""

import sys
import argparse

# Global process storage for CLI mode
_comfyui_process = None


def _prepare_cli_output(force: bool = False) -> None:
    if sys.platform != "win32" or (not force and not getattr(sys, "frozen", False)):
        return

    import ctypes

    ctypes.windll.kernel32.AllocConsole()
    sys.stdout = open("CONOUT$", "w")
    sys.stderr = open("CONOUT$", "w")


def _enable_per_monitor_dpi_awareness() -> None:
    """在 Qt 或任何窗口创建前声明进程为 Per-Monitor DPI V2 感知。

    必须在 QApplication 构造之前调用，使 Qt 的高 DPI 缩放按每块显示器独立生效，
    解决多显示器（不同缩放比例）间拖动窗口时模糊/错位的问题。全程失败则静默，
    不影响启动；Qt 自身的 AA_EnableHighDpiScaling 会在此基础上继续工作。
    """
    if sys.platform != "win32":
        return

    import ctypes

    # 1) 优先 Per-Monitor V2（Win10 1703+）
    try:
        # DPI_AWARENESS_CONTEXT 是 HANDLE（指针宽），64 位下必须显式 c_void_p
        # 避免把 PER_MONITOR_AWARE_V2 = -4 当成 int 截断成无意义值
        fn = ctypes.windll.user32.SetProcessDpiAwarenessContext
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_bool
        if fn(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass

    # 2) 退回 Per-Monitor V1（Win8.1+/Win10，via shcore）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return
    except Exception:
        pass

    # 3) 最后退回系统级 DPI 感知（Vista+）
    try:
        ctypes.windll.user32.SetProcessDpiAware()
    except Exception:
        pass


def main():
    global _comfyui_process

    # 尽早声明 Per-Monitor DPI V2 感知（必须在 QApplication / 任何窗口创建之前）
    _enable_per_monitor_dpi_awareness()

    # Add project root to path for imports
    sys.path.insert(0, ".")

    parser = argparse.ArgumentParser(prog="comfyui-launcher")
    parser.add_argument("--start", action="store_true", help="Start the launcher")
    parser.add_argument("--stop", action="store_true", help="Stop the launcher")
    parser.add_argument("--status", action="store_true", help="Check launcher status")

    args = parser.parse_args()

    if args.start:
        import os

        # Save original cwd before changing directory
        original_cwd = os.getcwd()
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        os.chdir(exe_dir)

        _prepare_cli_output(force=True)

        from headless_app import HeadlessAppContext
        from core.cli_start import cli_start

        # Use original cwd so config is found from where exe was run
        app = HeadlessAppContext(original_cwd)
        _comfyui_process = cli_start(app)

        if _comfyui_process is not None:
            print(f"ComfyUI started with PID {_comfyui_process.pid}")
            sys.exit(0)
        else:
            print("Failed to start ComfyUI")
            sys.exit(1)

    elif args.stop:
        import os

        original_cwd = os.getcwd()
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        os.chdir(exe_dir)

        _prepare_cli_output(force=True)

        from headless_app import HeadlessAppContext
        from core.runner_stop import stop

        app = HeadlessAppContext(original_cwd)

        # Create a simple PM-like object with comfyui_process attribute
        class PM:
            def __init__(self, process):
                self.comfyui_process = process

        pm = PM(_comfyui_process)
        killed = stop(app, pm)

        if killed:
            print("ComfyUI stopped")
            _comfyui_process = None
            sys.exit(0)
        else:
            print("Failed to stop ComfyUI (process may not be running)")
            sys.exit(1)

    elif args.status:
        import os

        original_cwd = os.getcwd()
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        os.chdir(exe_dir)

        from headless_app import HeadlessAppContext
        from core.probe import is_http_reachable

        app = HeadlessAppContext(original_cwd)
        running = is_http_reachable(app)

        if running:
            print("ComfyUI is running")
            sys.exit(0)
        else:
            print("ComfyUI is not running")
            sys.exit(1)

    # No CLI args - launch GUI mode
    # Change to exe directory so config files are found correctly
    import os

    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    os.chdir(exe_dir)

    # Import and run the original PyQt GUI application
    import comfyui_launcher_pyqt

    comfyui_launcher_pyqt.launch_gui()


if __name__ == "__main__":
    main()
