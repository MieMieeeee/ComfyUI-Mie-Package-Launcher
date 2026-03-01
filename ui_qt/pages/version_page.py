"""
内核版本管理页面
"""

from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from .base_page import BasePage
from ui_qt.widgets import InfoCard, StyledTableWidget
from ui_qt.widgets.custom import NoWheelComboBox
from ui_qt.theme_styles import ThemeStyles
from utils import common as COMMON
from utils.common import run_hidden
from ui_qt.widgets.progress_dialog import ProgressDialog


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

        self.lbl_ver_branch = QtWidgets.QLabel("检测中...")
        self.lbl_ver_commit = QtWidgets.QLabel("检测中...")

        # 绑定数据显示 - 内核提交只显示commit哈希，不显示完整版本
        if hasattr(self.app, 'comfyui_commit'):
            self.app.comfyui_commit.bind(lambda v: self.lbl_ver_commit.setText(v))

        # 使用更醒目的标签颜色，不是 muted
        lbl_style = f"color: {self.theme_manager.colors.get('label_dim')}; font: 10pt 'Microsoft YaHei UI';"
        val_style = f"color: {self.theme_manager.colors.get('text')}; font: bold 10pt 'Microsoft YaHei UI';"

        l_br = QtWidgets.QLabel("内核分支:")
        l_br.setStyleSheet(lbl_style)
        self.lbl_ver_branch.setStyleSheet(val_style)

        l_cm = QtWidgets.QLabel("内核提交:")
        l_cm.setStyleSheet(lbl_style)
        self.lbl_ver_commit.setStyleSheet(val_style)

        form_layout.addRow(l_br, self.lbl_ver_branch)
        form_layout.addRow(l_cm, self.lbl_ver_commit)
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
        lbl_st = QtWidgets.QLabel("升级策略:")
        lbl_st.setStyleSheet(lbl_style)

        cb_stable = QtWidgets.QCheckBox("仅更新到稳定版")
        if hasattr(self.app, 'stable_only_var'):
            cb_stable.setChecked(self.app.stable_only_var.get())
            cb_stable.toggled.connect(lambda c: (self.app.stable_only_var.set(c), self._save_config()))

        cb_deps = QtWidgets.QCheckBox("自动更新依赖库 (包括前端及模板库)")
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
        self.app._version_branch_label = self.lbl_ver_branch
        self.app._version_commit_label = self.lbl_ver_commit
        self.app._history_table = self.history_table

        # 分页相关
        self._commit_page = 1
        self._commits_per_page = 50
        self._total_commits = 0

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
        except Exception:
            pass

    def _save_config(self):
        """保存配置"""
        try:
            self.app.save_config()
        except Exception:
            pass

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

        # 显示进度对话框
        progress = ProgressDialog(parent=self, title="切换提交中", theme_manager=self.theme_manager)
        progress.set_status("正在切换 ComfyUI 到指定提交...")
        progress.set_progress(0, maximum=0)
        progress.show()

        try:
            if hasattr(self.app, "logger"):
                self.app.logger.info(f"UI: 请求切换到提交 {commit_hash}")

            base = Path(self.app.config.get("paths", {}).get("comfyui_root") or ".").resolve()
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
        """从远程刷新提交历史"""
        # 显示进度对话框
        progress = ProgressDialog(parent=self, title="刷新提交历史中", theme_manager=self.theme_manager)
        progress.set_status("正在从远程获取提交历史...")
        progress.set_progress(0, maximum=0)
        progress.show()

        try:
            from ui_qt.widgets.dialog_helper import DialogHelper
            base = Path(self.app.config.get("paths", {}).get("comfyui_root") or ".").resolve()
            root = (base / "ComfyUI").resolve()
            if not root.exists():
                progress.close()
                DialogHelper.show_warning(self, "失败", "ComfyUI目录不存在")
                return

            # Fetch
            progress.set_status("正在执行 git fetch...")
            if hasattr(self.app, "logger"):
                self.app.logger.info("UI: 正在执行 git fetch...")
            run_hidden([getattr(self.app, 'git_path', 'git') or "git", "fetch"], cwd=str(root))

            # Refresh info
            progress.set_status("正在刷新表格...")
            self._refresh_kernel_section(force_remote=True)

            # Trigger version check
            if hasattr(self.app, 'get_version_info'):
                self.app.get_version_info("core_only")

            progress.close()
            DialogHelper.show_info(self, "完成", "已刷新提交历史")
        except Exception as e:
            progress.close()
            DialogHelper.show_warning(self, "失败", str(e))

    def _prev_page(self):
        """上一页"""
        if self._commit_page > 1:
            self._commit_page -= 1
            self._load_commit_history()

    def _next_page(self):
        """下一页"""
        total_pages = (self._total_commits + self._commits_per_page - 1) // self._commits_per_page
        if self._commit_page < total_pages:
            self._commit_page += 1
            self._load_commit_history()

    def _update_page_info(self):
        """更新翻页信息"""
        total_pages = max(1, (self._total_commits + self._commits_per_page - 1) // self._commits_per_page)
        self.lbl_page_info.setText(f"第 {self._commit_page}/{total_pages} 页")
        self.btn_prev_page.setEnabled(self._commit_page > 1)
        self.btn_next_page.setEnabled(self._commit_page < total_pages)

    def _refresh_kernel_section(self, force_remote=False):
        """刷新版本信息"""
        try:
            if hasattr(self.app, 'services') and hasattr(self.app.services, 'version'):
                cur = self.app.services.version.get_current_kernel_version()
                self.lbl_ver_commit.setText(cur.get("commit") or "未知")
        except Exception:
            pass

        try:
            base = Path(self.app.config.get("paths", {}).get("comfyui_root") or ".").resolve()
            root = (base / "ComfyUI").resolve()
        except Exception:
            root = Path.cwd()

        # 获取分支信息
        try:
            r = run_hidden([getattr(self.app, 'git_path', 'git') or "git", "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True, timeout=6, cwd=str(root))
            self.lbl_ver_branch.setText(r.stdout.strip() if r.returncode == 0 else "unknown")
        except Exception:
            pass

        # 加载提交历史
        self._load_commit_history(show_remote=force_remote)

    def _load_commit_history(self, show_remote=False):
        """加载提交历史"""
        try:
            base = Path(self.app.config.get("paths", {}).get("comfyui_root") or ".").resolve()
            root = (base / "ComfyUI").resolve()
        except Exception:
            root = Path.cwd()

        git = getattr(self.app, 'git_path', 'git') or "git"
        target = "HEAD"

        # 智能判断：检查 HEAD 是否落后于远程分支
        # 如果落后（如 checkout 到旧版本），使用远程分支显示完整历史
        try:
            # 获取上游分支名称
            r_up = run_hidden([git, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                            capture_output=True, text=True, timeout=3, cwd=str(root))
            if r_up.returncode == 0 and r_up.stdout.strip():
                upstream = r_up.stdout.strip()
                # 检查 HEAD 是否包含上游的最新提交（HEAD..upstream 是否为空）
                r_behind = run_hidden([git, "rev-list", "--count", f"HEAD..{upstream}"],
                                     capture_output=True, text=True, timeout=3, cwd=str(root))
                if r_behind.returncode == 0 and r_behind.stdout.strip():
                    behind_count = int(r_behind.stdout.strip())
                    if behind_count > 0:
                        # HEAD 落后于上游，使用上游分支显示完整历史
                        target = upstream
        except Exception:
            pass

        # 如果明确要求显示远程，强制使用远程分支
        if show_remote and target == "HEAD":
            try:
                r_up = run_hidden([git, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                                capture_output=True, text=True, timeout=3, cwd=str(root))
                if r_up.returncode == 0 and r_up.stdout.strip():
                    target = r_up.stdout.strip()
                else:
                    target = "origin/HEAD"
            except Exception:
                target = "origin/HEAD"

        # 获取总提交数（用于分页）
        try:
            r_count = run_hidden([git, "rev-list", "--count", target],
                                capture_output=True, text=True, timeout=5, cwd=str(root))
            if r_count.returncode == 0 and r_count.stdout.strip():
                self._total_commits = int(r_count.stdout.strip())
            else:
                self._total_commits = 0
        except Exception:
            self._total_commits = 0

        # 计算分页偏移
        skip = (self._commit_page - 1) * self._commits_per_page

        r = run_hidden([git, "log", "--date=short",
                       "--pretty=format:%h|%ad|%an|%s", "-n", str(self._commits_per_page),
                       "--skip", str(skip), target],
                      capture_output=True, text=True, timeout=8, cwd=str(root))

        rows = []
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.splitlines():
                parts = line.split("|", 3)
                if len(parts) == 4:
                    rows.append(parts)

        # Fallback to local HEAD if remote failed
        if (r.returncode != 0 or not rows) and show_remote:
            r = run_hidden([git, "log", "--date=short",
                          "--pretty=format:%h|%ad|%an|%s", "-n", str(self._commits_per_page),
                          "--skip", str(skip), "HEAD"],
                         capture_output=True, text=True, timeout=8, cwd=str(root))
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.splitlines():
                    parts = line.split("|", 3)
                    if len(parts) == 4:
                        rows.append(parts)

        # 更新翻页信息
        self._update_page_info()

        self.history_table.setRowCount(len(rows))

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
        self.lbl_ver_branch.setStyleSheet(val_style)
        self.lbl_ver_commit.setStyleSheet(val_style)

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
