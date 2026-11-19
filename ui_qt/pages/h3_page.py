"""H3 短剧工作台页 (启停 / 端口 / 日志).

服务本体是 ComfyUI-Mie-H3-Engine 自带的 Flask 工作台 (webapp/__main__.py),
启动器把它当伴生服务管 (core.companion.h3_runtime).

与 openjutsu 页的差异:
  - **不要求 ComfyUI 在跑** (工作台离线也能管资产/剧本, 只有提交渲染才需要
    ComfyUI) → 没有「等 ComfyUI 启动」的两选一弹窗.
  - 单端口 (app 8200), 没有 proxy 中转.
  - **没有更新按钮**: H3 引擎本体是 ComfyUI 自定义节点, 升级走「插件管理」
    (git pull + 重启 ComfyUI); 工作台进程本身不需要单独更新.
  - 端口可改 (services.h3-engine.port), 引擎侧认 MIE_WEB_PORT.

主题: 所有配色走 theme_manager token, 禁硬编码 #rrggbb (AGENTS.md 规范).
"""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from .base_page import BasePage
from ui_qt.widgets.dialog_helper import DialogHelper
from ui_qt.widgets.custom import NoWheelComboBox
from ui_qt.log_viewer import LogTailer, read_tail_lines, VirtualTerminal, strip_ansi


STATE_NOT_INSTALLED = "not_installed"
STATE_NO_DEPS = "no_deps"
STATE_READY = "ready"
STATE_RUNNING = "running"
STATE_STARTING = "starting"
STATE_STOPPING = "stopping"
STATE_CHECKING = "checking"
STATE_DOWNLOADING = "downloading"        # 下载 H3 引擎中
STATE_INSTALLING_DEPS = "installing_deps"  # 安装 pip 依赖中
STATE_UPDATING = "updating"              # git 更新中

_BUSY_STATES = frozenset({
    STATE_CHECKING, STATE_STARTING, STATE_STOPPING,
    STATE_DOWNLOADING, STATE_INSTALLING_DEPS, STATE_UPDATING,
})

_BROWSER_OPEN_OPTS = [
    ("不自动打开", "disable"),
    ("使用默认浏览器", "default"),
    ("使用指定浏览器", "webbrowser"),
]

_RECENT_HISTORY_LINES = 500
_BATCH_INTERVAL_MS = 50


def _line_emitter_cls():
    """_LineEmitter 延迟定义 (与 openjutsu/webui 页同构)."""
    class _LineEmitter(QtCore.QObject):
        line_received = QtCore.pyqtSignal(str)
    return _LineEmitter


_LineEmitter = _line_emitter_cls()


def read_h3_version(root) -> str:
    """H3 引擎版本显示字符串: git describe 优先, 回落「未安装」/「未知」.

    必须先验 <root>/.git 存在: git -C 对非 git 目录会**向上冒泡**找外层仓库,
    把恰好盖在外层仓库下的目录 describe 成别人的版本 (openjutsu 页踩过).
    """
    from pathlib import Path as _P
    if not root or not _P(root).exists():
        return "未安装"
    try:
        if (_P(root) / ".git").exists():
            from utils.common import run_hidden
            r = run_hidden(["git", "-C", str(root), "describe", "--tags", "--always"],
                           capture_output=True, text=True, errors="ignore", timeout=10)
            if r.returncode == 0:
                v = (r.stdout or "").strip()
                if v:
                    return v
    except Exception:
        pass
    return "未知"


class H3Page(BasePage):
    """H3 短剧工作台: 启停 / 端口 / 日志."""

    SERVICE_ID = "h3-engine"

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self.theme_manager = theme_manager
        _styles = theme_manager.styles if theme_manager else None
        self._px = _styles._px if _styles else (lambda b: b)
        self._pt = _styles._pt if _styles else (lambda b: b)
        self._state: str = STATE_NOT_INSTALLED
        self._state_check_timer = None
        # 依赖探测缓存 (探测要 spawn python 验 import, 别每 5s 探一次)
        self._deps_cache_key: Optional[tuple] = None
        self._deps_cache_result: Optional[dict] = None
        # 日志 tail 状态 (复刻 openjutsu 页)
        self._tailer: Optional[LogTailer] = None
        self._emitter: Optional[_LineEmitter] = None
        self._batch_buffer: list[str] = []
        self._batch_timer: Optional[QtCore.QTimer] = None
        self._log_path: Optional[Path] = None
        self._history_loaded = False
        self._vt = VirtualTerminal()
        self._has_active_line = False
        self._setup_ui()
        self._refresh_state()
        self._start_log_tail()
        # 显式应用一次主题: _apply_theme 在页面构造**前**跑、register_listener
        # 不立即回调, 不自调的话输入框/下拉要等第一次切主题才有样式.
        try:
            self.update_theme()
        except Exception:
            pass
        # 5s 轮询 (busy 态跳过, 防 _poll_status 覆盖中间态)
        self._state_check_timer = QtCore.QTimer(self)
        self._state_check_timer.setInterval(5000)
        self._state_check_timer.timeout.connect(self._poll_status)
        self._state_check_timer.start()

    # ---------------- manager / registry ----------------

    def _mgr(self):
        from core.companion.manager import CompanionServiceManager
        return CompanionServiceManager(self.app, self.SERVICE_ID)

    def _spec(self):
        from core.companion.spec import BUILTIN_SERVICES
        return BUILTIN_SERVICES[self.SERVICE_ID]

    def _availability(self) -> dict:
        from core.companion import registry
        return registry.availability(self.app, self._spec())

    def _is_busy(self) -> bool:
        return self._state in _BUSY_STATES

    def _set_state(self, state: str) -> None:
        self._state = state
        self._update_ui_for_state()

    # ---------------- 主题 helper ----------------

    def _c(self, key: str, default: str = "") -> str:
        try:
            return self.theme_manager.colors.get(key, default)
        except Exception:
            return default

    def _log_view_style(self) -> str:
        return (
            "QPlainTextEdit {"
            f"  background-color: {self._c('input_readonly_bg', '#1F2937')};"
            f"  color: {self._c('input_readonly_text', '#9CA3AF')};"
            f"  font: {self._pt(9)}pt 'Consolas';"
            f"  border: 1px solid {self._c('input_border', '#4B5563')};"
            "  border-radius: 6px;"
            "}"
        )

    def _version_card_style(self) -> str:
        return (
            "QFrame {"
            f"  background-color: {self._c('card_bg', '#1F2937')};"
            f"  border: 1px solid {self._c('card_border', '#374151')};"
            "  border-radius: 6px;"
            "}"
        )

    def _config_label_style(self) -> str:
        return f'color: {self._c("label_muted", "#9CA3AF")}; font-weight: bold;'

    # ---------------- 配置读写 (services.h3-engine) ----------------

    def _svc_options(self) -> dict:
        cfg = getattr(self.app, "config", None)
        if isinstance(cfg, dict):
            svcs = cfg.get("services")
            if isinstance(svcs, dict):
                o = svcs.get(self.SERVICE_ID)
                if isinstance(o, dict):
                    return o
        return {}

    def _save_svc_option(self, key, value) -> None:
        try:
            cfg = getattr(self.app, "config", None)
            if not isinstance(cfg, dict):
                return
            svcs = cfg.setdefault("services", {})
            opts = svcs.setdefault(self.SERVICE_ID, {})
            opts[key] = value
            svc = getattr(self.app, "services", None)
            cfg_mgr = getattr(svc, "config", None) if svc else None
            if cfg_mgr is not None:
                saved = cfg_mgr.save(cfg)
                if saved is not None:
                    self.app.config = saved
        except Exception as e:
            try:
                self.app.logger.warning("保存 services.%s.%s 失败: %s",
                                        self.SERVICE_ID, key, e)
            except Exception:
                pass

    # ---------------- UI ----------------

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        lbl_style = self._config_label_style()

        # === 段1: 启动控制 ===
        launch_group = QtWidgets.QGroupBox("启动控制")
        launch_layout = QtWidgets.QHBoxLayout(launch_group)
        launch_layout.setContentsMargins(8, 12, 8, 12)
        launch_layout.setSpacing(15)
        layout.addWidget(launch_group)

        form_widget = QtWidgets.QWidget()
        form_layout = QtWidgets.QGridLayout(form_widget)
        form_layout.setColumnStretch(1, 1)
        form_layout.setHorizontalSpacing(20)
        form_layout.setVerticalSpacing(8)
        form_layout.setContentsMargins(0, 0, 0, 0)
        launch_layout.addWidget(form_widget, 1)

        port_label = QtWidgets.QLabel("工作台端口：")
        port_label.setStyleSheet(lbl_style)
        self._port_edit = QtWidgets.QLineEdit()
        self._port_edit_width_base = 60
        self._port_edit.setFixedWidth(self._px(self._port_edit_width_base))
        self._dpi_sized_widgets.append(
            (self._port_edit, "setFixedWidth", self._port_edit_width_base))
        self._port_edit.setText(str(self._svc_options().get("port") or 8200))
        self._port_edit.setToolTip("H3 短剧工作台端口，默认 8200（引擎侧同名端口）")
        self._port_edit.textChanged.connect(
            lambda v: self._save_svc_option("port", v.strip() or "8200"))

        hbox_port = QtWidgets.QHBoxLayout()
        hbox_port.setContentsMargins(0, 0, 0, 0)
        hbox_port.setSpacing(12)
        hbox_port.addWidget(port_label)
        hbox_port.addWidget(self._port_edit)
        hbox_port.addStretch(1)
        form_layout.addLayout(hbox_port, 0, 0, 1, 2)

        open_label = QtWidgets.QLabel("自动打开浏览器：")
        open_label.setStyleSheet(lbl_style)
        self._open_combo = NoWheelComboBox()
        for name, val in _BROWSER_OPEN_OPTS:
            self._open_combo.addItem(name, val)
        cur_mode = self._svc_options().get("browser_open_mode") or "default"
        for i, (name, val) in enumerate(_BROWSER_OPEN_OPTS):
            if val == cur_mode:
                self._open_combo.setCurrentIndex(i)
                break
        self._open_combo.currentIndexChanged.connect(
            lambda idx: self._save_svc_option("browser_open_mode",
                                              self._open_combo.itemData(idx) or "default"))
        self._open_combo.setToolTip("启动后自动打开浏览器访问 H3 短剧工作台")

        self._cpath_btn = QtWidgets.QPushButton()
        self._cpath_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._cpath_btn_width_base = 32
        self._cpath_btn.setFixedWidth(self._px(self._cpath_btn_width_base))
        self._dpi_sized_widgets.append(
            (self._cpath_btn, "setFixedWidth", self._cpath_btn_width_base))
        try:
            self._cpath_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_DirOpenIcon))
            self._cpath_btn.setIconSize(QtCore.QSize(14, 14))
        except Exception:
            pass
        self._cpath_btn.clicked.connect(self._on_pick_browser_path)
        self._update_cpath_vis()

        row_open = QtWidgets.QHBoxLayout()
        row_open.setContentsMargins(0, 0, 0, 0)
        row_open.setSpacing(8)
        row_open.addWidget(self._open_combo)
        row_open.addWidget(self._cpath_btn)
        row_open.addStretch(1)
        form_layout.addWidget(open_label, 1, 0)
        form_layout.addLayout(row_open, 1, 1)

        # --- 右: 按钮列 ---
        btn_col = QtWidgets.QVBoxLayout()
        btn_col.setSpacing(8)
        self._btn_primary = QtWidgets.QPushButton("🚀 一键启动")
        self._btn_primary.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_primary.setMinimumHeight(self._px(40))
        self._btn_primary.clicked.connect(self._on_primary_clicked)
        btn_col.addWidget(self._btn_primary)

        self._btn_open = QtWidgets.QPushButton("🌐 打开工作台")
        self._btn_open.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_open.clicked.connect(self._on_open_browser)
        btn_col.addWidget(self._btn_open)

        self._btn_update = QtWidgets.QPushButton("🔄 更新引擎")
        self._btn_update.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_update.clicked.connect(self._on_update_clicked)
        self._btn_update.setToolTip(
            "git 拉取 H3 引擎最新代码（用户资产与密钥不会被覆盖）")
        btn_col.addWidget(self._btn_update)
        launch_layout.addLayout(btn_col)

        # === 段2: 环境信息 ===
        info_group = QtWidgets.QGroupBox("环境信息")
        info_layout = QtWidgets.QHBoxLayout(info_group)
        info_layout.setContentsMargins(8, 12, 8, 12)
        info_layout.setSpacing(8)
        layout.addWidget(info_group)

        self._info_card = QtWidgets.QFrame()
        self._info_card.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        card_layout = QtWidgets.QVBoxLayout(self._info_card)
        card_layout.setContentsMargins(5, 2, 5, 2)
        card_layout.setSpacing(2)
        self._state_item = self._create_info_item("状态", "…", "🔎")
        self._version_item = self._create_info_item("引擎版本", "…", "🏷")
        self._asset_item = self._create_info_item("资产库", "…", "📦")
        self._keys_item = self._create_info_item("LLM 密钥", "…", "🔑")
        self._settings_item = self._create_info_item("设置文件", "…", "⚙")
        card_layout.addWidget(self._state_item)
        card_layout.addWidget(self._version_item)
        card_layout.addWidget(self._asset_item)
        card_layout.addWidget(self._keys_item)
        card_layout.addWidget(self._settings_item)
        info_layout.addWidget(self._info_card, 1)

        beta_hint = QtWidgets.QLabel(
            "Beta：H3 短剧工作台还在持续完善，功能与交互可能变化；"
            "遇到问题欢迎反馈（附日志更好定位）。")
        beta_hint.setStyleSheet(f'color: {self._c("warning", "#D97706")};')
        beta_hint.setWordWrap(True)
        info_layout.addWidget(beta_hint)

        hint = QtWidgets.QLabel("提示：H3 引擎本体是 ComfyUI 自定义节点，升级请到「插件管理」")
        hint.setStyleSheet(f'color: {self._c("label_dim", "#6B7280")};')
        hint.setWordWrap(True)
        info_layout.addWidget(hint, 1)

        # === 段3: 实时日志 ===
        log_group = QtWidgets.QGroupBox("实时日志")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        log_layout.setContentsMargins(8, 12, 8, 12)
        log_layout.setSpacing(6)
        layout.addWidget(log_group, 1)

        # 用 QPlainTextEdit (QSS 选择器就是它; 写成 QTextEdit 会静默吃不到样式)
        self._log_view = QtWidgets.QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(5000)
        self._log_view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        log_layout.addWidget(self._log_view, 1)

        log_btn_row = QtWidgets.QHBoxLayout()
        log_btn_row.addStretch(1)
        self._btn_log_clear = QtWidgets.QPushButton("🧹 清空")
        self._btn_log_clear.clicked.connect(self._on_clear_log)
        self._btn_log_open = QtWidgets.QPushButton("📂 打开日志文件")
        self._btn_log_open.clicked.connect(self._open_log_file)
        log_btn_row.addWidget(self._btn_log_clear)
        log_btn_row.addWidget(self._btn_log_open)
        log_layout.addLayout(log_btn_row)

    def _create_info_item(self, title: str, value: str, icon_str: str):
        card = QtWidgets.QFrame()
        card.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        card.setStyleSheet("QFrame { background: transparent; border: none; }")
        hb = QtWidgets.QHBoxLayout(card)
        hb.setContentsMargins(5, 2, 5, 2)
        hb.setSpacing(8)
        hb.setAlignment(QtCore.Qt.AlignCenter)
        icon_lbl = QtWidgets.QLabel(icon_str)
        icon_lbl.setStyleSheet(f"font-size: {self._pt(14)}pt; background: transparent;")
        hb.addWidget(icon_lbl)
        t = QtWidgets.QLabel("%s :" % title)
        t.setStyleSheet(
            f'color: {self._c("label_muted", "#9CA3AF")};'
            f' font: bold {self._pt(9)}pt "Microsoft YaHei UI"; background: transparent;'
        )
        hb.addWidget(t)
        v = QtWidgets.QLabel(value)
        v.setStyleSheet(
            f'font: bold {self._pt(10)}pt "Segoe UI", "Microsoft YaHei UI";'
            f' color: {self._c("text", "#E5E7EB")}; background: transparent;'
        )
        hb.addWidget(v)
        if not hasattr(self, "_info_title_refs"):
            self._info_title_refs = []
        if not hasattr(self, "_info_value_refs"):
            self._info_value_refs = []
        self._info_title_refs.append(t)
        self._info_value_refs.append(v)
        return card

    def _set_info_item_value(self, card, text: str, is_error: bool = False) -> None:
        try:
            layout = card.layout()
            if layout is None or layout.count() < 3:
                return
            v_lbl = layout.itemAt(2).widget()
            v_lbl.setText(str(text))
            color = self._c("error", "#EF4444") if is_error else self._c("text", "#E5E7EB")
            v_lbl.setStyleSheet(
                f'font: bold {self._pt(10)}pt "Segoe UI", "Microsoft YaHei UI";'
                f' color: {color}; background: transparent;'
            )
        except Exception:
            pass

    # ---------------- 状态机 ----------------

    def _detect_state(self) -> str:
        avail = self._availability()
        if not avail["available"]:
            return STATE_NOT_INSTALLED
        try:
            if self._mgr().is_running():
                return STATE_RUNNING
        except Exception:
            pass
        deps = self._deps_cached()
        if not deps.get("ok"):
            return STATE_NO_DEPS
        return STATE_READY

    def _deps_cached(self) -> dict:
        """依赖闸门 (带缓存): 入口 / 该环境 python / 资产库目录 / mie_* 依赖."""
        avail = self._availability()
        root = avail.get("root")
        if not root:
            return {"ok": False, "missing": ["服务未安装"]}
        key = (root,)
        if self._deps_cache_key == key and self._deps_cache_result is not None:
            return self._deps_cache_result
        try:
            from core.companion import h3_runtime
            paths = h3_runtime.resolve_paths(self.app)
            res = h3_runtime.check_deps(paths)
        except Exception:
            res = {"ok": False, "missing": ["依赖探测失败"]}
        self._deps_cache_key = key
        self._deps_cache_result = res
        return res

    def _reset_deps_cache(self):
        self._deps_cache_key = None
        self._deps_cache_result = None

    def _read_version(self) -> str:
        return read_h3_version(self._availability().get("root"))

    def _env_paths(self) -> dict:
        try:
            from core.companion import h3_runtime
            return h3_runtime.resolve_paths(self.app)
        except Exception:
            return {}

    def _refresh_state(self, force: bool = False):
        if self._is_busy() and not force:
            return
        self._set_state(self._detect_state())

    def _poll_status(self):
        if self._is_busy():
            return
        # 状态探测会一路走到 core/probe.py::find_pids_by_port_safe → Windows 上
        # 可能 spawn `netstat -ano` 并**同步等待**（几百 ms）。在 UI 主线程做这件事
        # = 每 5 秒把主线程堵一次 → 点别的页面时点击事件排在队列后面，体感就是
        # 「切换要卡一下才响应」（证据：launcher/stall_probe.log 里主线程栈顶是
        # probe.find_pids_by_port_safe → subprocess.run）。
        # 所以：后台线程探测 → 算好状态 → invokeMethod 回主线程应用。
        if getattr(self, "_poll_inflight", False):
            return
        self._poll_inflight = True

        def _worker():
            try:
                state = self._detect_state()
            except Exception:
                return
            finally:
                try:
                    self._poll_inflight = False
                except Exception:
                    pass
            try:
                QtCore.QMetaObject.invokeMethod(
                    self, "_apply_polled_state",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, state),
                )
            except Exception:
                pass

        try:
            import threading
            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            self._poll_inflight = False

    @QtCore.pyqtSlot(str)
    def _apply_polled_state(self, state: str):
        """后台探测算出的状态 → 回主线程应用（等价原来的 _refresh_state）。"""
        try:
            if self._is_busy():
                return
            self._set_state(state)
        except Exception:
            pass

    def _update_ui_for_state(self):
        avail = self._availability()
        paths = self._env_paths()
        ver_txt = self._read_version() if avail["available"] else "当前环境未检测到"
        try:
            self._version_item.setToolTip(
                f"解析 root: {avail.get('root')}\n"
                f"缺失: {', '.join(avail['missing_markers']) or '无'}")
        except Exception:
            pass

        _STATUS_TXT = {
            STATE_NOT_INSTALLED: "未安装",
            STATE_NO_DEPS: "依赖缺失",
            STATE_READY: "已就绪",
            STATE_RUNNING: "运行中",
            STATE_CHECKING: "检测中…",
            STATE_STARTING: "启动中…",
            STATE_STOPPING: "停止中…",
            STATE_DOWNLOADING: "下载中…",
            STATE_INSTALLING_DEPS: "安装依赖中…",
            STATE_UPDATING: "更新中…",
        }
        self._set_info_item_value(self._state_item,
                                 _STATUS_TXT.get(self._state, self._state),
                                 is_error=self._state in (STATE_NOT_INSTALLED, STATE_NO_DEPS))
        self._set_info_item_value(self._version_item, ver_txt)

        library = paths.get("asset_library")
        self._set_info_item_value(
            self._asset_item,
            str(library) if library else "未解析",
            is_error=not bool(library))
        keys = paths.get("keys_file")
        keys_ok = bool(keys) and os.path.exists(str(keys))
        self._set_info_item_value(
            self._keys_item,
            (str(keys) if keys else "未解析") + ("" if keys_ok else " (未填写)"),
            is_error=not keys_ok)
        settings = paths.get("settings_file")
        self._set_info_item_value(self._settings_item,
                                 str(settings) if settings else "未解析")

        _BTN_TEXT = {
            STATE_NOT_INSTALLED: "⬇ 下载 H3 引擎",
            STATE_NO_DEPS: "⚙ 安装依赖",
            STATE_READY: "🚀 一键启动",
            STATE_RUNNING: "⏹ 停止",
            STATE_CHECKING: "⏳ 检测中…",
            STATE_STARTING: "⏳ 启动中…",
            STATE_STOPPING: "⏳ 停止中…",
            STATE_DOWNLOADING: "⬇ 下载中…",
            STATE_INSTALLING_DEPS: "⚙ 安装依赖中…",
            STATE_UPDATING: "⏳ 更新中…",
        }
        self._btn_primary.setText(_BTN_TEXT.get(self._state, "…"))
        self._btn_primary.setEnabled(not self._is_busy())
        self._btn_open.setEnabled(self._state == STATE_RUNNING)
        # 更新只在「已安装且没在跑」时可用 (跑着更新会换掉正在用的代码)
        self._btn_update.setEnabled(self._state in (STATE_READY, STATE_NO_DEPS)
                                    and not self._is_busy())
        # 端口编辑: 运行中禁改 (改了也不生效, 徒增困惑)
        self._port_edit.setEnabled(self._state != STATE_RUNNING)

    # ---------------- 启停 ----------------

    def _on_primary_clicked(self):
        if self._is_busy():
            return
        if self._state == STATE_NOT_INSTALLED:
            self._download_h3()
        elif self._state == STATE_NO_DEPS:
            self._setup_deps()
        elif self._state == STATE_READY:
            self._start_service()
        elif self._state == STATE_RUNNING:
            self._stop_service()

    # ---------------- 下载 / 依赖 / 更新 ----------------

    def _download_h3(self):
        """下载 H3 引擎本体 (git clone 到 custom_nodes 下)."""
        self._set_state(STATE_DOWNLOADING)

        def runner(on_progress):
            res = self._mgr().install(on_progress=on_progress)
            return {"ok": bool(res.get("ok")),
                    "error": res.get("error") or "",
                    "already_exists": bool(res.get("already_exists"))}

        def on_done(result):
            self._after_install("下载失败: " + (result.get("error") or "未知")
                                if not result.get("ok") else "下载完成")

        self._run_with_progress("下载 H3 引擎", runner, on_done)

    def _setup_deps(self):
        """装 pip 依赖 (进该环境的 embedded python)."""
        self._set_state(STATE_INSTALLING_DEPS)

        def runner(on_progress):
            res = self._mgr().setup(on_progress=on_progress)
            missing = res.get("deps_missing") or []
            failed = res.get("deps_failed") or []
            return {"ok": bool(res.get("ok")),
                    "error": res.get("deps_error") or res.get("error") or "",
                    "missing": missing, "failed": failed}

        def on_done(result):
            if result.get("ok"):
                self._after_install("依赖安装完成")
                return
            detail = []
            if result.get("missing"):
                detail.append("装不上: " + ", ".join(result["missing"]))
            if result.get("failed"):
                detail.append("失败: " + ", ".join(
                    str(f.get("spec") or f) for f in result["failed"]))
            msg = "依赖安装失败"
            if detail:
                msg += "\n\n" + "\n".join(detail)
            self._after_install(msg)

    def _on_update_clicked(self):
        """更新引擎本体 (git fetch + reset --hard)."""
        if self._is_busy():
            return
        avail = self._availability()
        if not avail["available"]:
            DialogHelper.show_warning(self, "无法更新", "当前环境没有 H3 引擎，请先下载。")
            return
        root = avail.get("root")
        if root and not (Path(root) / ".git").exists():
            DialogHelper.show_warning(self, "无法更新",
                                      "H3 引擎目录不是 git 仓库，无法更新。")
            return

        def runner(on_progress):
            res = self._mgr().update(on_progress=on_progress)
            return {"ok": bool(res.get("ok")),
                    "updated": bool(res.get("updated")),
                    "error": res.get("error") or ""}

        def on_done(result):
            self._after_install("更新失败: " + (result.get("error") or "未知")
                                if not result.get("ok") else "更新完成")

        self._run_with_progress("更新 H3 引擎", runner, on_done)

    @QtCore.pyqtSlot(str)
    def _after_install(self, msg: str):
        """下载/装依赖/更新完成回主线程: 失败给「关闭 / 立即重试」两按钮."""
        self._reset_deps_cache()
        if msg.startswith("下载失败") or msg.startswith("更新失败") \
                or msg.startswith("依赖安装失败"):
            try:
                from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
                dlg = CustomConfirmDialog(
                    parent=self,
                    title="H3 短剧工作台操作失败",
                    content=msg + "\n\n可以关闭 (手动检查网络 / 镜像) 或 立即重试.",
                    buttons=[{"text": "关闭", "role": "normal"},
                             {"text": "立即重试", "role": "primary"}],
                    default_index=1,
                    theme_manager=self.theme_manager,
                )
                dlg.exec_()
                retry = (dlg.get_result() == 1)
            except Exception:
                retry = False
            self._set_state(self._detect_state())
            if retry:
                try:
                    self._on_primary_clicked()
                except Exception:
                    pass
            return
        self._set_state(self._detect_state())

    def _run_with_progress(self, task_title, runner, on_done_slot, parent=None):
        """后台任务调度 helper (复刻 webui_page._run_with_progress).

        弹进度窗 + 注册后台任务 + on_progress 派发; on_done_slot 必须回主线程
        (会动 _set_state / DialogHelper 等 Qt widgets).
        """
        from ui_qt.widgets.progress_dialog import ProgressDialog

        parent = parent or self.app
        registry = getattr(self.app, "_bg_task_registry", None)
        task_id = registry.register(task_title) if registry else None
        if isinstance(parent, QtWidgets.QWidget):
            pd = ProgressDialog(
                parent, title=task_title,
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
                    pd.mark_complete("完成 ✓" if success else "完成(有失败)")
                    pd.close()
                except Exception:
                    pass

        def _finish(success, result):
            _ui_post = getattr(self.app, "ui_post", None)
            if _ui_post:
                _ui_post(lambda: _do_finish(success))
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

    def _start_service(self):
        self._set_state(STATE_STARTING)

        def _worker():
            res = self._mgr().start(timeout=120)
            started_ok = bool(res.get("ok"))
            err = res.get("error")
            QtCore.QMetaObject.invokeMethod(
                self, "_after_action_done",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(bool, started_ok),
                QtCore.Q_ARG(str, err or ""),
            )
            if started_ok and self._should_auto_open():
                QtCore.QMetaObject.invokeMethod(
                    self, "_open_url_after_start",
                    QtCore.Qt.QueuedConnection,
                )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _stop_service(self):
        manager = self._mgr()
        health = manager.status().get("health") or {}
        busy = health.get("idle") is False
        if busy and not DialogHelper.show_confirmation(
                self, "H3 工作台正在渲染", "仍要停止 H3 工作台吗？",
                yes_text="停止工作台", no_text="继续运行", destructive=True):
            return
        self._set_state(STATE_STOPPING)

        def _worker():
            res = manager.stop(timeout=10, force=busy)
            err = res.get("error")
            QtCore.QMetaObject.invokeMethod(
                self, "_after_action_done",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(bool, bool(res.get("ok"))),
                QtCore.Q_ARG(str, err or ""),
            )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    @QtCore.pyqtSlot(bool, str)
    def _after_action_done(self, started_ok: bool, err: str):
        """启/停完成回主线程: 失败弹窗 (带日志路径), 成功 re-detect."""
        if not started_ok and err:
            DialogHelper.show_warning(
                self, "H3 短剧工作台操作失败",
                "%s\n\n详细日志: launcher/h3-engine.log" % err,
            )
        self._reset_deps_cache()
        self._set_state(self._detect_state())

    @QtCore.pyqtSlot()
    def _open_url_after_start(self):
        self._open_url(self._browser_url())

    # ---------------- 浏览器 ----------------

    def _should_auto_open(self) -> bool:
        mode = (self._svc_options().get("browser_open_mode") or "default").strip().lower()
        return mode not in ("disable", "none")

    def _open_url(self, url: str) -> None:
        opts = self._svc_options()
        mode = opts.get("browser_open_mode") or "default"
        if mode == "disable":
            return
        if mode == "webbrowser":
            cpath = (opts.get("custom_browser_path") or "").strip()
            if cpath and os.path.exists(cpath):
                try:
                    subprocess.Popen([cpath, url])
                    return
                except Exception:
                    pass
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _browser_url(self) -> str:
        from core.companion import registry
        ports = registry.resolved_ports(self.app, self._spec())
        return "http://127.0.0.1:%s/" % ports.get("app", 8200)

    def _on_open_browser(self):
        if self._state != STATE_RUNNING:
            return
        self._open_url(self._browser_url())

    def _on_pick_browser_path(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择浏览器可执行文件", "", "可执行文件 (*.exe);;所有文件 (*)")
        if path:
            self._save_svc_option("custom_browser_path", path)
        self._update_cpath_vis()

    def _update_cpath_vis(self):
        mode = self._svc_options().get("browser_open_mode") or "default"
        self._cpath_btn.setVisible(mode == "webbrowser")

    # ---------------- 日志 (复刻 openjutsu 页) ----------------

    def _resolve_log_path(self) -> Path:
        try:
            cwd = Path(getattr(self.app, "_cwd", ".") or ".")
        except Exception:
            cwd = Path(".")
        return cwd / "launcher" / "h3-engine.log"

    def showEvent(self, event):
        super().showEvent(event)
        if not self._history_loaded:
            self._history_loaded = True
            try:
                self._load_recent_history()
            except Exception:
                pass

    def _load_recent_history(self):
        path = self._log_path
        if path is None:
            return
        try:
            lines = read_tail_lines(path, _RECENT_HISTORY_LINES)
        except Exception:
            return
        for line in lines:
            self._enqueue_batch(strip_ansi(line))

    def _start_log_tail(self) -> None:
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
        self._emitter = _LineEmitter()
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
        if self._tailer is not None:
            try:
                self._tailer.stop()
            except Exception:
                pass
            self._tailer = None
        self._emitter = None
        active = self._vt.active_line
        if active:
            self._vt.reset()
            self._enqueue_batch(strip_ansi(active))

    def _on_line_from_tailer(self, line: str) -> None:
        emitter = self._emitter
        if emitter is None:
            return
        emitter.line_received.emit(line)

    def _on_line_main(self, line: str) -> None:
        finalized = self._vt.feed(line)
        for fl in finalized:
            if fl:
                self._enqueue_batch(strip_ansi(fl))
        self._enqueue_batch(None)

    def _enqueue_batch(self, line) -> None:
        if line is not None:
            self._batch_buffer.append(line)
            if len(self._batch_buffer) > 5000:
                self._batch_buffer = self._batch_buffer[-3000:]
        if self._batch_timer is None:
            self._batch_timer = QtCore.QTimer(self)
            self._batch_timer.setInterval(_BATCH_INTERVAL_MS)
            self._batch_timer.timeout.connect(self._flush_batch)
        if not self._batch_timer.isActive():
            self._batch_timer.start(_BATCH_INTERVAL_MS)

    def _flush_batch(self) -> None:
        active = strip_ansi(self._vt.active_line)
        if not self._batch_buffer and not active and not self._has_active_line:
            return
        text = "\n".join(self._batch_buffer)
        self._batch_buffer.clear()
        cursor = self._log_view.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        if self._has_active_line:
            cursor.movePosition(QtGui.QTextCursor.StartOfBlock)
            cursor.movePosition(QtGui.QTextCursor.EndOfBlock, QtGui.QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            self._has_active_line = False
        if text:
            cursor.insertText(text + "\n")
        if active:
            cursor.insertText(active)
            self._has_active_line = True
        bar = self._log_view.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def _on_clear_log(self):
        self._log_view.clear()
        self._vt.reset()
        self._has_active_line = False
        self._batch_buffer.clear()

    def _open_log_file(self):
        log_path = self._resolve_log_path()
        try:
            if sys.platform == "win32":
                os.startfile(str(log_path.parent))
            else:
                webbrowser.open("file://" + str(log_path))
        except Exception:
            pass

    # ---------------- 主题 / 外部 hook ----------------

    def _on_theme_changed(self, theme_styles):
        self.update_theme(theme_styles)

    def update_theme(self, theme_styles=None):
        """重应用所有主题化控件 QSS (响应深/浅切换)."""
        super().update_theme(theme_styles)
        styles = theme_styles if theme_styles is not None else self.theme_manager.styles
        input_ss = styles.input_style()
        primary_ss = styles.primary_button_style()
        self._btn_primary.setStyleSheet(primary_ss)
        self._btn_open.setStyleSheet(primary_ss)
        self._btn_update.setStyleSheet(styles.secondary_button_style())
        self._btn_log_clear.setStyleSheet(styles.secondary_button_style())
        self._btn_log_open.setStyleSheet(styles.secondary_button_style())
        self._port_edit.setStyleSheet(input_ss)
        self._open_combo.setStyleSheet(input_ss)
        self._cpath_btn.setStyleSheet(input_ss)
        self._log_view.setStyleSheet(self._log_view_style())
        self._info_card.setStyleSheet(self._version_card_style())
        self._update_cpath_vis()
        try:
            label_muted = self._c("label_muted", "#9CA3AF")
            for ref in getattr(self, "_info_title_refs", []):
                ref.setStyleSheet(
                    f'color: {label_muted}; font: bold {self._pt(9)}pt "Microsoft YaHei UI";'
                    f' background: transparent;'
                )
            for ref in getattr(self, "_info_value_refs", []):
                color = self._c("text", "#E5E7EB")
                ref.setStyleSheet(
                    f'font: bold {self._pt(10)}pt "Segoe UI", "Microsoft YaHei UI";'
                    f' color: {color}; background: transparent;'
                )
        except Exception:
            pass

    def refresh_after_env_switch(self):
        """环境切换后刷新 (依赖/资产/设置路径都随环境变)."""
        self._reset_deps_cache()
        try:
            self._port_edit.setText(str(self._svc_options().get("port") or 8200))
        except Exception:
            pass
        self._refresh_state(force=True)
