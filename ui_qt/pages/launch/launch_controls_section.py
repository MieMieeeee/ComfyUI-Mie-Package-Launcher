"""
启动控制区块
从 launch_page.py 提取的 LaunchControlsSection 类
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from ui_qt.widgets.custom import NoWheelComboBox


class LaunchControlsSection(QtWidgets.QWidget):
    """
    启动控制区块控件
    
    包含：GPU/CPU模式、端口设置、局域网访问、显存策略、
    注意力优化、浏览器选择、FP16/API/插件DEBUG选项、额外启动参数
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
        lbl_style = f"color: {self._get_label_color()}; font-weight: bold;"

        # 主布局
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 表单组
        form_group = QtWidgets.QGroupBox("启动控制")
        form_layout = QtWidgets.QGridLayout(form_group)
        form_layout.setColumnStretch(1, 1)
        form_layout.setColumnStretch(3, 1)
        form_layout.setColumnMinimumWidth(0, 90)
        form_layout.setHorizontalSpacing(20)
        form_layout.setVerticalSpacing(12)
        form_layout.setContentsMargins(12, 12, 12, 12)

        main_layout.addWidget(form_group)

        # 添加阴影效果
        try:
            shadow1 = QtWidgets.QGraphicsDropShadowEffect(self)
            shadow1.setBlurRadius(18)
            shadow1.setOffset(0, 4)
            shadow1.setColor(QtGui.QColor(0, 0, 0, 30))
            form_group.setGraphicsEffect(shadow1)
        except Exception:
            pass

        # ============== 运行模式 ==============
        mode_label = QtWidgets.QLabel("运行模式：")
        mode_label.setStyleSheet(lbl_style)
        mode_container = QtWidgets.QWidget()
        mode_layout = QtWidgets.QHBoxLayout(mode_container)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(15)

        modes = [("GPU", "gpu"), ("CPU", "cpu")]
        for label, val in modes:
            rb = QtWidgets.QRadioButton(label)
            if hasattr(self.app, 'compute_mode'):
                rb.setChecked(self.app.compute_mode.get() == val)
                rb.toggled.connect(lambda c, v=val: (self.app.compute_mode.set(v) if c else None, self._save_config()))
            rb.setToolTip("选择运行模式：GPU（推荐）或 CPU")
            mode_layout.addWidget(rb)
        mode_layout.addStretch(1)

        form_layout.addWidget(mode_label, 0, 0)
        form_layout.addWidget(mode_container, 0, 1)

        # ============== 端口号 + 局域网访问 ==============
        port_label = QtWidgets.QLabel("端口号：")
        port_label.setStyleSheet(lbl_style)
        port_edit = QtWidgets.QLineEdit()
        port_edit.setFixedWidth(60)
        if hasattr(self.app, 'custom_port'):
            port_edit.setText(self.app.custom_port.get())
            port_edit.textChanged.connect(lambda v: (self.app.custom_port.set(v), self._save_config()))
        port_edit.setToolTip("ComfyUI Web服务端口，默认8188")

        listen_chk = QtWidgets.QCheckBox("允许局域网访问")
        if hasattr(self.app, 'listen_all'):
            listen_chk.setChecked(self.app.listen_all.get())
            listen_chk.toggled.connect(lambda v: (self.app.listen_all.set(v), self._save_config()))
        listen_chk.setToolTip("允许局域网内其他设备访问ComfyUI")

        hbox_port = QtWidgets.QHBoxLayout()
        hbox_port.setContentsMargins(0, 0, 0, 0)
        hbox_port.setSpacing(15)
        hbox_port.addWidget(port_label)
        hbox_port.addWidget(port_edit)
        hbox_port.addWidget(listen_chk)
        hbox_port.addStretch(1)
        form_layout.addLayout(hbox_port, 0, 2, 1, 2)

        # ============== 显存策略 ==============
        opt_label = QtWidgets.QLabel("显存策略：")
        opt_label.setStyleSheet(lbl_style)
        opt_widget = NoWheelComboBox()
        opt_widget.addItems([
            "由 ComfyUI 决定（推荐）",
            "显存充足 (High)",
            "中等显存 (Normal)",
            "低显存 (Low)",
            "极低显存 (No)",
        ])
        opt_widget.setStyleSheet(self._get_input_style())

        if hasattr(self.app, 'vram_mode'):
            # 第 0 项为空字符串，表示不加任何 --*vram 参数，让 ComfyUI 自己选择
            vram_map_vals = ["", "--highvram", "--normalvram", "--lowvram", "--novram"]
            cur_vram = (self.app.vram_mode.get() or "").strip()
            if cur_vram in vram_map_vals:
                opt_widget.setCurrentIndex(vram_map_vals.index(cur_vram))
            else:
                # 未设置或未知值时，默认让 ComfyUI 决定
                opt_widget.setCurrentIndex(0)
            opt_widget.currentIndexChanged.connect(
                lambda i: (self.app.vram_mode.set(vram_map_vals[i]), self._save_config())
            )
        opt_widget.setToolTip("大多数情况可交给 ComfyUI 自动决定，必要时再手动指定显存策略")

        # ============== 注意力优化 ==============
        attn_label = QtWidgets.QLabel("注意力优化：")
        attn_label.setStyleSheet(lbl_style)
        attn_combo = NoWheelComboBox()
        attn_combo.setStyleSheet(self._get_input_style())

        attn_opts = [
            ("默认 (Default)", ""),
            ("PyTorch (SDPA)", "--use-pytorch-cross-attention"),
            ("Flash Attention", "--use-flash-attention"),
            ("Sage Attention", "--use-sage-attention"),
            ("Split Attention", "--use-split-cross-attention"),
            ("Quad Attention", "--use-quad-cross-attention"),
        ]
        for name, val in attn_opts:
            attn_combo.addItem(name, val)

        if hasattr(self.app, 'attention_mode'):
            cur_attn = self.app.attention_mode.get() or ""
            found_attn = False
            for i, (name, val) in enumerate(attn_opts):
                if val == cur_attn:
                    attn_combo.setCurrentIndex(i)
                    found_attn = True
                    break
            if not found_attn:
                attn_combo.setCurrentIndex(0)
            attn_combo.currentIndexChanged.connect(lambda i: (self.app.attention_mode.set(attn_opts[i][1]), self._save_config()))
        attn_combo.setToolTip("选择注意力计算优化方式，可加速图像生成")

        form_layout.addWidget(opt_label, 1, 0)
        form_layout.addWidget(opt_widget, 1, 1)
        form_layout.addWidget(attn_label, 1, 2)
        form_layout.addWidget(attn_combo, 1, 3)

        # ============== 自动打开浏览器 ==============
        open_label = QtWidgets.QLabel("自动打开浏览器：")
        open_label.setStyleSheet(lbl_style)
        open_combo = NoWheelComboBox()
        open_combo.setStyleSheet(self._get_input_style())

        open_opts = [
            ("不自动打开", "disable"),
            ("使用默认浏览器", "default"),
            ("使用指定浏览器", "webbrowser"),
        ]
        for name, val in open_opts:
            open_combo.addItem(name, val)

        if hasattr(self.app, 'browser_open_mode'):
            cur_open = self.app.browser_open_mode.get()
            for i, (name, val) in enumerate(open_opts):
                if val == cur_open:
                    open_combo.setCurrentIndex(i)
                    break
            open_combo.currentIndexChanged.connect(lambda i: (self.app.browser_open_mode.set(open_opts[i][1]), self._save_config()))
        open_combo.setToolTip("启动后自动打开浏览器访问Web界面")

        cpath_btn = QtWidgets.QPushButton("选择浏览器…")
        cpath_btn.setCursor(Qt.PointingHandCursor)
        cpath_btn.setMinimumWidth(120)
        cpath_btn.setStyleSheet(self._get_input_style())
        initial_path = ""
        try:
            if hasattr(self.app, "custom_browser_path"):
                initial_path = (self.app.custom_browser_path.get() or "").strip()
        except Exception:
            initial_path = ""
        if initial_path:
            try:
                from pathlib import Path
                name = Path(initial_path).name
                cpath_btn.setText(f"已添加: {name}")
            except Exception:
                try:
                    cpath_btn.setText("已添加浏览器")
                except Exception:
                    pass

        def _select_browser():
            from PyQt5.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "选择浏览器程序",
                "",
                "可执行文件 (*.exe);;所有文件 (*.*)",
            )
            if not file_path:
                return
            try:
                if hasattr(self.app, "custom_browser_path"):
                    self.app.custom_browser_path.set(file_path)
                from pathlib import Path
                try:
                    name = Path(file_path).name
                    cpath_btn.setText(f"已添加: {name}")
                except Exception:
                    cpath_btn.setText("已添加浏览器")
                self._save_config()
            except Exception:
                pass

        try:
            cpath_btn.clicked.connect(_select_browser)
        except Exception:
            pass

        row2_container = QtWidgets.QWidget()
        row2_layout = QtWidgets.QHBoxLayout(row2_container)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(15)
        row2_layout.addWidget(open_combo)
        row2_layout.addWidget(cpath_btn)
        row2_layout.addStretch(1)
        try:
            h = max(open_combo.sizeHint().height(), cpath_btn.sizeHint().height())
            row2_container.setFixedHeight(h)
        except Exception:
            pass

        def _update_cpath_vis():
            try:
                is_custom = (open_combo.currentData() == "webbrowser")
                cpath_btn.setVisible(is_custom)
            except Exception:
                try:
                    cpath_btn.setVisible(False)
                except Exception:
                    pass

        try:
            open_combo.currentIndexChanged.connect(lambda _: _update_cpath_vis())
        except Exception:
            pass
        _update_cpath_vis()

        form_layout.addWidget(open_label, 2, 0)
        form_layout.addWidget(row2_container, 2, 1, 1, 3)

        # ============== 复选框 ==============
        hbox_opts = QtWidgets.QHBoxLayout()
        hbox_opts.setContentsMargins(0, 0, 0, 0)
        hbox_opts.setSpacing(25)

        cb_fast = QtWidgets.QCheckBox("快速FP16累加")
        if hasattr(self.app, 'use_fast_mode'):
            cb_fast.setChecked(self.app.use_fast_mode.get())
            cb_fast.toggled.connect(lambda v: (self.app.use_fast_mode.set(v), self._save_config()))
        cb_fast.setToolTip("使用FP16精度加速计算，可能略微降低精度")

        cb_api = QtWidgets.QCheckBox("禁用API节点")
        if hasattr(self.app, 'disable_api_nodes'):
            cb_api.setChecked(self.app.disable_api_nodes.get())
            cb_api.toggled.connect(lambda v: (self.app.disable_api_nodes.set(v), self._save_config()))
        cb_api.setToolTip("禁用ComfyUI的API节点，不使用API节点可选择，能减少启动资源占用")

        cb_nodes = QtWidgets.QCheckBox("禁用所有插件(DEBUG)")
        if hasattr(self.app, 'disable_all_custom_nodes'):
            cb_nodes.setChecked(self.app.disable_all_custom_nodes.get())
            cb_nodes.toggled.connect(lambda v: (self.app.disable_all_custom_nodes.set(v), self._save_config()))
        cb_nodes.setToolTip("禁用所有自定义节点，用于调试目的")

        hbox_opts.addWidget(cb_fast)
        hbox_opts.addWidget(cb_api)
        hbox_opts.addWidget(cb_nodes)
        hbox_opts.addStretch(1)
        form_layout.addLayout(hbox_opts, 3, 0, 1, 4)

        # ============== 额外选项 ==============
        extra_label = QtWidgets.QLabel("额外选项：")
        extra_label.setStyleSheet(lbl_style)
        extra_edit = QtWidgets.QLineEdit()
        extra_edit.setPlaceholderText("例如: --disable-smart-memory --fp16-vae")
        extra_edit.setStyleSheet(self._get_input_style())

        if hasattr(self.app, 'extra_launch_args'):
            extra_edit.setText(self.app.extra_launch_args.get())
            extra_edit.textChanged.connect(lambda v: (self.app.extra_launch_args.set(v), self._save_config()))
        extra_edit.setToolTip("传入额外的启动参数")

        form_layout.addWidget(extra_label, 4, 0)
        form_layout.addWidget(extra_edit, 4, 1, 1, 3)

    def _get_label_color(self):
        """获取标签颜色"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'colors'):
                return self.theme_manager.colors.get('label_muted', '#9CA3AF')
        except Exception:
            pass
        return '#9CA3AF'

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

    def _save_config(self):
        """保存配置"""
        try:
            if hasattr(self.app, '_save_config'):
                self.app._save_config()
        except Exception:
            pass

    def _on_theme_changed(self, theme_styles):
        """主题变更回调"""
        self.update_theme(theme_styles)

    def update_theme(self, theme_styles=None):
        """更新主题"""
        # 重新设置标签样式
        lbl_style = f"color: {self._get_label_color()}; font-weight: bold;"
        
        # 找到所有 QLabel 并更新样式（标签，不含组标题）
        for label in self.findChildren(QtWidgets.QLabel):
            # 跳过 GroupBox 的标题
            if label.parent() and isinstance(label.parent(), QtWidgets.QGroupBox):
                parent_title = label.parent().title()
                if parent_title == "启动控制" and label.text() in ["运行模式：", "端口号：", "显存策略：", "注意力优化：", "自动打开浏览器：", "额外选项："]:
                    label.setStyleSheet(lbl_style)
        
        # 更新输入框样式
        input_style = self._get_input_style()
        for widget in self.findChildren((QtWidgets.QLineEdit, QtWidgets.QComboBox, QtWidgets.QPushButton)):
            try:
                widget.setStyleSheet(input_style)
            except Exception:
                pass
