"""openjutsu 伴生服务页 (启停 / 端口配置 / 更新 / 日志).

复刻 webui_page 的骨架 (状态机 + 后台线程 + QMetaObject 回主线程 + _run_with_progress
+ LogTailer), 但生命周期全部走 core.companion 新框架 (CompanionServiceManager).
webui 页本期不动 (strangler, 见 docs/companion-services-design.md §2).

与 webui 页的差异 (来自服务特性):
  - requires_comfyui=True: 启动前 ComfyUI 必须在跑 → 弹两选一 (取消 / 一键启动
    ComfyUI + openjutsu), 没有 webui 的「只启服务」选项 (裸启 openjutsu 会永远
    等不到 8188, 无意义).
  - 双端口 (proxy 8197 / app 8198), 配置项两个.
  - 无 install/下载态: openjutsu 随整合包分发, 「未安装」= 当前环境没有该服务
    (页面仍可看, 但只有说明文字).
  - 更新链是 5 步 (git → npm ci → build → pip --target → patch), 走进度对话框.
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
from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
from ui_qt.widgets.custom import NoWheelComboBox
from ui_qt.log_viewer import LogTailer, read_tail_lines, VirtualTerminal, strip_ansi


STATE_NOT_INSTALLED = "not_installed"
STATE_NO_DEPS = "no_deps"
STATE_READY = "ready"
STATE_RUNNING = "running"
STATE_STARTING = "starting"
STATE_STOPPING = "stopping"
STATE_CHECKING = "checking"
STATE_WAITING_COMFYUI = "waiting_comfyui"
STATE_UPDATING = "updating"

_BUSY_STATES = frozenset({
    STATE_CHECKING, STATE_WAITING_COMFYUI,
    STATE_STARTING, STATE_STOPPING, STATE_UPDATING,
})

_BROWSER_OPEN_OPTS = [
    ("不自动打开", "disable"),
    ("使用默认浏览器", "default"),
    ("使用指定浏览器", "webbrowser"),
]

_RECENT_HISTORY_LINES = 500
_BATCH_INTERVAL_MS = 50


def _line_emitter_cls():
    """_LineEmitter 延迟定义 (与 webui_page 同构: tailer 线程 → UI 线程信号桥)."""
    class _LineEmitter(QtCore.QObject):
        line_received = QtCore.pyqtSignal(str)
    return _LineEmitter


_LineEmitter = _line_emitter_cls()


def read_openjutsu_version(root) -> str:
    """版本显示字符串: git describe 优先, 回落 package.json 的 version, 再回落 '未知'.

    2026-10-31 真机教训: openjutsu 的 package.json **没有 version 字段**,
    单读它版本显示为空; 仓库本身有 tag, git describe 才是可靠来源.
    纯函数, 供页面与测试直接调.
    """
    from pathlib import Path as _P
    if not root or not _P(root).exists():
        return "未安装"
    # 1. git describe (tags 优先, 无 tag 落 commit hash).
    #    必须先验 <root>/.git 存在: git -C 对非 git 目录会**向上冒泡**找仓库,
    #    把恰好盖在某外层仓库下的目录 describe 成别人的版本 (测试实测:
    #    basetemp 里的假目录返回了启动器自己的 v1.0.18-1-g6508fff).
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
    # 2. package.json version
    try:
        import json as _json
        data = _json.loads((_P(root) / "package.json").read_text(encoding="utf-8"))
        v = str(data.get("version") or "").strip()
        if v:
            return v
    except Exception:
        pass
    return "未知"


class OpenjutsuPage(BasePage):
    """openjutsu 伴生服务: 启停 / 端口 / 更新 / 日志."""

    SERVICE_ID = "openjutsu"

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self.theme_manager = theme_manager
        _styles = theme_manager.styles if theme_manager else None
        self._px = _styles._px if _styles else (lambda b: b)
        self._pt = _styles._pt if _styles else (lambda b: b)
        self._state: str = STATE_NOT_INSTALLED
        self._state_check_timer = None
        self._updating = False
        # 依赖探测缓存 (同 webui 页: 探测要 spawn python, 别每 5s 探一次)
        self._deps_cache_key: Optional[tuple] = None
        self._deps_cache_result: Optional[dict] = None
        # 日志 tail 状态 (复刻 webui_page)
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
        # 不立即回调, 不自调的话输入框/下拉要等第一次切主题才有样式
        # (2026-10-31 真机验证: 下拉菜单看不清的根因).
        try:
            self.update_theme()
        except Exception:
            pass
        # 5s 轮询 (busy 态跳过, 防 _poll_status 覆盖中间态 —— 同 webui 页)
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

    # ---------------- 主题 helper (同 webui 页) ----------------

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

    # ---------------- 配置读写 (services.openjutsu) ----------------

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
                self.app.logger.warning("保存 services.%s.%s 失败: %s", self.SERVICE_ID, key, e)
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

        # 双端口: 前端 (app) + 中转 (proxy)
        app_port_label = QtWidgets.QLabel("前端端口：")
        app_port_label.setStyleSheet(lbl_style)
        self._app_port_edit = QtWidgets.QLineEdit()
        self._app_port_edit_width_base = 60
        self._app_port_edit.setFixedWidth(self._px(self._app_port_edit_width_base))
        self._dpi_sized_widgets.append((self._app_port_edit, "setFixedWidth", self._app_port_edit_width_base))
        self._app_port_edit.setText(str(self._svc_options().get("app_port") or 8198))
        self._app_port_edit.setToolTip("openjutsu 前端 (Next.js) 端口，默认 8198")
        self._app_port_edit.textChanged.connect(
            lambda v: self._save_svc_option("app_port", v.strip() or "8198"))

        proxy_port_label = QtWidgets.QLabel("中转端口：")
        proxy_port_label.setStyleSheet(lbl_style)
        self._proxy_port_edit = QtWidgets.QLineEdit()
        self._proxy_port_edit.setFixedWidth(self._px(self._app_port_edit_width_base))
        self._dpi_sized_widgets.append((self._proxy_port_edit, "setFixedWidth", self._app_port_edit_width_base))
        self._proxy_port_edit.setText(str(self._svc_options().get("proxy_port") or 8197))
        self._proxy_port_edit.setToolTip("comfy-api-proxy 上传中转端口，默认 8197")
        self._proxy_port_edit.textChanged.connect(
            lambda v: self._save_svc_option("proxy_port", v.strip() or "8197"))

        hbox_ports = QtWidgets.QHBoxLayout()
        hbox_ports.setContentsMargins(0, 0, 0, 0)
        hbox_ports.setSpacing(12)
        hbox_ports.addWidget(app_port_label)
        hbox_ports.addWidget(self._app_port_edit)
        hbox_ports.addWidget(proxy_port_label)
        hbox_ports.addWidget(self._proxy_port_edit)
        hbox_ports.addStretch(1)
        form_layout.addLayout(hbox_ports, 0, 0, 1, 2)

        # 自动打开浏览器
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
        self._open_combo.setToolTip("启动后自动打开浏览器访问 openjutsu 前端")

        self._cpath_btn = QtWidgets.QPushButton()
        self._cpath_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._cpath_btn_width_base = 32
        self._cpath_btn.setFixedWidth(self._px(self._cpath_btn_width_base))
        self._dpi_sized_widgets.append((self._cpath_btn, "setFixedWidth", self._cpath_btn_width_base))
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

        self._btn_open = QtWidgets.QPushButton("🌐 打开前端")
        self._btn_open.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_open.clicked.connect(self._on_open_browser)
        btn_col.addWidget(self._btn_open)
        launch_layout.addLayout(btn_col)

        # === 段2: 版本与更新 ===
        ver_group = QtWidgets.QGroupBox("版本与更新")
        ver_layout = QtWidgets.QHBoxLayout(ver_group)
        ver_layout.setContentsMargins(8, 12, 8, 12)
        ver_layout.setSpacing(8)
        layout.addWidget(ver_group)

        self._version_info_card = QtWidgets.QFrame()
        self._version_info_card.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        info_layout = QtWidgets.QVBoxLayout(self._version_info_card)
        info_layout.setContentsMargins(5, 2, 5, 2)
        info_layout.setSpacing(2)
        self._version_item = self._create_version_item("版本", "…", "🏷")
        self._config_status_item = self._create_version_item("状态", "…", "🔎")
        info_layout.addWidget(self._version_item)
        info_layout.addWidget(self._config_status_item)
        ver_layout.addWidget(self._version_info_card, 1)

        self._btn_update = QtWidgets.QPushButton("🔄 更新")
        self._btn_update.setCursor(QtCore.Qt.PointingHandCursor)
        self._btn_update.clicked.connect(self._on_update_clicked)
        ver_layout.addWidget(self._btn_update)

        # === 段3: 实时日志 ===
        log_group = QtWidgets.QGroupBox("实时日志")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        log_layout.setContentsMargins(8, 12, 8, 12)
        log_layout.setSpacing(6)
        layout.addWidget(log_group, 1)

        # 与 webui 页同款 QPlainTextEdit: _log_view_style() 的 QSS 选择器就是
        # QPlainTextEdit, 用 QTextEdit 会完全吃不到样式 (2026-10-31 真机「日志
        # 看不清」的根因). setMaximumBlockCount 自动截断超限历史, 防长跑涨内存.
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

    def _create_version_item(self, title: str, value: str, icon_str: str):
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
        if not hasattr(self, "_version_value_refs"):
            self._version_value_refs = []
        if not hasattr(self, "_version_title_refs"):
            self._version_title_refs = []
        self._version_title_refs.append(t)
        self._version_value_refs.append(v)
        return card

    def _set_version_item_value(self, card, text: str, is_error: bool = False) -> None:
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
        if not self._deps_ok_cached():
            return STATE_NO_DEPS
        return STATE_READY

    def _deps_ok_cached(self) -> bool:
        """依赖闸门 (带缓存): node / .proxy-site 可导入 / node_modules/next."""
        avail = self._availability()
        root = avail.get("root")
        if not root:
            return False
        key = (root,)
        if self._deps_cache_key == key and self._deps_cache_result is not None:
            return self._deps_cache_result.get("ok") is True
        try:
            from core.companion import openjutsu_runtime
            paths = openjutsu_runtime.resolve_paths(self.app)
            res = openjutsu_runtime.check_deps(paths)
        except Exception:
            res = {"ok": False}
        self._deps_cache_key = key
        self._deps_cache_result = res
        return res.get("ok") is True

    def _reset_deps_cache(self):
        self._deps_cache_key = None
        self._deps_cache_result = None

    def _read_version(self) -> str:
        return read_openjutsu_version(self._availability().get("root"))

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
        ver_txt = self._read_version() if avail["available"] else "当前环境未检测到"
        # 未检测到时把解析出的 root 挂 tooltip, 排查「服务在但页面说没有」有据可查
        try:
            self._version_item.setToolTip(
                f"解析 root: {avail.get('root')}\n缺失: {', '.join(avail['missing_markers']) or '无'}")
        except Exception:
            pass
        _STATUS_TXT = {
            STATE_NOT_INSTALLED: "未安装",
            STATE_NO_DEPS: "依赖缺失",
            STATE_READY: "已就绪",
            STATE_RUNNING: "运行中",
            STATE_CHECKING: "检测中…",
            STATE_WAITING_COMFYUI: "等待 ComfyUI 启动中…",
            STATE_STARTING: "启动中…",
            STATE_STOPPING: "停止中…",
            STATE_UPDATING: "更新中…",
        }
        self._set_version_item_value(self._version_item, ver_txt)
        self._set_version_item_value(
            self._config_status_item,
            _STATUS_TXT.get(self._state, self._state),
            is_error=self._state in (STATE_NOT_INSTALLED, STATE_NO_DEPS))

        _BTN_TEXT = {
            STATE_NOT_INSTALLED: "⊘ 当前环境无此服务",
            STATE_NO_DEPS: "⚠ 依赖缺失 (整合包不完整)",
            STATE_READY: "🚀 一键启动",
            STATE_RUNNING: "⏹ 停止",
            STATE_CHECKING: "⏳ 检测中…",
            STATE_WAITING_COMFYUI: "⏳ 等待 ComfyUI 启动中…",
            STATE_STARTING: "⏳ 启动中…",
            STATE_STOPPING: "⏳ 停止中…",
            STATE_UPDATING: "⏳ 更新中…",
        }
        self._btn_primary.setText(_BTN_TEXT.get(self._state, "…"))
        self._btn_primary.setEnabled(not self._is_busy())
        self._btn_open.setEnabled(self._state == STATE_RUNNING)
        self._btn_update.setEnabled(self._state == STATE_READY and not self._updating)
        # 端口编辑: 运行中禁改 (改了也不生效, 徒增困惑)
        running = self._state == STATE_RUNNING
        self._app_port_edit.setEnabled(not running)
        self._proxy_port_edit.setEnabled(not running)

    # ---------------- 启停 ----------------

    def _on_primary_clicked(self):
        if self._is_busy():
            return
        if self._state == STATE_READY:
            self._start_with_prompt()
        elif self._state == STATE_RUNNING:
            self._stop_service()

    def _start_with_prompt(self):
        """requires_comfyui: 先后台探活 ComfyUI, 没跑 → 两选一 (取消 / 一键全起)."""
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
        if comfyui_running:
            self._start_service()
            return
        self._set_state(STATE_READY)
        dlg = CustomConfirmDialog(
            parent=self,
            title="启动 openjutsu",
            content=(
                "openjutsu 需要 ComfyUI 作为后台运行工作流，\n"
                "当前 ComfyUI 未在运行。\n\n"
                "请选择启动方式:"
            ),
            buttons=[
                {"text": "取消", "role": "normal"},
                {"text": "一键启动 ComfyUI + openjutsu", "role": "primary"},
            ],
            default_index=1,
            theme_manager=self.theme_manager,
        )
        dlg.exec_()
        if dlg.get_result() == 1:
            self._start_comfyui_then_service()

    def _is_comfyui_running(self) -> bool:
        """ComfyUI 是否在跑 (HTTP 探活, 同 webui 页: 不能依赖 pidfile)."""
        try:
            from core.probe import is_http_reachable
            return bool(is_http_reachable(self.app, _log=False))
        except Exception:
            return False

    def _start_comfyui_then_service(self):
        self._set_state(STATE_WAITING_COMFYUI)

        def _worker():
            try:
                from core.cli.runner import start_service
                res = start_service(self.app, no_wait=False, timeout=60) or {}
                ok = bool(res.get("ready"))
                err = res.get("error")
            except Exception as e:
                ok = False
                err = str(e)
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
        if not ok:
            self._refresh_state()
            DialogHelper.show_warning(
                self, "ComfyUI 启动失败",
                "ComfyUI 启动失败, openjutsu 不启动。\n请查看 ComfyUI 日志排查。\n\n%s" % (err or ""),
            )
            return
        self._start_service()

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
        self._set_state(STATE_STOPPING)

        def _worker():
            res = self._mgr().stop(timeout=10)
            err = res.get("error")
            QtCore.QMetaObject.invokeMethod(
                self, "_after_action_done",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(bool, True),
                QtCore.Q_ARG(str, err or ""),
            )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    @QtCore.pyqtSlot(bool, str)
    def _after_action_done(self, started_ok: bool, err: str):
        """启/停完成回主线程: 失败弹窗 (带日志路径), 成功 re-detect."""
        if not started_ok and err:
            DialogHelper.show_warning(
                self, "openjutsu 操作失败",
                "%s\n\n详细日志: launcher/openjutsu.log" % err,
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
        return "http://127.0.0.1:%s/" % ports.get("app", 8198)

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

    # ---------------- 更新 ----------------

    def _on_update_clicked(self):
        if self._updating:
            return
        avail = self._availability()
        if not avail["available"]:
            DialogHelper.show_warning(self, "无法更新", "当前环境没有 openjutsu 服务。")
            return
        if self._mgr().is_running():
            DialogHelper.show_warning(self, "无法更新", "openjutsu 正在运行，请先停止再更新。")
            return

        self._updating = True
        self._set_state(STATE_UPDATING)

        def runner(on_progress):
            res = self._mgr().update(on_progress=on_progress)
            return {
                "ok": bool(res.get("ok")),
                "updated": bool(res.get("updated", False)),
                "error": res.get("error") or "",
            }

        def on_done(result):
            self._after_update(result.get("ok"), result.get("updated"), result.get("error", ""))

        self._run_with_progress("更新 openjutsu (git → npm ci → build → proxy → patch)",
                                runner, on_done)

    @QtCore.pyqtSlot(bool, bool, str)
    def _after_update(self, ok: bool, updated: bool, err: str):
        self._updating = False
        self._reset_deps_cache()
        if not ok:
            self._set_state(self._detect_state())
            DialogHelper.show_warning(
                self, "更新失败",
                "%s\n\n详细日志见进度信息与 launcher/launcher.log。" % (err or "未知错误"),
            )
        else:
            self._set_state(self._detect_state())
            if updated:
                DialogHelper.show_info(self, "更新完成", "openjutsu 已更新到最新版本。")
            else:
                DialogHelper.show_info(self, "已是最新", "openjutsu 已是最新版本。")

    def _run_with_progress(self, task_title, runner, on_done_slot, parent=None):
        """后台任务调度 helper (复刻 webui_page._run_with_progress)."""
        from ui_qt.widgets.progress_dialog import ProgressDialog

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

    # ---------------- 日志 (复刻 webui_page) ----------------

    def _resolve_log_path(self) -> Path:
        try:
            cwd = Path(getattr(self.app, "_cwd", ".") or ".")
        except Exception:
            cwd = Path(".")
        return cwd / "launcher" / "openjutsu.log"

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
        self._btn_update.setStyleSheet(primary_ss)
        self._btn_log_clear.setStyleSheet(styles.secondary_button_style())
        self._btn_log_open.setStyleSheet(styles.secondary_button_style())
        self._app_port_edit.setStyleSheet(input_ss)
        self._proxy_port_edit.setStyleSheet(input_ss)
        self._open_combo.setStyleSheet(input_ss)
        self._cpath_btn.setStyleSheet(input_ss)
        self._log_view.setStyleSheet(self._log_view_style())
        self._version_info_card.setStyleSheet(self._version_card_style())
        self._update_cpath_vis()
        try:
            label_muted = self._c("label_muted", "#9CA3AF")
            text_color = self._c("text", "#E5E7EB")
            for ref in getattr(self, "_version_title_refs", []):
                ref.setStyleSheet(
                    f'color: {label_muted}; font: bold {self._pt(9)}pt "Microsoft YaHei UI";'
                    f' background: transparent;'
                )
            for ref in getattr(self, "_version_value_refs", []):
                ref.setStyleSheet(
                    f'font: bold {self._pt(10)}pt "Segoe UI", "Microsoft YaHei UI";'
                    f' color: {text_color}; background: transparent;'
                )
        except Exception:
            pass
        # 主题切换强制刷新状态文案 (不应被 busy 态吞掉)
        self._update_ui_for_state()

    def refresh_after_env_switch(self):
        """env 切换后刷新 (QtApp.refresh_after_env_switch 调)."""
        try:
            self._reset_deps_cache()
            try:
                self._stop_log_tail()
                self._history_loaded = False
                self._log_view.clear()
                self._log_path = self._resolve_log_path()
                self._start_log_tail()
            except Exception:
                pass
            self._refresh_state()
        except Exception:
            pass
