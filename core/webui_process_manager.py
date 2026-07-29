"""WebUI 进程管理 (spawn / stop / probe).

不走 core.runner_start (跟 ComfyUI start_page / big_btn 绑太紧), 也不走
core.process_manager (跟 ComfyUI 自带的 browser_open / version_workers 耦合).
本模块是独立的轻量包装:
  - spawn: subprocess.Popen, stdout/stderr 进 log file
  - stop: pidfile + psutil / taskkill
  - probe: pidfile + is_http_reachable
  - pidfile: 独立 webui.pid, 跟 comfyui.pid 互不干扰

放在 core/ 是因为它不依赖 PyQt5, 可以在 CLI + GUI 两侧复用.
GUI 层 (ui_qt.pages.webui_page) 只是绑定 UI 状态机, 真正干活交给本模块.
"""
from __future__ import annotations

import os
import sys
import time
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from utils.common import run_hidden


# --- 兼容缺 psutil 的环境 ---
try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:
    psutil = None  # type: ignore
    _HAS_PSUTIL = False


def _webui_log_path(app: Any) -> Path:
    """WebUI 启动器写的日志文件 (<cwd>/launcher/webui.log)."""
    try:
        cwd = Path(getattr(app, "_cwd", ".") or ".").resolve()
    except Exception:
        cwd = Path(".").resolve()
    return cwd / "launcher" / "webui.log"


_UNRAISABLE_HOOK_INSTALLED = False

def _install_unraisable_hook() -> None:
    """把 Python 3.13 的 _readerthread UnicodeDecodeError 吞掉.

    subprocess 在 3.13 上读 stdout/stderr 时按 UTF-8 strict 解码,
    Windows cp1252 字节 (webui print 出来的中文/emoji) 会触发
    UnicodeDecodeError. 这是 Python bug (issue 118526 + 121633),
    跟我们 launcher 本身无关. 走 3 道防线: unraisablehook (async 类) + excepthook (thread 类)
    + stderr 过滤 (subprocess 直接 print 出来的线程 traceback).
    """
    global _UNRAISABLE_HOOK_INSTALLED
    if _UNRAISABLE_HOOK_INSTALLED:
        return
    _UNRAISABLE_HOOK_INSTALLED = True
    import sys as _sys
    prev = _sys.unraisablehook
    def _hook(unraisable):
        try:
            ex = unraisable.exc_value
        except Exception:
            ex = None
        msg = str(ex) if ex else ""
        if isinstance(ex, UnicodeDecodeError):
            # 只吞 cp1252 / utf-8 解码类的 unraisable
            return
        # 其它走原 hook
        try:
            if prev:
                prev(unraisable)
        except Exception:
            pass
    _sys.unraisablehook = _hook


def _install_excepthook() -> None:
    """sys.excepthook: 过滤 subprocess._readerthread 的 UnicodeDecodeError 输出.

    Python 3.13 线程里的 uncaught exception 走 sys.excepthook.
    让 _readerthread 那个 cp1252 字节异常安静下来 (unraisablehook 不够, 还得拦 excepthook).
    """
    import sys as _sys
    prev = _sys.excepthook
    def _hook(exc_type, exc_value, exc_tb):
        if exc_type is UnicodeDecodeError:
            return  # 吞
        try:
            prev(exc_type, exc_value, exc_tb)
        except Exception:
            pass
    _sys.excepthook = _hook


def _install_stderr_filter() -> None:
    """把 sys.stderr 整个换成有过滤的 wrapper, 屏蔽 subprocess._readerthread
    UnicodeDecodeError traceback (Python 3.13 内部直接 print, 走 sys.stderr.write
    钩子拦不住).

    做法: 包一层 TextIO-like, 写时检测 _readerthread + UnicodeDecodeError 模式,
    命中时吞掉 (返 0). 其它照常 write.
    """
    import sys as _sys
    _real_stderr = _sys.stderr

    class _FilteredStderr:
        def __init__(self, real):
            self._real = real
            self._in_traceback = False
            self._line = 0

        def _should_suppress(self, s):
            try:
                text = s if isinstance(s, str) else s.decode("utf-8", errors="replace")
            except Exception:
                return False
            if text.startswith("Exception in thread") and ("_readerthread" in text or "UnicodeDecodeError" in text):
                self._in_traceback = True
                self._line = 0
                return True
            if self._in_traceback:
                self._line += 1
                if text.strip() == "" or text.startswith("Exception in thread") or self._line > 80:
                    self._in_traceback = False
                return True
            return False

        def write(self, s):
            if self._should_suppress(s):
                return 0
            return self._real.write(s)

        def flush(self):
            try:
                self._real.flush()
            except Exception:
                pass

        def __getattr__(self, name):
            # 其他属性 (fileno, isatty, etc) 透传给真的 stderr
            return getattr(self._real, name)

    _sys.stderr = _FilteredStderr(_real_stderr)


# 模块加载时立即生效
_install_unraisable_hook()
_install_excepthook()
_install_stderr_filter()



class WebuiProcessManager:
    """WebUI 子进程管理. 一个 app 对应一个实例.

    跟 ProcessManager (ComfyUI) 完全独立, 不共享 pidfile / log / process handle.
    """

    def __init__(self, app: Any):
        self.app = app
        self.webui_process: Optional[subprocess.Popen] = None
        self._stopping = False
        self._log_file_handle: Optional[Any] = None

    # ---------------- pidfile ----------------
    def _pidfile_path(self) -> Path:
        try:
            cwd = Path(getattr(self.app, "_cwd", ".") or ".").resolve()
        except Exception:
            cwd = Path(".").resolve()
        from core.cli.webui_pidfile import default_path
        return default_path(cwd)

    def _pidfile_data(self) -> Optional[dict]:
        from core.cli.webui_pidfile import read
        return read(self._pidfile_path())

    # ---------------- probe ----------------
    def is_running(self, *, timeout: float = 1.5) -> bool:
        """综合判定: Popen 句柄在 + webui 进程 PID 活 + 端口可达 (任一即可, 优先级 Popen > PID > HTTP)."""
        try:
            if self.webui_process and self.webui_process.poll() is None:
                return True
        except Exception:
            pass
        pd = self._pidfile_data()
        if pd is None:
            return False
        # PID 活但 HTTP 没就绪也算 running (Flask 启动慢)
        return True

    def is_http_reachable(self, port: int | None = None, timeout: float = 1.5) -> bool:
        """对 webui 端口做最小 HTTP 探活 (GET / 返 200)."""
        try:
            if port is None:
                cfg = getattr(self.app, "config", {}) or {}
                webui_options = cfg.get("webui_options", {}) if isinstance(cfg, dict) else {}
                port = int(webui_options.get("port") or "8199")
            import socket
            # 先 TCP connect, 避免 urllib 对不监听端口拖 timeout
            with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
                pass
            # TCP 通再做 HTTP probe
            from urllib.request import urlopen
            try:
                resp = urlopen(f"http://127.0.0.1:{int(port)}/", timeout=timeout)
                return 200 <= getattr(resp, "status", 200) < 500
            except Exception:
                # TCP 通但 HTTP 还没好 (Flask 启动中) — 仍视为 running
                return True
        except Exception:
            return False

    # ---------------- start ----------------
    def start_webui(self, *, env_id: str | None = None, timeout: float = 60.0) -> dict:
        """同步启动 WebUI. 阻塞到 http 200 或 timeout.

        返: {"ok": bool, "pid": int|None, "port": int, "url": str,
              "elapsed_sec": float, "error": str|None}
        """
        from core.webui_launcher_cmd import build_webui_launch_params
        from core.cli.webui_pidfile import write as write_pidfile

        start_t = time.time()
        # 1. 已在跑 — 直接返回
        existing = self._pidfile_data()
        if existing is not None:
            port = int(existing.get("port") or 0)
            return {
                "ok": True,
                "pid": existing.get("pid"),
                "port": port,
                "url": f"http://127.0.0.1:{port}",
                "elapsed_sec": time.time() - start_t,
                "error": None,
                "already_running": True,
                "env_id": existing.get("env_id"),
            }

        # 2. 构造命令
        try:
            cmd, env, run_cwd, py, webui_root = build_webui_launch_params(self.app, env_id=env_id)
        except Exception as e:
            return {
                "ok": False, "pid": None, "port": 0, "url": "",
                "elapsed_sec": time.time() - start_t,
                "error": "build_webui_launch_params 失败: " + str(e),
            }

        # 3. 路径校验
        if not Path(py).exists():
            return {
                "ok": False, "pid": None, "port": 0, "url": "",
                "elapsed_sec": time.time() - start_t,
                "error": "python 不可执行: " + str(py),
            }
        if not webui_root.exists():
            return {
                "ok": False, "pid": None, "port": 0, "url": "",
                "elapsed_sec": time.time() - start_t,
                "error": "WebUI 目录不存在: " + str(webui_root),
            }
        # flask_app 入口校验
        flask_app = webui_root / "app" / "flask_app.py"
        if not flask_app.exists():
            return {
                "ok": False, "pid": None, "port": 0, "url": "",
                "elapsed_sec": time.time() - start_t,
                "error": "WebUI 入口缺失: " + str(flask_app),
            }

        # 4. 端口 (从 config 推)
        try:
            cfg = getattr(self.app, "config", {}) or {}
            webui_options = cfg.get("webui_options", {}) if isinstance(cfg, dict) else {}
            port = int(webui_options.get("port") or 8199)
        except Exception:
            port = 8199

        # 5. 端口占用检查 — 占用则 abort
        try:
            from core.probe import find_pids_by_port_safe
            occupancy = find_pids_by_port_safe(str(port))
        except Exception:
            occupancy = []
        if occupancy:
            return {
                "ok": False, "pid": None, "port": port, "url": "",
                "elapsed_sec": time.time() - start_t,
                "error": f"端口 {port} 已被占用 (PID: {', '.join(map(str, occupancy))}),"
                          " 请先停掉那个进程或改 webui_options.port",
                "port_in_use": True,
            }

        # 6. log file: 走 subprocess.PIPE + 自定义 pump 线程, 避免 Python 3.13
        # _readerthread 在直接给 fd 时按 UTF-8 解码老日志 (cp1252) 报 UnicodeDecodeError.
        log_path = _webui_log_path(self.app)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # truncate 老日志 (避免 cp1252 字节残留被 Popen 内部读时炸)
        try:
            if log_path.exists():
                log_path.unlink()
        except Exception:
            pass
        # header 写一行 spawn 时间 + cmd, 方便查日志时一眼定位
        try:
            with open(log_path, "a", encoding="utf-8", errors="replace") as hf:
                hf.write("=== webui spawn at " + datetime.now().isoformat() + " ===\n")
                hf.write("cmd: " + " ".join(cmd) + "\n")
                hf.write("cwd: " + str(run_cwd) + "\n")
                hf.write("\n")
        except Exception:
            pass

        # 7. spawn (binary file handle, 但 Python 3.13 仍会起 _readerthread 走 utf-8 解码)
        # 解决办法: 用 subprocess.run + 显式 stdin DEVNULL / stderr STDOUT (合并到 stdout),
        # 外加自定义 Popen 自己控 stdout. 实际效果一样但绕开 _readerthread.
        try:
            log_fh_for_proc = open(log_path, "ab", buffering=0)
            self._log_file_handle = log_fh_for_proc
            kwargs = {
                "stdin": subprocess.DEVNULL,
                "stdout": log_fh_for_proc,
                "stderr": subprocess.STDOUT,  # 合并, 走 stdout 同一个 fd
                "cwd": run_cwd,
                "env": env,
                "close_fds": True,  # 关其他继承 fd, 避免 stdin 泄漏
            }
            if os.name == "nt":
                kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            # 关键: 直接走 _execute_child 跳过 _readerthread
            # 实际上 Popen 一定会起 _readerthread, 改为不用 stdout fd, 用 PIPE 后立即 close
            # 这让 _readerthread 立刻 EOF 退出, 不会喂入 cp1252 字节踩 utf-8 解码陷阱
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.STDOUT
            self.webui_process = subprocess.Popen(cmd, **kwargs)

            # 立即 drain pipe: 关 stdout 后 _readerthread 走 EOF 分支, 干净退出
            # 同时把读到的东西 (主要是 cp1252/raw bytes) 写到 log file
            def _drain_and_log():
                try:
                    assert self.webui_process.stdout is not None
                    for raw in self.webui_process.stdout:
                        try:
                            log_fh_for_proc.write(raw)
                        except Exception:
                            pass
                except Exception:
                    pass
                finally:
                    try:
                        log_fh_for_proc.close()
                    except Exception:
                        pass

            import threading as _threading
            _threading.Thread(target=_drain_and_log, daemon=True, name="webui_drain").start()
            # 立刻关 stdout pipe, 让 _readerthread 走 EOF clean exit
            try:
                self.webui_process.stdout.close()
            except Exception:
                pass
        except Exception as e:
            try:
                log_fh_for_proc.close()
            except Exception:
                pass
            self._log_file_handle = None
            return {
                "ok": False, "pid": None, "port": port, "url": "",
                "elapsed_sec": time.time() - start_t,
                "error": "spawn 失败: " + str(e),
            }

        pid = self.webui_process.pid

        # 8. 写 pidfile (env_id 解析)
        try:
            from config.migrations import resolve_active_paths_for_webui
            cfg = getattr(self.app, "config", {}) or {}
            pw = resolve_active_paths_for_webui(cfg if isinstance(cfg, dict) else {})
            env_id_eff = pw.get("env_id")
        except Exception:
            env_id_eff = None
        try:
            write_pidfile(self._pidfile_path(), pid, port, log_path, env_id=env_id_eff)
        except Exception as e:
            try:
                self.app.logger.warning("写 webui pidfile 失败: %s", e)
            except Exception:
                pass

        # 9. 阻塞等 HTTP 就绪
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + timeout
        ready = False
        while time.time() < deadline:
            if self.webui_process.poll() is not None:
                # 进程已退出
                break
            if self.is_http_reachable(port=port, timeout=1.0):
                ready = True
                break
            time.sleep(0.5)

        if not ready:
            try:
                self.app.logger.warning("WebUI 启动超时 (%.1fs)", timeout)
            except Exception:
                pass

        return {
            "ok": ready,
            "pid": pid,
            "port": port,
            "url": url,
            "elapsed_sec": time.time() - start_t,
            "error": None if ready else "WebUI 启动超时 (未在指定时间内 HTTP 就绪)",
            "env_id": env_id_eff,
            "log_path": str(log_path),
        }

    # ---------------- stop ----------------
    def stop_webui(self, *, timeout: float = 8.0, force: bool = False) -> dict:
        """同步停止 WebUI. 幂等: 未跑返 ok=True.

        返: {"ok": bool, "pid": int|None, "elapsed_sec": float, "error": str|None}
        """
        start_t = time.time()
        from core.cli.webui_pidfile import clear as clear_pidfile, read as read_pidfile

        pd = read_pidfile(self._pidfile_path())
        pid = None
        if pd:
            pid = pd.get("pid")

        # 1. Popen 句柄还在 -> 直接 terminate
        popen_killed = False
        try:
            if self.webui_process and self.webui_process.poll() is None:
                pid = self.webui_process.pid
                try:
                    self.webui_process.terminate()
                except Exception:
                    pass
                # 等到真的退出
                try:
                    self.webui_process.wait(timeout=timeout)
                    popen_killed = True
                except Exception:
                    pass
                if not popen_killed or force:
                    try:
                        self.webui_process.kill()
                        self.webui_process.wait(timeout=2)
                        popen_killed = True
                    except Exception:
                        pass
        except Exception:
            pass

        # 2. 通过 PID taskkill (兜底, 处理外部启动 / 句柄丢失)
        port_killed = False
        if pid and not popen_killed:
            try:
                if os.name == "nt":
                    r = run_hidden(
                        ["taskkill", "/PID", str(pid), "/F"],
                        capture_output=True, text=True, timeout=5,
                    )
                    port_killed = (r.returncode == 0)
                else:
                    import signal
                    os.kill(int(pid), signal.SIGTERM)
                    port_killed = True
            except Exception:
                pass

        # 3. 兜底: 按端口杀 (如果 pidfile 失效)
        if not popen_killed and not port_killed:
            try:
                cfg = getattr(self.app, "config", {}) or {}
                webui_options = cfg.get("webui_options", {}) if isinstance(cfg, dict) else {}
                port = int(webui_options.get("port") or 8199)
            except Exception:
                port = 8199
            try:
                from core.probe import find_pids_by_port_safe
                occupy = find_pids_by_port_safe(str(port))
            except Exception:
                occupy = []
            for opid in occupy:
                try:
                    if os.name == "nt":
                        run_hidden(
                            ["taskkill", "/PID", str(opid), "/F"],
                            capture_output=True, text=True, timeout=5,
                        )
                    port_killed = True
                except Exception:
                    pass

        # 4. 清 pidfile
        try:
            clear_pidfile(self._pidfile_path())
        except Exception:
            pass

        # 5. 关 log handle
        try:
            if self._log_file_handle is not None:
                self._log_file_handle.flush()
                self._log_file_handle.close()
                self._log_file_handle = None
        except Exception:
            pass

        self.webui_process = None

        return {
            "ok": True,
            "pid": pid,
            "elapsed_sec": time.time() - start_t,
            "error": None,
            "killed": popen_killed or port_killed,
        }

    # ---------------- status ----------------
    def status(self) -> dict:
        """查询 WebUI 状态 (pidfile + http probe)."""
        from core.cli.webui_pidfile import read as read_pidfile
        import socket

        start_t = time.time()
        pd = read_pidfile(self._pidfile_path())
        try:
            cfg = getattr(self.app, "config", {}) or {}
            webui_options = cfg.get("webui_options", {}) if isinstance(cfg, dict) else {}
            port = int(webui_options.get("port") or 8199)
        except Exception:
            port = 8199

        http_ok = False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                http_ok = True
        except Exception:
            http_ok = False

        running = (pd is not None) and http_ok
        return {
            "running": running,
            "pid": pd.get("pid") if pd else None,
            "port": port,
            "url": f"http://127.0.0.1:{port}",
            "http_reachable": http_ok,
            "log_path": str(_webui_log_path(self.app)) if pd is not None else None,
            "since": pd.get("started_at") if pd else None,
            "env_id": pd.get("env_id") if pd else None,
        }
