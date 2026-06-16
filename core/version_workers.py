"""版本检测 Worker 模块。

从 ui_qt.qt_app 提取的版本检测 Worker 类。
"""

from pathlib import Path

from PyQt5 import QtCore

from utils.common import run_hidden
from utils import pip as PIPUTILS
from utils import paths as PATHS


class BaseVersionWorker(QtCore.QThread):
    """基础版本检测 Worker，支持重试和超时"""

    MAX_RETRIES = 3
    RETRY_DELAY_MS = 3000
    TIMEOUT = 30

    # 通用信号
    retryNeeded = QtCore.pyqtSignal(int)  # attempt number

    def __init__(self, app, attempt=1, parent=None):
        super().__init__(parent)
        self.app = app
        self.attempt = attempt

    def _get_paths(self):
        """获取 ComfyUI 路径"""
        # 复用 utils.paths 中的通用解析逻辑，保持与其他模块一致
        # comfy_root_from_config 在异常时会回退到 Path(".").resolve() / "ComfyUI"，
        # 与此前本地实现的回退行为保持一致。
        try:
            cfg = getattr(self.app, "config", None)
        except Exception:
            cfg = None
        return PATHS.comfy_root_from_config(cfg if isinstance(cfg, dict) else {})

    def _log(self, level, msg, *args):
        """安全日志方法"""
        try:
            if hasattr(self.app, "logger"):
                getattr(self.app.logger, level)(msg, *args)
        except Exception:
            pass


class PythonVersionWorker(BaseVersionWorker):
    """Python 版本检测 Worker"""

    versionReady = QtCore.pyqtSignal(str)

    def run(self):
        try:
            root = self._get_paths()
            if not root.exists():
                self.versionReady.emit("未找到")
                return

            r = run_hidden(
                [self.app.python_exec, "--version"],
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT,
            )
            val = (
                r.stdout.strip().replace("Python ", "")
                if r.returncode == 0
                else "获取失败"
            )
            self.versionReady.emit(val)
            self._log("info", "Python 版本=%s", val)
        except Exception as e:
            self._log("warning", "Python 版本检测失败: %s", e)
            if self.attempt < self.MAX_RETRIES:
                self.retryNeeded.emit(self.attempt)
            else:
                self.versionReady.emit("获取失败")


class TorchVersionWorker(BaseVersionWorker):
    """Torch 版本检测 Worker"""

    versionReady = QtCore.pyqtSignal(str)

    def run(self):
        try:
            root = self._get_paths()
            if not root.exists():
                self.versionReady.emit("未找到")
                return

            v = PIPUTILS.get_package_version(
                "torch",
                self.app.python_exec,
                logger=self.app.logger if hasattr(self.app, "logger") else None,
            )
            self.versionReady.emit(v or "未安装")
            self._log("info", "Torch 版本=%s", v or "未安装")
        except Exception as e:
            self._log("warning", "Torch 版本检测失败: %s", e)
            if self.attempt < self.MAX_RETRIES:
                self.retryNeeded.emit(self.attempt)
            else:
                self.versionReady.emit("获取失败")


class ComfyUIVersionWorker(BaseVersionWorker):
    """ComfyUI 内核版本检测 Worker"""

    versionReady = QtCore.pyqtSignal(str)
    commitReady = QtCore.pyqtSignal(str)

    def run(self):
        try:
            root = self._get_paths()
            if not root.exists():
                self.versionReady.emit("未找到")
                return

            git_cmd, _ = self.app.resolve_git()
            if git_cmd is None:
                self.versionReady.emit("未找到Git命令")
                return

            # 获取 commit
            r2 = run_hidden(
                [git_cmd, "rev-parse", "--short", "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            c = r2.stdout.strip() if r2.returncode == 0 else ""

            # 检测 HEAD 是否精确在 tag 上
            exact_tag = None
            try:
                r3 = run_hidden(
                    [git_cmd, "describe", "--tags", "--exact-match", "HEAD"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if r3.returncode == 0:
                    exact_tag = r3.stdout.strip()
            except Exception:
                pass

            # 获取日期
            date_str = None
            try:
                r4 = run_hidden(
                    [git_cmd, "log", "-1", "--format=%as", "HEAD"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if r4.returncode == 0:
                    date_str = r4.stdout.strip() or None
            except Exception:
                pass

            # 格式化
            if exact_tag:
                display = f"{exact_tag} ({date_str})" if date_str else exact_tag
            else:
                display = f"{c} ({date_str})" if c and date_str else (c or "未找到")

            self.versionReady.emit(display)
            self.commitReady.emit(display)
            self._log("info", "内核版本标签已生成")
        except Exception as e:
            self._log("warning", "内核版本检测失败: %s", e)
            if self.attempt < self.MAX_RETRIES:
                self.retryNeeded.emit(self.attempt)
            else:
                self.versionReady.emit("未找到")


class FrontendVersionWorker(BaseVersionWorker):
    """前端包版本检测 Worker"""

    versionReady = QtCore.pyqtSignal(str)

    def run(self):
        try:
            root = self._get_paths()
            if not root.exists():
                self.versionReady.emit("未找到")
                return

            vf = PIPUTILS.get_package_version(
                "comfyui-frontend-package",
                self.app.python_exec,
                logger=self.app.logger if hasattr(self.app, "logger") else None,
            )
            if not vf:
                vf = PIPUTILS.get_package_version(
                    "comfyui_frontend_package",
                    self.app.python_exec,
                    logger=self.app.logger if hasattr(self.app, "logger") else None,
                )
            self.versionReady.emit(vf or "未安装")
            self._log("info", "前端包版本=%s", vf or "未安装")
        except Exception as e:
            self._log("warning", "前端包版本检测失败: %s", e)
            if self.attempt < self.MAX_RETRIES:
                self.retryNeeded.emit(self.attempt)
            else:
                self.versionReady.emit("获取失败")


class TemplateVersionWorker(BaseVersionWorker):
    """模板库版本检测 Worker"""

    versionReady = QtCore.pyqtSignal(str)

    def run(self):
        try:
            root = self._get_paths()
            if not root.exists():
                self.versionReady.emit("未找到")
                return

            vt = PIPUTILS.get_package_version(
                "comfyui-workflow-templates",
                self.app.python_exec,
                logger=self.app.logger if hasattr(self.app, "logger") else None,
            )
            if not vt:
                vt = PIPUTILS.get_package_version(
                    "comfyui_workflow_templates",
                    self.app.python_exec,
                    logger=self.app.logger if hasattr(self.app, "logger") else None,
                )
            self.versionReady.emit(vt or "未安装")
            self._log("info", "模板库版本=%s", vt or "未安装")
        except Exception as e:
            self._log("warning", "模板库版本检测失败: %s", e)
            if self.attempt < self.MAX_RETRIES:
                self.retryNeeded.emit(self.attempt)
            else:
                self.versionReady.emit("获取失败")


class GitStatusWorker(BaseVersionWorker):
    """Git 状态检测 Worker"""

    versionReady = QtCore.pyqtSignal(str)

    def run(self):
        try:
            root = self._get_paths()
            if not root.exists():
                self.versionReady.emit("ComfyUI未找到")
                return

            git_cmd, git_text = self.app.resolve_git()
            if git_cmd is None:
                self.versionReady.emit("未找到Git命令")
                return

            self.versionReady.emit(git_text or "")
            self._log("info", "Git状态=%s", git_text or "")
        except Exception as e:
            self._log("warning", "Git状态检测失败: %s", e)
            if self.attempt < self.MAX_RETRIES:
                self.retryNeeded.emit(self.attempt)
            else:
                self.versionReady.emit("检测失败")


class GpuCheckWorker(BaseVersionWorker):
    """GPU 检测 Worker"""

    gpuStatusReady = QtCore.pyqtSignal(str)

    def run(self):
        try:
            self._log("info", "开始检测显卡驱动状态...")
            gpu_name = None
            driver_version = None

            # 方法1: pynvml
            pynvml_script = """
import sys
import os
import warnings
warnings.filterwarnings("ignore")

try:
    import pynvml
    pynvml.nvmlInit()
    count = pynvml.nvmlDeviceGetCount()
    if count > 0:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        driver = pynvml.nvmlSystemGetDriverVersion()
        print(f"{name}|{driver}")
    else:
        print("无NVIDIA显卡")
except Exception as e:
    print(f"pynvml错误:{e}")
"""

            result = run_hidden(
                [self.app.python_exec, "-c", pynvml_script],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                if "|" in output:
                    gpu_name, driver_version = output.split("|", 1)
                    self._log("info", "pynvml 检测成功 - GPU=%s Driver=%s", gpu_name, driver_version)
                else:
                    self._log("info", "pynvml 输出: %s", output)
            else:
                self._log("warning", "pynvml 检测失败: rc=%s", result.returncode)

            # 方法2: nvidia-smi 兜底
            if not gpu_name:
                import shutil
                nvidia_smi_path = shutil.which("nvidia-smi")
                if nvidia_smi_path:
                    try:
                        r = run_hidden(
                            [nvidia_smi_path, "--query-gpu=name,driver_version",
                             "--format=csv,noheader,nounits"],
                            capture_output=True, text=True, timeout=10,
                        )
                        if r.returncode == 0 and r.stdout.strip():
                            lines = r.stdout.strip().splitlines()
                            if lines:
                                parts = lines[0].split(",")
                                if len(parts) >= 1:
                                    gpu_name = parts[0].strip()
                                if len(parts) >= 2:
                                    driver_version = parts[1].strip()
                                self._log("info", "nvidia-smi 检测成功 - GPU=%s Driver=%s", gpu_name, driver_version)
                    except Exception as e:
                        self._log("warning", "nvidia-smi 检测失败: %s", e)

            # 生成结果
            if gpu_name and driver_version:
                self.gpuStatusReady.emit(f"✓ {gpu_name} ({driver_version})")
            elif gpu_name:
                self.gpuStatusReady.emit(f"✓ {gpu_name}")
            else:
                self.gpuStatusReady.emit("未检测到NVIDIA显卡")
                self._log("info", "未检测到NVIDIA显卡")
        except Exception as e:
            self.gpuStatusReady.emit("检测失败")
            self._log("warning", "GPU检测异常: %s", e)
            if self.attempt < self.MAX_RETRIES:
                self.retryNeeded.emit(self.attempt)


class GpuEnumerateWorker(BaseVersionWorker):
    """枚举所有可见 GPU（含索引、名称、显存），供启动器显卡下拉使用。"""

    # 信号载荷：list[dict]，每项形如 {"index": 0, "name": "NVIDIA RTX 4090", "memory_mb": 24576}
    inventoryReady = QtCore.pyqtSignal(list)

    def run(self):
        inventory = []
        try:
            self._log("info", "开始枚举 GPU ...")
            inventory = self._enumerate_via_pynvml()
            if not inventory:
                inventory = self._enumerate_via_nvidia_smi()
        except Exception as e:
            self._log("warning", "GPU 枚举异常: %s", e)
        self._log("info", "GPU 枚举完成，共 %d 张", len(inventory))
        try:
            summary = [(g.get("index"), g.get("name"), g.get("memory_mb")) for g in (inventory or [])]
            self._log("info", "gpu: 枚举完成 共 %d 张 -> %s", len(inventory), summary)
        except Exception:
            pass
        self.inventoryReady.emit(inventory)

    def _enumerate_via_pynvml(self):
        script = """
import sys, os, warnings
warnings.filterwarnings("ignore")
try:
    import pynvml
    pynvml.nvmlInit()
    count = pynvml.nvmlDeviceGetCount()
    for i in range(count):
        h = pynvml.nvmlDeviceGetHandleByIndex(i)
        name = pynvml.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        mem = pynvml.nvmlDeviceGetMemoryInfo(h).total // (1024 * 1024)
        # 用 \\x1f 作为字段分隔，避免名称中含 |
        print(f"{i}\\x1f{name}\\x1f{mem}", flush=True)
    pynvml.nvmlShutdown()
except Exception as e:
    print(f"ERROR:{e}", flush=True)
"""
        try:
            r = run_hidden(
                [self.app.python_exec, "-c", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as e:
            self._log("warning", "pynvml 枚举执行失败: %s", e)
            return []
        return self._parse_lines(r.stdout)

    def _enumerate_via_nvidia_smi(self):
        import shutil
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            return []
        try:
            r = run_hidden(
                [
                    nvidia_smi,
                    "--query-gpu=index,name,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as e:
            self._log("warning", "nvidia-smi 枚举执行失败: %s", e)
            return []
        if r.returncode != 0 or not r.stdout.strip():
            return []
        out = []
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                idx = int(parts[0])
            except Exception:
                continue
            name = parts[1] if len(parts) >= 2 else ""
            mem_mb = 0
            if len(parts) >= 3:
                try:
                    mem_mb = int(float(parts[2]))
                except Exception:
                    mem_mb = 0
            out.append({"index": idx, "name": name, "memory_mb": mem_mb})
        return out

    @staticmethod
    def _parse_lines(stdout):
        out = []
        if not stdout:
            return out
        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("ERROR:"):
                continue
            parts = line.split("\x1f")
            if len(parts) < 3:
                # 兜底：尝试 | 分隔
                parts = line.split("|")
            if len(parts) < 2:
                continue
            try:
                idx = int(parts[0])
            except Exception:
                continue
            name = parts[1].strip() if len(parts) >= 2 else ""
            mem_mb = 0
            if len(parts) >= 3:
                try:
                    mem_mb = int(parts[2])
                except Exception:
                    mem_mb = 0
            out.append({"index": idx, "name": name, "memory_mb": mem_mb})
        return out


# Alias for backward compatibility
CoreVersionWorker = ComfyUIVersionWorker
