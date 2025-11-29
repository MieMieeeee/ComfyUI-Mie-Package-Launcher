"""
负责管理 ComfyUI 子进程的启动、停止、监控和状态刷新。
从 comfyui_launcher_enhanced.py 中提取。
"""

import os
import subprocess
import threading
import shlex #
import shutil #
import locale #
import re #
import socket #
from tkinter import messagebox
from pathlib import Path
from utils.common import run_hidden #
from core.probe import is_http_reachable, find_pids_by_port_safe, is_comfyui_pid
from core.kill import kill_pids

# 尝试导入 psutil，如果失败则在相关功能中回退
try:
    import psutil #
except ImportError:
    psutil = None

class ProcessManager:
    def __init__(self, app):
        """
        初始化进程管理器。
        :param app: 主 ComfyUILauncherEnhanced 实例的引用。
        """
        self.app = app
        self.comfyui_process = None

    def toggle_comfyui(self): #
        # 防抖与状态保护：启动进行中时忽略重复点击
        try:
            if getattr(self.app, '_launching', False):
                try:
                    self.app.logger.warning("忽略重复点击：正在启动中")
                except Exception:
                    pass
                return
        except Exception:
            pass
        try:
            self.app.logger.info("点击一键启动/停止")
        except Exception:
            pass
        # 判断是否已有运行中的 ComfyUI（包括外部启动的同端口实例）
        running = False
        try:
            if self.comfyui_process and self.comfyui_process.poll() is None:
                running = True
            else:
                running = is_http_reachable(self.app)
        except Exception:
            running = False
        if running:
            self.stop_comfyui()
        else:
            # 启动前追加端口占用检测：若任何进程占用目标端口，则避免重复启动
            try:
                port = (self.app.custom_port.get() or "8188").strip()
                pids = find_pids_by_port_safe(port)
            except Exception:
                pids = []
            if pids:
                try:
                    from tkinter import messagebox
                    # 若端口被占用，优先提示并提供直接打开网页的选项；默认取消启动
                    proceed_open = messagebox.askyesno(
                        "端口被占用",
                        f"检测到端口 {port} 已被占用 (PID: {', '.join(map(str, pids))}).\n\n是否直接打开网页而不启动新的实例?"
                    )
                except Exception:
                    proceed_open = True
                if proceed_open:
                    try:
                        self.app.open_comfyui_web()
                    except Exception:
                        pass
                    return
                else:
                    # 用户选择不直接打开网页：提供停止旧实例并启动新实例的选项
                    try:
                        restart = messagebox.askyesno(
                            "端口被占用",
                            "是否停止现有实例并用当前配置启动新的 ComfyUI?"
                        )
                    except Exception:
                        restart = False
                    if restart:
                        try:
                            self.stop_all_comfyui_instances()
                        except Exception:
                            pass
                        # 尝试启动新的实例
                        self.start_comfyui()
                        return
                    else:
                        # 取消启动，维持按钮状态为“启动”
                        try:
                            self.app.logger.warning("端口占用，用户取消重启: %s", port)
                        except Exception:
                            pass
                        return
            # 未占用则正常启动
            self.start_comfyui()

    def start_comfyui(self): #
        try:
            from core.launcher_cmd import build_launch_params
            cmd, env, run_cwd, py, main = build_launch_params(self.app)
            try:
                if getattr(self.app, 'services', None):
                    self.app.services.runtime.pre_start_up()
            except Exception:
                pass
            if not py.exists():
                self._show_error("错误", f"Python不存在: {py}")
                return
            if not main.exists():
                self._show_error("错误", f"主文件不存在: {main}")
                return
            try:
                from pathlib import Path as _P
                rver = run_hidden([str(py), "--version"], capture_output=True, text=True, timeout=0.8)
                if rver.returncode != 0:
                    self._show_error("错误", f"Python无法执行: {py}")
                    return
            except Exception as _e:
                self._show_error("错误", str(_e))
                return
            try:
                self.app.logger.info("启动命令: %s", " ".join(cmd))
            except Exception:
                pass
            try:
                self.app.logger.info("环境变量(HF_ENDPOINT): %s", env.get("HF_ENDPOINT", ""))
            except Exception:
                pass
            try:
                self.app.logger.info("环境变量(GITHUB_ENDPOINT): %s", env.get("GITHUB_ENDPOINT", ""))
            except Exception:
                pass
            from core.runner_start import start as run_start
            run_start(self.app, self, cmd, env, run_cwd)
        except Exception as e:
            msg = str(e)
            try:
                self._show_error("启动失败", msg)
            except Exception:
                pass
            # 同样使用默认参数绑定，避免在 after 回调中出现自由变量问题
            self.on_start_failed(msg)

    def on_start_success(self): #
        self.app._launching = False
        try:
            self.app.logger.info("ComfyUI 启动成功")
        except Exception:
            pass
        self.app.big_btn.set_state("running")
        self.app.big_btn.set_text("停止")
        try:
            mode = (self.app.browser_open_mode.get() or "default").strip()
        except Exception:
            try:
                mode = (self.app.config.get("launch_options", {}).get("browser_open_mode") or "default").strip()
            except Exception:
                mode = "default"
        if mode != "none":
            def _open_when_ready():
                try:
                    import time
                    for _ in range(40):
                        try:
                            if self._is_http_reachable():
                                break
                        except Exception:
                            pass
                        time.sleep(0.25)
                    try:
                        self.app.root.after(0, self.app.open_comfyui_web)
                    except Exception:
                        pass
                except Exception:
                    pass
            try:
                threading.Thread(target=_open_when_ready, daemon=True).start()
            except Exception:
                pass

    def on_start_failed(self, error): #
        self.app._launching = False
        try:
            self.app.logger.error("ComfyUI 启动失败: %s", error)
        except Exception:
            pass
        self.app.big_btn.set_state("idle")
        self.app.big_btn.set_text("一键启动")
        self.comfyui_process = None

    def stop_comfyui(self): #
        def _bg():
            try:
                from core.runner_stop import stop as run_stop
                killed = False
                try:
                    # 若未跟踪到子进程，先尝试全局关闭（适配外部启动实例）
                    if not (self.comfyui_process and self.comfyui_process.poll() is None):
                        try:
                            self.app.stop_all_comfyui_instances()
                        except Exception:
                            pass
                except Exception:
                    pass
                killed = run_stop(self.app, self)
                try:
                    if killed:
                        self.app.root.after(0, self.on_process_ended)
                    else:
                        self.app.root.after(0, self._refresh_running_status)
                    
                except Exception:
                    pass
            except Exception:
                pass
        try:
            threading.Thread(target=_bg, daemon=True).start()
        except Exception:
            pass
        return True

    def stop_comfyui_sync(self):
        try:
            from core.runner_stop import stop as run_stop
        except Exception:
            return False
        try:
            if not (self.comfyui_process and self.comfyui_process.poll() is None):
                try:
                    self.app.stop_all_comfyui_instances()
                except Exception:
                    pass
        except Exception:
            pass
        killed = run_stop(self.app, self)
        try:
            import time
            for _ in range(20):
                still = False
                try:
                    if self.comfyui_process and self.comfyui_process.poll() is None:
                        still = True
                    else:
                        from core.probe import is_http_reachable
                        still = is_http_reachable(self.app)
                except Exception:
                    still = False
                if not still:
                    break
                time.sleep(0.25)
        except Exception:
            pass
        try:
            running = False
            if self.comfyui_process and self.comfyui_process.poll() is None:
                running = True
            else:
                from core.probe import is_http_reachable
                running = is_http_reachable(self.app)
            if not running:
                self.on_process_ended()
            else:
                self._refresh_running_status()
        except Exception:
            pass
        return not running

    def _show_error(self, title, msg):
        try:
            if getattr(self.app, 'headless', False):
                try:
                    self.app.logger.error(f"{title}: {msg}")
                except Exception:
                    pass
                return
            messagebox.showerror(title, msg)
        except Exception:
            try:
                self.app.logger.error(f"{title}: {msg}")
            except Exception:
                pass

    def _find_pids_by_port_safe(self, port_str): #
        # 解析端口并通过 psutil 或 netstat 查找 PID 列表
        try:
            port = int(port_str)
        except Exception:
            return []
        # 优先使用 psutil
        if psutil:
            try:
                pids = set()
                try:
                    for conn in psutil.net_connections(kind='inet'): #
                        try:
                            if conn.laddr and conn.laddr.port == port:
                                if conn.status in ('LISTEN', 'ESTABLISHED'):  # 监听或连接中
                                    if conn.pid:
                                        pids.add(conn.pid)
                        except Exception:
                            pass
                except Exception:
                    pass
                if pids:
                    return list(pids)
            except Exception:
                pass
        # 回退到 netstat 解析（Windows）
        try:
            import subprocess
            import re
            cmd = ["netstat", "-ano"]
            # 使用系统首选编码并忽略解码错误，且隐藏子进程窗口
            preferred_enc = locale.getpreferredencoding(False) or "utf-8" #
            r = run_hidden(
                cmd,
                capture_output=True,
                text=True,
                encoding=preferred_enc,
                errors="ignore",
            )
            if r.returncode == 0 and r.stdout:
                pids = set()
                # 只认 TCP 的 LISTENING 或 ESTABLISHED，避免 TIME_WAIT/Close 等状态误判
                pattern_tcp = re.compile( #
                    rf"^\s*TCP\s+\S+:{port}\s+\S+:\S+\s+(LISTENING|ESTABLISHED)\s+(\d+)\s*$",
                    re.IGNORECASE,
                )
                for line in r.stdout.splitlines():
                    m = pattern_tcp.match(line)
                    if m:
                        try:
                            pids.add(int(m.group(2)))
                        except Exception:
                            pass
                # 不再统计 UDP（ComfyUI 使用 HTTP/TCP），以减少误判
                return list(pids)
        except Exception:
            pass
        return []

    def _is_comfyui_pid(self, pid: int) -> bool: # **修正后的代码块**
        # 通过 cmdline/exe/cwd 多重特征判断是否为 ComfyUI 相关进程
        if psutil:
            try:
                p = psutil.Process(pid) #
                # 成功获取进程对象 p，在其内部安全获取属性
                try:
                    cmdline = " ".join(p.cmdline()).lower()
                except Exception:
                    cmdline = ""
                try:
                    exe = (p.exe() or "").lower()
                except Exception:
                    exe = ""
                try:
                    cwd = (p.cwd() or "").lower()
                except Exception:
                    cwd = ""

                # 关键特征：main.py、comfyui 字样。
                if ("main.py" in cmdline and ("comfyui" in cmdline or "windows-standalone-build" in cmdline)):
                    return True
                if ("comfyui" in cmdline or "comfyui" in exe or "comfyui" in cwd):
                    return True
            except (psutil.NoSuchProcess, Exception):
                # 进程不存在或获取信息失败，跳过 psutil 检查
                pass

        # 回退：使用 wmic 获取命令行（在部分 Windows 环境可用）
        if os.name == 'nt':
            try:
                # 首次检测 wmic 是否存在并缓存结果；不存在则不再尝试，避免日志噪音
                try:
                    if getattr(self.app, "_wmic_available", None) is None:
                        # 确保 app 对象上有 _wmic_available 属性
                        self.app._wmic_available = bool(shutil.which("wmic")) #
                except Exception:
                    self.app._wmic_available = False

                if self.app._wmic_available:
                    # 避免路径访问异常导致整个方法中断
                    try:
                        paths = self.app.config.get("paths", {})
                        base = Path(paths.get("comfyui_root") or ".").resolve()
                        comfy_root = str((base / "ComfyUI").resolve()).lower()
                    except Exception:
                        comfy_root = None
                        
                    preferred_enc = locale.getpreferredencoding(False) or "utf-8" #
                    try:
                        r = run_hidden([ #
                            "wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/format:list"
                        ], capture_output=True, text=True, encoding=preferred_enc, errors="ignore")
                        if r.returncode == 0 and r.stdout:
                            out = r.stdout.lower()
                            if ("comfyui" in out) or ("main.py" in out) or (comfy_root and comfy_root in out):
                                return True
                    except FileNotFoundError:
                        # 运行期确认 wmic 不存在，则标记为不可用，后续不再尝试
                        self.app._wmic_available = False
                    except Exception:
                        pass
            except Exception:
                pass

        return False

    def _kill_pids(self, pids): #
        # 优先使用 psutil 优雅终止，失败则回退到 taskkill
        try:
            self.app.logger.info("准备终止进程列表: %s", ", ".join(map(str, pids)))
        except Exception:
            pass
        killed_any = False
        if psutil:
            try:
                procs_to_wait = []
                for pid in pids:
                    try:
                        p = psutil.Process(pid) #
                        p.terminate()
                        procs_to_wait.append(p)
                        try:
                            self.app.logger.info("发送terminate信号: PID=%s", str(pid))
                        except Exception:
                            pass
                    except Exception:
                        pass
                if procs_to_wait:
                    # 批量等待
                    gone, alive = psutil.wait_procs(procs_to_wait, timeout=3) #
                    if gone:
                        killed_any = True
                        try:
                            self.app.logger.info("psutil 等待结束：已终止 %d 个进程", len(gone))
                        except Exception:
                            pass
                    # 对未结束的进程发送 SIGKILL (kill)
                    for p in alive:
                        try:
                            p.kill()
                            killed_any = True
                        except Exception:
                            pass
            except Exception:
                pass
        # 对未结束的进程使用 taskkill 强制终止（Windows）
        if os.name == 'nt':
            try:
                for pid in pids:
                    run_hidden(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True) #
                killed_any = True
                try:
                    self.app.logger.info("taskkill 强制终止：%s", ", ".join(map(str, pids)))
                except Exception:
                    pass
            except Exception:
                pass
        if not killed_any:
            try:
                self.app.logger.error("无法终止目标进程：%s", ", ".join(map(str, pids)))
            except Exception:
                pass
            raise RuntimeError("无法终止目标进程")

    def _is_http_reachable(self) -> bool: #
        try:
            from core.probe import is_http_reachable
            return is_http_reachable(self.app)
        except Exception:
            return False

    def _refresh_running_status(self): #
        # 根据进程与端口探测结果统一刷新按钮状态
        try:
            running = False
            if self.comfyui_process and self.comfyui_process.poll() is None:
                running = True
            else:
                running = is_http_reachable(self.app)
            if running:
                self.app.big_btn.set_state("running")
                self.app.big_btn.set_text("停止")
            else:
                self.app.big_btn.set_state("idle")
                self.app.big_btn.set_text("一键启动")
        except Exception:
            pass

    def refresh_running_status_async(self): #
        def _bg():
            try:
                running = False
                try:
                    if self.comfyui_process and self.comfyui_process.poll() is None:
                        running = True
                    else:
                        running = is_http_reachable(self.app)
                except Exception:
                    running = False
                def _ui():
                    try:
                        if running:
                            self.app.big_btn.set_state("running")
                            self.app.big_btn.set_text("停止")
                        else:
                            self.app.big_btn.set_state("idle")
                            self.app.big_btn.set_text("一键启动")
                    except Exception:
                        pass
                try:
                    self.app.root.after(0, _ui)
                except Exception:
                    pass
            except Exception:
                pass
        try:
            import threading
            threading.Thread(target=_bg, daemon=True).start()
        except Exception:
            pass

    def monitor_process(self): #
        from core.runner import monitor
        monitor(self.app, self)

    def on_process_ended(self): #
        try:
            self.app.logger.info("ComfyUI 进程结束")
        except Exception:
            pass
        self.comfyui_process = None
        # 根据端口探测决定显示“停止”或“一键启动”
        try:
            if is_http_reachable(self.app):
                self.app.big_btn.set_state("running")
                self.app.big_btn.set_text("停止")
            else:
                self.app.big_btn.set_state("idle")
                self.app.big_btn.set_text("一键启动")
        except Exception:
            self.app.big_btn.set_state("idle")
            self.app.big_btn.set_text("一键启动")
            
    def stop_all_comfyui_instances(self) -> bool: #
        """尝试关闭所有检测到的 ComfyUI 实例（包括非本启动器启动的）。

        返回 True 表示至少成功终止一个进程。
        """
        killed = False
        pids = set()
        # 1) 通过端口查找（当前自定义端口）
        try:
            port = (self.app.custom_port.get() or "8188").strip()
            for pid in find_pids_by_port_safe(port):
                try:
                    if is_comfyui_pid(self.app, pid):
                        pids.add(pid)
                except Exception:
                    pass
        except Exception:
            pass
        # 2) 通过进程枚举查找（可能是不同端口或手动启动）
        if psutil:
            try:
                for p in psutil.process_iter(attrs=["pid"]): #
                    pid = p.info.get("pid")
                    if not pid:
                        continue
                    try:
                        if is_comfyui_pid(self.app, int(pid)):
                            pids.add(int(pid))
                    except Exception:
                        pass
            except Exception:
                # 若无 psutil，可忽略此步骤（已有端口方法与回退的 taskkill）
                pass
        # 移除自身跟踪的句柄，避免重复
        try:
            if self.comfyui_process and self.comfyui_process.poll() is None:
                pids.discard(self.comfyui_process.pid)
        except Exception:
            pass
        if not pids:
            try:
                port = (self.app.custom_port.get() or "8188").strip()
            except Exception:
                port = "8188"
            try:
                cand = find_pids_by_port_safe(port)
            except Exception:
                cand = []
            for pid in cand:
                try:
                    pids.add(int(pid))
                except Exception:
                    pass
        if pids:
            try:
                kill_pids(self.app, list(pids))
                killed = True
            except Exception:
                try:
                    self.app.logger.error("在 stop_all_comfyui_instances 中统一终止进程失败")
                except Exception:
                    pass

        return killed