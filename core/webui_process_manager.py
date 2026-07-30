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
import time
import subprocess
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


# 历史说明: 此处曾装过 3 道全局 hook (unraisablehook / sys.excepthook / sys.stderr
# 猴补丁) 想吞掉 subprocess._readerthread 在 Python 3.13 上读 cp1252 字节时的
# UnicodeDecodeError (CPython issue 118526 / 121633). 但子线程未捕获异常走的是
# threading.excepthook 而非 sys.excepthook, 所以那 3 道 hook 对目标无效, 徒增全局
# 副作用, 已删除. 子进程 Python 自身的 stdout encoding 由 spawn env 里的
# PYTHONIOENCODING=utf-8 + PYTHONLEGACYWINDOWSSTDIO=1 兜底 (见 build_webui_launch_params);
# 残留的 readerthread cp1252 warning 属已知 cosmetic 噪声.


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

        # 7. spawn. 用 PIPE + 自定义 drain 线程, 把 stdout 写到 log file.
        try:
            # win32 必须显式 CREATE_NO_WINDOW, 否则 GUI 模式下会弹黑色 cmd 窗口.
            # (Popen 不会自动加这个 flag; installer/dependencies 走 run_hidden 也各自显式设.)
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.webui_process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # 合并到 stdout
                cwd=run_cwd,
                env=env,
                close_fds=True,
                creationflags=creationflags,
            )

            # drain thread: 把 stdout 写到 log file
            log_path_for_drain = log_path
            def _drain_and_log():
                try:
                    proc = self.webui_process
                    if proc is None or proc.stdout is None:
                        return
                    for raw in proc.stdout:
                        try:
                            with open(log_path_for_drain, "ab") as lf:
                                lf.write(raw)
                        except Exception:
                            pass
                except Exception:
                    pass

            import threading as _threading
            _threading.Thread(
                target=_drain_and_log,
                daemon=True,
                name="webui_drain",
            ).start()
        except Exception as e:
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
                        capture_output=True, timeout=5,
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
                            capture_output=True, timeout=5,
                        )
                    else:
                        # POSIX: 没有 taskkill, 走 SIGTERM
                        import signal
                        os.kill(int(opid), signal.SIGTERM)
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
        """查询 WebUI 状态 (进程层 + HTTP 探活, 分开表达).

        语义分层 (跟 is_running / http_reachable 对齐):
        - running: 进程是否存在 (pidfile 活 / Popen 句柄活), 含 Flask 启动中.
        - http_reachable: 配置端口是否有服务在监听 (无条件探测, 可能是别的进程占用).
        四状态矩阵: 进程在+端口通=就绪; 进程在+端口不通=启动中;
                    进程不在+端口通=端口被占(非本进程); 进程不在+端口不通=未跑.
        """
        from core.cli.webui_pidfile import read as read_pidfile

        start_t = time.time()
        pd = read_pidfile(self._pidfile_path())
        try:
            cfg = getattr(self.app, "config", {}) or {}
            webui_options = cfg.get("webui_options", {}) if isinstance(cfg, dict) else {}
            port = int(webui_options.get("port") or 8199)
        except Exception:
            port = 8199

        process_running = self.is_running()
        # 无条件探测端口: 端口可能被其他进程占用, 不能假设"没进程就端口不通".
        http_ok = self.is_http_reachable(port, timeout=1.0)

        return {
            "running": process_running,
            "pid": pd.get("pid") if pd else (
                # pidfile 缺失时, 若 Popen 句柄活, 回退到句柄 PID (避免 running=True 但 pid=None)
                self.webui_process.pid if (self.webui_process is not None) else None
            ),
            "port": port,
            "url": f"http://127.0.0.1:{port}",
            "http_reachable": http_ok,
            "log_path": str(_webui_log_path(self.app)) if pd is not None else None,
            "since": pd.get("started_at") if pd else None,
            "env_id": pd.get("env_id") if pd else None,
        }
