"""WebUI工作台页面 (Comfyui-Workbench-Mie 启停 / 配置 / 更新 / 日志).

布局 (纵向三段式; 启动控制段内部是左右结构, 仿首页 launch_page):
  ┌─ 启动控制 ──────────────────────────────────────┐
  │ 端口号 [8199] ☑允许局域网访问   ┌────────────┐ │
  │ 自动打开浏览器 [默认▾]          │ 🚀一键启动 │ │
  │                                 ├────────────┤ │
  │                                 │ 🌐打开网页 │ │
  │                                 └────────────┘ │
  └────────────────────────────────────────────────┘
  ┌─ 版本与更新 ────────────────────────────────────┐
  │ 版本：xxxx，已安装配置              [🔄更新]   │
  └────────────────────────────────────────────────┘
  ┌─ 实时日志 ──────────────────────────────────────┐
  │ ...实时 tail 日志...                            │
  │ [🧹清空] [📂打开日志文件]                       │
  └────────────────────────────────────────────────┘

状态机 (状态靠一键启动按钮文字体现):
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
import shutil
import sys
import subprocess
import webbrowser
from pathlib import Path
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from .base_page import BasePage
from utils.paths import webui_path_from_config, WEBUI_DIR_NAME, stable_project_root
from config.migrations import resolve_active_paths_for_webui
from core.webui_launcher_cmd import build_webui_launch_params
from core.webui_process_manager import WebuiProcessManager
from core.webui_dependencies import check_webui_dependencies, install_webui_requirements
from core.webui_installer import clone_webui, pull_webui
from utils.net import resolve_pypi_index_url, describe_git_proxy, describe_webui_proxy_for_mirror
from core.webui_installer import resolve_webui_repo_url, WEBUI_DEFAULT_MIRROR, WEBUI_REPOS
from ui_qt.widgets.dialog_helper import DialogHelper
from ui_qt.widgets.buttons import DestructiveButton
from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
from ui_qt.widgets.custom import NoWheelComboBox
from ui_qt.log_viewer import LogTailer, read_tail_lines


STATE_NOT_INSTALLED = "not_installed"
STATE_NO_DEPS = "no_deps"
STATE_READY = "ready"
STATE_RUNNING = "running"
STATE_STARTING = "starting"            # WebUI 工作台启动中
STATE_STOPPING = "stopping"
STATE_CHECKING = "checking"            # 检测 ComfyUI 是否在跑
STATE_WAITING_COMFYUI = "waiting_comfyui"  # 等待 ComfyUI 启动就绪
STATE_DOWNLOADING = "downloading"      # 下载 WebUI 工作台中
STATE_INSTALLING_DEPS = "installing_deps"  # 安装依赖中

# 所有"中间态"——有后台操作进行中, 按钮禁用, 轮询/刷新不覆盖.
_BUSY_STATES = frozenset({
    STATE_CHECKING, STATE_WAITING_COMFYUI,
    STATE_STARTING, STATE_STOPPING,
    STATE_DOWNLOADING, STATE_INSTALLING_DEPS,
})

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

    def _is_busy(self) -> bool:
        """是否有后台操作进行中 (启动/停止/检测/下载/装依赖等中间态).

        这些状态期间: 主按钮禁用; 轮询 (_poll_status) 和刷新 (_refresh_state) 不覆盖
        _state (中间态退出权交给 worker 回调 _after_*); _on_primary_clicked 拒绝重复点击.
        """
        return self._state in _BUSY_STATES

    def _resolve_hf_endpoint(self) -> Optional[str]:
        """从 app.config["proxy_settings"] 解析 HF 镜像 URL.

        与 core/launcher_cmd.py:build_launch_env 同体制 (该函数同时也设 HF_ENDPOINT 环境变量供 ComfyUI 子进程).
        hf_mirror_mode 为"不使用镜像" / 空 / 未设 → 返回 None (不设 HF_ENDPOINT).
        """
        try:
            cfg = getattr(self.app, "config", None)
            if not isinstance(cfg, dict):
                return None
            ps = cfg.get("proxy_settings", {})
            if not isinstance(ps, dict):
                return None
            mode = (ps.get("hf_mirror_mode") or "").strip()
            if not mode or mode == "不使用镜像":
                return None
            url = (ps.get("hf_mirror_url") or "").strip()
            return url or None
        except Exception:
            return None

    def _set_state(self, state: str) -> None:
        """切换 _state 并立即刷新 UI (主线程, 文案/可用性统一由 _update_ui_for_state 出)."""
        self._state = state
        self._update_ui_for_state()

    # ---------------- 主题 helper ----------------
    def _c(self, key: str, default: str = "") -> str:
        """读 theme_manager.colors token (含缺失兜底)."""
        try:
            return self.theme_manager.colors.get(key, default)
        except Exception:
            return default

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

    def _version_card_style(self) -> str:
        """版本信息卡片容器 QSS: card_bg + card_border + 圆角 (深浅自适应).

        把版本/配置状态两个条目包成一个视觉整体, 跟右边更新按钮形成"左信息卡 + 右按钮"
        的平衡结构, 避免更新按钮孤立突兀.
        """
        return (
            "QFrame {"
            f"  background-color: {self._c('card_bg', '#1F2937')};"
            f"  border: 1px solid {self._c('card_border', '#374151')};"
            "  border-radius: 6px;"
            "}"
        )

    def _label_muted_style(self) -> str:
        return (
            f'font: 9pt "Microsoft YaHei UI"; color: {self._c("label_muted", "#9CA3AF")};'
        )

    def _config_label_style(self) -> str:
        """配置项标签样式 (复刻首页 lbl_style: label_muted + bold)."""
        return f'color: {self._c("label_muted", "#9CA3AF")}; font-weight: bold;'

    def _create_version_item(self, title: str, value: str, icon_str: str):
        """版本信息卡片条目 (复刻首页 version_section._create_version_item 格式).

        一行: <图标> <标题 :> <值>. 标题 label_muted bold 9pt, 值 text bold 10pt.
        返回 QFrame; 值标签存 ref 供 update_theme 重应用样式.
        """
        card = QtWidgets.QFrame()
        card.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        card.setStyleSheet("QFrame { background: transparent; border: none; }")

        hb = QtWidgets.QHBoxLayout(card)
        hb.setContentsMargins(5, 2, 5, 2)
        hb.setSpacing(8)
        hb.setAlignment(QtCore.Qt.AlignCenter)

        icon_lbl = QtWidgets.QLabel(icon_str)
        icon_lbl.setStyleSheet("font-size: 14pt; background: transparent;")
        hb.addWidget(icon_lbl)

        t = QtWidgets.QLabel("%s :" % title)
        t.setStyleSheet(
            f'color: {self._c("label_muted", "#9CA3AF")};'
            f' font: bold 9pt "Microsoft YaHei UI"; background: transparent;'
        )
        hb.addWidget(t)

        v = QtWidgets.QLabel(value)
        v.setStyleSheet(
            f'font: bold 10pt "Segoe UI", "Microsoft YaHei UI";'
            f' color: {self._c("text", "#E5E7EB")}; background: transparent;'
        )
        hb.addWidget(v)

        # 存 ref 供 update_theme 重应用 (值标签可能因状态切 error 色)
        if not hasattr(self, "_version_value_refs"):
            self._version_value_refs = []
        if not hasattr(self, "_version_title_refs"):
            self._version_title_refs = []
        self._version_title_refs.append(t)
        self._version_value_refs.append(v)
        return card

    def _set_version_item_value(self, card, text: str, is_error: bool = False) -> None:
        """更新卡片值标签文本 (值标签是 card 里第 3 个子控件)."""
        try:
            # HBox 顺序: icon, title, value -> value 是第 3 个 layout item
            layout = card.layout()
            if layout is None or layout.count() < 3:
                return
            v_lbl = layout.itemAt(2).widget()
            v_lbl.setText(str(text))
            color = self._c("error", "#EF4444") if is_error else self._c("text", "#E5E7EB")
            v_lbl.setStyleSheet(
                f'font: bold 10pt "Segoe UI", "Microsoft YaHei UI";'
                f' color: {color}; background: transparent;'
            )
        except Exception:
            pass

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

        lbl_style = self._config_label_style()

        # === 段1: 启动控制 (左配置项 + 右按钮列, 仿首页 launch_page 左右结构) ===
        launch_group = QtWidgets.QGroupBox("启动控制")
        launch_layout = QtWidgets.QHBoxLayout(launch_group)
        launch_layout.setContentsMargins(8, 12, 8, 12)
        launch_layout.setSpacing(15)
        layout.addWidget(launch_group)

        # --- 左: 配置项 (端口/监听 + 自动打开浏览器) ---
        form_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QGridLayout(form_widget)
        form_layout.setColumnStretch(1, 1)
        form_layout.setHorizontalSpacing(20)
        form_layout.setVerticalSpacing(8)
        form_layout.setContentsMargins(0, 0, 0, 0)
        launch_layout.addWidget(form_widget, 1)

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
        # v6.5: 默认允许局域网访问 (display_host=0.0.0.0).
        # v6.5: 默认允许局域网访问 (display_host=0.0.0.0). 显式 listen_lan=False 时仍按用户选择.
        listen_lan = bool(self._webui_options().get("listen_lan", True))
        self._listen_chk.setChecked(listen_lan)
        self._listen_chk.setToolTip("允许局域网内其他设备访问 WebUI工作台")
        # 把默认值同步到 config: 用户首次进来 config 没 listen_lan/display_host 时,
        # 让 config 也写出这两个键 (跟 checkbox 状态一致), 后续读 config 永远拿到显式值.
        # 已有 config 时保留用户原值.
        opts = self._webui_options()
        if "listen_lan" not in opts:
            self._save_webui_option("listen_lan", listen_lan)
        if "display_host" not in opts:
            self._save_webui_option("display_host", "0.0.0.0" if listen_lan else "127.0.0.1")
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

        # 仓库源 (gitee / github). 已安装未安装都能切; 已安装时
        # 切换会同时 "git remote set-url origin", 已 clone 的代码不重下,
        # 下次更新走新源. 国内优先 Gitee (直连快), 海外用 GitHub.
        mirror_label = QtWidgets.QLabel("仓库源：")
        mirror_label.setStyleSheet(lbl_style)
        self._mirror_combo = NoWheelComboBox()
        self._mirror_combo.setMaxVisibleItems(2)
        self._mirror_combo.setToolTip(
            "下载/更新 WebUI 工作台时用的 git 仓库源. 国内选 Gitee 直连快. "
            "已安装的工作台切换会同时改 git remote.origin.url, 不会重下代码."
        )
        _mirror_opts = [
            ("Gitee（国内推荐）", "gitee"),
            ("GitHub（海外）", "github"),
        ]
        for _name, _val in _mirror_opts:
            self._mirror_combo.addItem(_name, _val)
        # 读 config 拿当前 mirror, 默认 gitee. blockSignals 防初始化时触发 handler.
        _cur_mirror = (self._webui_options().get("download_mirror") or WEBUI_DEFAULT_MIRROR).strip().lower()
        if _cur_mirror not in {"gitee", "github", "custom"}:
            _cur_mirror = WEBUI_DEFAULT_MIRROR
        self._mirror_combo.blockSignals(True)
        for _i, (_name, _val) in enumerate(_mirror_opts):
            if _val == _cur_mirror:
                self._mirror_combo.setCurrentIndex(_i)
                break
        self._mirror_combo.blockSignals(False)
        self._mirror_combo.currentIndexChanged.connect(self._on_mirror_changed)
        row_mirror = QtWidgets.QHBoxLayout()
        row_mirror.setContentsMargins(0, 0, 0, 0)
        row_mirror.setSpacing(8)
        row_mirror.addWidget(self._mirror_combo)
        row_mirror.addStretch(1)
        form_layout.addWidget(mirror_label, 2, 0)
        form_layout.addLayout(row_mirror, 2, 1)

        # --- 右: 按钮列 (固定宽, 一键启动大按钮 + 打开网页, 上下堆叠) ---
        btn_container = QtWidgets.QWidget()
        btn_container.setFixedWidth(180)
        btn_col = QtWidgets.QVBoxLayout(btn_container)
        btn_col.setContentsMargins(0, 0, 0, 0)
        btn_col.setSpacing(8)
        launch_layout.addWidget(btn_container, 0)

        # 一键启动 大按钮 (随状态变文字; stretch 4 跟左侧配置项高度对齐)
        self._btn_primary = QtWidgets.QPushButton()
        self._btn_primary.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_primary.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self._btn_primary.clicked.connect(self._on_primary_clicked)
        self._btn_primary.setMinimumHeight(60)
        btn_col.addWidget(self._btn_primary, 4)

        # 打开网页 (stretch 1, 紧贴一键启动下方)
        self._btn_open = QtWidgets.QPushButton("🌐 打开网页")
        self._btn_open.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_open.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self._btn_open.setMinimumHeight(40)
        self._btn_open.clicked.connect(self._on_open_browser)
        btn_col.addWidget(self._btn_open, 1)

        # === 段2: 版本与更新 (版本/配置状态卡片条目 + 更新按钮) ===
        version_group = QtWidgets.QGroupBox("版本与更新")
        version_layout = QtWidgets.QHBoxLayout(version_group)
        version_layout.setContentsMargins(8, 12, 8, 12)
        version_layout.setSpacing(12)
        layout.addWidget(version_group)

        # 左: 版本 + 配置状态两个首页式条目, 套一层卡片容器 (card_bg + card_border),
        # 让版本信息成视觉整体, 跟右边更新按钮形成"左信息卡 + 右按钮"的平衡结构.
        self._version_info_card = QtWidgets.QFrame()
        self._version_info_card.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        card_inner = QtWidgets.QGridLayout(self._version_info_card)
        card_inner.setContentsMargins(10, 8, 10, 8)
        card_inner.setHorizontalSpacing(12)
        card_inner.setVerticalSpacing(0)
        self._version_item = self._create_version_item("版本", "—", "🏷️")
        self._config_status_item = self._create_version_item("配置状态", "—", "⚙️")
        card_inner.addWidget(self._version_item, 0, 0)
        card_inner.addWidget(self._config_status_item, 0, 1)
        card_inner.setColumnStretch(0, 1)
        card_inner.setColumnStretch(1, 1)
        version_layout.addWidget(self._version_info_card, 1)

        # 右: 更新 + 移除按钮 (垂直排列, 移除 destructive 红色)
        update_col = QtWidgets.QVBoxLayout()
        update_col.setSpacing(6)
        version_layout.addLayout(update_col)

        self._btn_update = QtWidgets.QPushButton("🔄 更新")
        self._btn_update.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_update.setMinimumHeight(36)
        self._btn_update.clicked.connect(self._on_update_clicked)
        self._btn_update.setToolTip("git pull 更新 WebUI工作台到最新版本")
        update_col.addWidget(self._btn_update)

        # 移除按钮: 实色红 (destructive), 跟 models_page "移除所选" + "退出启动器" 确认按钮一致.
        # 用 DestructiveButton widget 而不是 setStyleSheet(destructive_outline_button_style()):
        # - destructive_outline 是 ActionBar 次级操作风格 (禁用/卸载选中), 太克制
        # - DestructiveButton 是实色 #EF4444, 跟全应用"高风险破坏性操作"视觉一致
        self._btn_remove = DestructiveButton("🗑 移除", self.theme_manager.styles)
        self._btn_remove.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_remove.setMinimumHeight(36)
        self._btn_remove.clicked.connect(self._on_remove_clicked)
        self._btn_remove.setToolTip(
            "删除 WebUI工作台目录 (弹确认). "
            "工作台运行时禁用, 必须先停止."
        )
        update_col.addWidget(self._btn_remove)

        # === 段3: 实时日志 (实时 tail, 与实时日志页一致) ===
        log_group = QtWidgets.QGroupBox("实时日志")
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

    @QtCore.pyqtSlot(int)
    def _on_mirror_changed(self, idx: int) -> None:
        """仓库源切换 handler (Gitee / GitHub).

        流程:
          1. 解析 idx -> new_mirror (gitee / github).
          2. 读当前持久化的 old_mirror; 相同则 no-op.
          3. 持久化 new_mirror.
          4. 已安装 (webui_path/.git 存在): 弹 [仅保存配置 / 立即切换 origin].
             选立即切换 -> git remote set-url origin <new_url>; 失败弹 DialogHelper.
        """
        if not (0 <= idx < self._mirror_combo.count()):
            return
        new_mirror = (self._mirror_combo.itemData(idx) or "").strip().lower()
        if new_mirror not in WEBUI_REPOS:
            return
        old_mirror = (
            self._webui_options().get("download_mirror") or WEBUI_DEFAULT_MIRROR
        ).strip().lower()
        if old_mirror not in WEBUI_REPOS:
            old_mirror = WEBUI_DEFAULT_MIRROR
        if new_mirror == old_mirror:
            return

        # 持久化新 mirror.
        self._save_webui_option("download_mirror", new_mirror)

        # 已安装 (.git 存在) 才考虑同步 git remote.origin.url.
        info = self._resolve_paths()
        webui_path = info.get("webui_path")
        new_url = info.get("download_url") or ""
        if not (webui_path and (webui_path / ".git").exists()):
            return

        dlg = CustomConfirmDialog(
            parent=self,
            title="切换仓库源",
            content=(
                f"已安装的工作台位于:\n  {webui_path}\n\n",
                f"git remote.origin.url 将切换为:\n  {new_url}\n\n",
                "已 clone 的代码不重下; 下次「更新」/「下载」会从新源拉取.\n\n",
                "现在执行 git remote set-url 吗?\n",
                "(选「仅保存配置」则只持久化新 mirror, 不动 git remote)",
            ),
            buttons=[
                {"text": "仅保存配置", "role": "normal"},
                {"text": "立即切换 origin", "role": "primary"},
            ],
            default_index=1,
            theme_manager=self.theme_manager,
        )
        dlg.exec_()
        if dlg.get_result() != 1:
            return
        try:
            kwargs = dict(
                cwd=str(webui_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
            )
            if sys.platform.startswith("win"):
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                kwargs["startupinfo"] = si
                kwargs["creationflags"] = (
                    kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
                )
            r = subprocess.run(
                ["git", "remote", "set-url", "origin", new_url], **kwargs
            )
        except Exception as e:
            try:
                self.app.logger.warning("git remote set-url 异常: %s", e)
            except Exception:
                pass
            DialogHelper.show_error(self, "切换失败", f"git remote set-url 异常: {e}")
            return
        if r.returncode != 0:
            err = (getattr(r, "stderr", "") or getattr(r, "stdout", "") or "").strip()
            DialogHelper.show_error(
                self, "切换失败", f"git remote set-url 失败: {err or "未知错误"}",
            )
            return
        try:
            self.app.logger.info(
                "webui 仓库源已切换: %s -> %s", old_mirror, new_url,
            )
        except Exception:
            pass
        DialogHelper.show_info(
            self,
            "已切换",
            f"WebUI 工作台 origin 已切到:\n  {new_url}\n下次更新会从新源拉取.",
        )
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
        # DestructiveButton.update_theme() 内部重 apply destructive_button_style (实色红).
        self._btn_remove.update_theme(styles)
        self._btn_log_clear.setStyleSheet(styles.secondary_button_style())
        self._btn_log_open.setStyleSheet(styles.secondary_button_style())
        # 输入控件
        self._port_edit.setStyleSheet(input_ss)
        self._open_combo.setStyleSheet(input_ss)
        self._mirror_combo.setStyleSheet(input_ss)
        self._cpath_btn.setStyleSheet(input_ss)
        # 文本/日志
        self._log_view.setStyleSheet(self._log_view_style())
        # 版本信息卡片容器 (card_bg + card_border)
        self._version_info_card.setStyleSheet(self._version_card_style())
        self._update_cpath_vis()
        # 版本与更新卡片条目标签重应用主题色 (复刻首页 update_theme)
        try:
            label_muted = self._c("label_muted", "#9CA3AF")
            text_color = self._c("text", "#E5E7EB")
            for ref in getattr(self, "_version_title_refs", []):
                ref.setStyleSheet(
                    f'color: {label_muted}; font: bold 9pt "Microsoft YaHei UI";'
                    f' background: transparent;'
                )
            for ref in getattr(self, "_version_value_refs", []):
                ref.setStyleSheet(
                    f'font: bold 10pt "Segoe UI", "Microsoft YaHei UI";'
                    f' color: {text_color}; background: transparent;'
                )
        except Exception:
            pass
        # 状态相关文案重算 (版本/配置状态值). force: 主题切换不应被 busy 态吞掉刷新.
        self._refresh_state(force=True)

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
        # 镜像源: gitee / github.
        # 未设 (None 或 空) 默认跳 gitee, 国内推荐.
        download_mirror = (webui_options.get("download_mirror") or WEBUI_DEFAULT_MIRROR).strip().lower()
        if download_mirror not in WEBUI_REPOS and download_mirror != "custom":
            download_mirror = WEBUI_DEFAULT_MIRROR
        download_url = resolve_webui_repo_url(
            download_mirror, webui_options.get("download_url")
        )

        def _anchor(v):
            p = Path(v)
            if p.is_absolute():
                return p.resolve()
            # Relative config value -- anchor to launcher project root, NOT
            # to Path.cwd(); see stable_project_root docstring.
            return (stable_project_root() / v).resolve()

        pw = resolve_active_paths_for_webui(cfg if isinstance(cfg, dict) else {})
        webui_path = _anchor(pw["webui_path"]) if pw.get("webui_path") else None
        py_path = _anchor(pw["python_path"]) if pw.get("python_path") else None
        env_id = pw.get("env_id")

        return {
            "webui_path": webui_path,
            "python_path": py_path,
            "env_id": env_id,
            "port": port,
            "display_host": display_host,
            "download_url": download_url,
            "download_mirror": download_mirror,
            "mirror_options": list(WEBUI_REPOS.keys()),
        }

    def _reset_deps_cache(self, reason: str) -> None:
        """失效依赖探测缓存. install/download/update 等改动 webui 文件系统后调用."""
        try:
            if self._deps_cache_result is not None or self._deps_cache_key is not None:
                self.app.logger.info(
                    "依赖探测缓存失效: reason=%s old_key=%s",
                    reason, self._deps_cache_key,
                )
        except Exception:
            pass
        self._deps_cache_key = None
        self._deps_cache_result = None

    def _safe_rmtree(self, path: Path) -> tuple[bool, list]:
        """Best-effort recursive delete with anti-handle-leak retries.

        Context (user-observed failure): on LAN shares / 装了实时防护的
        环境下, shutil.rmtree 经常会因 .git/objects/pack/pack-*.idx 这类
        内部索引文件被防病毒扫描器或 SMB 层短暂持有句柄而报 [WinError 5].
        而同一目录手动在文件资源管理器里删除很快, 说明是瞬时共享冲突.

        策略 (per attempt):
        1. chmod-writable 全树 (cp / mv / smb 可能留了 read-only bit)
        2. shutil.rmtree 走 full tree, onerror 抓单个文件失败:
           重新 chmod + retry 该文件; 失败累积到 errors list, 不让整棵挂.
        3. 外层多 retry 几轮 (间隔递增), 处理 SMB 多次确认的现象.

        Returns (ok, remaining_errors). ok=True 即目录已不存在;
        ok=False 时 remaining_errors 列出仍未删掉的文件.
        """
        import stat
        import time as _time
        if not path.exists():
            return True, []

        def _chmod_w(p):
            try:
                os.chmod(str(p), stat.S_IWRITE | stat.S_IWGRP | stat.S_IWOTH)
            except Exception:
                pass

        def _onerror(func, p, exc_info):
            try:
                _chmod_w(p)
                func(str(p))
                return
            except Exception as e2:
                errors.append((str(p), str(e2)))

        errors = []
        for attempt in range(4):
            del errors[:]
            try:
                for p in path.rglob("*"):
                    _chmod_w(p)
            except Exception:
                pass
            _chmod_w(path)
            try:
                shutil.rmtree(path, onerror=_onerror)
            except Exception as e:
                errors.append((str(path), str(e)))
            if not path.exists():
                return True, []
            if not errors:
                break
            _time.sleep(0.3 + 0.3 * attempt)
        if path.exists():
            return False, errors
        return True, []


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

    def _refresh_state(self, force: bool = False):
        # 中间态期间不覆盖: 探测到的状态可能 "跑赢" worker (如 STARTING 时进程还没起,
        # _detect_state 返 READY), 会把按钮刷回可点击态, 破坏状态机. 中间态退出权交给
        # worker 的 _after_* 回调 (它们用 _set_state 显式切到稳定态).
        # force=True: env 切换/主题切换等场景, 路径或上下文可能变了, 需强制重新探测.
        if not force and self._is_busy():
            return
        self._state = self._detect_state()
        self._update_ui_for_state()

    def _poll_status(self):
        """定时器: running 状态会变, 勤跑探测. 中间态跳过 (防覆盖, 见 _refresh_state)."""
        if self._is_busy():
            return
        try:
            new_state = self._detect_state()
            if new_state != self._state:
                self._state = new_state
                self._update_ui_for_state()
        except Exception:
            pass

    def _update_ui_for_state(self):
        info = self._resolve_paths()
        webui_path = info["webui_path"]
        version = _read_workbench_version(webui_path) if webui_path else None

        # 版本与更新段: 拆成两个独立卡片条目 (版本 / 配置状态), 仿首页格式.
        ver_txt = version if version else "—"
        # 配置状态文案: _state -> 中文 (中间态也中文化, 不再露英文 key).
        _STATUS_TXT = {
            STATE_NOT_INSTALLED: "未安装",
            STATE_NO_DEPS: "待安装依赖",
            STATE_READY: "已安装配置",
            STATE_RUNNING: "运行中",
            STATE_CHECKING: "检测中…",
            STATE_WAITING_COMFYUI: "等待 ComfyUI 启动…",
            STATE_STARTING: "启动中…",
            STATE_STOPPING: "停止中…",
            STATE_DOWNLOADING: "下载中…",
            STATE_INSTALLING_DEPS: "安装依赖中…",
        }
        status_txt = _STATUS_TXT.get(self._state, self._state)
        self._set_version_item_value(self._version_item, ver_txt)
        self._set_version_item_value(self._config_status_item, status_txt)

        # 主按钮文案: _state -> 单行文字. 中间态显示进度文案 + 禁用.
        _BTN_TEXT = {
            STATE_NOT_INSTALLED: "⬇ 下载WebUI工作台",
            STATE_NO_DEPS: "⚙ 安装依赖",
            STATE_READY: "🚀 一键启动",
            STATE_RUNNING: "⏹ 停止",
            STATE_CHECKING: "⏳ 检测中…",
            STATE_WAITING_COMFYUI: "⏳ 等待 ComfyUI 启动中…",
            STATE_STARTING: "⏳ 启动中…",
            STATE_STOPPING: "⏳ 停止中…",
            STATE_DOWNLOADING: "⬇ 下载中…",
            STATE_INSTALLING_DEPS: "⚙ 安装依赖中…",
        }
        self._btn_primary.setText(_BTN_TEXT.get(self._state, "…"))
        # 中间态禁用按钮 (防重复点击); 四个稳定态可点.
        self._btn_primary.setEnabled(not self._is_busy())

        # 打开网页按钮: 仅 running 可用 (没跑起来打开无意义)
        self._btn_open.setEnabled(self._state == STATE_RUNNING)
        # 更新按钮: 仅 ready (已安装未跑) 可用; 更新中/启动停止中禁用
        self._btn_update.setEnabled(self._state == STATE_READY and not self._updating)
        # 移除按钮: 仅 NO_DEPS/READY 可用 (有目录可删); NOT_INSTALLED 没东西删, RUNNING 必须先停, busy 全禁用.
        self._btn_remove.setEnabled(self._state in (STATE_NO_DEPS, STATE_READY))

    # ---------------- 按钮回调 ----------------
    def _on_primary_clicked(self):
        # 中间态 (检测/启动/停止/下载/装依赖/等 ComfyUI) 拒绝重复点击.
        # (按钮已 setEnabled(False), 这里是双保险: 防定时器竞态把态刷回稳定态)
        if self._is_busy():
            return
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

        def runner(on_progress):
            res = pull_webui(
                self.app, webui_path,
                on_progress=on_progress,
                logger=self.app.logger,
            )
            return {
                "ok": bool(res.get("ok")),
                "updated": bool(res.get("updated", False)),
                "error": res.get("error") or "",
            }

        def on_done(result):
            self._after_update(result.get("ok"), result.get("updated"), result.get("error", ""))

        # Task title explicitly says which proxy / 直连 + which repo so the
        # progress dialog makes the fetch path obvious from the first second.
        # Mirror-aware: Gitee 永远直连 (gh-proxy 不适用), GitHub 才走用户配置的代理.
        # 之前只用 describe_git_proxy, 即使用户切到 Gitee 仍显示 通过 gh-proxy ", 误导.
        _mirror_name = info.get("download_mirror") or WEBUI_DEFAULT_MIRROR
        proxy_desc = describe_webui_proxy_for_mirror(_mirror_name, getattr(self.app, "config", None))
        task_title = f"拉取 Comfyui-Workbench-Mie ({_mirror_name}, {proxy_desc})"
        self._run_with_progress(task_title, runner, on_done)

    @QtCore.pyqtSlot(bool, bool, str)
    def _after_update(self, ok: bool, updated: bool, err: str):
        self._updating = False
        self._btn_update.setText("🔄 更新")
        # success 路径显式 re-detect: _refresh_state 在 busy 时直接 return, 会卡死状态.
        if not ok:
            # User feedback: when the proxy fetch fails the only button used
            # to be "OK" -- users could not retry from this dialog. Replace
            # with [close / retry]; user picks retry and we re-trigger
            # _on_update_clicked so the GUI immediately tries again.
            err_msg = err or "未知 (可能 5 分钟 git 超时, 见 launcher/launcher.log)"
            dlg = CustomConfirmDialog(
                parent=self,
                title="更新失败",
                content=(
                    "拉取 Comfyui-Workbench-Mie 没有成功.\n\n"
                    f"原因: {err_msg}\n\n"
                    "可能是 5 分钟 git fetch 超时 (代理抽风 / DNS 慢) 或 仓库不可达.\n\n"
                    "可以关闭 (手动换网络/代理后再来) 或 立即重试."
                ),
                buttons=[
                    {"text": "关闭", "role": "normal"},
                    {"text": "立即重试", "role": "primary"},
                ],
                default_index=1,
                theme_manager=self.theme_manager,
            )
            dlg.exec_()
            retry = (dlg.get_result() == 1)
            self._set_state(self._detect_state())
            if retry:
                try:
                    self._on_update_clicked()
                except Exception:
                    pass
        else:
            self._reset_deps_cache("update")
            self._set_state(self._detect_state())
            if updated:
                DialogHelper.show_info(self, "更新完成", "WebUI工作台已更新到最新版本。")
            else:
                DialogHelper.show_info(self, "已是最新", "WebUI工作台已是最新版本。")

    def _start_with_prompt(self):
        """点「一键启动」后: 先进入「检测中」, 后台线程探活 ComfyUI 是否在跑.

        探活挪到后台线程: is_http_reachable 是 HTTP 探活 (最长 ~1.9s), 在主线程做会
        短暂冻 UI 且来不及显示「检测中…」. 探活完经 _after_comfyui_check 回主线程:
        在跑 → 直接启 WebUI工作台; 没跑 → 弹 3 选 1 询问框.
        """
        self._set_state(STATE_CHECKING)

        def _worker():
            running = self._is_comfyui_running()
            QtCore.QMetaObject.invokeMethod(
                self, "_after_comfyui_check",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(bool, running),
            )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    @QtCore.pyqtSlot(bool)
    def _after_comfyui_check(self, comfyui_running: bool):
        """ComfyUI 探活完成后回主线程: 在跑 -> 直接启; 没跑 -> 弹询问框."""
        if comfyui_running:
            self._start_webui(with_comfyui=False)
            return
        self._set_state(STATE_READY)  # 先恢复可点击态, 弹框期间按钮可用
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
        """ComfyUI 是否在跑 (直接 HTTP 探活 /system_stats).

        不能依赖 pidfile: 首页 GUI 启动 ComfyUI (走 core/runner_start + ProcessManager)
        不写 pidfile (只有 CLI 路径 start_service 才写). 用 pidfile 判断会让"首页启的
        ComfyUI"永远探不到, 误弹"是否同时启动". 这里跟首页 process_manager.py 用同款
        is_http_reachable(app), 端口读 app.custom_port, 不碰 pidfile.
        """
        try:
            from core.probe import is_http_reachable
            return bool(is_http_reachable(self.app, _log=False))
        except Exception:
            return False

    def _start_comfyui_then_webui(self):
        """先启 ComfyUI (后台线程), 成功后再启 WebUI工作台.

        必须在后台线程调 start_service: start_service 阻塞等就绪, 而 ready 信号
        (pm.on_start_success) 是经 _post_to_ui 投递到 UI 线程执行的 —— 若在 UI 主线程
        同步调, 主线程被 wait_for_start 占住收不到那个投递, 死锁到 60s 超时再误判失败
        (界面也会冻死). 跟 _start_webui/_stop_webui 一样走"后台线程 + invokeMethod 回主线程".
        """
        self._set_state(STATE_WAITING_COMFYUI)

        def _worker():
            try:
                from core.cli.runner import start_service
                res = start_service(self.app, no_wait=False, timeout=60) or {}
                # start_service 返回 started/ready (无 ok 字段); ready=True 才算真就绪.
                ok = bool(res.get("ready"))
                err = res.get("error")
            except Exception as e:
                ok = False
                err = str(e)
                try:
                    self.app.logger.warning("ComfyUI 启动异常: %s", e)
                except Exception:
                    pass
            QtCore.QMetaObject.invokeMethod(
                self, "_after_comfyui_start",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(bool, ok),
                QtCore.Q_ARG(str, err or ""),
            )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    @QtCore.pyqtSlot(bool, str)
    def _after_comfyui_start(self, ok: bool, err: str):
        """ComfyUI 启动完成后回主线程: 成功 -> 继续启 WebUI工作台; 失败 -> 弹窗."""
        if not ok:
            self._refresh_state()  # 恢复按钮状态
            DialogHelper.show_warning(
                self, "ComfyUI 启动失败",
                "ComfyUI 启动失败, WebUI工作台不启动。\n请查看 ComfyUI 日志排查。\n\n%s" % (err or ""),
            )
            return
        self._start_webui(with_comfyui=False)

    def _start_webui(self, with_comfyui: bool):
        """后台启 WebUI工作台."""
        if self._pm is None:
            self._pm = WebuiProcessManager(self.app)
        self._set_state(STATE_STARTING)

        def _worker():
            res = self._pm.start_webui(timeout=60)
            started_ok = bool(res.get("ok"))
            err = res.get("error")
            # _state 切换交回主线程 slot 做 (不跨线程写); err 在主线程弹窗.
            QtCore.QMetaObject.invokeMethod(
                self, "_after_action_done",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(bool, started_ok),
                QtCore.Q_ARG(str, err or ""),
            )
            # 自动打开浏览器必须在主线程做: webbrowser.open 在后台线程会静默失败
            # (Windows 上注册表查询/COM 初始化依赖主线程). 启动成功才考虑打开.
            if started_ok and self._should_auto_open():
                QtCore.QMetaObject.invokeMethod(
                    self, "_open_url_after_start",
                    QtCore.Qt.QueuedConnection,
                )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _should_auto_open(self) -> bool:
        """是否启动后自动打开浏览器.

        browser_open_mode 缺省视为 "default" (跟下拉框默认选中 "使用默认浏览器" 一致),
        不再回退到老的 auto_open_browser 布尔 (老字段默认 False, 会让"看起来已开启"的
        下拉选项静默失效). 只有显式 disable / none 才不打开.
        """
        mode = (self._webui_options().get("browser_open_mode") or "default").strip().lower()
        return mode not in ("disable", "none")

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

    def _browser_url(self) -> str:
        """供"打开浏览器"用的 URL: 永远走 127.0.0.1, 不用 display_host.

        display_host 是服务端 *绑定* 地址, listen_lan 勾选时为 0.0.0.0 ——
        浏览器把 0.0.0.0 当客户端地址打不开 (跟首页 open_web 一律用 127.0.0.1 同理).
        """
        info = self._resolve_paths()
        return "http://127.0.0.1:%s/" % info["port"]

    def _on_open_browser(self):
        """打开网页按钮."""
        self._open_url(self._browser_url())

    def _stop_webui(self):
        if self._pm is None:
            self._pm = WebuiProcessManager(self.app)
        self._set_state(STATE_STOPPING)

        def _worker():
            self._pm.stop_webui(timeout=10)
            # _state 切换交回主线程 slot 做 (不跨线程写).
            QtCore.QMetaObject.invokeMethod(
                self, "_after_action_done",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(bool, False),  # is_start=False -> 停止完成
                QtCore.Q_ARG(str, ""),
            )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    @QtCore.pyqtSlot(bool, str)
    def _after_action_done(self, started_ok: bool, err: str):
        """启动/停止 worker 完成后回主线程切换 _state + 刷新 UI.

        统一入口: 启动成功 -> RUNNING; 启动失败 -> READY (弹 err); 停止完成 -> READY.
        _state 只在此 (主线程) 写, 避免 worker 跨线程写.
        """
        if started_ok:
            self._set_state(STATE_RUNNING)
            return
        # 启动失败或停止完成: 回 READY. 启动失败且有 err 则弹窗 (停止无 err 不弹).
        self._set_state(STATE_READY)
        if err:
            DialogHelper.show_warning(
                None, "WebUI工作台启动失败",
                "WebUI工作台启动失败: %s\n\n请查看 launcher/webui.log" % err,
            )

    def _on_remove_clicked(self):
        """移除工作台: 弹确认 -> 删 webui 目录.

        双保险: 按钮 setEnabled(False) 已经禁用了 NOT_INSTALLED/RUNNING/busy 状态,
        这里再补一道 _is_busy / running 检查防定时器竞态.
        """
        # 双保险: 中间态拒绝 (防定时器竞态把态刷回稳定态)
        if self._is_busy():
            return
        info = self._resolve_paths()
        webui_path = info["webui_path"]
        if webui_path is None or not webui_path.exists():
            DialogHelper.show_warning(self, "无法移除", "WebUI工作台目录不存在，无需移除。")
            return
        # 双保险: 检查 webui 仍在跑 (按钮已禁用但兜底)
        if self._pm is None:
            self._pm = WebuiProcessManager(self.app)
        if self._pm.is_running():
            DialogHelper.show_warning(
                self, "无法移除",
                "WebUI工作台正在运行，请先停止后再移除。",
            )
            return

        dlg = CustomConfirmDialog(
            parent=self,
            title="移除 WebUI工作台",
            content=(
                f"将永久删除以下目录及其全部内容:\n\n"
                f"  {webui_path}\n\n"
                f"此操作不可撤销。是否继续?"
            ),
            buttons=[
                {"text": "取消", "role": "normal"},
                {"text": "确认移除", "role": "destructive"},
            ],
            default_index=0,
            theme_manager=self.theme_manager,
        )
        dlg.exec_()
        result = dlg.get_result()
        if result != 1:
            # 取消 (或弹窗关闭)
            return

        # 确认 -> rmtree (带 .git handle-leak 重试)
        ok, remaining = self._safe_rmtree(webui_path)
        if not ok:
            try:
                self.app.logger.warning(
                    "WebUI 工作台删除残留 %d 项: %s",
                    len(remaining),
                    "; ".join(f"{p} -> {e}" for p, e in remaining[:5]),
                )
            except Exception:
                pass
            sample = "; ".join(f"{p}" for p, _ in remaining[:3])
            hint = (
                f"删除目录失败: 共 {len(remaining)} 个文件未被删除。\n\n"
                f"通常是 .git/objects/pack/ 下索引文件被防病毒或 SMB 短暂持有句柄,\n"
                f"或个别文件被占用。\n\n未删掉的文件示例:\n  {sample}\n\n"
                f"可关闭占用进程后重试,或在文件资源管理器中手动删除 (右键 -> 删除)。\n"
                f"更多细节见 launcher/launcher.log."
            )
            DialogHelper.show_warning(self, "移除失败", hint)
            return

        # 失效 deps 缓存, 重新探测状态
        self._reset_deps_cache('remove')
        self._refresh_state(force=True)

    @QtCore.pyqtSlot()
    def _open_url_after_start(self):
        """启动成功后在主线程打开浏览器 (webbrowser.open 在后台线程会静默失败)."""
        if self._should_auto_open():
            self._open_url(self._browser_url())

    def _download_webui(self):
        """下载 (git clone) + 完成后自动 setup deps."""
        info = self._resolve_paths()
        webui_path = info["webui_path"]
        if not webui_path:
            return
        download_url = info["download_url"]

        self._set_state(STATE_DOWNLOADING)

        def runner(on_progress):
            # clone
            try:
                res = clone_webui(
                    self.app, webui_path, repo_url=download_url,
                    on_progress=on_progress,
                    logger=self.app.logger,
                )
            except Exception as e:
                res = {"ok": False, "error": str(e)}
            if not res.get("ok"):
                return {"ok": False, "error": res.get("error") or "未知"}
            # 同一 worker 内继续装依赖, 不走 self._setup_deps(silent=True)
            # 那个起新 thread 的旧路径 (双 worker 竞态隐患源头).
            py = info["python_path"]
            req = info["webui_path"] / "requirements.txt" if info["webui_path"] else None
            if py and py.exists() and req and req.exists():
                idx_url = resolve_pypi_index_url(self.app)
                install_webui_requirements(
                    py, req, index_url=idx_url,
                    on_progress=on_progress,
                    logger_=self.app.logger,
                    hf_endpoint=self._resolve_hf_endpoint(),
                )
            return {"ok": True}

        def on_done(result):
            if not result.get("ok"):
                self._after_download("下载失败: " + (result.get("error") or "未知"))
            else:
                self._after_download("下载完成")

        # 任务标题明确说出在拉哪个仓库 (repo short name + full owner/repo)
        # 和走哪条代理 (与更新工作台一致; 用户在弹窗打开第一秒就知道走了哪条路).
        dl_repo_url = info.get("download_url") or "https://github.com/MieMieeeee/Comfyui-Workbench-Mie.git"
        dl_repo_short = (dl_repo_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or "WebUI")
        dl_proxy_desc = describe_webui_proxy_for_mirror(dl_mirror_name, getattr(self.app, "config", None))
        dl_mirror_name = info.get("download_mirror") or WEBUI_DEFAULT_MIRROR
        dl_task_title = f"下载 {dl_repo_short} (镜像: {dl_mirror_name}, {dl_proxy_desc})"
        self._run_with_progress(dl_task_title, runner, on_done)

    @QtCore.pyqtSlot(str, str)
    def _after_download(self, msg: str, repo: str = ""):
        # 下载流程可能顺带跑 install_webui_requirements; 不论成功失败都得
        # 失效 deps 探测缓存, 否则下次 _detect_state 会命中装之前的 
        # `ok=False` 缓存, UI 永远停在 STATE_NO_DEPS ("安装依赖").
        self._reset_deps_cache("download")
        if msg.startswith("下载失败"):
            self._set_state(STATE_NOT_INSTALLED)
            err_text = msg.replace("下载失败: ", "", 1) if msg.startswith("下载失败: ") else msg
            retry_dlg = CustomConfirmDialog(
                parent=self,
                title="下载失败",
                content=(
                    f"下载 {repo or '代理仓库'} 没有完成.\n\n"
                    f"原因: {err_text}\n\n"
                    "可能是 5 分钟 git clone 超时 (代理抽风 / DNS 慢) 或 仓库不可达.\n\n"
                    "可以关闭 (手动换网络/代理后再来) 或 立即重试."
                ),
                buttons=[
                    {"text": "关闭", "role": "normal"},
                    {"text": "立即重试", "role": "primary"},
                ],
                default_index=1,
                theme_manager=self.theme_manager,
            )
            retry_dlg.exec_()
            retry = (retry_dlg.get_result() == 1)
            if retry:
                try:
                    self._on_primary_clicked()
                except Exception:
                    pass
        else:
            # success: 显式离开 busy 态 (re-detect). _refresh_state 在 busy 时直接 return.
            self._set_state(self._detect_state())

    def _run_with_progress(self, task_title, runner, on_done_slot, parent=None):
        """后台任务调度 helper: 弹进度窗 + 注册后台任务 + on_progress 派发.

        流程:
        - parent 是 QWidget 则建 ProgressDialog (show_cancel=False, show_background=True)
        - app._bg_task_registry 非空则注册后台任务 (侧边栏"后台任务"可看)
        - runner 跑后台线程; on_progress(文本, percent) 经 ui_post 投回主线程
        - runner 返回后调 _do_finish: registry.complete + pd.mark_complete + pd.close

        适配: parent 不是 QWidget (测试 / 纯 CLI) 跳弹窗; 无 _bg_task_registry 跳注册表.
        """
        from ui_qt.widgets.progress_dialog import ProgressDialog
        from PyQt5 import QtWidgets

        parent = parent or self.app
        registry = getattr(self.app, "_bg_task_registry", None)
        task_id = registry.register(task_title) if registry else None
        if isinstance(parent, QtWidgets.QWidget):
            pd = ProgressDialog(
                parent,
                title=task_title,
                theme_manager=getattr(self, "theme_manager", None),
                show_cancel=False, show_background=True,
            )
            pd.show()
            QtWidgets.QApplication.processEvents()
            if registry and task_id:
                registry.set_dialog(task_id, pd)
        else:
            pd = None

        def _apply_progress(text, percent):
            if pd is None:
                return
            try:
                pd.set_status(text)
                pd.set_progress(percent if percent is not None else None)
            except Exception:
                pass

        def on_progress(text, percent=None):
            _ui_post = getattr(self.app, "ui_post", None)
            if _ui_post:
                _ui_post(lambda: _apply_progress(text, percent))

        def _do_finish(success):
            if registry and task_id:
                try:
                    registry.complete(task_id, error=not success)
                except Exception:
                    pass
            if pd is not None:
                try:
                    _label = "完成 ✓" if success else "完成(有失败)"
                    pd.mark_complete(_label)
                    pd.close()
                except Exception:
                    pass

        def _finish(success, result):
            _ui_post = getattr(self.app, "ui_post", None)
            if _ui_post:
                _ui_post(lambda: _do_finish(success))
                # on_done_slot 也必须在主线程跳 (会动 _set_state / DialogHelper 等 Qt widgets)
                _ui_post(lambda: on_done_slot(result))
            else:
                _do_finish(success)
                on_done_slot(result)

        def _worker():
            result = None
            try:
                result = runner(on_progress)
            except Exception as e:
                result = {"ok": False, "error": str(e) or e.__class__.__name__}
            success = bool(result and result.get("ok"))
            _finish(success, result)

        import threading
        threading.Thread(target=_worker, daemon=True).start()



    def _setup_deps(self, silent: bool = False):
        """装依赖.

        silent=True 时跳过早退分支的 DialogHelper 提示.
        """
        info = self._resolve_paths()
        py = info["python_path"]
        req = info["webui_path"] / "requirements.txt" if info["webui_path"] else None
        if not py or not py.exists():
            self._set_state(STATE_NO_DEPS)
            if not silent:
                DialogHelper.show_warning(self, "Python 不可用", "Python 路径无效: %s" % py)
            self._refresh_state()
            return
        if not req or not req.exists():
            self._set_state(STATE_NO_DEPS)
            if not silent:
                DialogHelper.show_warning(
                    self, "requirements.txt 不存在",
                    "WebUI工作台目录里没找到 requirements.txt: %s" % req,
                )
            self._refresh_state()
            return

        self._set_state(STATE_INSTALLING_DEPS)

        def runner(on_progress):
            idx_url = resolve_pypi_index_url(self.app)
            res = install_webui_requirements(
                py, req, index_url=idx_url,
                on_progress=on_progress,
                logger_=self.app.logger,
                hf_endpoint=self._resolve_hf_endpoint(),
            )
            return {"ok": res.get("ok") is True, "error": res.get("error") or ""}

        def on_done(result):
            self._after_setup(result.get("ok"), result.get("error", ""))

        # 任务标题明确说出 PyPI 镜像源 + requirements.txt 路径, 用户能立刻分辨
        # "装哪个的依赖", "走哪条 PyPI 镜像" (避免点完按钮干等时全靠掌).
        pypi_idx = (resolve_pypi_index_url(self.app) or "").rstrip("/")
        pypi_short = pypi_idx.rsplit("/", 1)[-1] if pypi_idx else "默认"
        req_short_name = req.name if req else "requirements.txt"
        # 镜像不直接影响 install, 但写到 title 里和 download 一致, 让用户看到
        # "安装依赖 (镜像: gitee, PyPI: 阿里云, 文件: requirements.txt)".
        _in_mirror = info.get("download_mirror") or WEBUI_DEFAULT_MIRROR
        install_task_title = (
            f"安装依赖 (镜像: {_in_mirror}, PyPI: {pypi_short}, 文件: {req_short_name})"
        )
        self._run_with_progress(install_task_title, runner, on_done)

    @QtCore.pyqtSlot(bool, str)
    def _after_setup(self, ok: bool, err: str):
        # 依赖刚装过 (或尝试过), 失效探测缓存 (下次 _detect_state 重新探测)
        self._reset_deps_cache("setup")
        if not ok:
            # 失败 dialog 与 _after_update / _after_download 一致: [关闭 / 立即重试],
            # body 明确说是哪个 python / 哪个 requirements / 走哪个 PyPI 镜像,
            # 不再是" pip install 失败"这么稀里糊涂.
            # runner 里的 py / req / idx_url 在出事时在局部 scope, 不能跨 on_done 读到;
            # 采用 _resolve_paths() 重新取, 要么走 fallback.
            try:
                info2 = self._resolve_paths()
                py2 = str(info2.get("python_path") or "python")
                req_base = info2.get("webui_path")
                req2 = str((req_base / "requirements.txt")) if req_base else "requirements.txt"
            except Exception:
                py2 = "python"; req2 = "requirements.txt"
            try:
                pypi_str = (resolve_pypi_index_url(self.app) or "默认").rstrip("/")
            except Exception:
                pypi_str = "默认"
            setup_dlg = CustomConfirmDialog(
                parent=self,
                title="依赖安装失败",
                content=(
                    "安装 WebUI 工作台依赖失败.\n\n"
                    f"原因: {err or '未知'}\n\n"
                    f"Python: {py2}\n"
                    f"requirements: {req2}\n"
                    f"PyPI 镜像: {pypi_str}\n\n"
                    "可以关闭 (手动检查网络 / 镜像) 或 立即重试."
                ),
                buttons=[
                    {"text": "关闭", "role": "normal"},
                    {"text": "立即重试", "role": "primary"},
                ],
                default_index=1,
                theme_manager=self.theme_manager,
            )
            setup_dlg.exec_()
            retry = (setup_dlg.get_result() == 1)
            self._set_state(STATE_NOT_INSTALLED)
            if retry:
                try:
                    self._setup_deps(silent=True)
                except Exception:
                    pass
        else:
            # success: 显式离开 busy 态 (re-detect). _refresh_state 在 busy 时直接 return.
            self._set_state(self._detect_state())

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
        # UniqueConnection 作双保险防重复挂同一 slot; 但它在测试/某些 PyQt5 环境下偶发抛
        # TypeError('connection is not unique') (Qt 跨实例信号槽注册冲突), 失败时回退普通连接.
        try:
            self._emitter.line_received.connect(
                self._on_line_main,
                QtCore.Qt.QueuedConnection | QtCore.Qt.UniqueConnection,
            )
        except TypeError:
            self._emitter.line_received.connect(
                self._on_line_main,
                QtCore.Qt.QueuedConnection,
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
            # 日志 tailer 重定向到新路径 (复刻 qt_app 对 LogViewerPage 的处理).
            # tailer 部分单独 try: 即使 tailer 重建失败 (如测试环境 UniqueConnection
            # 偶发冲突), 也不能拖累后面的 _refresh_state (状态机必须刷新).
            try:
                self._stop_log_tail()
                self._history_loaded = False
                self._log_view.clear()
                self._log_path = self._resolve_log_path()
                self._start_log_tail()
            except Exception as e:
                try:
                    self.app.logger.warning("refresh_after_env_switch: 日志 tailer 重建失败: %s", e)
                except Exception:
                    pass
            # 状态刷新独立于 tailer: 不带 force (env 切换 GUI 侧已限制; 本页 busy 时不打断).
            self._refresh_state()
        except Exception:
            pass
