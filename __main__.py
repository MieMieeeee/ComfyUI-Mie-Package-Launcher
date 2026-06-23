"""PyInstaller entry point.

CLI 子命令（start/stop/status/...）由 core.cli.main 接管。
无 CLI 参数时启动 GUI。
"""
import sys


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
        fn = ctypes.windll.user32.SetProcessDpiAwarenessContext
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_bool
        if fn(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass

    # 2) 退回 Per-Monitor V1（Win8.1+/Win10，via shcore）
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass

    # 3) 最后退回系统级 DPI 感知（Vista+）
    try:
        ctypes.windll.user32.SetProcessDpiAware()
    except Exception:
        pass


def _is_cli_invocation() -> bool:
    """argv 是否要进 CLI 路径。

    规则（按优先级）：
    1) 任何 -h/--help 出现 → CLI（让 argparse 打印帮助）
    2) 跳过全局 flag（--json/-v 等）后，剩下的第一个非 flag token 是已知
       subcommand → CLI
    3) 否则 → GUI
    """
    if len(sys.argv) < 2:
        return False
    # 规则 1：help flag
    for arg in sys.argv[1:]:
        if arg in ("-h", "--help"):
            return True
    # 规则 2：subcommand
    from core.cli.parser import SUBCOMMANDS
    for arg in sys.argv[1:]:
        if arg.startswith("-"):
            continue
        return arg in SUBCOMMANDS
    return False


def main() -> int:
    # 尽早声明 Per-Monitor DPI V2 感知（必须在 QApplication / 任何窗口创建之前）
    _enable_per_monitor_dpi_awareness()

    import os
    # 切到 exe 所在目录，让 launcher/config.json 永远能找到
    # （PyInstaller 打包后 sys.executable 是 exe 路径；开发模式下也是脚本路径）
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    try:
        os.chdir(exe_dir)
    except Exception:
        pass
    sys.path.insert(0, ".")

    if _is_cli_invocation():
        from core.cli.main import main as cli_main
        return cli_main()

    # 无 CLI args - 启动 GUI
    import comfyui_launcher_pyqt
    comfyui_launcher_pyqt.launch_gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
