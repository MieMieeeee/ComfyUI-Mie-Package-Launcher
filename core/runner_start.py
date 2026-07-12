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
    if show_console is False and log_path is not None:
        # 兼容 str 和 Path 两种入参
        log_path = Path(log_path)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        log_fh = open(log_path, "ab")

    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        if show_console:
            si.wShowWindow = 1  # SW_SHOWNORMAL
            # 临时把启动器的三个 std handle (stdin=-10, stdout=-11, stderr=-12)
            # 全部设为 NULL,spawn 后立即恢复。两个目的:
            #
            # 1) 防 WinError 6:Nuitka --windows-console-mode=attach 打包后,
            #    双击启动的 GUI 进程 std handle 是无效/已关闭句柄。Popen 内部
            #    _get_handles() 继承到无效句柄时,DuplicateHandle 抛
            #    WinError 6(句柄无效)。三个 handle 全清 NULL 后,CreateProcess
            #    在 CREATE_NEW_CONSOLE 下会给子进程的新 console 分配全套
            #    有效 std handle。
            #
            # 2) 防 conhost 黑窗口:CLI launcher 调 _attach_parent_console 后,
            #    stdout handle 是父 PowerShell 的有效(inheritable)句柄,
            #    ComfyUI 的 print 会跑到 PowerShell 而不是新弹的 conhost 窗口
            #    (窗口看着是黑的)。清成 NULL 后,Windows 给新 console 分配
            #    新 handle,输出正确进 conhost 窗口。
            #
            # 关键:这里 *不能* 传 stdin=DEVNULL。一旦传 stdin=,subprocess
            # 会设 STARTF_USESTDHANDLES,把 stdout/stderr 也强制为 NULL 句柄
            # (因为已经 SetStdHandle 清零),ComfyUI 第一次 print 就抛
            # [Errno 22] Invalid argument,进程立即以 returncode=120 退出,
            # conhost 窗口是黑的没有任何输出 —— 这正是之前的 bug。
            # 不传 stdin= 时,Windows 走 CREATE_NEW_CONSOLE 默认路径,自己给
            # 新 console 分配全套有效 std handle,不依赖 STARTF_USESTDHANDLES。
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
                    cmd,
                    env=env,
                    cwd=run_cwd,
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
            if log_fh is not None:
                popen_kwargs["stdout"] = log_fh
                popen_kwargs["stderr"] = subprocess.STDOUT
            pm.comfyui_process = subprocess.Popen(cmd, **popen_kwargs)
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