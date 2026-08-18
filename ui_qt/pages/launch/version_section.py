"""
版本与更新区块
从 launch_page.py 提取的 VersionSection 类
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from ui_qt.widgets.custom import NoWheelComboBox


class VersionSection(QtWidgets.QWidget):
    """
    版本与更新区块控件
    
    包含：版本信息网格、内核升级策略选项、刷新按钮、更新按钮
    """

    def __init__(self, app_context, theme_manager=None, parent=None):
        super().__init__(parent)
        self.app = app_context
        self.theme_manager = theme_manager
        self._setup_ui()

        # 注册主题监听
        if self.theme_manager:
            self.theme_manager.register_listener(self._on_theme_changed)

    # DPI 缩放 helper —— 每次调用读 self.theme_manager.styles 的【当前】实例。
    # set_scale 会新建 ThemeStyles 替换 self.styles（theme_manager.py）；若像旧
    # 代码那样在 __init__ 把 self._px 绑定到当时实例的 _px 方法，DPI 变化后
    # self._px 永远停在首次 scale（与 qt_app.self._sp 同族 bug，见
    # test_sp_reads_live_scale）。改成方法后所有 self._px(x)/self._pt(x)
    # 调用点零改动（属性→方法，调用语法一致）。
    def _px(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._px(base) if styles else base

    def _pt(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._pt(base) if styles else base

    def _setup_ui(self):
        """设置 UI"""
        _pt = self._pt
        lbl_style = f"color: {self._get_label_color()}; font: {_pt(10)}pt 'Microsoft YaHei UI';"

        # 主布局
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 表单组
        form_group = QtWidgets.QGroupBox("版本与更新")
        form_layout = QtWidgets.QVBoxLayout(form_group)
        form_layout.setContentsMargins(8, 8, 8, 8)
        form_layout.setSpacing(0)

        main_layout.addWidget(form_group)

        # 版本信息网格
        cur_grid = QtWidgets.QGridLayout()
        cur_grid.setSpacing(12)
        cur_grid.setContentsMargins(8, 4, 8, 6)
        form_layout.addLayout(cur_grid)

        self._version_label_refs = []
        try:
            self._version_title_refs = []
            self._version_value_refs = []
        except Exception:
            pass

        version_items = [
            ("内核", getattr(self.app, 'comfyui_version', None), "🧬"),
            ("前端", getattr(self.app, 'frontend_version', None), "🎨"),
            ("模板库", getattr(self.app, 'template_version', None), "📋"),
            ("Python", getattr(self.app, 'python_version', None), "🐍"),
            ("Torch", getattr(self.app, 'torch_version', None), "🔥"),
            ("Git", getattr(self.app, 'git_status', None), "🐙"),
            ("显卡驱动", getattr(self.app, 'gpu_driver_status', None), "🖥️"),
        ]

        for i, (title, src, ico) in enumerate(version_items):
            card = self._create_version_item(title, src or "获取中...", ico)
            r, cidx = divmod(i, 3)
            
            # 特殊处理显卡驱动，让它占据整行，防止显卡型号过长被截断
            if title == "显卡驱动":
                cur_grid.addWidget(card, r, 0, 1, 3)
            else:
                cur_grid.addWidget(card, r, cidx)

        for col in range(3):
            cur_grid.setColumnStretch(col, 1)

        opts_row = QtWidgets.QHBoxLayout()
        opts_row.setContentsMargins(0, 0, 0, 0)
        opts_row.setSpacing(12)

        lbl_st = QtWidgets.QLabel("内核升级策略:")
        lbl_st.setStyleSheet(lbl_style)

        self.cb_stable = QtWidgets.QCheckBox("仅更新到稳定版")
        try:
            self.cb_stable.setChecked(self.app.stable_only_var.get())
            self.cb_stable.toggled.connect(lambda c: (self.app.stable_only_var.set(c), self._save_config()))
        except Exception:
            pass

        self.cb_deps = QtWidgets.QCheckBox("同时更新依赖库")
        try:
            self.cb_deps.setChecked(self.app.auto_update_deps_var.get())
            self.cb_deps.toggled.connect(lambda c: (self.app.auto_update_deps_var.set(c), self._save_config()))
        except Exception:
            pass

        self.btn_update = QtWidgets.QPushButton("更新")
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.setStyleSheet(self._get_primary_button_style())
        try:
            w1 = self.btn_update.sizeHint().width()
            self.btn_update.setText("更新中…")
            w2 = self.btn_update.sizeHint().width()
            self.btn_update.setText("更新")
            self.btn_update.setMinimumWidth(max(w1, w2))
        except Exception:
            pass
        self.btn_update.clicked.connect(self._on_update_clicked)

        # 刷新按钮
        self.btn_refresh = QtWidgets.QPushButton("刷新")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet(self._get_primary_button_style())
        try:
            w1 = self.btn_refresh.sizeHint().width()
            self.btn_refresh.setText("刷新中...")
            w2 = self.btn_refresh.sizeHint().width()
            self.btn_refresh.setText("刷新")
            self.btn_refresh.setMinimumWidth(max(w1, w2))
        except Exception:
            pass
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)

        # 超时选择器
        lbl_timeout = QtWidgets.QLabel("超时:")
        lbl_timeout.setStyleSheet(lbl_style)

        self.timeout_combo = NoWheelComboBox()
        self.timeout_combo.addItems(["60秒", "120秒", "180秒", "300秒", "600秒"])
        self.timeout_combo.setFixedWidth(self._px(85))
        self.timeout_combo.setStyleSheet(self._get_input_style())

        try:
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
        except Exception:
            pass

        opts_row.addWidget(lbl_st)
        opts_row.addWidget(self.cb_stable)
        opts_row.addSpacing(12)
        opts_row.addWidget(self.cb_deps)
        opts_row.addSpacing(12)
        opts_row.addWidget(lbl_timeout)
        opts_row.addWidget(self.timeout_combo)
        opts_row.addStretch(1)
        opts_row.addWidget(self.btn_refresh)
        opts_row.addSpacing(8)
        opts_row.addWidget(self.btn_update)
        form_layout.addLayout(opts_row)

        # 阴影效果：DPI 变化时需重建（见 _apply_shadow / update_theme）。
        self._form_group = form_group
        self._apply_shadow()

        # DPI 相关尺寸：DPI 变化时需重算（见 _reapply_dpi_sizes / update_theme）。
        # 元素：(widget, setter_name, base_int_or_tuple)；setter_name 为原生 Qt setter（getattr 分发）。
        self._dpi_sized_widgets = [
            (self.timeout_combo, "setFixedWidth", 85),
        ]

    def _create_version_item(self, title, value_source, icon_str):
        """创建版本信息条目"""
        card = QtWidgets.QFrame()
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet("QFrame { background: transparent; border: none; }")

        hb = QtWidgets.QHBoxLayout(card)
        hb.setContentsMargins(5, 2, 5, 2)
        hb.setSpacing(8)
        hb.setAlignment(Qt.AlignCenter)

        icon_lbl = QtWidgets.QLabel(icon_str)
        icon_lbl.setStyleSheet(f"font-size: {self._pt(14)}pt; background: transparent;")
        hb.addWidget(icon_lbl)

        t = QtWidgets.QLabel(f"{title} :")
        t.setStyleSheet(f"color: {self._get_label_color()}; font: bold {self._pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;")
        hb.addWidget(t)
        try:
            self._version_title_refs.append(t)
        except Exception:
            pass

        v_text = str(value_source.get() if hasattr(value_source, "get") else value_source)
        v = QtWidgets.QLabel(v_text)

        # 检查是否需要显示为错误颜色（显卡驱动状态包含"仅支持CPU模式"）
        if title == "显卡驱动" and "仅支持CPU模式" in v_text:
            text_color = self._get_error_color()
        else:
            text_color = self._get_text_color()

        v.setStyleSheet(f"font: bold {self._pt(10)}pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {text_color}; background: transparent;")
        hb.addWidget(v)

        if hasattr(value_source, "bind"):
            def _update_v(val, vv=v, tt=title, tm=self.theme_manager):
                vv.setText(str(val))
                # 更新时也检查颜色
                if tt == "显卡驱动" and "仅支持CPU模式" in str(val):
                    vv.setStyleSheet(f"font: bold {self._pt(10)}pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {tm.colors.get('error')}; background: transparent;")
                else:
                    vv.setStyleSheet(f"font: bold {self._pt(10)}pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {tm.colors.get('text')}; background: transparent;")
            value_source.bind(_update_v)
        try:
            self._version_value_refs.append(v)
        except Exception:
            pass

        return card

    def _on_update_clicked(self):
        """点击更新时，按钮显示"更新中..."，禁用并变灰，完成后恢复"""
        btn = self.btn_update
        if getattr(self.app, "_update_running", False):
            return
        if btn:
            try:
                btn.setText("更新中...")
                btn.setEnabled(False)
                QtWidgets.QApplication.processEvents()
            except Exception:
                pass
        try:
            stable_only = self.app.stable_only_var.get() if hasattr(self.app, 'stable_only_var') else True
            self.app.start_update(
                stable_only,
                on_done=lambda: (btn.setText("更新"), btn.setEnabled(True)) if btn else None,
            )
        except Exception:
            if btn:
                try:
                    btn.setText("更新")
                    btn.setEnabled(True)
                except Exception:
                    pass

    def _on_refresh_clicked(self):
        """刷新版本信息"""
        btn = self.btn_refresh
        if btn:
            try:
                btn.setText("刷新中...")
                btn.setEnabled(False)
                QtWidgets.QApplication.processEvents()
            except Exception:
                pass
        try:
            self.app.get_version_info("all")
        except Exception:
            pass
        # 延迟恢复按钮状态
        def _restore():
            if btn:
                try:
                    btn.setText("刷新")
                    btn.setEnabled(True)
                except Exception:
                    pass
        QtCore.QTimer.singleShot(1500, _restore)

    def _get_label_color(self):
        """获取标签颜色"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'colors'):
                return self.theme_manager.colors.get('label_muted', '#9CA3AF')
        except Exception:
            pass
        return '#9CA3AF'

    def _get_text_color(self):
        """获取文本颜色"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'colors'):
                return self.theme_manager.colors.get('text', '#E5E7EB')
        except Exception:
            pass
        return '#E5E7EB'

    def _get_error_color(self):
        """获取错误颜色"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'colors'):
                return self.theme_manager.colors.get('error', '#EF4444')
        except Exception:
            pass
        return '#EF4444'

    def _get_input_style(self):
        """获取输入框样式"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'styles'):
                return self.theme_manager.styles.input_style()
        except Exception:
            pass
        # 返回默认样式
        return """
        QComboBox, QLineEdit, QPushButton {
            min-height: 28px;
            border: 1px solid #4B5563;
            border-radius: 6px;
            padding: 2px 8px;
            color: #E5E7EB;
            background-color: rgba(0, 0, 0, 0.3);
        }
        """

    def _get_primary_button_style(self):
        """获取主要按钮样式"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'styles'):
                return self.theme_manager.styles.primary_button_style()
        except Exception:
            pass
        return """
        QPushButton {
            min-height: 28px;
            border: 1px solid #4B5563;
            border-radius: 6px;
            padding: 2px 12px;
            color: #E5E7EB;
            background-color: rgba(75, 85, 99, 0.5);
        }
        QPushButton:hover {
            background-color: rgba(75, 85, 99, 0.8);
        }
        """

    def _save_config(self):
        """保存配置"""
        try:
            if hasattr(self.app, 'save_config'):
                self.app.save_config()
        except Exception:
            pass

    def _on_theme_changed(self, theme_styles):
        """主题变更回调"""
        self.update_theme(theme_styles)

    def _apply_shadow(self):
        """给 form_group 重建阴影 effect。

        QGraphicsDropShadowEffect 在 Qt5 下会把源 widget 渲染进内部缓存；
        DPI 变化 / backing store 重建（见 qt_app._apply_screen_change 的
        wh.create()）后，缓存按旧 DPR/旧尺寸的渲染会残留在画面上，表现为
        QGroupBox 边缘外的「黑条」且切回原 DPI 也无法恢复。重建 effect 能
        强制缓存按当前 DPR 重新分配，消除残影。
        """
        try:
            from core.render_guard import is_safe_ui as _is_safe_ui
            if _is_safe_ui():
                return
        except Exception:
            pass
        fg = getattr(self, "_form_group", None)
        if fg is None:
            return
        try:
            fg.setGraphicsEffect(None)  # 拆掉旧 effect（连同它的缓存）
            shadow = QtWidgets.QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(18)
            shadow.setOffset(0, 4)
            shadow.setColor(QtGui.QColor(0, 0, 0, 30))
            fg.setGraphicsEffect(shadow)
        except Exception:
            pass

    def _reapply_dpi_sizes(self):
        """重算所有用 _px() / sizeHint() 设定的 DPI 相关尺寸（DPI 变化时调用）。"""
        _px = self._px
        for w, setter_name, base in getattr(self, "_dpi_sized_widgets", []):
            try:
                setter = getattr(w, setter_name)
                if isinstance(base, tuple):
                    setter(_px(base[0]), _px(base[1]))
                else:
                    setter(_px(base))
            except Exception:
                pass
        # btn_update / btn_refresh 的 minWidth 按文本 sizeHint 算，DPI 变化后字体重测，
        # 需重走一遍 _setup_ui 里的临时 setText 测量法。
        self._reapply_btn_min_width(getattr(self, "btn_update", None), "更新中…", "更新")
        self._reapply_btn_min_width(getattr(self, "btn_refresh", None), "刷新中...", "刷新")

    def _reapply_btn_min_width(self, btn, transient_text, final_text):
        if btn is None:
            return
        try:
            w1 = btn.sizeHint().width()
            btn.setText(transient_text)
            w2 = btn.sizeHint().width()
            btn.setText(final_text)
            btn.setMinimumWidth(max(w1, w2))
        except Exception:
            pass

    def update_theme(self, theme_styles=None):
        """更新主题"""
        label_muted = self._get_label_color()
        text_color = self._get_text_color()
        
        try:
            for ref in getattr(self, "_version_title_refs", []):
                ref.setStyleSheet(f"color: {label_muted}; font: bold {self._pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;")
            for ref in getattr(self, "_version_value_refs", []):
                ref.setStyleSheet(f"font: bold {self._pt(10)}pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {text_color}; background: transparent;")
        except Exception:
            pass

        # 更新按钮样式
        if hasattr(self, 'btn_update'):
            self.btn_update.setStyleSheet(self._get_primary_button_style())
        if hasattr(self, 'btn_refresh'):
            self.btn_refresh.setStyleSheet(self._get_primary_button_style())
        
        # 更新输入框样式
        input_style = self._get_input_style()
        if hasattr(self, 'timeout_combo'):
            self.timeout_combo.setStyleSheet(input_style)

        # DPI 变化时重算尺寸 + 重建阴影（消除 QGraphicsDropShadowEffect 缓存残影）
        self._reapply_dpi_sizes()
        self._apply_shadow()
