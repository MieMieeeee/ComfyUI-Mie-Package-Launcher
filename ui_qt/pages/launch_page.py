"""
启动页面
包含启动控制、环境配置、版本与更新、快捷目录等功能
"""

from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from .base_page import BasePage
from ui_qt.theme_styles import ThemeStyles
from ui_qt.widgets.custom import NoWheelComboBox


class LaunchPage(BasePage):
    """启动页面"""

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self.theme_manager = theme_manager
        self._setup_ui()
        try:
            if hasattr(self.app, "services") and hasattr(self.app.services, "process"):
                self.app.services.process.refresh_status()
        except Exception:
            pass

    def _update_button_state(self):
        """与旧版兼容的占位方法：实际状态由 ProcessManager 控制 big_btn"""
        try:
            if hasattr(self.app, "big_btn"):
                text = getattr(self.app.big_btn, "_text", None)
                if text and hasattr(self, "btn_toggle"):
                    self.btn_toggle.setText(text)
        except Exception:
            pass

    def _setup_ui(self):
        """设置 UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 调试日志：检查根目录设置
        try:
            comfy_root = self.app.config.get('paths', {}).get('comfyui_root', '.')
            if hasattr(self.app, 'logger'):
                self.app.logger.info("LaunchPage 初始化: comfyui_root=%s", comfy_root)
        except Exception:
            pass

        # ============== 启动控制区块 ==============
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(15)
        layout.addLayout(top_row)

        # 启动大按钮
        btn_toggle = QtWidgets.QPushButton("🚀 一键启动")
        btn_toggle.setCursor(Qt.PointingHandCursor)
        btn_toggle.setFixedWidth(120)
        btn_toggle.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        btn_toggle.setStyleSheet(self._get_primary_button_style())
        btn_toggle.clicked.connect(self._on_toggle_launch)
        btn_toggle.setToolTip("启动或停止ComfyUI服务")
        self.btn_toggle = btn_toggle
        # 初始化按钮状态
        self._update_button_state()

        # 启动控制表单
        form_group = QtWidgets.QGroupBox("启动控制")
        form_layout = QtWidgets.QGridLayout(form_group)
        form_layout.setColumnStretch(1, 1)
        form_layout.setColumnStretch(3, 1)
        form_layout.setColumnMinimumWidth(0, 90)
        form_layout.setHorizontalSpacing(20)
        # 与环境配置区块保持一致的行间距
        form_layout.setVerticalSpacing(12)
        form_layout.setContentsMargins(12, 12, 12, 12)

        top_row.addWidget(form_group, 1)
        top_row.addWidget(btn_toggle, 0)

        # 添加阴影效果
        try:
            shadow1 = QtWidgets.QGraphicsDropShadowEffect(self)
            shadow1.setBlurRadius(18)
            shadow1.setOffset(0, 4)
            shadow1.setColor(QtGui.QColor(0, 0, 0, 30))
            form_group.setGraphicsEffect(shadow1)
        except Exception:
            pass

        self._build_launch_controls(form_layout)

        # 让一键启动按钮高度与启动控制区域保持一致
        try:
            from PyQt5.QtCore import QTimer
            def _sync_btn_height():
                try:
                    btn_toggle.setFixedHeight(form_group.sizeHint().height())
                except Exception:
                    pass
            QTimer.singleShot(0, _sync_btn_height)
        except Exception:
            pass

        # ============== 环境配置区块 ==============
        env_group = QtWidgets.QGroupBox("环境配置")
        env_main_v = QtWidgets.QVBoxLayout(env_group)
        env_main_v.setContentsMargins(0, 0, 0, 0)
        env_main_v.setSpacing(0)
        layout.addWidget(env_group)

        self._build_environment_config(env_main_v)

        # ============== 版本与更新区块 ==============
        ver_group = QtWidgets.QGroupBox("版本与更新")
        ver_layout = QtWidgets.QVBoxLayout(ver_group)
        layout.addWidget(ver_group)

        self._build_version_section(ver_layout)

        # ============== 快捷目录区块 ==============
        quick_group = QtWidgets.QGroupBox("快捷目录")
        quick_layout = QtWidgets.QHBoxLayout(quick_group)
        layout.addWidget(quick_group)

        self._build_quick_dir(quick_layout)

        # 将多余高度留给页面底部的弹性空白，而不是拉伸“版本与更新”等区块
        layout.addStretch(1)

        # 存储需要主题更新的组件
        self._styled_widgets = [form_group, env_group, ver_group]
        if hasattr(self.app, "_styled_widgets"):
            self.app._theme_widgets.extend(self._styled_widgets)
        try:
            self._version_title_refs = []
            self._version_value_refs = []
            self._quick_dir_buttons = []
        except Exception:
            pass

    def _build_launch_controls(self, layout):
        """构建启动控制表单"""
        lbl_style = f"color: {self.theme_manager.colors.get('label_muted')}; font-weight: bold;"

        # 运行模式
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

        layout.addWidget(mode_label, 0, 0)
        layout.addWidget(mode_container, 0, 1)

        # 端口号 + 局域网访问
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
        layout.addLayout(hbox_port, 0, 2, 1, 2)

        # 显存策略
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
        opt_widget.setStyleSheet(self.theme_manager.styles.input_style())

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

        # 注意力优化
        attn_label = QtWidgets.QLabel("注意力优化：")
        attn_label.setStyleSheet(lbl_style)
        attn_combo = NoWheelComboBox()
        attn_combo.setStyleSheet(self.theme_manager.styles.input_style())

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

        layout.addWidget(opt_label, 1, 0)
        layout.addWidget(opt_widget, 1, 1)
        layout.addWidget(attn_label, 1, 2)
        layout.addWidget(attn_combo, 1, 3)

        # 自动打开浏览器
        open_label = QtWidgets.QLabel("自动打开浏览器：")
        open_label.setStyleSheet(lbl_style)
        open_combo = NoWheelComboBox()
        open_combo.setStyleSheet(self.theme_manager.styles.input_style())

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
        # 使用与输入框一致的样式，避免单独一行被撑高
        cpath_btn.setStyleSheet(self.theme_manager.styles.input_style())
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

        layout.addWidget(open_label, 2, 0)
        layout.addWidget(row2_container, 2, 1, 1, 3)

        # 复选框
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

        # cb_new_manager = QtWidgets.QCheckBox("使用新版Manager")
        # if hasattr(self.app, 'use_new_manager'):
        #     cb_new_manager.setChecked(self.app.use_new_manager.get())
        #     cb_new_manager.toggled.connect(lambda v: (self.app.use_new_manager.set(v), self._save_config()))
        # cb_new_manager.setToolTip("切换到新版 ComfyUI-Manager 界面")

        cb_nodes = QtWidgets.QCheckBox("禁用所有插件(DEBUG)")
        if hasattr(self.app, 'disable_all_custom_nodes'):
            cb_nodes.setChecked(self.app.disable_all_custom_nodes.get())
            cb_nodes.toggled.connect(lambda v: (self.app.disable_all_custom_nodes.set(v), self._save_config()))
        cb_nodes.setToolTip("禁用所有自定义节点，用于调试目的")

        hbox_opts.addWidget(cb_fast)
        hbox_opts.addWidget(cb_api)
        # hbox_opts.addWidget(cb_new_manager)
        hbox_opts.addWidget(cb_nodes)
        hbox_opts.addStretch(1)
        layout.addLayout(hbox_opts, 3, 0, 1, 4)

        # 额外选项
        extra_label = QtWidgets.QLabel("额外选项：")
        extra_label.setStyleSheet(lbl_style)
        extra_edit = QtWidgets.QLineEdit()
        extra_edit.setPlaceholderText("例如: --disable-smart-memory --fp16-vae")
        extra_edit.setStyleSheet(self.theme_manager.styles.input_style())

        if hasattr(self.app, 'extra_launch_args'):
            extra_edit.setText(self.app.extra_launch_args.get())
            extra_edit.textChanged.connect(lambda v: (self.app.extra_launch_args.set(v), self._save_config()))
        extra_edit.setToolTip("传入额外的启动参数")

        layout.addWidget(extra_label, 4, 0)
        layout.addWidget(extra_edit, 4, 1, 1, 3)

    def _build_environment_config(self, layout):
        """构建环境配置区块"""
        env_layout = QtWidgets.QGridLayout()
        env_layout.setColumnMinimumWidth(0, 100)
        env_layout.setColumnStretch(1, 3)
        env_layout.setHorizontalSpacing(15)
        env_layout.setVerticalSpacing(12)
        env_layout.setContentsMargins(15, 15, 15, 15)
        layout.addLayout(env_layout)

        lbl_style = f"color: {self.theme_manager.colors.get('label_muted')}; font-weight: bold;"

        # HF 镜像
        env_hf_combo = NoWheelComboBox()
        env_hf_combo.addItems(["不使用", "hf-mirror", "自定义"])
        env_hf_combo.setMinimumWidth(120)
        env_hf_combo.setStyleSheet(self.theme_manager.styles.input_style())

        env_hf_entry = QtWidgets.QLineEdit()
        env_hf_entry.setPlaceholderText("请输入镜像地址...")
        env_hf_entry.setStyleSheet(self.theme_manager.styles.input_style())
        env_hf_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        env_hf_entry.setMinimumWidth(520)

        if hasattr(self.app, 'selected_hf_mirror'):
            env_hf_combo.setCurrentText(self.app.selected_hf_mirror.get() if self.app.selected_hf_mirror.get() in ["不使用", "hf-mirror", "自定义"] else "hf-mirror")
            if hasattr(self.app, 'hf_mirror_url'):
                env_hf_entry.setText(self.app.hf_mirror_url.get())

        def _env_hf_change(text):
            is_custom = (text == "自定义")
            is_none = (text == "不使用")
            env_hf_entry.setReadOnly(not is_custom)
            env_hf_entry.setVisible(not is_none)

            if text == "hf-mirror":
                env_hf_entry.setText("https://hf-mirror.com")
                if hasattr(self.app, 'hf_mirror_url'):
                    self.app.hf_mirror_url.set("https://hf-mirror.com")
            elif is_custom:
                if hasattr(self.app, 'selected_hf_mirror') and self.app.selected_hf_mirror.get() != "自定义":
                    env_hf_entry.setText("")
                if hasattr(self.app, 'hf_mirror_url'):
                    self.app.hf_mirror_url.set(env_hf_entry.text())
            else:
                if hasattr(self.app, 'hf_mirror_url'):
                    self.app.hf_mirror_url.set("")
            if hasattr(self.app, 'selected_hf_mirror'):
                self.app.selected_hf_mirror.set(text)
            self._save_config()

        env_hf_combo.currentTextChanged.connect(_env_hf_change)
        try:
            _env_hf_change(env_hf_combo.currentText())
        except Exception:
            pass
        env_hf_combo.setToolTip("选择Hugging Face镜像源，加速模型下载")

        _add_hf_container = QtWidgets.QWidget()
        _add_hf_layout = QtWidgets.QHBoxLayout(_add_hf_container)
        _add_hf_layout.setContentsMargins(0, 0, 0, 0)
        _add_hf_layout.setSpacing(10)
        _add_hf_layout.addWidget(env_hf_combo)
        _add_hf_layout.addWidget(env_hf_entry)
        _add_hf_layout.addStretch(1)

        hf_label = QtWidgets.QLabel("HF 镜像源：")
        hf_label.setStyleSheet(lbl_style)
        hf_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hf_label.setFixedWidth(100)

        env_layout.addWidget(hf_label, 0, 0)
        env_layout.addWidget(_add_hf_container, 0, 1)

        # GitHub 代理
        env_gh_combo = NoWheelComboBox()
        env_gh_combo.addItems(["不使用", "gh-proxy", "自定义"])
        env_gh_combo.setMinimumWidth(120)
        env_gh_combo.setStyleSheet(self.theme_manager.styles.input_style())

        env_gh_entry = QtWidgets.QLineEdit()
        env_gh_entry.setPlaceholderText("请输入代理地址...")
        env_gh_entry.setStyleSheet(self.theme_manager.styles.input_style())
        env_gh_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        env_gh_entry.setMinimumWidth(520)

        if hasattr(self.app, 'version_manager') and hasattr(self.app.version_manager, 'proxy_mode_ui_var'):
            env_gh_combo.setCurrentText(self.app.version_manager.proxy_mode_ui_var.get())
            env_gh_entry.setText(self.app.version_manager.proxy_url_var.get())

        def _env_gh_change(text):
            is_custom = (text == "自定义")
            is_none = (text == "不使用")
            env_gh_entry.setReadOnly(not is_custom)
            env_gh_entry.setVisible(not is_none)

            m = "none" if is_none else ("gh-proxy" if text == "gh-proxy" else "custom")

            if text == "gh-proxy":
                url = "https://gh-proxy.com/"
                env_gh_entry.setText(url)
                if hasattr(self.app, 'version_manager'):
                    self.app.version_manager.proxy_url_var.set(url)
            elif is_custom:
                if hasattr(self.app, 'version_manager') and self.app.version_manager.proxy_mode_ui_var.get() != "自定义":
                    env_gh_entry.setText("")
                if hasattr(self.app, 'version_manager'):
                    self.app.version_manager.proxy_url_var.set(env_gh_entry.text())

            if hasattr(self.app, 'version_manager'):
                self.app.version_manager.proxy_mode_var.set(m)
                self.app.version_manager.proxy_mode_ui_var.set(text)
                self.app.version_manager.save_proxy_settings()

        env_gh_combo.currentTextChanged.connect(_env_gh_change)
        try:
            _env_gh_change(env_gh_combo.currentText())
        except Exception:
            pass
        env_gh_combo.setToolTip("选择GitHub下载代理，加速国内访问")

        _add_gh_container = QtWidgets.QWidget()
        _add_gh_layout = QtWidgets.QHBoxLayout(_add_gh_container)
        _add_gh_layout.setContentsMargins(0, 0, 0, 0)
        _add_gh_layout.setSpacing(10)
        _add_gh_layout.addWidget(env_gh_combo)
        _add_gh_layout.addWidget(env_gh_entry)
        _add_gh_layout.addStretch(1)

        gh_label = QtWidgets.QLabel("GitHub 代理：")
        gh_label.setStyleSheet(lbl_style)
        gh_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gh_label.setFixedWidth(100)

        env_layout.addWidget(gh_label, 1, 0)
        env_layout.addWidget(_add_gh_container, 1, 1)

        # PyPI 代理
        env_pypi_combo = NoWheelComboBox()
        env_pypi_combo.addItems(["不使用", "阿里云", "自定义"])
        env_pypi_combo.setMinimumWidth(120)
        env_pypi_combo.setStyleSheet(self.theme_manager.styles.input_style())

        env_pypi_entry = QtWidgets.QLineEdit()
        env_pypi_entry.setPlaceholderText("请输入 PyPI 源地址...")
        env_pypi_entry.setStyleSheet(self.theme_manager.styles.input_style())
        env_pypi_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        env_pypi_entry.setMinimumWidth(520)

        if hasattr(self.app, 'pypi_proxy_mode_ui'):
            env_pypi_combo.setCurrentText(self.app.pypi_proxy_mode_ui.get())
        if hasattr(self.app, 'pypi_proxy_url'):
            env_pypi_entry.setText(self.app.pypi_proxy_url.get())

        def _env_pypi_change(text):
            is_custom = (text == "自定义")
            is_none = (text == "不使用")
            env_pypi_entry.setReadOnly(not is_custom)
            env_pypi_entry.setVisible(not is_none)

            mode = "none" if is_none else ("aliyun" if text == "阿里云" else "custom")

            if text == "阿里云":
                url = "https://mirrors.aliyun.com/pypi/simple/"
                env_pypi_entry.setText(url)
                if hasattr(self.app, 'pypi_proxy_url'):
                    self.app.pypi_proxy_url.set(url)
            elif is_custom:
                if hasattr(self.app, 'pypi_proxy_mode_ui') and self.app.pypi_proxy_mode_ui.get() != "自定义":
                    env_pypi_entry.setText("")
                if hasattr(self.app, 'pypi_proxy_url'):
                    self.app.pypi_proxy_url.set(env_pypi_entry.text())

            if hasattr(self.app, 'pypi_proxy_mode'):
                self.app.pypi_proxy_mode.set(mode)
            if hasattr(self.app, 'pypi_proxy_mode_ui'):
                self.app.pypi_proxy_mode_ui.set(text)
            self._save_config()

        env_pypi_combo.currentTextChanged.connect(_env_pypi_change)
        try:
            _env_pypi_change(env_pypi_combo.currentText())
        except Exception:
            pass
        env_pypi_combo.setToolTip("选择PyPI镜像源，加速Python包安装")

        _add_pypi_container = QtWidgets.QWidget()
        _add_pypi_layout = QtWidgets.QHBoxLayout(_add_pypi_container)
        _add_pypi_layout.setContentsMargins(0, 0, 0, 0)
        _add_pypi_layout.setSpacing(10)
        _add_pypi_layout.addWidget(env_pypi_combo)
        _add_pypi_layout.addWidget(env_pypi_entry)
        _add_pypi_layout.addStretch(1)

        pypi_label = QtWidgets.QLabel("PyPI 代理：")
        pypi_label.setStyleSheet(lbl_style)
        pypi_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pypi_label.setFixedWidth(100)

        env_layout.addWidget(pypi_label, 2, 0)
        env_layout.addWidget(_add_pypi_container, 2, 1)

        # 分割线
        div_line = QtWidgets.QFrame()
        div_line.setFrameShape(QtWidgets.QFrame.HLine)
        div_line.setFrameShadow(QtWidgets.QFrame.Plain)
        div_line.setStyleSheet(self.theme_manager.styles.divider_style())
        env_layout.addWidget(div_line, 3, 0, 1, 2)

        # 根目录
        root_show = QtWidgets.QLineEdit()
        root_show.setReadOnly(True)
        root_show.setStyleSheet(self.theme_manager.styles.input_style())
        root_show.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        root_show.setMinimumWidth(520)
        if hasattr(self.app, 'config'):
            root_show.setText(str(Path(self.app.config.get('paths', {}).get('comfyui_root') or '.')))

        root_btn = QtWidgets.QPushButton("选取")
        root_btn.setCursor(Qt.PointingHandCursor)
        root_btn.setStyleSheet(self.theme_manager.styles.primary_button_style())
        root_btn.clicked.connect(self._choose_root)
        root_btn.setToolTip("选择ComfyUI安装根目录")

        _add_root_container = QtWidgets.QWidget()
        _add_root_layout = QtWidgets.QHBoxLayout(_add_root_container)
        _add_root_layout.setContentsMargins(0, 0, 0, 0)
        _add_root_layout.setSpacing(10)
        _add_root_layout.addWidget(root_show)
        _add_root_layout.addWidget(root_btn)
        try:
            self._root_show = root_show
        except Exception:
            pass

        root_label = QtWidgets.QLabel("根目录：")
        root_label.setStyleSheet(lbl_style)
        root_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        root_label.setFixedWidth(100)

        env_layout.addWidget(root_label, 4, 0)
        env_layout.addWidget(_add_root_container, 4, 1)

        # Python 路径选择
        py_label = QtWidgets.QLabel("Python 路径：")
        py_label.setStyleSheet(lbl_style)
        py_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        py_label.setFixedWidth(100)

        py_show = QtWidgets.QLineEdit()
        py_show.setReadOnly(True)
        py_show.setStyleSheet(self.theme_manager.styles.input_style())
        py_show.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        py_show.setMinimumWidth(520)
        try:
            if hasattr(self.app, 'config'):
                from pathlib import Path as _P
                py_val = self.app.config.get('paths', {}).get('python_path') or ''
                if py_val:
                    py_path = _P(py_val)
                    # 只有当路径存在时才显示，否则显示"未设置"
                    if py_path.exists():
                        py_show.setText(str(py_path.resolve()))
                    else:
                        py_show.setText("未设置")
                else:
                    py_show.setText("未设置")
        except Exception:
            py_show.setText("未设置")

        py_btn = QtWidgets.QPushButton("选取")
        py_btn.setCursor(Qt.PointingHandCursor)
        py_btn.setStyleSheet(self.theme_manager.styles.primary_button_style())
        py_btn.setToolTip("选择 Python 可执行文件")
        py_btn.clicked.connect(lambda: self._choose_python(py_show))

        _add_py_container = QtWidgets.QWidget()
        _add_py_layout = QtWidgets.QHBoxLayout(_add_py_container)
        _add_py_layout.setContentsMargins(0, 0, 0, 0)
        _add_py_layout.setSpacing(10)
        _add_py_layout.addWidget(py_show)
        _add_py_layout.addWidget(py_btn)

        env_layout.addWidget(py_label, 5, 0)
        env_layout.addWidget(_add_py_container, 5, 1)
        try:
            self._py_show = py_show
        except Exception:
            pass

    def _build_version_section(self, layout):
        """构建版本与更新区块"""
        # 版本信息网格
        cur_grid = QtWidgets.QGridLayout()
        cur_grid.setSpacing(12)
        cur_grid.setContentsMargins(8, 4, 8, 6)
        layout.addLayout(cur_grid)

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
        ]

        for i, (title, src, ico) in enumerate(version_items):
            card = self._create_version_item(title, src or "获取中...", ico)
            r, cidx = divmod(i, 3)
            cur_grid.addWidget(card, r, cidx)

        for col in range(3):
            cur_grid.setColumnStretch(col, 1)

        opts_row = QtWidgets.QHBoxLayout()
        opts_row.setContentsMargins(0, 0, 0, 0)
        opts_row.setSpacing(12)

        lbl_style = f"color: {self.theme_manager.colors.get('label_dim')}; font: 10pt 'Microsoft YaHei UI';"

        lbl_st = QtWidgets.QLabel("升级策略:")
        lbl_st.setStyleSheet(lbl_style)

        cb_stable = QtWidgets.QCheckBox("仅更新到稳定版")
        try:
            cb_stable.setChecked(self.app.stable_only_var.get())
            cb_stable.toggled.connect(lambda c: (self.app.stable_only_var.set(c), self._save_config()))
        except Exception:
            pass

        cb_deps = QtWidgets.QCheckBox("自动更新依赖库")
        try:
            cb_deps.setChecked(self.app.auto_update_deps_var.get())
            cb_deps.toggled.connect(lambda c: (self.app.auto_update_deps_var.set(c), self._save_config()))
        except Exception:
            pass

        btn_update = QtWidgets.QPushButton("更 新")
        btn_update.setCursor(Qt.PointingHandCursor)
        btn_update.setStyleSheet(self.theme_manager.styles.primary_button_style())
        try:
            w1 = btn_update.sizeHint().width()
            btn_update.setText("更新中…")
            w2 = btn_update.sizeHint().width()
            btn_update.setText("更 新")
            btn_update.setMinimumWidth(max(w1, w2))
        except Exception:
            pass
        self._update_btn = btn_update
        try:
            btn_update.clicked.connect(self._on_update_clicked)
        except Exception:
            pass

        # 超时选择器
        lbl_timeout = QtWidgets.QLabel("超时:")
        lbl_timeout.setStyleSheet(lbl_style)

        self.timeout_combo = NoWheelComboBox()
        self.timeout_combo.addItems(["60秒", "120秒", "180秒", "300秒", "600秒"])
        self.timeout_combo.setFixedWidth(85)
        self.timeout_combo.setStyleSheet(self.theme_manager.styles.input_style())

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
        opts_row.addWidget(cb_stable)
        opts_row.addSpacing(12)
        opts_row.addWidget(cb_deps)
        opts_row.addSpacing(12)
        opts_row.addWidget(lbl_timeout)
        opts_row.addWidget(self.timeout_combo)
        opts_row.addStretch(1)
        opts_row.addWidget(btn_update)
        layout.addLayout(opts_row)

    def _on_update_clicked(self):
        """点击更新时，按钮显示“更新中…”，禁用并变灰，完成后恢复"""
        btn = getattr(self, "_update_btn", None)
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
        t.setStyleSheet(f"color: {self.theme_manager.colors.get('label_muted')}; font: bold 9pt \"Microsoft YaHei UI\"; background: transparent;")
        hb.addWidget(t)
        try:
            self._version_title_refs.append(t)
        except Exception:
            pass

        v_text = str(value_source.get() if hasattr(value_source, "get") else value_source)
        v = QtWidgets.QLabel(v_text)
        v.setStyleSheet(f"font: bold 10pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {self.theme_manager.colors.get('text')}; background: transparent;")
        hb.addWidget(v)

        if hasattr(value_source, "bind"):
            def _update_v(val, vv=v):
                vv.setText(str(val))
            value_source.bind(_update_v)
        try:
            self._version_value_refs.append(v)
        except Exception:
            pass

        return card

    def _build_quick_dir(self, layout):
        """构建快捷目录区块"""
        layout.setSpacing(6)
        layout.setContentsMargins(10, 4, 10, 4)
        buttons = [
            ("📂 根目录", self._open_root_dir),
            ("📝 ComfyUI日志", self._open_comfyui_log),
            ("🧰 启动器日志", self._open_launcher_log),
            ("🖼️ 输出目录", self._open_output_dir),
            ("📦 输入目录", self._open_input_dir),
            ("🧩 插件目录", self._open_nodes_dir),
            ("🎨 模型目录", self._open_models_dir),
        ]

        for text, callback in buttons:
            b = QtWidgets.QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(32)
            b.setStyleSheet(self.theme_manager.styles.secondary_button_style())
            b.clicked.connect(callback)
            layout.addWidget(b)
            try:
                self._quick_dir_buttons.append(b)
            except Exception:
                pass

        layout.addStretch(1)

    def _open_comfyui_log(self):
        """打开 ComfyUI 日志文件"""
        try:
            if hasattr(self.app, 'open_logs_dir'):
                self.app.open_logs_dir()
            else:
                from utils import paths as PATHS
                try:
                    root = PATHS.get_comfy_root(self.app.config.get("paths", {}))
                    from utils.ui_actions import open_file as _open_file
                    _open_file(self.app, PATHS.logs_file(root))
                except Exception:
                    pass
        except Exception:
            pass

    def _open_launcher_log(self):
        """打开启动器日志文件"""
        try:
            if hasattr(self.app, 'open_launcher_log'):
                self.app.open_launcher_log()
            else:
                from utils.ui_actions import open_launcher_log as _a
                _a(self.app)
        except Exception:
            pass

    def _get_primary_button_style(self):
        """获取主要按钮样式"""
        return self.theme_manager.styles.primary_button_style()

    def _save_config(self):
        """保存配置"""
        try:
            if hasattr(self.app, 'save_config'):
                self.app.save_config()
        except Exception:
            pass

    def _get_danger_button_style(self):
        return self.theme_manager.styles.button_style(primary=False, danger=True)

    def _on_toggle_launch(self):
        """切换启动状态"""
        if hasattr(self.app, 'services') and hasattr(self.app.services, 'process'):
            self.app.services.process.toggle()

    def _choose_root(self):
        """选择根目录"""
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择 ComfyUI 根目录", str(Path.cwd()))
        if d:
            # 验证选择的目录是否包含 ComfyUI/main.py
            comfy_path = Path(d) / "ComfyUI"
            if not (comfy_path.exists() and (comfy_path / "main.py").exists()):
                from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
                dlg = CustomConfirmDialog(
                    parent=self,
                    title="目录验证失败",
                    content=(
                        "选择的目录无效。\n\n"
                        f"根目录：{d}\n"
                        f"ComfyUI 目录：{comfy_path}\n\n"
                        "请确保选择的目录是包含 ComfyUI 文件夹的父目录，"
                        "且 ComfyUI 文件夹中存在 main.py 文件。"
                    ),
                    buttons=[{"text": "确定", "role": "primary"}],
                    default_index=0,
                    theme_manager=self.theme_manager
                )
                dlg.exec_()
                return  # 拒绝应用无效目录

            if hasattr(self.app, 'config'):
                self.app.config.setdefault('paths', {})['comfyui_root'] = d
                try:
                    # 保存配置并同步更新app.config引用
                    saved_config = self.app.services.config.save(self.app.config)
                    if saved_config is not None:
                        self.app.config = saved_config
                except Exception:
                    pass

            # Update UI display
            try:
                if hasattr(self, '_root_show'):
                    self._root_show.setText(d)
            except Exception:
                pass

            # 与旧版一致：联动解析并更新 Python 路径
            try:
                base = Path(d).resolve()
                python_embeded_dir = base / "python_embeded"
                python_exe_path = python_embeded_dir / "python.exe"
                if python_embeded_dir.exists() and python_exe_path.exists():
                    self.app.python_exec = str(python_exe_path.resolve())
                else:
                    comfy_path = (base / "ComfyUI").resolve()
                    try:
                        from utils import paths as PATHS
                        configured = self.app.config.get("paths", {}).get("python_path", "python_embeded/python.exe")
                        py = PATHS.resolve_python_exec(comfy_path, configured)
                        self.app.python_exec = str(py)
                    except Exception:
                        pass
                # 写入配置并更新显示
                try:
                    self.app.config.setdefault('paths', {})['python_path'] = self.app.python_exec
                    if hasattr(self.app, 'services') and hasattr(self.app.services, 'config'):
                        saved_config = self.app.services.config.save(self.app.config)
                        if saved_config is not None:
                            self.app.config = saved_config
                except Exception:
                    pass
                try:
                    if hasattr(self, "_py_show") and isinstance(self._py_show, QtWidgets.QLineEdit):
                        self._py_show.setText(self.app.python_exec)
                except Exception:
                    pass
            except Exception:
                pass
            if hasattr(self.app, 'get_version_info'):
                self.app.get_version_info("all")

    def _choose_python(self, py_show: QtWidgets.QLineEdit):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 Python 可执行文件", str(Path.cwd()), "可执行文件 (*.exe);;所有文件 (*.*)")
        if not p:
            return
        try:
            py_show.setText(p)
        except Exception:
            pass
        # 与旧版保持一致：更新 python_exec、配置并刷新版本信息
        try:
            self.app.python_exec = p
        except Exception:
            pass
        try:
            self.app.config.setdefault('paths', {})['python_path'] = p
            if hasattr(self.app, 'services') and hasattr(self.app.services, 'config'):
                saved_config = self.app.services.config.save(self.app.config)
                if saved_config is not None:
                    self.app.config = saved_config
        except Exception:
            pass
        try:
            if hasattr(self.app, 'get_version_info'):
                self.app.get_version_info("all")
        except Exception:
            pass

    def _open_root_dir(self):
        """打开根目录"""
        self._open_path(str(Path(self.app.config.get('paths', {}).get('comfyui_root', '.')).resolve()))

    def _open_logs_dir(self):
        """打开日志目录"""
        self._open_path(str(Path.cwd()))

    def _open_output_dir(self):
        """打开输出目录"""
        root = Path(self.app.config.get('paths', {}).get('comfyui_root', '.'))
        output = root / "ComfyUI" / "output"
        if output.exists():
            self._open_path(str(output))

    def _open_input_dir(self):
        """打开输入目录"""
        root = Path(self.app.config.get('paths', {}).get('comfyui_root', '.'))
        input_dir = root / "ComfyUI" / "input"
        if input_dir.exists():
            self._open_path(str(input_dir))

    def _open_nodes_dir(self):
        """打开插件目录"""
        root = Path(self.app.config.get('paths', {}).get('comfyui_root', '.'))
        nodes = root / "ComfyUI" / "custom_nodes"
        if nodes.exists():
            self._open_path(str(nodes))

    def _open_models_dir(self):
        """打开模型目录"""
        root = Path(self.app.config.get('paths', {}).get('comfyui_root', '.'))
        models = root / "ComfyUI" / "models"
        if models.exists():
            self._open_path(str(models))

    def _open_path(self, path_str):
        """打开路径"""
        try:
            import subprocess
            import platform
            path = Path(path_str)
            if platform.system() == "Windows":
                subprocess.Popen(['explorer', str(path)])
        except Exception:
            pass

    def update_theme(self, theme_styles=None):
        """更新主题"""
        super().update_theme(theme_styles)
        label_muted = self.theme_manager.colors.get('label_muted')
        text_color = self.theme_manager.colors.get('text')
        try:
            for ref in getattr(self, "_version_title_refs", []):
                ref.setStyleSheet(f"color: {label_muted}; font: bold 9pt \"Microsoft YaHei UI\"; background: transparent;")
            for ref in getattr(self, "_version_value_refs", []):
                ref.setStyleSheet(f"font: bold 10pt \"Segoe UI\", \"Microsoft YaHei UI\"; color: {text_color}; background: transparent;")
        except Exception:
            pass

        # 更新按钮样式
        if hasattr(self, 'btn_toggle'):
            self.btn_toggle.setStyleSheet(self._get_primary_button_style())

        # 更新样式组件
        for widget in self._styled_widgets:
            if hasattr(widget, 'update_theme'):
                widget.update_theme(self.theme_manager.styles)
        try:
            for b in getattr(self, "_quick_dir_buttons", []):
                b.setStyleSheet(self.theme_manager.styles.secondary_button_style())
        except Exception:
            pass

        try:
            for w in self.findChildren(QtWidgets.QLineEdit):
                w.setStyleSheet(self.theme_manager.styles.input_style())
            for w in self.findChildren(QtWidgets.QComboBox):
                w.setStyleSheet(self.theme_manager.styles.input_style())
        except Exception:
            pass
