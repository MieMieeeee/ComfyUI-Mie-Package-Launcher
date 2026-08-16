"""
环境配置区块
从 launch_page.py 提取的 EnvironmentSection 类
"""

from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, pyqtSignal
from ui_qt.widgets.custom import NoWheelComboBox


class EnvironmentSection(QtWidgets.QWidget):
    """
    环境配置区块控件

    包含：HF镜像源、GitHub代理、PyPI代理、根目录选择、Python路径选择
    """

    # 用户在本区块改了根目录 / python 路径后发出，供 LaunchPage 同步刷新
    # 顶部环境选择器的路径摘要。
    paths_changed = pyqtSignal()

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
        lbl_style = f"color: {self._get_label_color()}; font-weight: bold;"

        # 主布局
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 表单组
        form_group = QtWidgets.QGroupBox("环境配置")
        form_layout = QtWidgets.QGridLayout(form_group)
        form_layout.setColumnMinimumWidth(0, 100)
        form_layout.setColumnStretch(1, 3)
        form_layout.setHorizontalSpacing(15)
        form_layout.setVerticalSpacing(12)
        form_layout.setContentsMargins(15, 15, 15, 15)

        main_layout.addWidget(form_group)

        # 阴影效果：DPI 变化时需重建（见 _apply_shadow / update_theme）。
        self._form_group = form_group
        self._apply_shadow()

        # ============== HF 镜像 ==============
        env_hf_combo = NoWheelComboBox()
        env_hf_combo.addItems(["不使用", "hf-mirror", "自定义"])
        env_hf_combo.setMinimumWidth(self._px(120))
        env_hf_combo.setStyleSheet(self._get_input_style())

        env_hf_entry = QtWidgets.QLineEdit()
        env_hf_entry.setPlaceholderText("请输入镜像地址...")
        env_hf_entry.setStyleSheet(self._get_input_style())
        env_hf_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        env_hf_entry.setMinimumWidth(self._px(520))

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
        hf_label.setFixedWidth(self._px(100))

        form_layout.addWidget(hf_label, 0, 0)
        form_layout.addWidget(_add_hf_container, 0, 1)

        # ============== GitHub 代理 ==============
        env_gh_combo = NoWheelComboBox()
        env_gh_combo.addItems(["不使用", "gh-proxy", "自定义"])
        env_gh_combo.setMinimumWidth(self._px(120))
        env_gh_combo.setStyleSheet(self._get_input_style())

        env_gh_entry = QtWidgets.QLineEdit()
        env_gh_entry.setPlaceholderText("请输入代理地址...")
        env_gh_entry.setStyleSheet(self._get_input_style())
        env_gh_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        env_gh_entry.setMinimumWidth(self._px(520))

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
        gh_label.setFixedWidth(self._px(100))

        form_layout.addWidget(gh_label, 1, 0)
        form_layout.addWidget(_add_gh_container, 1, 1)

        # ============== PyPI 代理 ==============
        # Built-in PyPI mirror presets. ``text`` is what the combo box shows
        # to the user; ``mode`` is the value persisted in config; ``url`` is
        # what gets written to pip.ini / passed to ``pip -i``. Keep these in
        # sync with ``utils.net.get_pypi_index_url_for_mode`` and the
        # ``_pypi_mode_ui_text`` helper in ``qt_app.py``.
        _pypi_builtin_options = [
            ("阿里云", "aliyun", "https://mirrors.aliyun.com/pypi/simple/"),
            ("清华", "tsinghua", "https://pypi.tuna.tsinghua.edu.cn/simple/"),
            ("华为云", "huaweicloud", "https://repo.huaweicloud.com/repository/pypi/simple/"),
        ]
        _pypi_builtin_texts = [t for (t, _m, _u) in _pypi_builtin_options]
        env_pypi_combo = NoWheelComboBox()
        env_pypi_combo.addItems(["不使用"] + _pypi_builtin_texts + ["自定义"])
        env_pypi_combo.setMinimumWidth(self._px(120))
        env_pypi_combo.setStyleSheet(self._get_input_style())

        env_pypi_entry = QtWidgets.QLineEdit()
        env_pypi_entry.setPlaceholderText("请输入 PyPI 源地址...")
        env_pypi_entry.setStyleSheet(self._get_input_style())
        env_pypi_entry.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        env_pypi_entry.setMinimumWidth(self._px(520))

        if hasattr(self.app, 'pypi_proxy_mode_ui'):
            env_pypi_combo.setCurrentText(self.app.pypi_proxy_mode_ui.get())
        if hasattr(self.app, 'pypi_proxy_url'):
            env_pypi_entry.setText(self.app.pypi_proxy_url.get())

        def _env_pypi_change(text):
            is_custom = (text == "自定义")
            is_none = (text == "不使用")
            env_pypi_entry.setReadOnly(not is_custom)
            env_pypi_entry.setVisible(not is_none)

            # Resolve the new text -> (mode, url). All built-in mirrors are
            # read-only; only "自定义" lets the user type a URL.
            builtin = next(
                (item for item in _pypi_builtin_options if item[0] == text),
                None,
            )
            if is_none:
                mode = "none"
            elif builtin is not None:
                mode = builtin[1]
            else:
                mode = "custom"

            if builtin is not None:
                url = builtin[2]
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
        pypi_label.setFixedWidth(self._px(100))

        form_layout.addWidget(pypi_label, 2, 0)
        form_layout.addWidget(_add_pypi_container, 2, 1)

        # 注：根目录 / Python 路径选择已移除 —— 它们属于「环境」定义，
        # 现在由顶部环境栏（EnvironmentSelector）的路径摘要 + 管理弹窗统一展示和编辑，
        # 不再在此重复。代理设置（HF/GitHub/PyPI）保留。

        # DPI 相关尺寸：DPI 变化时需重算（见 _reapply_dpi_sizes / update_theme）。
        self._dpi_sized_widgets = [
            (env_hf_combo, "min", 120), (env_gh_combo, "min", 120), (env_pypi_combo, "min", 120),
            (env_hf_entry, "min", 520), (env_gh_entry, "min", 520), (env_pypi_entry, "min", 520),
            (hf_label, "fixed", 100), (gh_label, "fixed", 100), (pypi_label, "fixed", 100),
        ]

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

    def _get_divider_style(self):
        """获取分割线样式"""
        try:
            if self.theme_manager and hasattr(self.theme_manager, 'styles'):
                return self.theme_manager.styles.divider_style()
        except Exception:
            pass
        return "QFrame { border: none; border-top: 1px solid #4B5563; margin: 8px 0; }"

    def _save_config(self):
        """保存配置"""
        try:
            if hasattr(self.app, 'save_config'):
                self.app.save_config()
        except Exception:
            pass

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
                # 多环境支持：写回当前激活环境的 comfyui_root（不污染老 paths 段）
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
            # 通知顶部环境选择器刷新路径摘要
            self.paths_changed.emit()

    def _choose_python(self, py_show: QtWidgets.QLineEdit):
        """选择 Python 可执行文件"""
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
        # 通知顶部环境选择器刷新路径摘要
        self.paths_changed.emit()

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
        """重算所有用 _px() 设定的 DPI 相关尺寸（DPI 变化时调用）。"""
        for w, kind, base in getattr(self, "_dpi_sized_widgets", []):
            try:
                if kind == "min":
                    w.setMinimumWidth(self._px(base))
                elif kind == "fixed":
                    w.setFixedWidth(self._px(base))
            except Exception:
                pass

    def update_theme(self, theme_styles=None):
        """更新主题"""
        # 重新设置标签样式
        lbl_style = f"color: {self._get_label_color()}; font-weight: bold;"
        
        # 找到所有 QLabel 并更新样式（标签，不含组标题）
        for label in self.findChildren(QtWidgets.QLabel):
            # 跳过 GroupBox 的标题
            if label.parent() and isinstance(label.parent(), QtWidgets.QGroupBox):
                parent_title = label.parent().title()
                if parent_title == "环境配置" and label.text() in ["HF 镜像源：", "GitHub 代理：", "PyPI 代理：", "根目录：", "Python 路径："]:
                    label.setStyleSheet(lbl_style)
        
        # 更新输入框样式
        input_style = self._get_input_style()
        for widget in self.findChildren((QtWidgets.QLineEdit, QtWidgets.QComboBox, QtWidgets.QPushButton)):
            try:
                widget.setStyleSheet(input_style)
            except Exception:
                pass
        
        # 更新按钮样式
        primary_style = self._get_primary_button_style()
        for btn in self.findChildren(QtWidgets.QPushButton):
            try:
                btn.setStyleSheet(primary_style)
            except Exception:
                pass

        # DPI 变化时重算尺寸 + 重建阴影（消除 QGraphicsDropShadowEffect 缓存残影）
        self._reapply_dpi_sizes()
        self._apply_shadow()
