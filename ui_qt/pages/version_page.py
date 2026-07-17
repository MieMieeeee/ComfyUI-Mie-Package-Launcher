"""
内核版本管理页面
"""

import threading
from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from .base_page import BasePage
from ui_qt.widgets import InfoCard, StyledTableWidget
from ui_qt.widgets.custom import NoWheelComboBox
from ui_qt.theme_styles import ThemeStyles
from utils import common as COMMON
from utils.common import run_hidden
from ui_qt.widgets.progress_dialog import ProgressDialog
from ui_qt.background_loader import BackgroundLoader


class VersionPage(BasePage):
    """内核版本管理页面"""

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self.theme_manager = theme_manager
        self._setup_ui()

    def _setup_ui(self):
        """设置 UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        # 标题
        title = QtWidgets.QLabel("ComfyUI 内核版本管理")
        title.setStyleSheet(f"""
            font: bold 16pt "Microsoft YaHei UI";
            color: {self.theme_manager.colors.get('label')};
            margin-bottom: 5px;
        """)
        layout.addWidget(title)
        self._page_title_refs = [title]

        # 版本信息卡片（包含版本信息、设置面板和操作按钮）
        info_card = InfoCard("当前版本信息", self.theme_manager.styles)
        layout.addWidget(info_card)

        # 版本信息内容
        info_layout = info_card.layout()
        info_layout.setSpacing(12)

        # 版本信息表单
        form_layout = QtWidgets.QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(10)
        form_layout.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.lbl_kernel_version = QtWidgets.QLabel("检测中...")

        # 使用更醒目的标签颜色，不是 muted
        lbl_style = f"color: {self.theme_manager.colors.get('label_dim')}; font: 10pt 'Microsoft YaHei UI';"
        val_style = f"color: {self.theme_manager.colors.get('text')}; font: bold 10pt 'Microsoft YaHei UI';"

        l_kv = QtWidgets.QLabel("内核版本:")
        l_kv.setStyleSheet(lbl_style)
        self.lbl_kernel_version.setStyleSheet(val_style)

        form_layout.addRow(l_kv, self.lbl_kernel_version)
        info_layout.addLayout(form_layout)

        # 设置面板
        self.settings_panel = QtWidgets.QWidget()
        self.settings_panel.setObjectName("SettingsPanel")
        bg_color = self.theme_manager.colors.get('group_bg')
        self.settings_panel.setStyleSheet(f"background-color: {bg_color}; border-radius: 8px; padding: 10px;")
        sp_layout = QtWidgets.QVBoxLayout(self.settings_panel)
        sp_layout.setSpacing(12)

        # 代理设置行
        row_proxy = QtWidgets.QHBoxLayout()
        row_proxy.setContentsMargins(0, 0, 0, 0)
        lbl_gh = QtWidgets.QLabel("GitHub代理:")
        lbl_gh.setStyleSheet(lbl_style)

        self.pv_proxy_combo = NoWheelComboBox()
        self.pv_proxy_combo.addItems(["不使用", "gh-proxy", "自定义"])
        self.pv_proxy_combo.setFixedWidth(140)
        self.pv_proxy_combo.setStyleSheet(self.theme_manager.styles.input_style())

        if hasattr(self.app, 'version_manager'):
            self.pv_proxy_combo.setCurrentText(self.app.version_manager.proxy_mode_ui_var.get())

            def _pv_proxy_changed(text):
                m = "none" if text == "不使用" else ("gh-proxy" if text == "gh-proxy" else "custom")
                self.app.version_manager.proxy_mode_var.set(m)
                self.app.version_manager.proxy_mode_ui_var.set(text)

                if text == "gh-proxy":
                    self.app.version_manager.proxy_url_var.set("https://gh-proxy.com/")
                self.app.version_manager.save_proxy_settings()

            self.pv_proxy_combo.currentTextChanged.connect(_pv_proxy_changed)

            self.app.version_manager.proxy_mode_ui_var.bind(
                lambda v: self.pv_proxy_combo.setCurrentText(v) if self.pv_proxy_combo.currentText() != v else None
            )

        row_proxy.addWidget(lbl_gh)
        row_proxy.addWidget(self.pv_proxy_combo)
        row_proxy.addStretch(1)
        sp_layout.addLayout(row_proxy)

        # 策略复选框行
        row_strat = QtWidgets.QHBoxLayout()
        row_strat.setContentsMargins(0, 0, 0, 0)
        lbl_st = QtWidgets.QLabel("内核升级策略:")
        lbl_st.setStyleSheet(lbl_style)

        cb_stable = QtWidgets.QCheckBox("仅更新到稳定版")
        if hasattr(self.app, 'stable_only_var'):
            cb_stable.setChecked(self.app.stable_only_var.get())
            cb_stable.toggled.connect(lambda c: (self.app.stable_only_var.set(c), self._save_config()))

        cb_deps = QtWidgets.QCheckBox("同时更新依赖库")
        if hasattr(self.app, 'auto_update_deps_var'):
            cb_deps.setChecked(self.app.auto_update_deps_var.get())
            cb_deps.toggled.connect(lambda c: (self.app.auto_update_deps_var.set(c), self._save_config()))

        # 超时选择器（放在同一行）
        lbl_timeout = QtWidgets.QLabel("超时:")
        lbl_timeout.setStyleSheet(lbl_style)

        self.timeout_combo = NoWheelComboBox()
        self.timeout_combo.addItems(["60秒", "120秒", "180秒", "300秒", "600秒"])
        self.timeout_combo.setFixedWidth(85)
        self.timeout_combo.setStyleSheet(self.theme_manager.styles.input_style())

        # 设置当前值
        if hasattr(self.app, 'update_timeout_var'):
            current_timeout = self.app.update_timeout_var.get()
            timeout_map = {60: 0, 120: 1, 180: 2, 300: 3, 600: 4}
            self.timeout_combo.setCurrentIndex(timeout_map.get(current_timeout, 1))

            def _timeout_changed(text):
                try:
                    seconds = int(text.replace("秒", ""))
                    self.app.update_timeout_var.set(seconds)
                    self._save_config()
                except Exception:
                    pass

            self.timeout_combo.currentTextChanged.connect(_timeout_changed)

        row_strat.addWidget(lbl_st)
        row_strat.addWidget(cb_stable)
        row_strat.addSpacing(15)
        row_strat.addWidget(cb_deps)
        row_strat.addSpacing(15)
        row_strat.addWidget(lbl_timeout)
        row_strat.addWidget(self.timeout_combo)
        row_strat.addStretch(1)
        sp_layout.addLayout(row_strat)

        info_layout.addWidget(self.settings_panel)

        # 操作按钮行（放在 info_card 里面）
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_upd = QtWidgets.QPushButton("更 新")
        self.btn_upd.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_upd.setStyleSheet(self.theme_manager.styles.primary_button_style())
        try:
            w1 = self.btn_upd.sizeHint().width()
            self.btn_upd.setText("更新中…")
            w2 = self.btn_upd.sizeHint().width()
            self.btn_upd.setText("更 新")
            self.btn_upd.setMinimumWidth(max(w1, w2))
        except Exception:
            pass
        self.btn_upd.clicked.connect(self._on_update_clicked)
        self.btn_upd.setToolTip("更新到ComfyUI最新稳定版或开发版")

        self.btn_switch = QtWidgets.QPushButton("切换到所选提交")
        self.btn_switch.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_switch.setStyleSheet(self.theme_manager.styles.primary_button_style())
        self.btn_switch.setToolTip("切换ComfyUI到历史任意提交版本")
        self.btn_switch.clicked.connect(self._do_checkout_commit)

        self.btn_refresh = QtWidgets.QPushButton("刷新提交历史 (远端)")
        self.btn_refresh.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet(self.theme_manager.styles.primary_button_style())
        self.btn_refresh.setToolTip("从远程仓库拉取最新的提交历史")
        self.btn_refresh.clicked.connect(self._fetch_remote_and_refresh)

        btn_row.addWidget(self.btn_upd)
        btn_row.addWidget(self.btn_switch)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addStretch(1)

        info_layout.addLayout(btn_row)

        # 提交历史卡片（包含标题和表格）
        history_card = InfoCard("提交历史", self.theme_manager.styles)
        layout.addWidget(history_card)

        history_layout = history_card.layout()
        history_layout.setSpacing(10)

        # 提交历史表格
        self.history_table = StyledTableWidget(self.theme_manager.styles)
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["提交哈希", "日期", "作者", "提交信息"])
        self.history_table.setMinimumHeight(400)

        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)

        history_layout.addWidget(self.history_table)

        # 添加样式组件引用
        self._styled_widgets = [info_card, self.history_table, self.settings_panel]
        if hasattr(self.app, "_styled_widgets"):
            self.app._theme_widgets.extend(self._styled_widgets)

        # 暴露标签给主应用
        self.app._version_kernel_label = self.lbl_kernel_version
        self.app._history_table = self.history_table

        # 分页相关
        self._commit_page = 1
        self._commits_per_page = 50
        self._total_commits = 0
        # 提交数快照：只在用户主动刷新时更新，分页导航时使用快照值避免竞争
        self._commit_count_snapshot = 0
        # 全量提交缓存（一次性加载，Python 侧分页，避免 git log --skip 跨页重复）
        self._all_commits_cache = []

        # 翻页控件
        page_row = QtWidgets.QHBoxLayout()
        page_row.addStretch(1)

        self.lbl_page_info = QtWidgets.QLabel("第 1 页")
        self.lbl_page_info.setStyleSheet(f"color: {self.theme_manager.colors.get('label_muted')};")

        self.btn_prev_page = QtWidgets.QPushButton("上一页")
        self.btn_prev_page.setStyleSheet(self.theme_manager.styles.secondary_button_style())
        self.btn_prev_page.clicked.connect(self._prev_page)

        self.btn_next_page = QtWidgets.QPushButton("下一页")
        self.btn_next_page.setStyleSheet(self.theme_manager.styles.secondary_button_style())
        self.btn_next_page.clicked.connect(self._next_page)

        page_row.addWidget(self.btn_prev_page)
        page_row.addWidget(self.lbl_page_info)
        page_row.addWidget(self.btn_next_page)
        history_layout.addLayout(page_row)

        # 延迟刷新版本信息与提交历史（避免阻塞 UI 显示）
        try:
            QtCore.QTimer.singleShot(100, self._refresh_kernel_section)
            self._setup_loaders()
            # 本地提交历史：启动后快速加载（无网络），先填满表格
            QtCore.QTimer.singleShot(500, self._local_loader.load_if_not_loaded)
            # 后台静默 fetch 增强：默认 30s，可由 version_preferences.background_fetch_delay_seconds 配置
            delay_seconds = 30
            try:
                cfg = getattr(self.app, "config", None)
                vp = cfg.get("version_preferences", {}) if isinstance(cfg, dict) else {}
                delay_seconds = int(vp.get("background_fetch_delay_seconds", 30))
                if delay_seconds < 0:
                    delay_seconds = 0
            except Exception:
                delay_seconds = 30
            QtCore.QTimer.singleShot(int(delay_seconds * 1000), self._fetch_loader.load)
        except Exception:
            pass

    def _save_config(self):
        """保存配置"""
        try:
            self.app.save_config()
        except Exception:
            pass

    # ==================== BackgroundLoader 集成 ====================
    # 两个 loader 收编原来三个手写 threading.Thread 的 git 任务：
    #   _local_loader：本地 git log（快，无网络）—— 原 _load_local_commits_background
    #   _fetch_loader：fetch + git log（慢，有网络，带可选进度框）—— 原 _background_fetch / _fetch_remote_and_refresh
    # 两者共享 _on_commits_loaded 回调：后跑的覆盖先跑的缓存，实现「先本地后远端」渐进增强。

    def _run_in_bg(self, fn):
        """丢工作线程（注入给 BackgroundLoader）。"""
        threading.Thread(target=fn, daemon=True).start()

    def _post_to_ui(self, fn):
        """派回 UI 线程（注入给 BackgroundLoader）。复用 app.ui_post 标准入口。"""
        try:
            self.app.ui_post(fn)
        except Exception:
            QtCore.QTimer.singleShot(0, fn)

    def _setup_loaders(self):
        """构造三个 loader。_setup_ui 末尾调一次。"""
        self._local_loader = BackgroundLoader(
            load_fn=lambda _report: self._load_local_commits_work(),
            on_loaded=self._on_commits_loaded,
            run_in_background=self._run_in_bg,
            post_to_ui=self._post_to_ui,
            on_error=lambda e: self._log("warning", "UI: 本地提交历史加载失败: %s", e),
        )
        self._fetch_loader = BackgroundLoader(
            load_fn=self._fetch_and_load_work,
            on_loaded=self._on_commits_loaded,
            run_in_background=self._run_in_bg,
            post_to_ui=self._post_to_ui,
            on_progress=self._fetch_progress,
            on_state_change=self._fetch_state_changed,
            on_error=self._on_fetch_error,
        )
        # 内核版本检测（get_current_kernel_version：4 个同步 git 子进程，必须后台跑，
        # 否则在 _refresh_kernel_section 的 singleShot 回调里冻死主线程——曾导致启动卡 54s）
        self._kernel_version_loader = BackgroundLoader(
            load_fn=lambda _report: self._detect_kernel_version_work(),
            on_loaded=self._on_kernel_version_loaded,
            run_in_background=self._run_in_bg,
            post_to_ui=self._post_to_ui,
            on_error=lambda e: self._log("warning", "UI: 内核版本检测失败: %s", e),
        )

    def _log(self, level, msg, *args):
        try:
            logger = getattr(self.app, "logger", None)
            if logger:
                getattr(logger, level, logger.info)(msg, *args)
        except Exception:
            pass

    # ---- 内核版本检测 loader（后台跑 get_current_kernel_version，不阻塞主线程）----
    def _detect_kernel_version_work(self):
        """后台执行体：调 version service 跑 4 个 git 子进程，返回 display 字符串。

        这段在主线程跑会冻死 UI（4×timeout=10s 串行 git，遇 dubious ownership 还翻倍），
        故必须放后台线程。与 ComfyUIVersionWorker 做的事类似，但那条路径的信号更新的是
        comfyui_version Var（启动页用），这里专门为 version 页的 lbl_kernel_version 标签服务。
        """
        try:
            if hasattr(self.app, 'services') and hasattr(self.app.services, 'version'):
                cur = self.app.services.version.get_current_kernel_version()
                return cur.get("display_version") or "未知"
        except Exception as e:
            self._log("warning", "UI: 内核版本检测异常: %s", e)
        return "未知"

    def _on_kernel_version_loaded(self, display):
        """UI 线程回调：后台内核版本检测完成 → 更新标签。"""
        try:
            self.lbl_kernel_version.setText(display)
        except Exception:
            pass

    # ---- 两个 loader 的 load_fn（后台线程执行体）----
    def _load_local_commits_work(self):
        """本地 git log，无网络。对应原 _load_local_commits_background 的后台逻辑。"""
        # 更新进行中不读，避免与更新的 fetch 竞争
        if getattr(self.app, "_update_running", False):
            return []
        root = self._comfyui_root()
        if not root or not root.exists():
            return []
        git = getattr(self.app, 'git_path', 'git') or "git"
        commits = self._fetch_all_commits(root, git)
        try:
            self._log("info", "UI: 本地提交历史加载完成: %d 条, root=%s", len(commits), root)
        except Exception:
            pass
        return commits

    def _fetch_and_load_work(self, report):
        """fetch + git log，有网络。对应原 _background_fetch / _fetch_remote_and_refresh 的后台逻辑。

        report(status)：透传进度文字到 UI（带进度框时显示；后台静默 fetch 时无 on_progress 则空转）。
        保留原 run_git_network 的 blocking=False 跳过逻辑（更新占用 git 锁时 returncode==2 跳过）。
        """
        root = self._comfyui_root()
        if not root or not root.exists():
            raise RuntimeError("ComfyUI目录不存在")
        git = getattr(self.app, 'git_path', 'git') or "git"
        is_shallow = (root / ".git" / "shallow").exists()
        version_svc = getattr(getattr(self.app, "services", None), "version", None)
        report("正在执行 git fetch...")
        if is_shallow:
            if version_svc and hasattr(version_svc, "run_git_network"):
                r = version_svc.run_git_network(
                    [git, "fetch", "--unshallow"],
                    capture_output=True, text=True, timeout=120, cwd=str(root),
                    blocking=False, busy_message="skip background fetch: update running",
                )
                if getattr(r, "returncode", 0) == 2:
                    self._log("info", "UI: 后台fetch跳过（更新占用git锁）")
                    return []  # 跳过：不刷新缓存，保留现有数据
            else:
                run_hidden([git, "fetch", "--unshallow"],
                           capture_output=True, text=True, timeout=120, cwd=str(root))
        else:
            if version_svc and hasattr(version_svc, "run_git_network"):
                r = version_svc.run_git_network(
                    [git, "fetch"],
                    capture_output=True, text=True, timeout=30, cwd=str(root),
                    blocking=False, busy_message="skip background fetch: update running",
                )
                if getattr(r, "returncode", 0) == 2:
                    self._log("info", "UI: 后台fetch跳过（更新占用git锁）")
                    return []
            else:
                run_hidden([git, "fetch"],
                           capture_output=True, text=True, timeout=30, cwd=str(root))
        report("正在加载提交历史...")
        commits = self._fetch_all_commits(root, git)
        if hasattr(self.app, "logger"):
            self.app.logger.info("UI: git log target=origin/HEAD")
        return commits

    def _comfyui_root(self):
        """解析 ComfyUI 代码目录（激活环境 comfyui_root + /ComfyUI）。失败返回 None。"""
        try:
            # 多环境支持：读激活环境的 comfyui_root
            paths = self.app.get_active_paths() if hasattr(self.app, "get_active_paths") \
                else self.app.config.get("paths", {})
            base = Path(paths.get("comfyui_root") or ".").resolve()
            return (base / "ComfyUI").resolve()
        except Exception:
            return None

    # ---- 两个 loader 的 on_loaded / on_error / on_progress / on_state_change（UI 线程）----
    def _on_commits_loaded(self, commits):
        """统一的缓存写入 + 渲染回调（两个 loader 共享）。后跑的覆盖先跑的。

        用户触发（有进度框）时额外刷新版本信息；后台静默 fetch 则只填表格不打扰。
        """
        if commits and not getattr(self.app, "_update_running", False):
            self._all_commits_cache = commits
            self._commit_page = 1
            self._load_commit_history()
        # 仅用户触发的 fetch（有进度框）才刷新版本信息 + 后续在关框时提示完成
        if getattr(self, "_fetch_progress_dialog", None) is not None:
            try:
                self._refresh_kernel_section()
                if hasattr(self.app, 'get_version_info'):
                    self.app.get_version_info("core_only")
            except Exception:
                pass

    def _fetch_progress(self, status):
        """带进度框时（用户点「刷新提交历史(远端)」）更新状态文字。后台静默 fetch 无进度框，此回调空转。"""
        pd = getattr(self, "_fetch_progress_dialog", None)
        if pd:
            try:
                pd.set_status(status)
            except Exception:
                pass

    def _fetch_state_changed(self, loading):
        """仅当存在进度框时开关它（用户点按钮触发的那次）。后台 fetch 不建框，此回调空转。

        loading=False（加载结束）时关框；若此前未走 on_error（即成功），提示「已刷新」。
        """
        pd = getattr(self, "_fetch_progress_dialog", None)
        if pd and not loading:
            try:
                pd.close()
            except Exception:
                pass
            self._fetch_progress_dialog = None
            # 成功提示：on_error 不会同时触发（load 成功才走 on_loaded→state=False 路径），
            # 失败时 on_error 已关框并置 None，这里 pd 已是 None 不会重复提示。
            from ui_qt.widgets.dialog_helper import DialogHelper
            DialogHelper.show_info(self, "完成", "已刷新提交历史")

    def _on_fetch_error(self, exc):
        """fetch 失败：关进度框（若有）并提示。后台静默 fetch 失败则静默（不弹框打扰）。"""
        pd = getattr(self, "_fetch_progress_dialog", None)
        had_dialog = pd is not None
        if pd:
            try:
                pd.close()
            except Exception:
                pass
            self._fetch_progress_dialog = None
        if had_dialog:
            try:
                from ui_qt.widgets.dialog_helper import DialogHelper
                DialogHelper.show_warning(self, "失败", str(exc))
            except Exception:
                pass
        else:
            self._log("warning", "UI: 后台fetch失败: %s", exc)

    def _upgrade_latest(self):
        """更新到最新版本"""
        if hasattr(self.app, '_upgrade_latest'):
            stable_only = self.app.stable_only_var.get() if hasattr(self.app, 'stable_only_var') else False
            self.app._upgrade_latest(stable_only)

    def _on_update_clicked(self):
        """点击更新时，按钮显示"更新中…"，禁用并变灰，完成后恢复"""
        btn = getattr(self, "btn_upd", None)
        if getattr(self.app, "_update_running", False):
            return
        if btn:
            try:
                btn.setText("更新中…")
                btn.setEnabled(False)
                QtWidgets.QApplication.processEvents()
            except Exception:
                pass
        try:
            stable_only = self.app.stable_only_var.get() if hasattr(self.app, 'stable_only_var') else True
            self.app.start_update(
                stable_only,
                on_done=lambda: (btn.setText("更 新"), btn.setEnabled(True)) if btn else None,
            )
        except Exception:
            if btn:
                try:
                    btn.setText("更 新")
                    btn.setEnabled(True)
                except Exception:
                    pass

    def _do_checkout_commit(self):
        """切换到选定提交"""
        row = self.history_table.currentRow()
        if row < 0:
            from ui_qt.widgets.dialog_helper import DialogHelper
            DialogHelper.show_warning(self, "未选择", "请先选择一个提交记录")
            return

        item = self.history_table.item(row, 0)
        if not item:
            return

        commit_hash = item.text().strip()
        if not commit_hash:
            return

        # 检查 ComfyUI 是否正在运行
        if hasattr(self.app, '_is_comfyui_running') and self.app._is_comfyui_running():
            from ui_qt.widgets.dialog_helper import DialogHelper
            DialogHelper.show_warning(
                self, "无法切换",
                "ComfyUI 正在运行中，无法切换提交。\n请先停止 ComfyUI 后再试。"
            )
            return

        # 显示进度对话框
        progress = ProgressDialog(parent=self, title="切换提交中", theme_manager=self.theme_manager)
        progress.set_status("正在切换 ComfyUI 到指定提交...")
        progress.set_progress(0, maximum=0)
        progress.show()

        try:
            if hasattr(self.app, "logger"):
                self.app.logger.info(f"UI: 请求切换到提交 {commit_hash}")

            # 多环境支持：读激活环境的 comfyui_root
            paths = self.app.get_active_paths() if hasattr(self.app, "get_active_paths") \
                else self.app.config.get("paths", {})
            base = Path(paths.get("comfyui_root") or ".").resolve()
            root = (base / "ComfyUI").resolve()

            # 执行git checkout
            progress.set_status("正在执行 git checkout...")
            result = COMMON.run_hidden(
                [getattr(self.app, 'git_path', 'git') or "git", "checkout", commit_hash],
                cwd=str(root)
            )

            if result.returncode != 0:
                raise RuntimeError(f"Git checkout 失败: {result.stderr or '未知错误'}")

            # 刷新版本信息
            progress.set_status("正在刷新版本信息...")
            if hasattr(self.app, 'get_version_info'):
                self.app.get_version_info("all")
            self._refresh_kernel_section()

            progress.close()
            from ui_qt.widgets.dialog_helper import DialogHelper
            DialogHelper.show_info(self, "切换成功", f"已切换到提交 {commit_hash}")
        except Exception as e:
            progress.close()
            from ui_qt.widgets.dialog_helper import DialogHelper
            DialogHelper.show_warning(self, "切换失败", str(e))

    def _fetch_remote_and_refresh(self):
        """从远程刷新提交历史（用户点「刷新提交历史(远端)」按钮）。

        走 _fetch_loader.load()（带进度框）：建进度框 → 触发后台 fetch+log →
        on_progress 更新状态 → on_loaded 填表格 → on_state_change(False) 关框 + 提示完成。
        与启动时的后台静默 fetch 共用同一个 loader（防重入：二者只跑一个）。
        """
        # 兜底校验：目录不存在直接提示，不进 loader（loader 的 on_error 也会兜，但这里更早）
        root = self._comfyui_root()
        if not root or not root.exists():
            from ui_qt.widgets.dialog_helper import DialogHelper
            DialogHelper.show_warning(self, "失败", "ComfyUI目录不存在")
            return

        # 建进度框，挂到实例字段供 loader 的 on_progress/on_state_change 回调操作。
        # _on_commits_loaded / _fetch_state_changed 据「有无进度框」区分用户触发 vs 后台静默。
        self._fetch_progress_dialog = ProgressDialog(
            parent=self, title="刷新提交历史中", theme_manager=self.theme_manager)
        self._fetch_progress_dialog.set_status("正在从远程获取提交历史...")
        self._fetch_progress_dialog.set_progress(0, maximum=0)
        self._fetch_progress_dialog.show()

        self._fetch_loader.load()

    def _fetch_all_commits(self, root, git):
        """从本地 git 仓库获取全部提交记录"""
        # 使用 run_hidden 启动子进程，自动隐藏 Windows 控制台窗口
        # (utils.common.run_hidden 内部会设置 STARTUPINFO + CREATE_NO_WINDOW)
        target = None
        for candidate in ["origin/HEAD", "origin/master", "origin/main"]:
            try:
                r = run_hidden(
                    [git, "rev-parse", "--verify", candidate],
                    capture_output=True, timeout=3, cwd=str(root)
                )
                if r.returncode == 0:
                    target = candidate
                    break
            except Exception:
                pass
        try:
            if hasattr(self.app, "logger"):
                self.app.logger.info("UI: git log target=%s", target or "HEAD")
        except Exception:
            pass
        if not target:
            target = "HEAD"
            try:
                if hasattr(self.app, "logger"):
                    self.app.logger.warning(
                        "UI: 未找到远端跟踪分支 (origin/HEAD|master|main)，"
                        "提交历史仅显示本地数据，可能不完整。"
                        "请执行'刷新提交历史(远端)'补全。"
                    )
            except Exception:
                pass

        commits = []
        try:
            # --first-parent 保证单线历史，避免合并带来的图遍历乱序
            # 同样使用 run_hidden 隐藏 Windows 控制台窗口
            r = run_hidden(
                [git, "log", "--first-parent", "--date-order", "--date=short",
                 "--pretty=format:%h|%ad|%an|%s", target],
                capture_output=True, timeout=15, cwd=str(root)
            )
            # 直接读 bytes 用 UTF-8 解码，避免 Windows GBK 解码中文失败
            stdout = r.stdout.decode("utf-8", errors="replace") if r.stdout else ""
            if r.returncode == 0 and stdout:
                for line in stdout.splitlines():
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        commits.append(parts)
            else:
                try:
                    if hasattr(self.app, "logger"):
                        self.app.logger.warning(
                            "UI: git log 失败: target=%s, rc=%d, stderr=%s",
                            target, r.returncode,
                            r.stderr.decode("utf-8", errors="replace")[:200] if r.stderr else ""
                        )
                except Exception:
                    pass
        except Exception as e:
            try:
                if hasattr(self.app, "logger"):
                    self.app.logger.warning("UI: git log 异常: target=%s, error=%s", target, e)
            except Exception:
                pass
        # 按日期降序（最新在前），消除 --first-parent 遍历导致的日期交错
        commits.sort(key=lambda c: c[1], reverse=True)
        return commits

    def showEvent(self, event):
        """页面切换到前台时，若缓存有数据但表格为空则刷新"""
        super().showEvent(event)
        if self._all_commits_cache and self.history_table.rowCount() == 0:
            self._load_commit_history()

    def _prev_page(self):
        """上一页"""
        if self._commit_page > 1:
            self._commit_page -= 1
            self._load_commit_history()

    def _next_page(self):
        """下一页"""
        total = len(self._all_commits_cache) if self._all_commits_cache else self._commit_count_snapshot
        total_pages = (total + self._commits_per_page - 1) // self._commits_per_page
        if self._commit_page < total_pages:
            self._commit_page += 1
            self._load_commit_history()

    def _refresh_kernel_section(self, force_remote=False):
        """刷新内核版本信息 + 提交历史表格。

        内核版本检测（get_current_kernel_version：4 个同步 git 子进程）丢后台 loader，
        不在主线程跑——否则 singleShot 回调里会冻死 UI（曾导致启动卡 54s）。
        提交历史渲染从内存缓存读，纯 CPU，留主线程（快）。
        """
        # 内核版本 → 后台检测，结果经 _on_kernel_version_loaded 回设标签
        try:
            self._kernel_version_loader.load()
        except Exception:
            pass

        # 加载提交历史（始终优先使用远端）—— 从内存缓存渲染，不阻塞
        self._load_commit_history()

    def _load_commit_history(self):
        """从本地缓存加载提交历史（fetch 已预填充缓存）"""
        all_commits = self._all_commits_cache
        if not all_commits:
            # 缓存尚未加载，等待 loader 的 _on_commits_loaded 回调刷新
            return

        total = len(all_commits)
        total_pages = max(1, (total + self._commits_per_page - 1) // self._commits_per_page)
        self.lbl_page_info.setText(f"第 {self._commit_page}/{total_pages} 页")
        self.btn_prev_page.setEnabled(self._commit_page > 1)
        self.btn_next_page.setEnabled(self._commit_page < total_pages)

        skip = (self._commit_page - 1) * self._commits_per_page
        rows = all_commits[skip:skip + self._commits_per_page]

        self.history_table.setRowCount(len(rows))

        # 翻页后滚动到最上面
        if rows:
            self.history_table.scrollToItem(self.history_table.item(0, 0))

        try:
            import re
            _kw_ver = re.compile(r"ComfyUI v\d+\.\d+\.\d+")
        except Exception:
            _kw_ver = None

        for ri, cols in enumerate(rows):
            for ci, val in enumerate(cols):
                item = QtWidgets.QTableWidgetItem(val)
                if ci == 0:
                    # 哈希列 - 使用 muted 文本颜色
                    f = item.font()
                    f.setFamily("Consolas")
                    item.setFont(f)
                    item.setForeground(QtGui.QBrush(QtGui.QColor(self.theme_manager.colors.get('label_muted'))))
                if ci == 3:
                    # 提交信息列
                    try:
                        if _kw_ver and _kw_ver.search(val):
                            # 版本关键词 - 使用强调色
                            f = item.font()
                            f.setBold(True)
                            item.setFont(f)
                            item.setForeground(QtGui.QBrush(QtGui.QColor(self.theme_manager.colors.get('text'))))
                        else:
                            # 其他 - 使用 muted 文本颜色
                            item.setForeground(QtGui.QBrush(QtGui.QColor(self.theme_manager.colors.get('label_muted'))))
                    except Exception:
                        item.setForeground(QtGui.QBrush(QtGui.QColor(self.theme_manager.colors.get('label_muted'))))
                self.history_table.setItem(ri, ci, item)

    def _refresh_table_item_colors(self):
        """重新刷新表格项的颜色（主题切换时调用）"""
        import re
        try:
            _kw_ver = re.compile(r"ComfyUI v\d+\.\d+\.\d+")
        except Exception:
            _kw_ver = None

        for row in range(self.history_table.rowCount()):
            for col in range(self.history_table.columnCount()):
                item = self.history_table.item(row, col)
                if item and col == 0:
                    # 哈希列 - 使用 muted 文本颜色
                    item.setForeground(QtGui.QBrush(QtGui.QColor(self.theme_manager.colors.get('label_muted'))))
                elif item and col == 3:
                    # 提交信息列
                    val = item.text()
                    try:
                        if _kw_ver and _kw_ver.search(val):
                            # 版本关键词 - 使用强调色
                            item.setForeground(QtGui.QBrush(QtGui.QColor(self.theme_manager.colors.get('text'))))
                        else:
                            # 其他 - 使用 muted 文本颜色
                            item.setForeground(QtGui.QBrush(QtGui.QColor(self.theme_manager.colors.get('label_muted'))))
                    except Exception:
                        item.setForeground(QtGui.QBrush(QtGui.QColor(self.theme_manager.colors.get('label_muted'))))

    def update_theme(self, theme_styles=None):
        """更新主题"""
        super().update_theme(theme_styles)

        title_color = self.theme_manager.colors.get('label')
        for ref in self._page_title_refs:
            ref.setStyleSheet(f"font: bold 12pt 'Microsoft YaHei UI'; color: {title_color}; margin-top: 10px;" if "提交历史" in ref.text() else f"font: bold 16pt 'Microsoft YaHei UI'; color: {title_color}; margin-bottom: 5px;")

        # 更新版本信息标签样式
        lbl_style = f"color: {self.theme_manager.colors.get('label_muted')}; font: 10pt 'Microsoft YaHei UI';"
        val_style = f"color: {self.theme_manager.colors.get('text')}; font: bold 10pt 'Microsoft YaHei UI';"
        self.lbl_kernel_version.setStyleSheet(val_style)

        # 更新设置面板背景颜色
        if hasattr(self, 'settings_panel'):
            bg_color = self.theme_manager.colors.get('group_bg')
            self.settings_panel.setStyleSheet(f"background-color: {bg_color}; border-radius: 8px; padding: 10px;")

        # 更新组合框样式
        if hasattr(self, 'pv_proxy_combo'):
            self.pv_proxy_combo.setStyleSheet(self.theme_manager.styles.input_style())

        # 更新表格样式
        for widget in self._styled_widgets:
            if hasattr(widget, 'update_theme'):
                widget.update_theme(self.theme_manager.styles)

        # 更新操作按钮样式
        if hasattr(self, 'btn_upd') and hasattr(self, 'btn_switch') and hasattr(self, 'btn_refresh'):
            btn_style = self.theme_manager.styles.primary_button_style()
            self.btn_upd.setStyleSheet(btn_style)
            self.btn_switch.setStyleSheet(btn_style)
            self.btn_refresh.setStyleSheet(btn_style)

        # 更新翻页按钮样式
        if hasattr(self, 'btn_prev_page') and hasattr(self, 'btn_next_page'):
            page_btn_style = self.theme_manager.styles.secondary_button_style()
            self.btn_prev_page.setStyleSheet(page_btn_style)
            self.btn_next_page.setStyleSheet(page_btn_style)

        if hasattr(self, 'lbl_page_info'):
            self.lbl_page_info.setStyleSheet(f"color: {self.theme_manager.colors.get('label_muted')};")

        # 重新应用表格项颜色（因为表格内容有硬编码颜色）
        self._refresh_table_item_colors()
