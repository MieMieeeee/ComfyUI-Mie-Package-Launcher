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

    def _setup_ui(self):
        """设置 UI"""
        lbl_style = f"color: {self._get_label_color()}; font: 10pt 'Microsoft YaHei UI';"

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
        self.timeout_combo.setFixedWidth(85)
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

        # 添加阴影效果
        try:
            shadow1 = QtWidgets.QGraphicsDropShadowEffect(self)
            shadow1.setBlurRadius(18)
            shadow1.setOffset(0, 4)
            shadow1.setColor(QtGui.QColor(0, 0, 0, 30))
            form_group.setGraphicsEffect(shadow1)
        except Exception:
            pass

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
        icon_lbl.setStyleSheet("font-size: 14pt; background: transparent;")
        hb.addWidget(icon_lbl)

        t = QtWidgets.QLabel(f"{title} :")
        t.setStyleSheet(f"color: {self._get_label_color()}; font: bold 9pt \"Microsoft YaHei UI\"; background: transparent;")
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

        v.setStyleSheet(f"font: bold 10pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {text_color}; background: transparent;")
        hb.addWidget(v)

        if hasattr(value_source, "bind"):
            def _update_v(val, vv=v, tt=title, tm=self.theme_manager):
                vv.setText(str(val))
                # 更新时也检查颜色
                if tt == "显卡驱动" and "仅支持CPU模式" in str(val):
                    vv.setStyleSheet(f"font: bold 10pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {tm.colors.get('error')}; background: transparent;")
                else:
                    vv.setStyleSheet(f"font: bold 10pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {tm.colors.get('text')}; background: transparent;")
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

    def update_theme(self, theme_styles=None):
        """更新主题"""
        label_muted = self._get_label_color()
        text_color = self._get_text_color()
        
        try:
            for ref in getattr(self, "_version_title_refs", []):
                ref.setStyleSheet(f"color: {label_muted}; font: bold 9pt \"Microsoft YaHei UI\"; background: transparent;")
            for ref in getattr(self, "_version_value_refs", []):
                ref.setStyleSheet(f"font: bold 10pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {text_color}; background: transparent;")
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
