"""WebUI 页面 (Comfyui-Workbench-Mie 启停 / 配置 / 日志).

状态机:
  not_installed  -> [下载工作台] [配置]
  no_deps        -> [安装依赖] [配置]
  ready          -> [一键启动] [打开网页] [配置]
  running        -> [停止] [打开网页] [配置]
  starting/stopping -> 进度显示 (禁用按钮)

参考: ui_qt/pages/launch_page.py (大按钮 + 状态机模式).
Pyllow 设计: 状态点 + 文本 + 按钮 (跟 launch_page 同源风格).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from .base_page import BasePage
from utils.paths import webui_path_from_config, WEBUI_DIR_NAME
from config.migrations import resolve_active_paths_for_webui
from core.webui_launcher_cmd import build_webui_launch_params
from core.webui_process_manager import WebuiProcessManager
from core.webui_dependencies import check_webui_dependencies, install_webui_requirements
from core.webui_installer import clone_webui, pull_webui
from utils.net import resolve_pypi_index_url


STATE_NOT_INSTALLED = "not_installed"
STATE_NO_DEPS = "no_deps"
STATE_READY = "ready"
STATE_RUNNING = "running"
STATE_STARTING = "starting"
STATE_STOPPING = "stopping"

# 状态颜色 (跟 launch_page 风格一致)
STATE_COLOR = {
    STATE_NOT_INSTALLED: "#ff6b6b",  # 红
    STATE_NO_DEPS: "#ffa500",       # 黄
    STATE_READY: "#5cdc5c",         # 绿
    STATE_RUNNING: "#5cdc5c",       # 绿
    STATE_STARTING: "#4fc3f7",      # 蓝
    STATE_STOPPING: "#4fc3f7",      # 蓝
}


def _read_workbench_version(webui_root: Optional[Path]) -> Optional[str]:
    """从 <webui_root>/app/config.py 解析 WORKBENCH_VERSION."""
    if not webui_root:
        return None
    cfg = webui_root / "app" / "config.py"
    if not cfg.exists():
        return None
    try:
        text = cfg.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    # 找 WORKBENCH_VERSION: str = "..." 这一行
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("WORKBENCH_VERSION"):
            parts = s.split("=", 1)
            if len(parts) == 2:
                v = parts[1].strip().strip("'").strip('"')
                if v:
                    return v
    return None


class WebuiPage(BasePage):
    """WebUI 启停 / 配置 / 日志."""

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self.theme_manager = theme_manager
        self._state: str = STATE_NOT_INSTALLED
        self._state_check_timer = None
        self._pm: Optional[WebuiProcessManager] = None
        # 依赖探测缓存: 同一 (py, webui_path) 不重复 spawn 3 个 python 子进程.
        # 失效点: _after_setup / refresh_after_env_switch (路径或依赖可能变).
        self._deps_cache_key: Optional[tuple] = None
        self._deps_cache_result: Optional[dict] = None
        self._setup_ui()
        self._refresh_state()

    # ---------------- 主 UI ----------------
    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # === 状态卡 ===
        status_group = QtWidgets.QGroupBox("工作台状态")
        status_layout = QtWidgets.QHBoxLayout(status_group)
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setSpacing(12)

        # 状态圆点
        self._status_dot = QtWidgets.QLabel()
        self._status_dot.setFixedSize(20, 20)
        self._status_dot.setStyleSheet(
            "background-color: #888; border-radius: 10px;"
        )
        status_layout.addWidget(self._status_dot)

        # 状态文本
        self._status_text = QtWidgets.QLabel("检测中...")
        self._status_text.setStyleSheet(
            'font: bold 11pt "Microsoft YaHei UI";'
        )
        status_layout.addWidget(self._status_text, 1)

        # 刷新按钮
        self._btn_refresh = QtWidgets.QPushButton("🔄 刷新")
        self._btn_refresh.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_refresh.clicked.connect(self._refresh_state)
        status_layout.addWidget(self._btn_refresh)

        layout.addWidget(status_group)

        # 详情行 (路径 + 版本)
        self._detail_label = QtWidgets.QLabel("")
        self._detail_label.setStyleSheet(
            'font: 9pt "Microsoft YaHei UI"; color: #888;'
        )
        self._detail_label.setWordWrap(True)
        layout.addWidget(self._detail_label)

        # === 操作按钮区 ===
        action_group = QtWidgets.QGroupBox("操作")
        action_layout = QtWidgets.QHBoxLayout(action_group)
        action_layout.setContentsMargins(10, 8, 10, 8)
        action_layout.setSpacing(8)

        self._btn_primary = QtWidgets.QPushButton()
        self._btn_primary.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_primary.setMinimumHeight(44)
        self._btn_primary.setStyleSheet(
            "QPushButton {"
            "  font: bold 11pt 'Microsoft YaHei UI';"
            "  background-color: #4a90e2; color: white;"
            "  border-radius: 6px; padding: 8px 16px;"
            "}"
            "QPushButton:hover { background-color: #5aa0f2; }"
            "QPushButton:disabled { background-color: #888; }"
        )
        self._btn_primary.clicked.connect(self._on_primary_clicked)
        action_layout.addWidget(self._btn_primary, 2)

        self._btn_secondary = QtWidgets.QPushButton("打开网页")
        self._btn_secondary.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_secondary.setMinimumHeight(44)
        self._btn_secondary.setStyleSheet(
            "QPushButton {"
            "  font: 10pt 'Microsoft YaHei UI';"
            "  background-color: #5cb85c; color: white;"
            "  border-radius: 6px; padding: 8px 16px;"
            "}"
            "QPushButton:hover { background-color: #6cc86c; }"
            "QPushButton:disabled { background-color: #888; }"
        )
        self._btn_secondary.clicked.connect(self._on_open_browser)
        action_layout.addWidget(self._btn_secondary, 1)

        self._btn_config = QtWidgets.QPushButton("⚙ 配置")
        self._btn_config.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_config.setMinimumHeight(44)
        self._btn_config.setStyleSheet(
            "QPushButton {"
            "  font: 10pt 'Microsoft YaHei UI';"
            "  background-color: #777; color: white;"
            "  border-radius: 6px; padding: 8px 16px;"
            "}"
            "QPushButton:hover { background-color: #888; }"
        )
        self._btn_config.clicked.connect(self._on_config_clicked)
        action_layout.addWidget(self._btn_config, 1)

        layout.addWidget(action_group)

        # === 状态指示 (运行时显示 port / pid / uptime) ===
        info_group = QtWidgets.QGroupBox("服务信息")
        info_layout = QtWidgets.QFormLayout(info_group)
        info_layout.setContentsMargins(10, 8, 10, 8)
        info_layout.setSpacing(6)

        self._info_port = QtWidgets.QLabel("-")
        self._info_pid = QtWidgets.QLabel("-")
        self._info_url = QtWidgets.QLabel("-")
        self._info_env = QtWidgets.QLabel("-")
        self._info_since = QtWidgets.QLabel("-")
        info_layout.addRow("端口:", self._info_port)
        info_layout.addRow("PID:", self._info_pid)
        info_layout.addRow("URL:", self._info_url)
        info_layout.addRow("Env:", self._info_env)
        info_layout.addRow("启动时间:", self._info_since)
        layout.addWidget(info_group)

        # === 日志区域 ===
        log_group = QtWidgets.QGroupBox("日志 (launcher/webui.log)")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(4)

        self._log_view = QtWidgets.QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(500)
        self._log_view.setStyleSheet(
            "QPlainTextEdit {"
            "  background-color: #1e1e1e; color: #d4d4d4;"
            "  font: 9pt 'Consolas';"
            "  border: 1px solid #555;"
            "}"
        )
        log_layout.addWidget(self._log_view)

        # 日志工具栏
        log_toolbar = QtWidgets.QHBoxLayout()
        log_toolbar.setSpacing(4)
        self._btn_log_refresh = QtWidgets.QPushButton("🔄 刷新日志")
        self._btn_log_refresh.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_log_refresh.clicked.connect(self._refresh_log)
        log_toolbar.addWidget(self._btn_log_refresh)

        self._btn_log_open = QtWidgets.QPushButton("📂 打开日志文件")
        self._btn_log_open.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_log_open.clicked.connect(self._open_log_file)
        log_toolbar.addWidget(self._btn_log_open)
        log_toolbar.addStretch(1)
        log_layout.addLayout(log_toolbar)

        layout.addWidget(log_group, 1)

        # 底部留白
        layout.addSpacing(4)

        # 注册状态定时器 (5s)
        self._state_check_timer = QtCore.QTimer(self)
        self._state_check_timer.timeout.connect(self._poll_status)
        self._state_check_timer.start(5000)

    # ---------------- 状态探测 ----------------
    def _resolve_paths(self) -> dict:
        """返回 webui 路径 + python 路径 + 端口等."""
        cfg = getattr(self.app, "config", None)
        webui_options = (cfg or {}).get("webui_options") or {}
        port = int(webui_options.get("port") or 8199)
        display_host = webui_options.get("display_host") or "127.0.0.1"
        auto_open = bool(webui_options.get("auto_open_browser", False))
        download_url = webui_options.get("download_url") or "https://github.com/MieMieeeee/Comfyui-Workbench-Mie.git"

        pw = resolve_active_paths_for_webui(cfg if isinstance(cfg, dict) else {})
        webui_path = Path(pw["webui_path"]) if pw.get("webui_path") else None
        py_path = Path(pw["python_path"]) if pw.get("python_path") else None
        env_id = pw.get("env_id")

        return {
            "webui_path": webui_path,
            "python_path": py_path,
            "env_id": env_id,
            "port": port,
            "display_host": display_host,
            "auto_open": auto_open,
            "download_url": download_url,
        }

    def _detect_state(self) -> str:
        """综合判定当前状态."""
        info = self._resolve_paths()
        webui_path = info["webui_path"]
        py_path = info["python_path"]

        # 1. 是否在跑 (ProcessManager 已知)
        if self._pm is None:
            self._pm = WebuiProcessManager(self.app)
        running = self._pm.is_running()
        if running:
            return STATE_RUNNING

        # 2. webui 路径 + 入口
        if webui_path is None or not webui_path.exists():
            return STATE_NOT_INSTALLED
        if not (webui_path / "app" / "flask_app.py").exists():
            return STATE_NOT_INSTALLED

        # 3. python 依赖 (带缓存: 同一 (py, webui_path) 不重复探测)
        if py_path is None or not py_path.exists():
            return STATE_NO_DEPS
        cache_key = (str(py_path), str(webui_path))
        if self._deps_cache_key == cache_key and self._deps_cache_result is not None:
            dep = self._deps_cache_result
        else:
            dep = check_webui_dependencies(py_path)
            self._deps_cache_key = cache_key
            self._deps_cache_result = dep
        if not dep["ok"]:
            return STATE_NO_DEPS

        return STATE_READY

    def _refresh_state(self):
        self._state = self._detect_state()
        self._update_ui_for_state()
        self._update_info_panel()
        self._refresh_log()

    def _poll_status(self):
        """定时器: 仅在 running / starting / stopping 时勤跑 (running 状态会变)."""
        try:
            new_state = self._detect_state()
            if new_state != self._state:
                self._state = new_state
                self._update_ui_for_state()
            self._update_info_panel()
        except Exception:
            pass

    def _update_ui_for_state(self):
        color = STATE_COLOR.get(self._state, "#888")
        self._status_dot.setStyleSheet(
            "background-color: %s; border-radius: 10px;" % color
        )

        info = self._resolve_paths()
        webui_path = info["webui_path"]
        version = _read_workbench_version(webui_path) if webui_path else None

        if self._state == STATE_NOT_INSTALLED:
            txt = "工作台未安装"
            detail = "期望位置: %s" % (str(webui_path) if webui_path else "未解析")
            if webui_path:
                detail += "\n点击 [下载工作台] 拉取最新版本"
        elif self._state == STATE_NO_DEPS:
            txt = "待安装依赖"
            detail = "位置: %s\nPython 缺少 flask / requests / websockets, 点击 [安装依赖]" % (
                str(webui_path) if webui_path else "?"
            )
        elif self._state == STATE_READY:
            v_str = " v" + version if version else ""
            txt = "工作台就绪" + v_str
            detail = "位置: %s\nPython: %s\n点击 [一键启动] 拉起服务" % (
                str(webui_path) if webui_path else "?",
                str(info["python_path"]) if info["python_path"] else "?",
            )
        elif self._state == STATE_RUNNING:
            txt = "工作中"
            detail = "服务已起, 浏览器打开 http://%s:%s/" % (info["display_host"], info["port"])
        else:
            txt = self._state
            detail = ""

        self._status_text.setText(txt)
        self._detail_label.setText(detail)

        # 按钮
        if self._state == STATE_NOT_INSTALLED:
            self._btn_primary.setText("⬇ 下载工作台")
            self._btn_primary.setEnabled(True)
            self._btn_secondary.setEnabled(False)
            self._btn_secondary.setText("打开网页")
        elif self._state == STATE_NO_DEPS:
            self._btn_primary.setText("⚙ 安装依赖")
            self._btn_primary.setEnabled(True)
            self._btn_secondary.setEnabled(False)
            self._btn_secondary.setText("打开网页")
        elif self._state == STATE_READY:
            self._btn_primary.setText("🚀 一键启动")
            self._btn_primary.setEnabled(True)
            self._btn_secondary.setEnabled(True)
            self._btn_secondary.setText("打开网页")
        elif self._state == STATE_RUNNING:
            self._btn_primary.setText("⏹ 停止")
            self._btn_primary.setEnabled(True)
            self._btn_secondary.setEnabled(True)
            self._btn_secondary.setText("🌐 打开网页")
        else:
            self._btn_primary.setText("...")
            self._btn_primary.setEnabled(False)

    def _update_info_panel(self):
        info = self._resolve_paths()
        self._info_port.setText(str(info["port"]))
        self._info_url.setText("http://%s:%s/" % (info["display_host"], info["port"]))
        self._info_env.setText(str(info["env_id"]) if info["env_id"] else "-")

        # PID / 启动时间 — 来自 ProcessManager.status
        if self._pm is None:
            self._pm = WebuiProcessManager(self.app)
        try:
            st = self._pm.status()
        except Exception:
            st = {}
        if st.get("pid"):
            self._info_pid.setText(str(st["pid"]))
        else:
            self._info_pid.setText("-")
        if st.get("since"):
            self._info_since.setText(str(st["since"]))
        else:
            self._info_since.setText("-")

    # ---------------- 按钮回调 ----------------
    def _on_primary_clicked(self):
        if self._state == STATE_NOT_INSTALLED:
            self._download_webui()
        elif self._state == STATE_NO_DEPS:
            self._setup_deps()
        elif self._state == STATE_READY:
            self._start_with_prompt()
        elif self._state == STATE_RUNNING:
            self._stop_webui()

    def _start_with_prompt(self):
        """弹 3 选 1 dialog: 同时启动 / 只启 WebUI / 取消."""
        info = self._resolve_paths()
        env_id = info["env_id"]

        # 检查 ComfyUI 是否在跑
        comfyui_running = self._is_comfyui_running()

        if comfyui_running:
            # ComfyUI 在跑, 直接启 WebUI (不弹 dialog)
            self._start_webui(with_comfyui=False)
            return

        # ComfyUI 没跑, 弹 dialog
        msg = QtWidgets.QMessageBox(self)
        msg.setIcon(QtWidgets.QMessageBox.Question)
        msg.setWindowTitle("启动 WebUI")
        msg.setText(
            "WebUI 是以 ComfyUI 为后台运行工作流的。\n"
            "ComfyUI 当前未在跑, 提交任务时会失败。\n\n"
            "请选择启动方式:"
        )
        btn_both = msg.addButton("同时启动 ComfyUI + WebUI", QtWidgets.QMessageBox.AcceptRole)
        btn_alone = msg.addButton("只启动 WebUI", QtWidgets.QMessageBox.DestructiveRole)
        btn_cancel = msg.addButton("取消", QtWidgets.QMessageBox.RejectRole)
        msg.setDefaultButton(btn_both)
        msg.exec_()
        clicked = msg.clickedButton()
        if clicked is btn_both:
            # 先启 ComfyUI, 再启 WebUI
            self._start_comfyui_then_webui()
        elif clicked is btn_alone:
            self._start_webui(with_comfyui=False)
        # else: 取消

    def _is_comfyui_running(self) -> bool:
        """ComfyUI 是否在跑 (HTTP 探活 + pidfile)."""
        try:
            # 复用 core.cli.runner.service_status
            from core.cli.runner import service_status
            st = service_status(self.app) or {}
            return bool(st.get("running"))
        except Exception:
            return False

    def _start_comfyui_then_webui(self):
        """先启 ComfyUI (同步), 成功后再启 WebUI."""
        try:
            from core.cli.runner import start_service
            res = start_service(self.app, no_wait=False, timeout=60)
            ok = bool(res.get("ok"))
        except Exception as e:
            ok = False
            try:
                self.app.logger.warning("ComfyUI 启动失败: %s", e)
            except Exception:
                pass
        if not ok:
            QtWidgets.QMessageBox.warning(
                self, "ComfyUI 启动失败",
                "ComfyUI 启动失败, WebUI 不启动。\n请查看 ComfyUI 日志排查。",
            )
            return
        self._start_webui(with_comfyui=False)

    def _start_webui(self, with_comfyui: bool):
        """后台启 WebUI."""
        info = self._resolve_paths()
        if self._pm is None:
            self._pm = WebuiProcessManager(self.app)
        self._state = STATE_STARTING
        self._update_ui_for_state()

        def _worker():
            res = self._pm.start_webui(timeout=60)
            # 回到 UI 线程刷新
            if res.get("ok"):
                self._state = STATE_RUNNING
            else:
                # 启失败, 回到 ready
                self._state = STATE_READY
            QtCore.QMetaObject.invokeMethod(
                self, "_after_action_done",
                QtCore.Qt.QueuedConnection,
            )
            err = res.get("error")
            if err:
                QtWidgets.QMessageBox.warning(
                    None, "WebUI 启动失败",
                    "WebUI 启动失败: %s\n\n请查看 launcher/webui.log" % err,
                )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _stop_webui(self):
        if self._pm is None:
            self._pm = WebuiProcessManager(self.app)
        self._state = STATE_STOPPING
        self._update_ui_for_state()

        def _worker():
            self._pm.stop_webui(timeout=10)
            self._state = STATE_READY
            QtCore.QMetaObject.invokeMethod(
                self, "_after_action_done",
                QtCore.Qt.QueuedConnection,
            )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    @QtCore.pyqtSlot()
    def _after_action_done(self):
        self._refresh_state()

    def _on_open_browser(self):
        info = self._resolve_paths()
        url = "http://%s:%s/" % (info["display_host"], info["port"])
        try:
            webbrowser.open(url)
        except Exception as e:
            try:
                self.app.logger.warning("打开浏览器失败: %s", e)
            except Exception:
                pass

    def _download_webui(self):
        """下载 (git clone) + 完成后自动 setup deps."""
        info = self._resolve_paths()
        webui_path = info["webui_path"]
        if not webui_path:
            return

        download_url = info["download_url"]

        self._state = STATE_STARTING
        self._btn_primary.setText("⏳ 下载中...")
        self._btn_primary.setEnabled(False)

        def _worker():
            try:
                res = clone_webui(self.app, webui_path, repo_url=download_url)
            except Exception as e:
                res = {"ok": False, "error": str(e)}
            if not res.get("ok"):
                QtCore.QMetaObject.invokeMethod(
                    self, "_after_download",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, "下载失败: " + (res.get("error") or "未知")),
                )
                return
            # 成功, 自动 setup deps
            try:
                self._setup_deps(silent=True)
            except Exception:
                pass
            QtCore.QMetaObject.invokeMethod(
                self, "_after_download",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, "下载完成"),
            )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    @QtCore.pyqtSlot(str)
    def _after_download(self, msg: str):
        if msg.startswith("下载失败"):
            self._state = STATE_NOT_INSTALLED
            QtWidgets.QMessageBox.warning(self, "下载失败", msg)
        self._refresh_state()

    def _setup_deps(self, silent: bool = False):
        """装依赖 (BackgroundTask 风格)."""
        info = self._resolve_paths()
        py = info["python_path"]
        req = info["webui_path"] / "requirements.txt" if info["webui_path"] else None
        if not py or not py.exists():
            self._state = STATE_NO_DEPS
            if not silent:
                QtWidgets.QMessageBox.warning(
                    self, "Python 不可用",
                    "Python 路径无效: %s" % py,
                )
            self._refresh_state()
            return
        if not req or not req.exists():
            self._state = STATE_NO_DEPS
            if not silent:
                QtWidgets.QMessageBox.warning(
                    self, "requirements.txt 不存在",
                    "WebUI 目录里没找到 requirements.txt: %s" % req,
                )
            self._refresh_state()
            return

        # 走 pypi proxy (统一走 utils.net.resolve_pypi_index_url)
        idx_url = resolve_pypi_index_url(self.app)

        self._state = STATE_STARTING
        self._btn_primary.setText("⏳ 安装依赖中...")
        self._btn_primary.setEnabled(False)

        def _worker():
            res = install_webui_requirements(py, req, index_url=idx_url)
            ok = res.get("ok") is True
            # 回到 UI 线程
            QtCore.QMetaObject.invokeMethod(
                self, "_after_setup",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(bool, ok),
                QtCore.Q_ARG(str, res.get("error") or ""),
            )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    @QtCore.pyqtSlot(bool, str)
    def _after_setup(self, ok: bool, err: str):
        if not ok:
            QtWidgets.QMessageBox.warning(
                self, "依赖安装失败",
                "pip install 失败: %s\n\n请查看 launcher/webui.log" % (err or "未知"),
            )
        # 依赖刚装过, 失效探测缓存 (下次 _detect_state 重新探测)
        self._deps_cache_key = None
        self._deps_cache_result = None
        self._refresh_state()

    def _on_config_clicked(self):
        """配置 dialog: 改 webui_options."""
        info = self._resolve_paths()
        dlg = WebuiConfigDialog(
            self,
            initial=info,
            theme_manager=self.theme_manager,
        )
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            new_options = dlg.get_values()
            try:
                cfg = getattr(self.app, "config", None)
                if isinstance(cfg, dict):
                    cfg["webui_options"] = new_options
                    # 持久化
                    if hasattr(self.app, "services") and getattr(self.app.services, "config", None):
                        saved = self.app.services.config.save(cfg)
                        if saved is not None:
                            self.app.config = saved
            except Exception as e:
                try:
                    self.app.logger.warning("保存 webui_options 失败: %s", e)
                except Exception:
                    pass
            self._refresh_state()

    # ---------------- 日志 ----------------
    def _refresh_log(self):
        info = self._resolve_paths()
        log_path = Path(self.app._cwd) / "launcher" / "webui.log" if hasattr(self.app, "_cwd") else Path("launcher/webui.log")
        if not log_path.exists():
            self._log_view.setPlainText("# 日志文件不存在 (webui 还没启动过或路径未配置)\n")
            return
        try:
            # 读最后 200 行
            with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            tail = lines[-200:]
            self._log_view.setPlainText("".join(tail))
            # 滚到底
            sb = self._log_view.verticalScrollBar()
            sb.setValue(sb.maximum())
        except Exception as e:
            self._log_view.setPlainText("# 读取日志失败: %s\n" % e)

    def _open_log_file(self):
        log_path = Path(self.app._cwd) / "launcher" / "webui.log" if hasattr(self.app, "_cwd") else Path("launcher/webui.log")
        try:
            if sys.platform == "win32":
                os.startfile(str(log_path.parent))
            else:
                webbrowser.open("file://" + str(log_path))
        except Exception:
            pass

    # ---------------- 外部 hook ----------------
    def refresh_after_env_switch(self):
        """env 切换后刷新 (QtApp.refresh_after_env_switch 调)."""
        try:
            # env 换了, py/webui_path 可能变, 失效探测缓存
            self._deps_cache_key = None
            self._deps_cache_result = None
            self._refresh_state()
        except Exception:
            pass


class WebuiConfigDialog(QtWidgets.QDialog):
    """WebUI 配置: port / display_host / auto_open_browser / download_url."""

    def __init__(self, parent, initial: dict, theme_manager):
        super().__init__(parent)
        self.setWindowTitle("WebUI 配置")
        self.setMinimumWidth(420)
        self._initial = initial
        self._theme_manager = theme_manager

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # port
        self._port_input = QtWidgets.QSpinBox()
        self._port_input.setRange(1024, 65535)
        self._port_input.setValue(int(initial.get("port") or 8199))
        form_layout = QtWidgets.QFormLayout()
        form_layout.addRow("端口:", self._port_input)
        layout.addLayout(form_layout)

        # display_host
        self._host_input = QtWidgets.QLineEdit(str(initial.get("display_host") or "127.0.0.1"))
        form_layout.addRow("监听地址:", self._host_input)

        # auto_open_browser
        self._auto_open_check = QtWidgets.QCheckBox("启动后自动打开浏览器")
        self._auto_open_check.setChecked(bool(initial.get("auto_open", False)))
        layout.addWidget(self._auto_open_check)

        # download_url
        self._url_input = QtWidgets.QLineEdit(str(initial.get("download_url") or ""))
        form_layout.addRow("Git 仓库 URL:", self._url_input)

        # extra_args
        self._extra_args = QtWidgets.QLineEdit(str(initial.get("extra_args") or ""))
        form_layout.addRow("附加参数 (透传给 app.flask_app):", self._extra_args)

        # 提示
        info_label = QtWidgets.QLabel(
            "提示: 端口 / 监听 / Git URL / 额外参数写在这里, 依赖安装 / 下载复用现有 "
            "github proxy + pypi proxy 配置。"
        )
        info_label.setStyleSheet('font: 9pt "Microsoft YaHei UI"; color: #888;')
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # 按钮
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_values(self) -> dict:
        return {
            "port": int(self._port_input.value()),
            "display_host": self._host_input.text().strip() or "127.0.0.1",
            "auto_open_browser": bool(self._auto_open_check.isChecked()),
            "download_url": self._url_input.text().strip()
                or "https://github.com/MieMieeeee/Comfyui-Workbench-Mie.git",
            "extra_args": self._extra_args.text().strip(),
        }
