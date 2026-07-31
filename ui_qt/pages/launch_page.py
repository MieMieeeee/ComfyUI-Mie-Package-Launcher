"""
启动页面
包含启动控制、环境配置、版本与更新、快捷目录等功能
"""

from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from .base_page import BasePage
from ui_qt.theme_styles import ThemeStyles
from ui_qt.pages.launch import LaunchControlsSection, EnvironmentSection, EnvironmentSelector, VersionSection


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

    def _on_env_switched(self, env_id):
        """环境下拉切换成功后的刷新槽。

        由 EnvironmentSelector.env_switched 信号触发。统一调 app 的
        refresh_after_env_switch，集中刷新所有依赖环境路径的页面（版本信息、
        版本页、模型页、插件页、日志页）。
        """
        try:
            if hasattr(self.app, 'refresh_after_env_switch'):
                self.app.refresh_after_env_switch()
        except Exception:
            pass

    def _goto_settings_env(self):
        """点"管理…"按钮 → 跳转到设置页的环境管理卡片。

        通过模拟点击侧边栏的 settings 导航按钮触发页面切换（复用现有的
        _select_tab 逻辑），然后刷新环境列表。
        """
        try:
            nav_map = getattr(self.app, "_nav_btn_map", None) or {}
            btn = nav_map.get("settings")
            if btn is not None:
                btn.click()
        except Exception:
            pass
        # 切到设置页后，刷新环境列表（可能在别处被改动过）
        try:
            settings_page = getattr(self.app, "_new_pages", {}).get("settings")
            if settings_page is not None:
                mgr = getattr(settings_page, "env_manager_section", None)
                if mgr is not None:
                    mgr.reload()
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

        # ============== 环境选择器（多环境支持） ==============
        # 放在最顶部：用户先选环境，再启动。切换环境前会检查是否在跑。
        self.environment_selector = EnvironmentSelector(
            app_context=self.app,
            theme_manager=self.theme_manager,
        )
        layout.addWidget(self.environment_selector)

        # ============== 启动控制区块 ==============
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(15)
        layout.addLayout(top_row)

        # 右侧按钮容器
        right_container = QtWidgets.QWidget()
        right_container.setFixedWidth(200)
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
        btn_faq = QtWidgets.QPushButton("常见问题")
        btn_faq.setCursor(Qt.PointingHandCursor)
        btn_faq.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        btn_faq.setStyleSheet(self._get_primary_button_style())
        btn_faq.clicked.connect(lambda _: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://dcn8q5lcfe3s.feishu.cn/wiki/ELY2wwPgciIA56kS3eBciY4RnPd")))
        btn_faq.setToolTip("查看常见问题解决方案")
        self.btn_faq = btn_faq

        # 打包日志按钮（报bug用）
        btn_package = QtWidgets.QPushButton("打包日志")
        btn_package.setCursor(Qt.PointingHandCursor)
        btn_package.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        btn_package.setStyleSheet(self._get_primary_button_style())
        btn_package.clicked.connect(self._on_package_logs)
        btn_package.setToolTip("将启动器和 ComfyUI 日志打包成 zip，方便报bug时附带")
        self.btn_package = btn_package

        right_layout.addWidget(btn_toggle, 4)

        # 底部：常见问题 + 打包日志 横排
        bottom_row = QtWidgets.QWidget()
        bottom_layout = QtWidgets.QHBoxLayout(bottom_row)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(4)
        btn_faq.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        btn_package.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        bottom_layout.addWidget(btn_faq)
        bottom_layout.addWidget(btn_package)
        right_layout.addWidget(bottom_row, 1)

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

        # 多环境：下拉切换环境后，刷新环境配置区块的路径显示 + 版本信息
        self.environment_selector.env_switched.connect(self._on_env_switched)
        # 多环境：点"管理…"按钮跳转到设置页的环境管理卡片
        self.environment_selector.manage_requested.connect(self._goto_settings_env)
        # 多环境：用户在环境配置区块改了根目录/python 路径 → 刷新顶部摘要
        self.environment_section.paths_changed.connect(
            self.environment_selector._refresh_path_summary
        )

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

        # 底部留白：用固定间距而非 addStretch(1)。之前用 stretch(1) 会把
        # 快捷目录顶到视口外（加环境选择器后页面更高了）。固定间距保证
        # 快捷目录始终在首屏可见范围内，超出部分由外层 ScrollArea 滚动。
        layout.addSpacing(8)

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
                    # 多环境支持：读激活环境的路径
                    _paths = self.app.get_active_paths() if hasattr(self.app, "get_active_paths") \
                        else self.app.config.get("paths", {})
                    root = PATHS.get_comfy_root(_paths)
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

    def _on_package_logs(self):
        """打包启动器和 ComfyUI 日志，弹窗让用户选保存位置。"""
        import os
        from utils.ui_actions import package_logs
        from ui_qt.widgets.dialog_helper import DialogHelper

        result = package_logs(self.app, parent=self)
        if result is None:
            return  # 用户取消
        if result is False:
            DialogHelper.show_error(
                self,
                '打包失败',
                '日志打包失败，请检查写入权限或重试。',
            )
            return

        try:
            os.startfile(str(result.parent))
        except Exception:
            pass
        DialogHelper.show_info(
            self,
            '日志已打包',
            f"已保存到\n{result}\n\n所在文件夹已打开",
        )

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
                # 多环境支持：写回当前激活环境的 comfyui_root
                try:
                    from config.migrations import update_active_env
                    update_active_env(self.app.config, comfyui_root=d)
                except Exception:
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
                        # 多环境支持：兜底用激活环境的 python_path
                        _ap = self.app.get_active_paths() if hasattr(self.app, "get_active_paths") \
                            else self.app.config.get("paths", {})
                        configured = _ap.get("python_path", "python_embeded/python.exe")
                        py = PATHS.resolve_python_exec(comfy_path, configured)
                        self.app.python_exec = str(py)
                    except Exception:
                        pass
                # 写入配置并更新显示（多环境：写激活环境的 python_path）
                try:
                    from config.migrations import update_active_env
                    update_active_env(self.app.config, python_path=self.app.python_exec)
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
            # 多环境支持：写激活环境的 python_path
            from config.migrations import update_active_env
            update_active_env(self.app.config, python_path=p)
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

    def _active_root(self):
        """多环境支持：取激活环境的 ComfyUI 根目录。

        必须走 ``app.get_active_paths()`` 而不是直接读 ``config['paths']`` ——
        后者是老 schema 的全局回退段，环境切换后不会跟着 ``active_env_id`` 变，
        会导致快捷目录按钮始终指向原始根目录。
        """
        _paths = self.app.get_active_paths() if hasattr(self.app, "get_active_paths") \
            else self.app.config.get("paths", {})
        return Path(_paths.get('comfyui_root', '.'))

    def _open_root_dir(self):
        """打开根目录"""
        self._open_path(str(self._active_root().resolve()))

    def _open_logs_dir(self):
        """打开日志目录"""
        self._open_path(str(Path.cwd()))

    def _open_output_dir(self):
        """打开输出目录"""
        output = self._active_root() / "ComfyUI" / "output"
        if output.exists():
            self._open_path(str(output))

    def _open_input_dir(self):
        """打开输入目录"""
        input_dir = self._active_root() / "ComfyUI" / "input"
        if input_dir.exists():
            self._open_path(str(input_dir))

    def _open_nodes_dir(self):
        """打开插件目录"""
        nodes = self._active_root() / "ComfyUI" / "custom_nodes"
        if nodes.exists():
            self._open_path(str(nodes))

    def _open_models_dir(self):
        """打开模型目录"""
        models = self._active_root() / "ComfyUI" / "models"
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
        wf = self._active_root() / "ComfyUI" / "user" / "default" / "workflows"
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
