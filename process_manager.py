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
from utils import run_hidden #

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
                running = self._is_http_reachable()
        except Exception:
            running = False
        if running:
            self.stop_comfyui()
        else:
            # 启动前追加端口占用检测：若任何进程占用目标端口，则避免重复启动
            try:
                port = (self.app.custom_port.get() or "8188").strip()
                pids = self._find_pids_by_port_safe(port)
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
            comfy_root = Path(self.app.config["paths"]["comfyui_path"]).resolve()
            py = Path(self.app.config["paths"]["python_path"]).resolve()
            # 若 Python 路径与当前 ComfyUI 根目录不一致，且新根目录下存在 python_embeded，则自动切换
            try:
                py_root = py.parent.parent.resolve()
            except Exception:
                py_root = None
            candidate_py = comfy_root.parent / "python_embeded" / ("python.exe" if os.name == 'nt' else "python")
            if (not py.exists()) or (py_root and py_root != comfy_root.parent.resolve() and candidate_py.exists()):
                py = candidate_py
                try:
                    self.app.config["paths"]["python_path"] = str(py)
                    # 立即保存，避免后续启动仍读到旧路径
                    self.app.save_config()
                    try:
                        self.app.logger.info("自动切换 Python 路径为当前根目录: %s", py)
                    except Exception:
                        pass
                except Exception:
                    pass
            main = comfy_root / "main.py"
            if not py.exists():
                messagebox.showerror("错误", f"Python不存在: {py}")
                return
            if not main.exists():
                messagebox.showerror("错误", f"主文件不存在: {main}")
                return
            cmd = [str(py), "-s", str(main), "--windows-standalone-build"]
            if self.app.compute_mode.get() == "cpu":
                cmd.append("--cpu")
            if self.app.use_fast_mode.get():
                cmd.extend(["--fast"])
            if self.app.listen_all.get():
                cmd.extend(["--listen", "0.0.0.0"])
            port = self.app.custom_port.get().strip()
            if port and port != "8188":
                cmd.extend(["--port", port])
            if self.app.enable_cors.get():
                cmd.extend(["--enable-cors-header", "*"])
            # 追加自定义额外参数（支持引号与空格）
            extra = (self.app.extra_launch_args.get() or "").strip()
            if extra:
                try:
                    extra_tokens = shlex.split(extra) #
                except Exception:
                    extra_tokens = extra.split()
                cmd.extend(extra_tokens)
            try:
                self.app.logger.info("启动命令: %s", " ".join(cmd))
                if extra:
                    self.app.logger.info("附加参数: %s", extra)
            except Exception:
                pass
            env = os.environ.copy()
            sel = self.app.selected_hf_mirror.get()
            if sel != "不使用镜像":
                # 使用输入框的 URL；当选择“hf-mirror”时已自动填充默认值
                endpoint = (self.app.hf_mirror_url.get() or "").strip()
                if endpoint:
                    env["HF_ENDPOINT"] = endpoint
            try:
                self.app.logger.info("环境变量(HF_ENDPOINT): %s", env.get("HF_ENDPOINT", ""))
            except Exception:
                pass
            # 若设置了 GitHub 代理，则注入 GITHUB_ENDPOINT 环境变量
            try:
                vm = getattr(self.app, 'version_manager', None)
                if vm and vm.proxy_mode_var.get() in ('gh-proxy', 'custom'):
                    base = (vm.proxy_url_var.get() or '').strip()
                    if base:
                        if not base.endswith('/'):
                            base += '/'
                        env["GITHUB_ENDPOINT"] = f"{base}https://github.com"
            except Exception:
                pass
            try:
                self.app.logger.info("环境变量(GITHUB_ENDPOINT): %s", env.get("GITHUB_ENDPOINT", ""))
            except Exception:
                pass
            # 为 GitPython 指定 Git 可执行文件，优先使用整合包的便携 Git
            try:
                git_cmd = None
                try:
                    # 若之前已解析过，直接使用；否则尝试解析
                    git_cmd = self.app.git_path if getattr(self.app, 'git_path', None) else None
                except Exception:
                    git_cmd = None
                if not git_cmd:
                    try:
                        # 确保 resolve_git 存在且可用
                        resolve_git_func = getattr(self.app, 'resolve_git', None)
                        if resolve_git_func:
                            git_cmd, _src = resolve_git_func()
                    except Exception:
                        git_cmd = None
                if git_cmd and git_cmd != 'git':
                    # 设置 GitPython 专用环境变量
                    env["GIT_PYTHON_GIT_EXECUTABLE"] = str(git_cmd)
                    # 兼容某些脚本直接调用 git：将便携 Git 的 bin 目录置于 PATH 前侧
                    try:
                        git_bin = str(Path(git_cmd).resolve().parent)
                        env["PATH"] = git_bin + os.pathsep + env.get("PATH", "")
                    except Exception:
                        pass
                try:
                    self.app.logger.info("环境变量(GIT_PYTHON_GIT_EXECUTABLE): %s", env.get("GIT_PYTHON_GIT_EXECUTABLE", ""))
                except Exception:
                    pass
            except Exception:
                pass
            self.app.big_btn.set_state("starting")
            self.app.big_btn.set_text("启动中…")
            self.app._launching = True

            def worker():
                try:
                    # 始终以当前配置的 ComfyUI 根目录作为工作目录运行
                    try:
                        run_cwd = str(Path(self.app.config["paths"]["comfyui_path"]).resolve())
                    except Exception:
                        run_cwd = os.getcwd()
                    try:
                        self.app.logger.info("启动工作目录(cwd): %s", run_cwd)
                    except Exception:
                        pass
                    if os.name == 'nt':
                        # 始终显示控制台窗口
                        self.comfyui_process = subprocess.Popen(
                            cmd, env=env, cwd=run_cwd,
                            creationflags=subprocess.CREATE_NEW_CONSOLE, #
                        )
                    else:
                        self.comfyui_process = subprocess.Popen(
                            cmd, env=env, cwd=run_cwd
                        )
                    threading.Event().wait(2)
                    if self.comfyui_process.poll() is None:
                        self.app.root.after(0, self.on_start_success)
                    else:
                        self.app.root.after(0, lambda: self.on_start_failed("进程退出"))
                except Exception as e:
                    msg = str(e)
                    # 捕获当前异常信息到默认参数，避免闭包中变量未绑定问题
                    self.app.root.after(0, lambda m=msg: self.on_start_failed(m))

            threading.Thread(target=worker, daemon=True).start()
        except Exception as e:
            msg = str(e)
            try:
                messagebox.showerror("启动失败", msg)
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
        try:
            self.app.logger.info("用户点击停止：开始关闭 ComfyUI")
        except Exception:
            pass
        # 停止过程中也避免重复点击触发启动
        self.app._launching = False
        killed = False
        # 1) 优先停止当前已跟踪的进程
        if getattr(self, "comfyui_process", None) and self.comfyui_process.poll() is None:
            try:
                self.app.logger.info("检测到已跟踪进程，PID=%s，按平台策略终止", str(self.comfyui_process.pid))
            except Exception:
                pass
            pid_str = str(self.comfyui_process.pid)
            if os.name == 'nt':
                # Windows：按序尝试 /T、/T /F，然后回退到 terminate/kill，避免残留控制台窗口
                try:
                    r_soft = run_hidden(["taskkill", "/PID", pid_str, "/T"], capture_output=True, text=True) #
                    try:
                        self.app.logger.info("Windows 停止阶段: taskkill /T 返回码=%s", str(r_soft.returncode))
                    except Exception:
                        pass
                    if r_soft.returncode == 0:
                        killed = True
                        try:
                            self.app.logger.info("Windows 停止阶段: 已通过 taskkill /T 终止 PID=%s (含控制台)", pid_str)
                        except Exception:
                            pass
                    else:
                        r_hard = run_hidden(["taskkill", "/PID", pid_str, "/T", "/F"], capture_output=True, text=True) #
                        try:
                            self.app.logger.info("Windows 停止阶段: taskkill /T /F 返回码=%s", str(r_hard.returncode))
                        except Exception:
                            pass
                        if r_hard.returncode == 0:
                            killed = True
                            try:
                                self.app.logger.info("Windows 停止阶段: 已通过 taskkill /T /F 强制终止 PID=%s", pid_str)
                            except Exception:
                                pass
                        else:
                            # taskkill 未能终止，改用 Popen API
                            try:
                                self.comfyui_process.terminate()
                                self.comfyui_process.wait(timeout=5)
                                killed = True
                                try:
                                    self.app.logger.warning("Windows 停止阶段: taskkill 失败，已回退到 terminate+wait，PID=%s", pid_str)
                                except Exception:
                                    pass
                            except subprocess.TimeoutExpired: #
                                try:
                                    self.comfyui_process.kill()
                                    killed = True
                                    try:
                                        self.app.logger.warning("Windows 停止阶段: terminate 超时，已 kill，PID=%s", pid_str)
                                    except Exception:
                                        pass
                                except Exception as e3:
                                    try:
                                        self.app.logger.error("Windows 停止阶段: 回退强制结束失败: %s", str(e3))
                                    except Exception:
                                        pass
                                    messagebox.showerror("错误", f"停止失败: {e3}")
                except Exception as e:
                    try:
                        self.app.logger.error("Windows 停止阶段: taskkill 执行异常: %s，回退到 terminate/kill", str(e))
                    except Exception:
                        pass
                    try:
                        self.comfyui_process.terminate()
                        self.comfyui_process.wait(timeout=5)
                        killed = True
                        try:
                            self.app.logger.warning("Windows 停止阶段: 已回退到 terminate+wait，PID=%s", pid_str)
                        except Exception:
                            pass
                    except subprocess.TimeoutExpired: #
                        try:
                            self.comfyui_process.kill()
                            killed = True
                            try:
                                self.app.logger.warning("Windows 停止阶段: 回退 terminate 超时，已 kill，PID=%s", pid_str)
                            except Exception:
                                pass
                        except Exception as e2:
                            try:
                                self.app.logger.error("Windows 停止阶段: 回退强制结束失败: %s", str(e2))
                            except Exception:
                                pass
                            messagebox.showerror("错误", f"停止失败: {e2}")
            else:
                # 非 Windows：沿用 terminate -> wait -> kill
                try:
                    self.comfyui_process.terminate()
                    self.comfyui_process.wait(timeout=5)
                    killed = True
                    try:
                        self.app.logger.info("已终止跟踪进程，PID=%s", pid_str)
                    except Exception:
                        pass
                except subprocess.TimeoutExpired: #
                    try:
                        self.comfyui_process.kill()
                        killed = True
                        try:
                            self.app.logger.warning("优雅终止超时，已强制结束，PID=%s", pid_str)
                        except Exception:
                            pass
                    except Exception as e:
                        try:
                            self.app.logger.error("强制结束失败: %s", str(e))
                        except Exception:
                            pass
                        messagebox.showerror("错误", f"停止失败: {e}")
        else:
            # 2) 未跟踪到句柄：根据端口查找并强制终止对应进程
            port = (self.app.custom_port.get() or "8188").strip()
            pids = self._find_pids_by_port_safe(port)
            try:
                self.app.logger.info("未跟踪到句柄；端口 %s 的PID列表: %s", port, ", ".join(map(str, pids)) or "<空>")
            except Exception:
                pass
            if pids:
                try:
                    self._kill_pids(pids)
                    killed = True
                    try:
                        self.app.logger.info("已强制终止端口 %s 上的相关进程: %s", port, ", ".join(map(str, pids)))
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        self.app.logger.error("强制停止失败: %s", str(e))
                    except Exception:
                        pass
                    messagebox.showerror("错误", f"强制停止失败: {e}")
            else:
                try:
                    self.app.logger.warning("未找到端口 %s 上运行的进程，可能已外部关闭或端口设置不一致", port)
                except Exception:
                    pass
                messagebox.showwarning("警告", f"未找到端口 {port} 上运行的进程")

        # 根据结果刷新按钮
        if killed:
            self.app.big_btn.set_state("idle")
            self.app.big_btn.set_text("一键启动")
            self.comfyui_process = None
            try:
                self.app.logger.info("停止流程完成：已关闭 ComfyUI")
            except Exception:
                pass
        else:
            # 若仍被判定为运行中，保持“停止”以避免误导
            try:
                reachable = self._is_http_reachable()
                try:
                    self.app.logger.warning("停止未成功：端口可达=%s。可能原因：外部启动的实例、权限不足、端口配置不同。", str(reachable))
                except Exception:
                    pass
                if reachable:
                    self.app.big_btn.set_state("running")
                    self.app.big_btn.set_text("停止")
                else:
                    self.app.big_btn.set_state("idle")
                    self.app.big_btn.set_text("一键启动")
            except Exception:
                self.app.big_btn.set_state("idle")
                self.app.big_btn.set_text("一键启动")

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
                        comfy_root = str(Path(self.app.config["paths"]["comfyui_path"]).resolve()).lower()
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
        """运行探测：优先使用 TCP 直连判断端口监听，其次回退到进程/端口解析。

        - 首选尝试 `socket.create_connection((127.0.0.1, port))`，成功即认为“运行中”。
        - 若直连失败，回退到 `_find_pids_by_port_safe` 的 psutil/netstat 解析。
        """
        try:
            port_str = (self.app.custom_port.get() or "8188").strip()
            port = int(port_str)
        except Exception:
            return False

        # 首选：TCP 直连判断监听
        try:
            import socket
            with socket.create_connection(("127.0.0.1", port), timeout=0.4): #
                return True
        except Exception:
            pass

        # 回退：端口对应的 PID 列表（严格的 TCP 状态筛选已在 netstat 解析内实现）
        try:
            pids = self._find_pids_by_port_safe(port_str)
            return bool(pids)
        except Exception:
            return False

    def _refresh_running_status(self): #
        # 根据进程与端口探测结果统一刷新按钮状态
        try:
            running = False
            if self.comfyui_process and self.comfyui_process.poll() is None:
                running = True
            else:
                running = self._is_http_reachable()
            if running:
                self.app.big_btn.set_state("running")
                self.app.big_btn.set_text("停止")
            else:
                self.app.big_btn.set_state("idle")
                self.app.big_btn.set_text("一键启动")
        except Exception:
            pass

    def monitor_process(self): #
        while True:
            try:
                # 若处于关闭流程，则停止监控循环，避免销毁窗口前的 UI 冲突
                if getattr(self.app, "_shutting_down", False):
                    break
                # 进程结束时，置空句柄并根据端口探测决定按钮显示
                if self.comfyui_process and self.comfyui_process.poll() is not None:
                    self.comfyui_process = None
                self.app.root.after(0, self._refresh_running_status)
                threading.Event().wait(2)
            except:
                break

    def on_process_ended(self): #
        try:
            self.app.logger.info("ComfyUI 进程结束")
        except Exception:
            pass
        self.comfyui_process = None
        # 根据端口探测决定显示“停止”或“一键启动”
        try:
            if self._is_http_reachable():
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
            for pid in self._find_pids_by_port_safe(port):
                try:
                    if self._is_comfyui_pid(pid):
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
                        if self._is_comfyui_pid(int(pid)):
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
        # 统一终止
        if pids:
            try:
                # 统一调用 _kill_pids
                self._kill_pids(list(pids))
                killed = True
            except Exception:
                # _kill_pids 内部已尽力终止，此处仅打印错误
                try:
                    self.app.logger.error("在 stop_all_comfyui_instances 中统一终止进程失败")
                except Exception:
                    pass

        return killed