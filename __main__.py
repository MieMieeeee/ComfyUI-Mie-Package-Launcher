"""启动器入口（Nuitka / 开发模式共用）。

CLI 子命令（start/stop/status/...）由 core.cli.main 接管。
无 CLI 参数时启动 GUI。

CLI 路径会在最开始尝试 AttachConsole(-1) 把 stdout / stderr 挂回父进程的
console —— 这是 GUI subsystem 打包（Nuitka --windows-console-mode=disable
或 --windows-console-mode=attach）下唯一的可移植方案。
"""
import sys


def _attach_parent_console() -> None:
    r"""Win32: attach 当前进程到父进程的 console，让 stdout / stderr 可见。

    背景：Nuitka 用 --windows-console-mode=disable 打包时是 GUI subsystem，
    Python 的 stdout 指向 \\.\NUL 所以 PowerShell / cmd 看不到输出，cmd 的
    %errorlevel% 也读不到正确的退出码。AttachConsole(-1) (ATTACH_PARENT_PROCESS)
    会在父进程有 console 时挂上去；之后重新打开 CONOUT$ / CONERR$ 并替换
    sys.stdout / sys.stderr，否则 Python 的 file buffer 还在原位。

    - 仅在 sys.platform == "win32" 且父进程是命令行进程时真正起作用。
    - AttachConsole 失败（没有父 console / 已 attach / 拒绝访问）一律静默。
    - dev 模式（python.exe 是 console subsystem）调用也会"成功"但不需要重绑。
    """
    if sys.platform != 'win32':
        return

    import ctypes
    from ctypes import wintypes

    ATTACH_PARENT_PROCESS = wintypes.DWORD(-1)
    kernel32 = ctypes.windll.kernel32
    kernel32.AttachConsole.argtypes = [wintypes.DWORD]
    kernel32.AttachConsole.restype = wintypes.BOOL

    if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
        return

    # Attach 成功：把 stdout / stderr 重新指向控制台。
    try:
        import os
        conout_fd = os.open('CONOUT$', os.O_WRONLY | os.O_TEXT)
        conerr_fd = os.open('CONERR$', os.O_WRONLY | os.O_TEXT)
        sys.stdout = os.fdopen(conout_fd, 'w', buffering=1, encoding='utf-8', errors='replace')
        sys.stderr = os.fdopen(conerr_fd, 'w', buffering=1, encoding='utf-8', errors='replace')
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
        # 仅 CLI 需要挂父 console；GUI 路径调用会破坏 subprocess 标准句柄 → WinError 6
        _attach_parent_console()
        from core.cli.main import main as cli_main
        return cli_main()

    # 无 CLI args - 启动 GUI
    import comfyui_launcher_pyqt
    comfyui_launcher_pyqt.launch_gui()
    return 0


if __name__ == "__main__":
    sys.exit(main())
