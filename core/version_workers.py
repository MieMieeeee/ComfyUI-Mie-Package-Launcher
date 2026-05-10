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
                    self.gpuStatusReady.emit(f"{gpu_name} ({driver_version})")
                    self._log("info", "显卡驱动状态=%s (%s)", gpu_name, driver_version)
                elif "无NVIDIA" in output or "错误" in output:
                    self.gpuStatusReady.emit("未检测到NVIDIA显卡")
                    self._log("info", "未检测到NVIDIA显卡")
                else:
                    self.gpuStatusReady.emit(output)
            else:
                self.gpuStatusReady.emit("检测失败")
                self._log(
                    "warning",
                    "GPU检测失败: rc=%s stdout=%s stderr=%s",
                    result.returncode,
                    result.stdout,
                    result.stderr,
                )
        except Exception as e:
            self.gpuStatusReady.emit("检测失败")
            self._log("warning", "GPU检测异常: %s", e)
            if self.attempt < self.MAX_RETRIES:
                self.retryNeeded.emit(self.attempt)


# Alias for backward compatibility
CoreVersionWorker = ComfyUIVersionWorker
