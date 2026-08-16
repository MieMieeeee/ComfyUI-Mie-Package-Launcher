import os
import time
import threading
import subprocess
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request


def _post_to_ui(app, fn):
    """将函数投递到 UI 线程执行（线程安全）"""
    try:
        app.ui_post(fn)
    except Exception:
        try:
            app.root.after(0, fn)
        except Exception:
            pass


def _pump_output(source, target):
    """把子进程输出逐块写入日志，并立即 flush 供 LogTailer 实时读取。"""
    try:
        read_chunk = getattr(source, "read1", source.read)
        while True:
            chunk = read_chunk(4096)
            if not chunk:
                break
            target.write(chunk)
            target.flush()
    finally:
        try:
            source.close()
        except Exception:
            pass
        try:
            target.close()
        except Exception:
            pass


def _start_log_pump(pm, source, target):
    thread = threading.Thread(
        target=_pump_output, args=(source, target),
        name="ComfyUILogPump", daemon=True,
    )
    thread.start()
    pm._log_pump_thread = thread


def _build_tail_script() -> str:
    """生成 tail 日志文件的 PowerShell 脚本（纯 ASCII 内容）。

    编码声明三件套（PS 5.1 UTF-8 标准姿势，修 issue #94 中文 Windows mojibake）：
    - chcp 65001：切控制台 host 码页，box-drawing 字符(ComfyUI banner 的 ─ │ ╭ ╰)
      才能正确渲染。中文 Windows 默认 cp936，不切则 UTF-8 字节 mojibake。
      重定向到 $null，避免 "Active code page: 65001" 污染窗口首行。
    - [Console]::OutputEncoding = UTF8：控制台输出编码，影响 Get-Content 管道输出
      往 host 的字节流。
    - Get-Content -Encoding UTF8：覆盖 PS 5.1「无 BOM ⇒ 系统 ANSI」的默认读法，
      显式按 UTF-8 解码（comfyui.log 是无 BOM UTF-8）。
      附带好处：也让 -Wait 的流式读取在 UTF-8 多字节序列上正确切边界——
      pump 每次 flush 几 KB，若按 cp936 双字节切可能切在 UTF-8 码点中间，
      偶发损坏单行内容；显式 UTF-8 解码消除这个隐患。

    注：脚本内容是纯 ASCII，write_text(encoding="utf-8") 无 BOM 即可；
    若日后加入非 ASCII（如中文注释），需改用 BOM 或 Default 编码写，
    否则 PS 5.1 会按系统 ANSI 解析脚本本身。

    $OutputEncoding 是防御性的（只在管道传给外部程序时生效，本场景无害）。
    """
    return (
        "param([string]$LogPath)\n"
        "$host.UI.RawUI.WindowTitle = 'ComfyUI'\n"
        "chcp 65001 > $null\n"
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "Get-Content -LiteralPath $LogPath -Wait -Tail 80 -Encoding UTF8\n"
    )


def _start_console_log_window(pm, log_path):
    """打开独立 PowerShell 窗口，持续显示与实时日志页相同的日志文件。"""
    script = Path(os.environ.get("TEMP", ".")) / "comfyui_launcher_tail.ps1"
    script.write_text(_build_tail_script(), encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    pm._console_log_process = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(script), str(log_path)],
        creationflags=flags,
    )


def _spawn_process(pm, cmd, env, run_cwd, show_console=True, log_path=None):
    """spawn ComfyUI 子进程。

    参数:
        pm: 进程管理器,用于承接 Popen 句柄(pm.comfyui_process)
        cmd / env / run_cwd: Popen 入参
        show_console: 是否为 ComfyUI 弹出独立 conhost 窗口
        log_path: Optional[Path]
            - show_console=False 时:把 stdout/stderr 重定向到此文件(binary append),
              stderr 合并到 stdout,这样 LogViewerPage tail 这个文件就能拿到实时输出
            - show_console=True 时:维持原 conhost 行为,不接管 stdout/stderr

    stdin/stdout 保护(Windows 分支):
        Nuitka --windows-console-mode=attach 打包后,双击启动的 GUI 进程三个
        std handle 都可能是无效值/已关闭句柄。

        - show_console=True: 临时把三个 std handle 全部 SetStdHandle NULL,
          让 CREATE_NEW_CONSOLE 给子进程的新 console 分配全套有效 handle。
          *不能* 传 stdin= 参数——会触发 STARTF_USESTDHANDLES 把 stdout/stderr
          也强制成 NULL,ComfyUI print 立即崩(returncode=120,黑窗口无输出)。
        - show_console=False: CREATE_NO_WINDOW 不会自动分配 std handle,
          所以必须显式 stdin=DEVNULL(给个有效的 nul 句柄)+ stdout/stderr
          重定向到 log_fh。
        Unix 不受 Win32 句柄继承影响,继承父进程 stdin 即可。
    """
    log_fh = None
    capture_for_console = bool(show_console and log_path is not None)
    if log_path is not None:
        # 兼容 str 和 Path 两种入参
        log_path = Path(log_path)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        if log_path.exists() and log_path.stat().st_size > 0:
            with open(log_path, "rb") as existing:
                existing.seek(-1, os.SEEK_END)
                if existing.read(1) not in (b"\n", b"\r"):
                    with open(log_path, "ab") as boundary:
                        boundary.write(b"\n")
        log_fh = open(log_path, "ab")

    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        if show_console and not capture_for_console:
            si.wShowWindow = 1  # SW_SHOWNORMAL
            _k32 = None
            _si_h = _so = _se = None
            try:
                import ctypes as _ct
                _k32 = _ct.windll.kernel32
                _si_h = _k32.GetStdHandle(-10)
                _so = _k32.GetStdHandle(-11)
                _se = _k32.GetStdHandle(-12)
                _k32.SetStdHandle(-10, None)
                _k32.SetStdHandle(-11, None)
                _k32.SetStdHandle(-12, None)
            except Exception:
                pass
            try:
                pm.comfyui_process = subprocess.Popen(
                    cmd, env=env, cwd=run_cwd,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                    startupinfo=si,
                )
            finally:
                if _k32 is not None:
                    try:
                        _k32.SetStdHandle(-10, _si_h)
                        _k32.SetStdHandle(-11, _so)
                        _k32.SetStdHandle(-12, _se)
                    except Exception:
                        pass
        else:
            si.wShowWindow = subprocess.SW_HIDE
            popen_kwargs = dict(
                env=env,
                cwd=run_cwd,
                creationflags=subprocess.CREATE_NO_WINDOW,
                startupinfo=si,
                # 显式给 stdin 一个有效句柄(nul),避免继承 GUI exe 的无效 stdin
                # 句柄导致 WinError 6。ComfyUI 是 web 服务,启动后只通过 HTTP
                # /system_stats 探测就绪,从不读 stdin,DEVNULL 安全。
                # (与 utils/common.py:run_hidden 的 capture_output 路径一致)
                stdin=subprocess.DEVNULL,
            )
            if capture_for_console:
                popen_kwargs["stdout"] = subprocess.PIPE
                popen_kwargs["stderr"] = subprocess.STDOUT
            elif log_fh is not None:
                popen_kwargs["stdout"] = log_fh
                popen_kwargs["stderr"] = subprocess.STDOUT
            pm.comfyui_process = subprocess.Popen(cmd, **popen_kwargs)
            if capture_for_console:
                _start_log_pump(pm, pm.comfyui_process.stdout, log_fh)
                _start_console_log_window(pm, log_path)
    else:
        # Unix: stdin 继承父进程即可,Win32 的无效句柄继承问题在这里不存在
        popen_kwargs = dict(env=env, cwd=run_cwd)
        if log_fh is not None:
            popen_kwargs["stdout"] = log_fh
            popen_kwargs["stderr"] = subprocess.STDOUT
        pm.comfyui_process = subprocess.Popen(cmd, **popen_kwargs)

    # 保持文件 handle 引用,防止 Popen 内部 dup 完之前被 GC
    if log_fh is not None:
        try:
            pm._log_file_handle = log_fh
        except Exception:
            pass


def _check_system_stats(port: str, timeout: float = 1.5) -> bool:
    """通过 /system_stats API 检查 ComfyUI 是否完全启动"""
    try:
        url = f"http://127.0.0.1:{port}/system_stats"
        req = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "ComfyUI-Launcher",
        })
        with urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None)
            if code is None:
                try:
                    code = resp.getcode()
                except Exception:
                    code = None
            return code == 200
    except Exception:
        return False


def start(app, pm, cmd, env, run_cwd, log_path=None):
    app.big_btn.set_state("starting")
    app.big_btn.set_display("启动中…", "点击停止")
    app._launching = True

    # 读取是否显示命令行窗口的配置
    show_console = True
    try:
        if hasattr(app, "show_console"):
            show_console = app.show_console.get()
    except Exception:
        pass

    # 获取端口
    port = "8188"
    try:
        port = (app.custom_port.get() or "8188").strip()
    except Exception:
        pass

    def worker():
        try:
            try:
                app.logger.info("启动工作目录(cwd): %s", run_cwd)
            except Exception:
                pass

            _spawn_process(
                pm, cmd, env, run_cwd,
                show_console=show_console,
                log_path=log_path,
            )

            # 等待进程初始化，再开始轮询 API
            time.sleep(3)

            # 轮询 /system_stats 直到 ComfyUI 完全启动（最多 120 秒）
            deadline = time.time() + 120.0
            while time.time() < deadline:
                # 进程已退出
                if pm.comfyui_process and pm.comfyui_process.poll() is not None:
                    _post_to_ui(app, lambda: pm.on_start_failed("进程意外退出"))
                    return

                if _check_system_stats(port):
                    try:
                        app.logger.info("ComfyUI /system_stats 就绪，启动完成")
                    except Exception:
                        pass
                    _post_to_ui(app, pm.on_start_success)
                    return

                time.sleep(1.5)

            # 超时，但进程仍在运行 - 视为启动成功
            try:
                if pm.comfyui_process and pm.comfyui_process.poll() is None:
                    app.logger.warning("启动轮询超时，但进程仍在运行，视为启动成功")
                    _post_to_ui(app, pm.on_start_success)
                else:
                    _post_to_ui(app, lambda: pm.on_start_failed("启动超时"))
            except Exception:
                _post_to_ui(app, lambda: pm.on_start_failed("启动超时"))

        except Exception as e:
            msg = str(e)
            _post_to_ui(app, lambda m=msg: pm.on_start_failed(m))

    threading.Thread(target=worker, daemon=True).start()