"""
启动页面
包含启动控制、环境配置、版本与更新、快捷目录等功能
"""

from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from .base_page import BasePage
from ui_qt.theme_styles import ThemeStyles
from ui_qt.pages.launch import LaunchControlsSection, EnvironmentSection, VersionSection


class LaunchPage(BasePage):
    """启动页面"""

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self.theme_manager = theme_manager
        self._setup_ui()
        # 注意：refresh_status 不在这里调用，而是在 attach 之后由 QtApp 延迟调用

    def _update_button_state(self):
        """与旧版兼容的占位方法：实际状态由 ProcessManager 通过 BigBtnProxy 控制"""
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

        # 右侧按钮容器
        right_container = QtWidgets.QWidget()
        right_container.setFixedWidth(150)
        right_layout = QtWidgets.QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # 启动大按钮（使用 QPushButton + 内部 QLabel 实现双行不同字号）
        btn_toggle = QtWidgets.QPushButton()
        btn_toggle.setCursor(Qt.PointingHandCursor)
        btn_toggle.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        btn_toggle.setStyleSheet(self._get_primary_button_style())
        btn_toggle.clicked.connect(self._on_toggle_launch)
        btn_toggle.setToolTip("启动或停止ComfyUI服务")
        self.btn_toggle = btn_toggle

        # 按钮内部布局：两个标签覆盖在按钮上，实现不同字号的双行显示
        btn_inner = QtWidgets.QVBoxLayout(btn_toggle)
        btn_inner.setContentsMargins(4, 4, 4, 4)
        btn_inner.setSpacing(2)

        self._btn_status_label = QtWidgets.QLabel("🚀 一键启动")
        self._btn_status_label.setAlignment(Qt.AlignCenter)
        self._btn_status_label.setStyleSheet(
            'font: bold 12pt "Microsoft YaHei UI"; color: #FFFFFF; background: transparent;'
        )

        self._btn_action_label = QtWidgets.QLabel()
        self._btn_action_label.setAlignment(Qt.AlignCenter)
        self._btn_action_label.setStyleSheet(
            'font: 8pt "Microsoft YaHei UI"; color: rgba(255,255,255,170); background: transparent;'
        )
        self._btn_action_label.hide()

        btn_inner.addStretch(1)
        btn_inner.addWidget(self._btn_status_label)
        btn_inner.addWidget(self._btn_action_label)
        btn_inner.addStretch(1)
        # 初始化按钮状态
        self._update_button_state()

        # 常见问题按钮
        btn_faq = QtWidgets.QPushButton("查看常见问题")
        btn_faq.setCursor(Qt.PointingHandCursor)
        btn_faq.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        btn_faq.setStyleSheet(self._get_primary_button_style())
        btn_faq.clicked.connect(lambda _: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://dcn8q5lcfe3s.feishu.cn/wiki/ELY2wwPgciIA56kS3eBciY4RnPd")))
        btn_faq.setToolTip("查看常见问题解决方案")
        self.btn_faq = btn_faq

        right_layout.addWidget(btn_toggle, 4)
        right_layout.addWidget(btn_faq, 1)

        # 启动控制区块
        self.launch_controls_section = LaunchControlsSection(
            app_context=self.app,
            theme_manager=self.theme_manager
        )
        top_row.addWidget(self.launch_controls_section, 1)
        top_row.addWidget(right_container, 0)

        # 让右侧按钮区域高度与启动控制区域保持一致
        try:
            from PyQt5.QtCore import QTimer
            def _sync_btn_height():
                try:
                    right_container.setFixedHeight(form_group.sizeHint().height())
                except Exception:
                    pass
            QTimer.singleShot(0, _sync_btn_height)
        except Exception:
            pass

        # ============== 环境配置区块 ==============
        self.environment_section = EnvironmentSection(
            app_context=self.app,
            theme_manager=self.theme_manager
        )
        layout.addWidget(self.environment_section)

        # ============== 版本与更新区块 ==============
        self.version_section = VersionSection(
            app_context=self.app,
            theme_manager=self.theme_manager
        )
        layout.addWidget(self.version_section)

        # ============== 快捷目录区块 ==============
        quick_group = QtWidgets.QGroupBox("快捷目录")
        quick_layout = QtWidgets.QHBoxLayout(quick_group)
        layout.addWidget(quick_group)

        self._build_quick_dir(quick_layout)

        # 将多余高度留给页面底部的弹性空白，而不是拉伸"版本与更新"等区块
        layout.addStretch(1)

        # 存储需要主题更新的组件
        self._styled_widgets = [self.launch_controls_section, self.environment_section, self.version_section]
        if hasattr(self.app, "_styled_widgets"):
            self.app._theme_widgets.extend(self._styled_widgets)
        try:
            self._quick_dir_buttons = []
        except Exception:
            pass

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
            ("🧾 工作流目录", self._open_workflows_dir),
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

    def _open_workflows_dir(self):
        """打开工作流目录"""
        try:
            from utils.ui_actions import open_workflows_dir as _a
            _a(self.app)
            return
        except Exception:
            pass
        root = Path(self.app.config.get('paths', {}).get('comfyui_root', '.'))
        wf = root / "ComfyUI" / "user" / "default" / "workflows"
        if wf.exists():
            self._open_path(str(wf))

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

    def _on_theme_changed(self, theme_styles):
        """主题变更回调"""
        self.update_theme(theme_styles)

    def update_theme(self, theme_styles=None):
        """更新主题"""
        super().update_theme(theme_styles)

        # 确保 styles 对象是最新的
        if theme_styles is None:
             theme_styles = self.theme_manager.styles

        # 更新按钮
        if hasattr(self, "btn_toggle"):
            self.btn_toggle.setStyleSheet(theme_styles.primary_button_style())
        if hasattr(self, "btn_faq"):
            self.btn_faq.setStyleSheet(theme_styles.primary_button_style())
        if hasattr(self, "_quick_dir_buttons"):
            for btn in self._quick_dir_buttons:
                btn.setStyleSheet(theme_styles.secondary_button_style())

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
