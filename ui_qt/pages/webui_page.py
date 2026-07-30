"""WebUI工作台页面 (Comfyui-Workbench-Mie 启停 / 配置 / 更新 / 日志).

布局 (仿首页 launch_page 左右结构):
  状态卡 (圆点 + 文案 + 刷新)              <- 横跨顶部
  ┌ 启动控制 (端口/监听/自动打开) ┐ ┌─右侧按钮列─┐
  │  (左, stretch 1)              │ │ [一键启动] │  <- 大按钮
  │                               │ │ [打开网页] │  <- 竖排
  └───────────────────────────────┘ │ [更新]     │
                                     └────────────┘
  日志 (launcher/webui.log, 实时 tail)  <- 底部, 与实时日志页一致

状态机:
  not_installed -> [下载WebUI工作台]  打开网页/更新禁用
  no_deps       -> [安装依赖]         打开网页/更新禁用
  ready         -> [一键启动]         打开网页/更新可用
  running       -> [停止]             打开网页可用 / 更新禁用

主题: 全部走 theme_manager (跟 launch_page 一致), 实现 update_theme 响应深/浅切换.
配置: 直接读写 config["webui_options"] + app.services.config.save (webui 无 app Var).
日志: 复用 ui_qt.log_viewer.LogTailer (后台线程 + Qt 信号 + 50ms 批量渲染), 与实时日志页一致.
弹窗: 走共享 DialogHelper / CustomConfirmDialog, 不用原生 QMessageBox.
"""
from __future__ import annotations

import os
import sys
import subprocess
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
from ui_qt.widgets.dialog_helper import DialogHelper
from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
from ui_qt.widgets.custom import NoWheelComboBox
from ui_qt.log_viewer import LogTailer, read_tail_lines


STATE_NOT_INSTALLED = "not_installed"
STATE_NO_DEPS = "no_deps"
STATE_READY = "ready"
STATE_RUNNING = "running"
STATE_STARTING = "starting"
STATE_STOPPING = "stopping"

# 状态圆点配色: 项目主题没有 green/blue 状态 token, 用固定现代色板.
# 深色版用 500 档 (明亮), 浅色版用 600 档 (加深保证对比度), 在 update_theme 里切换.
_STATE_COLORS_DARK = {
    STATE_NOT_INSTALLED: "#EF4444",  # 红
    STATE_NO_DEPS: "#F59E0B",        # 黄
    STATE_READY: "#10B981",          # 绿
    STATE_RUNNING: "#10B981",
    STATE_STARTING: "#3B82F6",       # 蓝
    STATE_STOPPING: "#3B82F6",
}
_STATE_COLORS_LIGHT = {
    STATE_NOT_INSTALLED: "#DC2626",
    STATE_NO_DEPS: "#D97706",
    STATE_READY: "#059669",
    STATE_RUNNING: "#059669",
    STATE_STARTING: "#2563EB",
    STATE_STOPPING: "#2563EB",
}

# 自动打开浏览器三选项 (跟首页 launch_controls_section 一致: disable/default/webbrowser)
_BROWSER_OPEN_OPTS = [
    ("不自动打开", "disable"),
    ("使用默认浏览器", "default"),
    ("使用指定浏览器", "webbrowser"),
]

# 日志: 历史回填行数 + 批量渲染间隔 (与实时日志页 LogViewerPage 一致)
_RECENT_HISTORY_LINES = 500
_BATCH_INTERVAL_MS = 50
_MAX_LOG_LINES = 5000


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
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("WORKBENCH_VERSION"):
            parts = s.split("=", 1)
            if len(parts) == 2:
                v = parts[1].strip().strip("'").strip('"')
                if v:
                    return v
    return None


class _LineEmitter(QtCore.QObject):
    """tailer 线程 → UI 线程的行投递信号桥 (复刻 log_viewer)."""
    line_received = QtCore.pyqtSignal(str)


class WebuiPage(BasePage):
    """WebUI工作台 启停 / 配置 / 更新 / 日志."""

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self.theme_manager = theme_manager
        self._state: str = STATE_NOT_INSTALLED
        self._state_check_timer = None
        self._pm: Optional[WebuiProcessManager] = None
        self._updating = False  # 更新进行中标志 (禁用按钮)
        # 依赖探测缓存: 同一 (py, webui_path) 不重复 spawn 3 个 python 子进程.
        # 失效点: _after_setup / refresh_after_env_switch (路径或依赖可能变).
        self._deps_cache_key: Optional[tuple] = None
        self._deps_cache_result: Optional[dict] = None
        # 日志实时 tail 状态 (复刻 LogViewerPage)
        self._tailer: Optional[LogTailer] = None
        self._emitter: Optional[_LineEmitter] = None
        self._batch_buffer: list[str] = []
        self._batch_timer: Optional[QtCore.QTimer] = None
        self._log_path: Optional[Path] = None
        self._history_loaded = False
        self._setup_ui()
        self._refresh_state()
        self._start_log_tail()

    # ---------------- 主题 helper ----------------
    def _c(self, key: str, default: str = "") -> str:
        """读 theme_manager.colors token (含缺失兜底)."""
        try:
            return self.theme_manager.colors.get(key, default)
        except Exception:
            return default

    def _state_color(self, state: str) -> str:
        """按当前深/浅主题选状态圆点色."""
        is_dark = bool(getattr(self.theme_manager, "is_dark", True))
        palette = _STATE_COLORS_DARK if is_dark else _STATE_COLORS_LIGHT
        return palette.get(state, self._c("label_dim", "#888"))

    def _log_view_style(self) -> str:
        """日志视图 QSS: 走 input_readonly_* token (深浅自适应), 终端字体保留."""
        return (
            "QPlainTextEdit {"
            f"  background-color: {self._c('input_readonly_bg', '#1F2937')};"
            f"  color: {self._c('input_readonly_text', '#9CA3AF')};"
            "  font: 9pt 'Consolas';"
            f"  border: 1px solid {self._c('input_border', '#4B5563')};"
            "  border-radius: 6px;"
            "}"
        )

    def _label_muted_style(self) -> str:
        return (
            f'font: 9pt "Microsoft YaHei UI"; color: {self._c("label_muted", "#9CA3AF")};'
        )

    def _status_text_style(self) -> str:
        return (
            f'font: bold 11pt "Microsoft YaHei UI"; color: {self._c("label", "#E5E7EB")};'
        )

    def _config_label_style(self) -> str:
        """配置项标签样式 (复刻首页 lbl_style: label_muted + bold)."""
        return f'color: {self._c("label_muted", "#9CA3AF")}; font-weight: bold;'

    # ---------------- 配置读写 (直接读写 config["webui_options"]) ----------------
    def _webui_options(self) -> dict:
        cfg = getattr(self.app, "config", None)
        if isinstance(cfg, dict):
            return cfg.get("webui_options") or {}
        return {}

    def _save_webui_option(self, key, value) -> None:
        """写单个 webui_options 字段并持久化."""
        try:
            cfg = getattr(self.app, "config", None)
            if not isinstance(cfg, dict):
                return
            opts = cfg.setdefault("webui_options", {})
            opts[key] = value
            svc = getattr(self.app, "services", None)
            cfg_mgr = getattr(svc, "config", None) if svc else None
            if cfg_mgr is not None:
                saved = cfg_mgr.save(cfg)
                if saved is not None:
                    self.app.config = saved
        except Exception as e:
            try:
                self.app.logger.warning("保存 webui_options.%s 失败: %s", key, e)
            except Exception:
                pass

    # ---------------- 主 UI ----------------
    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # === 状态卡 (横跨顶部) ===
        status_group = QtWidgets.QGroupBox("WebUI工作台状态")
        status_layout = QtWidgets.QHBoxLayout(status_group)
        status_layout.setContentsMargins(10, 8, 10, 8)
        status_layout.setSpacing(12)

        self._status_dot = QtWidgets.QLabel()
        self._status_dot.setFixedSize(20, 20)
        status_layout.addWidget(self._status_dot)

        self._status_text = QtWidgets.QLabel("检测中...")
        self._status_text.setStyleSheet(self._status_text_style())
        status_layout.addWidget(self._status_text, 1)

        self._btn_refresh = QtWidgets.QPushButton("🔄 刷新")
        self._btn_refresh.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_refresh.clicked.connect(self._refresh_state)
        status_layout.addWidget(self._btn_refresh)

        layout.addWidget(status_group)

        # === 顶部行: 左启动控制 + 右按钮列 (仿 launch_page top_row) ===
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(15)
        layout.addLayout(top_row)

        # --- 左: 启动控制 (端口 / 允许局域网访问 / 自动打开浏览器) ---
        form_group = QtWidgets.QGroupBox("启动控制")
        form_layout = QtWidgets.QGridLayout(form_group)
        form_layout.setColumnStretch(1, 1)
        form_layout.setHorizontalSpacing(20)
        form_layout.setVerticalSpacing(8)
        form_layout.setContentsMargins(8, 12, 8, 12)
        top_row.addWidget(form_group, 1)

        lbl_style = self._config_label_style()

        # 端口号 + 允许局域网访问 (同一行 HBox, 复刻 launch_controls_section)
        port_label = QtWidgets.QLabel("端口号：")
        port_label.setStyleSheet(lbl_style)
        self._port_edit = QtWidgets.QLineEdit()
        self._port_edit.setFixedWidth(60)
        self._port_edit.setText(str(self._webui_options().get("port") or 8199))
        self._port_edit.setToolTip("WebUI工作台服务端口，默认8199")
        self._port_edit.textChanged.connect(
            lambda v: self._save_webui_option("port", v.strip() or "8199")
        )

        self._listen_chk = QtWidgets.QCheckBox("允许局域网访问")
        listen_lan = bool(self._webui_options().get("listen_lan", False))
        self._listen_chk.setChecked(listen_lan)
        self._listen_chk.setToolTip("允许局域网内其他设备访问 WebUI工作台")
        self._listen_chk.toggled.connect(self._on_listen_toggled)

        hbox_port = QtWidgets.QHBoxLayout()
        hbox_port.setContentsMargins(0, 0, 0, 0)
        hbox_port.setSpacing(15)
        hbox_port.addWidget(port_label)
        hbox_port.addWidget(self._port_edit)
        hbox_port.addWidget(self._listen_chk)
        hbox_port.addStretch(1)
        form_layout.addLayout(hbox_port, 0, 0, 1, 2)

        # 自动打开浏览器 (三选下拉 + 指定浏览器路径按钮)
        open_label = QtWidgets.QLabel("自动打开浏览器：")
        open_label.setStyleSheet(lbl_style)
        self._open_combo = NoWheelComboBox()
        for name, val in _BROWSER_OPEN_OPTS:
            self._open_combo.addItem(name, val)
        cur_mode = self._webui_options().get("browser_open_mode") or "default"
        for i, (name, val) in enumerate(_BROWSER_OPEN_OPTS):
            if val == cur_mode:
                self._open_combo.setCurrentIndex(i)
                break
        self._open_combo.currentIndexChanged.connect(self._on_open_mode_changed)
        self._open_combo.setToolTip("启动后自动打开浏览器访问 WebUI工作台")

        self._cpath_btn = QtWidgets.QPushButton()
        self._cpath_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._cpath_btn.setFixedWidth(32)
        try:
            self._cpath_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DirOpenIcon))
            self._cpath_btn.setIconSize(QtCore.QSize(14, 14))
        except Exception:
            pass
        self._cpath_btn.clicked.connect(self._on_pick_browser_path)

        row_open = QtWidgets.QHBoxLayout()
        row_open.setContentsMargins(0, 0, 0, 0)
        row_open.setSpacing(8)
        row_open.addWidget(self._open_combo)
        row_open.addWidget(self._cpath_btn)
        row_open.addStretch(1)

        form_layout.addWidget(open_label, 1, 0)
        form_layout.addLayout(row_open, 1, 1)

        # --- 右: 按钮列 (固定宽 200px, 仿 launch_page right_container) ---
        right_container = QtWidgets.QWidget()
        right_container.setFixedWidth(200)
        right_layout = QtWidgets.QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        top_row.addWidget(right_container, 0)

        # 启动/停止 大按钮 (随状态变文字)
        self._btn_primary = QtWidgets.QPushButton()
        self._btn_primary.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_primary.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self._btn_primary.clicked.connect(self._on_primary_clicked)
        self._btn_primary.setMinimumHeight(60)
        right_layout.addWidget(self._btn_primary, 4)

        # 底部横排: 打开网页 + 更新 (复刻 launch_page bottom_row)
        bottom_row = QtWidgets.QWidget()
        bottom_layout = QtWidgets.QHBoxLayout(bottom_row)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(4)

        self._btn_open = QtWidgets.QPushButton("🌐 打开网页")
        self._btn_open.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_open.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self._btn_open.setMinimumHeight(40)
        self._btn_open.clicked.connect(self._on_open_browser)
        bottom_layout.addWidget(self._btn_open)

        self._btn_update = QtWidgets.QPushButton("🔄 更新")
        self._btn_update.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_update.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self._btn_update.setMinimumHeight(40)
        self._btn_update.clicked.connect(self._on_update_clicked)
        self._btn_update.setToolTip("git pull 更新 WebUI工作台到最新版本")
        bottom_layout.addWidget(self._btn_update)

        right_layout.addWidget(bottom_row, 1)

        # === 日志区域 (实时 tail, 与实时日志页一致) ===
        log_group = QtWidgets.QGroupBox("日志 (launcher/webui.log)")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(4)

        self._log_view = QtWidgets.QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(_MAX_LOG_LINES)
        log_layout.addWidget(self._log_view)

        log_toolbar = QtWidgets.QHBoxLayout()
        log_toolbar.setSpacing(4)
        self._btn_log_clear = QtWidgets.QPushButton("🧹 清空")
        self._btn_log_clear.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_log_clear.clicked.connect(self._on_clear_log)
        log_toolbar.addWidget(self._btn_log_clear)

        self._btn_log_open = QtWidgets.QPushButton("📂 打开日志文件")
        self._btn_log_open.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_log_open.clicked.connect(self._open_log_file)
        log_toolbar.addWidget(self._btn_log_open)
        log_toolbar.addStretch(1)
        log_layout.addLayout(log_toolbar)

        layout.addWidget(log_group, 1)
        layout.addSpacing(4)

        # 注册状态定时器 (5s)
        self._state_check_timer = QtCore.QTimer(self)
        self._state_check_timer.timeout.connect(self._poll_status)
        self._state_check_timer.start(5000)

        # 应用初始主题
        self.update_theme()

    # ---------------- 配置控件回调 ----------------
    def _on_listen_toggled(self, checked: bool) -> None:
        """允许局域网访问勾选框: 隐式决定 display_host (勾=0.0.0.0 / 不勾=127.0.0.1)."""
        self._save_webui_option("listen_lan", bool(checked))
        self._save_webui_option("display_host", "0.0.0.0" if checked else "127.0.0.1")

    def _on_open_mode_changed(self, idx: int) -> None:
        mode = _BROWSER_OPEN_OPTS[idx][1] if 0 <= idx < len(_BROWSER_OPEN_OPTS) else "default"
        self._save_webui_option("browser_open_mode", mode)
        self._update_cpath_vis()

    def _update_cpath_vis(self) -> None:
        """指定浏览器路径按钮仅在 webbrowser 模式可见 (复刻 launch_controls_section)."""
        try:
            is_custom = (self._open_combo.currentData() == "webbrowser")
            self._cpath_btn.setVisible(is_custom)
        except Exception:
            pass

    def _on_pick_browser_path(self) -> None:
        """选自定义浏览器 exe 路径."""
        cur = self._webui_options().get("custom_browser_path") or ""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择浏览器", cur or "", "可执行文件 (*.exe);;所有文件 (*)"
        )
        if path:
            self._save_webui_option("custom_browser_path", path)

    # ---------------- 主题切换 ----------------
    def _on_theme_changed(self, theme_styles):
        self.update_theme(theme_styles)

    def update_theme(self, theme_styles=None):
        """重应用所有主题化控件 QSS (响应深/浅切换)."""
        super().update_theme(theme_styles)
        styles = theme_styles if theme_styles is not None else self.theme_manager.styles
        input_ss = styles.input_style()
        primary_ss = styles.primary_button_style()
        # 按钮
        self._btn_primary.setStyleSheet(primary_ss)
        self._btn_open.setStyleSheet(primary_ss)
        self._btn_update.setStyleSheet(primary_ss)
        self._btn_refresh.setStyleSheet(styles.secondary_button_style())
        self._btn_log_clear.setStyleSheet(styles.secondary_button_style())
        self._btn_log_open.setStyleSheet(styles.secondary_button_style())
        # 输入控件
        self._port_edit.setStyleSheet(input_ss)
        self._open_combo.setStyleSheet(input_ss)
        self._cpath_btn.setStyleSheet(input_ss)
        # 文本/日志
        self._log_view.setStyleSheet(self._log_view_style())
        self._status_text.setStyleSheet(self._status_text_style())
        self._update_cpath_vis()
        # 状态圆点颜色重算 (深/浅版不同)
        self._refresh_state()

    # ---------------- 状态探测 ----------------
    def _resolve_paths(self) -> dict:
        """返回 webui 路径 + python 路径 + 端口等."""
        cfg = getattr(self.app, "config", None)
        webui_options = (cfg or {}).get("webui_options") or {}
        port = int(webui_options.get("port") or 8199)
        if "listen_lan" in webui_options:
            display_host = "0.0.0.0" if webui_options.get("listen_lan") else "127.0.0.1"
        else:
            display_host = webui_options.get("display_host") or "127.0.0.1"
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
            "download_url": download_url,
        }

    def _detect_state(self) -> str:
        """综合判定当前状态."""
        info = self._resolve_paths()
        webui_path = info["webui_path"]
        py_path = info["python_path"]

        if self._pm is None:
            self._pm = WebuiProcessManager(self.app)
        running = self._pm.is_running()
        if running:
            return STATE_RUNNING

        if webui_path is None or not webui_path.exists():
            return STATE_NOT_INSTALLED
        if not (webui_path / "app" / "flask_app.py").exists():
            return STATE_NOT_INSTALLED

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

    def _poll_status(self):
        """定时器: running 状态会变, 勤跑探测."""
        try:
            new_state = self._detect_state()
            if new_state != self._state:
                self._state = new_state
                self._update_ui_for_state()
        except Exception:
            pass

    def _update_ui_for_state(self):
        color = self._state_color(self._state)
        self._status_dot.setStyleSheet(
            "background-color: %s; border-radius: 10px;" % color
        )

        info = self._resolve_paths()
        webui_path = info["webui_path"]
        version = _read_workbench_version(webui_path) if webui_path else None

        # 状态文案: 只留一句话描述, 不带路径/操作提示 (按需求精简)
        if self._state == STATE_NOT_INSTALLED:
            txt = "WebUI工作台未安装"
        elif self._state == STATE_NO_DEPS:
            txt = "待安装依赖"
        elif self._state == STATE_READY:
            v_str = " v" + version if version else ""
            txt = "WebUI工作台就绪" + v_str
        elif self._state == STATE_RUNNING:
            txt = "工作中"
        else:
            txt = self._state

        self._status_text.setText(txt)

        # 主按钮 (随状态变文字)
        if self._state == STATE_NOT_INSTALLED:
            self._btn_primary.setText("⬇ 下载WebUI工作台")
            self._btn_primary.setEnabled(True)
        elif self._state == STATE_NO_DEPS:
            self._btn_primary.setText("⚙ 安装依赖")
            self._btn_primary.setEnabled(True)
        elif self._state == STATE_READY:
            self._btn_primary.setText("🚀 一键启动")
            self._btn_primary.setEnabled(True)
        elif self._state == STATE_RUNNING:
            self._btn_primary.setText("⏹ 停止")
            self._btn_primary.setEnabled(True)
        else:
            self._btn_primary.setText("...")
            self._btn_primary.setEnabled(False)

        # 打开网页按钮: 仅 running 可用 (没跑起来打开无意义)
        self._btn_open.setEnabled(self._state == STATE_RUNNING)
        # 更新按钮: 仅 ready (已安装未跑) 可用; 更新中/启动停止中禁用
        self._btn_update.setEnabled(self._state == STATE_READY and not self._updating)

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

    def _on_update_clicked(self):
        """更新按钮: git pull WebUI工作台."""
        if self._updating:
            return
        info = self._resolve_paths()
        webui_path = info["webui_path"]
        if not webui_path or not webui_path.exists():
            DialogHelper.show_warning(self, "无法更新", "WebUI工作台尚未安装，请先下载。")
            return
        if not (webui_path / ".git").exists():
            DialogHelper.show_warning(self, "无法更新", "WebUI工作台目录不是 git 仓库，无法更新。")
            return

        self._updating = True
        self._btn_update.setText("更新中…")
        self._btn_update.setEnabled(False)

        def _worker():
            try:
                res = pull_webui(self.app, webui_path)
            except Exception as e:
                res = {"ok": False, "error": str(e), "updated": False}
            updated = bool(res.get("updated"))
            ok = bool(res.get("ok"))
            QtCore.QMetaObject.invokeMethod(
                self, "_after_update",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(bool, ok),
                QtCore.Q_ARG(bool, updated),
                QtCore.Q_ARG(str, res.get("error") or ""),
            )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    @QtCore.pyqtSlot(bool, bool, str)
    def _after_update(self, ok: bool, updated: bool, err: str):
        self._updating = False
        self._btn_update.setText("🔄 更新")
        self._refresh_state()
        if not ok:
            DialogHelper.show_warning(self, "更新失败", "git pull 失败: %s" % (err or "未知"))
        elif updated:
            DialogHelper.show_info(self, "更新完成", "WebUI工作台已更新到最新版本。")
        else:
            DialogHelper.show_info(self, "已是最新", "WebUI工作台已是最新版本。")

    def _start_with_prompt(self):
        """弹 3 选 1 dialog: 同时启动 / 只启 WebUI工作台 / 取消."""
        if self._is_comfyui_running():
            self._start_webui(with_comfyui=False)
            return

        dlg = CustomConfirmDialog(
            parent=self,
            title="启动 WebUI工作台",
            content=(
                "WebUI工作台是以 ComfyUI 为后台运行工作流的。\n"
                "ComfyUI 当前未在跑, 提交任务时会失败。\n\n"
                "请选择启动方式:"
            ),
            buttons=[
                {"text": "取消", "role": "normal"},
                {"text": "只启动 WebUI工作台", "role": "destructive"},
                {"text": "同时启动 ComfyUI + WebUI工作台", "role": "primary"},
            ],
            default_index=2,
            theme_manager=self.theme_manager,
        )
        dlg.exec_()
        result = dlg.get_result()
        if result == 2:
            self._start_comfyui_then_webui()
        elif result == 1:
            self._start_webui(with_comfyui=False)

    def _is_comfyui_running(self) -> bool:
        """ComfyUI 是否在跑 (HTTP 探活 + pidfile)."""
        try:
            from core.cli.runner import service_status
            st = service_status(self.app) or {}
            return bool(st.get("running"))
        except Exception:
            return False

    def _start_comfyui_then_webui(self):
        """先启 ComfyUI (同步), 成功后再启 WebUI工作台."""
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
            DialogHelper.show_warning(
                self, "ComfyUI 启动失败",
                "ComfyUI 启动失败, WebUI工作台不启动。\n请查看 ComfyUI 日志排查。",
            )
            return
        self._start_webui(with_comfyui=False)

    def _start_webui(self, with_comfyui: bool):
        """后台启 WebUI工作台."""
        if self._pm is None:
            self._pm = WebuiProcessManager(self.app)
        self._state = STATE_STARTING
        self._update_ui_for_state()

        def _worker():
            res = self._pm.start_webui(timeout=60)
            if res.get("ok"):
                self._state = STATE_RUNNING
                if self._should_auto_open():
                    info = self._resolve_paths()
                    self._open_url("http://%s:%s/" % (info["display_host"], info["port"]))
            else:
                self._state = STATE_READY
            QtCore.QMetaObject.invokeMethod(
                self, "_after_action_done",
                QtCore.Qt.QueuedConnection,
            )
            err = res.get("error")
            if err:
                DialogHelper.show_warning(
                    None, "WebUI工作台启动失败",
                    "WebUI工作台启动失败: %s\n\n请查看 launcher/webui.log" % err,
                )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _should_auto_open(self) -> bool:
        """是否启动后自动打开浏览器 (browser_open_mode != disable)."""
        mode = self._webui_options().get("browser_open_mode")
        if mode is None:
            return bool(self._webui_options().get("auto_open_browser", False))
        return mode != "disable"

    def _open_url(self, url: str) -> None:
        """按 browser_open_mode 打开 URL (disable/default/webbrowser)."""
        opts = self._webui_options()
        mode = opts.get("browser_open_mode") or "default"
        if mode == "disable":
            return
        if mode == "webbrowser":
            cpath = (opts.get("custom_browser_path") or "").strip()
            if cpath and os.path.exists(cpath):
                try:
                    subprocess.Popen([cpath, url])
                    return
                except Exception as e:
                    try:
                        self.app.logger.warning("用指定浏览器打开失败: %s, 回退默认", e)
                    except Exception:
                        pass
        try:
            webbrowser.open(url)
        except Exception as e:
            try:
                self.app.logger.warning("打开浏览器失败: %s", e)
            except Exception:
                pass

    def _on_open_browser(self):
        """打开网页按钮."""
        info = self._resolve_paths()
        self._open_url("http://%s:%s/" % (info["display_host"], info["port"]))

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
            DialogHelper.show_warning(self, "下载失败", msg)
        self._refresh_state()

    def _setup_deps(self, silent: bool = False):
        """装依赖 (BackgroundTask 风格)."""
        info = self._resolve_paths()
        py = info["python_path"]
        req = info["webui_path"] / "requirements.txt" if info["webui_path"] else None
        if not py or not py.exists():
            self._state = STATE_NO_DEPS
            if not silent:
                DialogHelper.show_warning(self, "Python 不可用", "Python 路径无效: %s" % py)
            self._refresh_state()
            return
        if not req or not req.exists():
            self._state = STATE_NO_DEPS
            if not silent:
                DialogHelper.show_warning(
                    self, "requirements.txt 不存在",
                    "WebUI工作台目录里没找到 requirements.txt: %s" % req,
                )
            self._refresh_state()
            return

        idx_url = resolve_pypi_index_url(self.app)

        self._state = STATE_STARTING
        self._btn_primary.setText("⏳ 安装依赖中...")
        self._btn_primary.setEnabled(False)

        def _worker():
            res = install_webui_requirements(py, req, index_url=idx_url)
            ok = res.get("ok") is True
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
            DialogHelper.show_warning(
                self, "依赖安装失败",
                "pip install 失败: %s\n\n请查看 launcher/webui.log" % (err or "未知"),
            )
        # 依赖刚装过, 失效探测缓存 (下次 _detect_state 重新探测)
        self._deps_cache_key = None
        self._deps_cache_result = None
        self._refresh_state()

    # ---------------- 日志 (实时 tail, 复刻 LogViewerPage) ----------------
    def _resolve_log_path(self) -> Path:
        try:
            cwd = Path(getattr(self.app, "_cwd", ".") or ".")
        except Exception:
            cwd = Path(".")
        return cwd / "launcher" / "webui.log"

    def showEvent(self, event):
        """页面首次显示时按需加载最近历史 (之后靠 tailer 跟随)."""
        super().showEvent(event)
        if not self._history_loaded:
            self._history_loaded = True
            try:
                self._load_recent_history()
            except Exception:
                pass

    def _load_recent_history(self):
        """读日志文件最后 N 行批量填进视图 (复刻 LogViewerPage)."""
        path = self._log_path
        if path is None:
            return
        try:
            lines = read_tail_lines(path, _RECENT_HISTORY_LINES)
        except Exception:
            return
        for line in lines:
            self._enqueue_batch(line)

    def _start_log_tail(self) -> None:
        """启动 tailer (从 EOF 跟新行). 复刻 LogViewerPage.start_tailing."""
        self._log_path = self._resolve_log_path()
        if self._log_path is None:
            return
        if self._tailer is not None:
            return
        self._tailer = LogTailer(
            self._log_path,
            on_line=self._on_line_from_tailer,
            start_from_beginning=False,
        )
        # 每次启动用全新 emitter (1:1 与 tailer 生命周期), 避免 disconnect 静默失败导致重复渲染
        self._emitter = _LineEmitter()
        self._emitter.line_received.connect(
            self._on_line_main,
            QtCore.Qt.QueuedConnection | QtCore.Qt.UniqueConnection,
        )
        self._tailer.start()

    def _stop_log_tail(self) -> None:
        """停止 tailer (清 tailer + emitter 引用). 复刻 LogViewerPage.stop_tailing."""
        if self._tailer is not None:
            try:
                self._tailer.stop()
            except Exception:
                pass
            self._tailer = None
        self._emitter = None

    def _on_line_from_tailer(self, line: str) -> None:
        """tailer 线程回调: 通过 signal 投到 UI 线程. stop 后丢弃尾包."""
        emitter = self._emitter
        if emitter is None:
            return
        emitter.line_received.emit(line)

    def _on_line_main(self, line: str) -> None:
        """UI 线程: 入批量缓冲 (50ms 定时器统一 flush)."""
        self._enqueue_batch(line)

    def _enqueue_batch(self, line) -> None:
        """行入缓冲, 启动 50ms 定时器统一 flush (复刻 LogViewerPage)."""
        if line is not None:
            self._batch_buffer.append(line)
        if self._batch_timer is None:
            self._batch_timer = QtCore.QTimer(self)
            self._batch_timer.setSingleShot(True)
            self._batch_timer.timeout.connect(self._flush_batch)
        if not self._batch_timer.isActive():
            self._batch_timer.start(_BATCH_INTERVAL_MS)

    def _flush_batch(self) -> None:
        """把缓冲行一次性 insertText + 滚到底 (一次 DOM 写入, 复刻 LogViewerPage)."""
        if not self._batch_buffer:
            return
        text = "\n".join(self._batch_buffer)
        self._batch_buffer.clear()
        cursor = self._log_view.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText(text + "\n")
        bar = self._log_view.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def _on_clear_log(self):
        """清空日志视图."""
        self._log_view.clear()

    def _open_log_file(self):
        log_path = self._resolve_log_path()
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
            # 日志 tailer 重定向到新路径 (复刻 qt_app 对 LogViewerPage 的处理)
            self._stop_log_tail()
            self._history_loaded = False
            self._log_view.clear()
            self._log_path = self._resolve_log_path()
            self._start_log_tail()
            self._refresh_state()
        except Exception:
            pass
