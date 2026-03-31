"""
环境配置区块
从 launch_page.py 提取的 EnvironmentSection 类
"""

from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt
from ui_qt.widgets.custom import NoWheelComboBox


class EnvironmentSection(QtWidgets.QWidget):
    """
    环境配置区块控件
    
    包含：HF镜像源、GitHub代理、PyPI代理、根目录选择、Python路径选择
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
        form_group = QtWidgets.QGroupBox("环境配置")
        form_layout = QtWidgets.QGridLayout(form_group)
        form_layout.setColumnMinimumWidth(0, 100)
        form_layout.setColumnStretch(1, 3)
        form_layout.setHorizontalSpacing(15)
        form_layout.setVerticalSpacing(12)
        form_layout.setContentsMargins(15, 15, 15, 15)

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

        # ============== HF 镜像 ==============
        env_hf_combo = NoWheelComboBox()
        env_hf_combo.addItems(["不使用", "hf-mirror", "自定义"])
        env_hf_combo.setMinimumWidth(120)
        env_hf_combo.setStyleSheet(self._get_input_style())

        env_hf_entry = QtWidgets.QLineEdit()
        env_hf_entry.setPlaceholderText("请输入镜像地址...")
        env_hf_entry.setStyleSheet(self._get_input_style())
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

        form_layout.addWidget(hf_label, 0, 0)
        form_layout.addWidget(_add_hf_container, 0, 1)

        # ============== GitHub 代理 ==============
        env_gh_combo = NoWheelComboBox()
        env_gh_combo.addItems(["不使用", "gh-proxy", "自定义"])
        env_gh_combo.setMinimumWidth(120)
        env_gh_combo.setStyleSheet(self._get_input_style())

        env_gh_entry = QtWidgets.QLineEdit()
        env_gh_entry.setPlaceholderText("请输入代理地址...")
        env_gh_entry.setStyleSheet(self._get_input_style())
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

        form_layout.addWidget(gh_label, 1, 0)
        form_layout.addWidget(_add_gh_container, 1, 1)

        # ============== PyPI 代理 ==============
        env_pypi_combo = NoWheelComboBox()
        env_pypi_combo.addItems(["不使用", "阿里云", "自定义"])
        env_pypi_combo.setMinimumWidth(120)
        env_pypi_combo.setStyleSheet(self._get_input_style())

        env_pypi_entry = QtWidgets.QLineEdit()
        env_pypi_entry.setPlaceholderText("请输入 PyPI 源地址...")
        env_pypi_entry.setStyleSheet(self._get_input_style())
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

        form_layout.addWidget(pypi_label, 2, 0)
        form_layout.addWidget(_add_pypi_container, 2, 1)

        # ============== 分割线 ==============
        div_line = QtWidgets.QFrame()
        div_line.setFrameShape(QtWidgets.QFrame.HLine)
        div_line.setFrameShadow(QtWidgets.QFrame.Plain)
        div_line.setStyleSheet(self._get_divider_style())
        form_layout.addWidget(div_line, 3, 0, 1, 2)

        # ============== 根目录 ==============
        root_show = QtWidgets.QLineEdit()
        root_show.setReadOnly(True)
        root_show.setStyleSheet(self._get_input_style())
        root_show.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        root_show.setMinimumWidth(520)
        if hasattr(self.app, 'config'):
            root_show.setText(str(Path(self.app.config.get('paths', {}).get('comfyui_root') or '.')))

        root_btn = QtWidgets.QPushButton("选择")
        root_btn.setCursor(Qt.PointingHandCursor)
        root_btn.setStyleSheet(self._get_primary_button_style())
        root_btn.clicked.connect(self._choose_root)
        root_btn.setToolTip("选择ComfyUI安装根目录")

        _add_root_container = QtWidgets.QWidget()
        _add_root_layout = QtWidgets.QHBoxLayout(_add_root_container)
        _add_root_layout.setContentsMargins(0, 0, 0, 0)
        _add_root_layout.setSpacing(10)
        _add_root_layout.addWidget(root_show)
        _add_root_layout.addWidget(root_btn)
        self._root_show = root_show

        root_label = QtWidgets.QLabel("根目录：")
        root_label.setStyleSheet(lbl_style)
        root_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        root_label.setFixedWidth(100)

        form_layout.addWidget(root_label, 4, 0)
        form_layout.addWidget(_add_root_container, 4, 1)

        # ============== Python 路径选择 ==============
        py_label = QtWidgets.QLabel("Python 路径：")
        py_label.setStyleSheet(lbl_style)
        py_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        py_label.setFixedWidth(100)

        py_show = QtWidgets.QLineEdit()
        py_show.setReadOnly(True)
        py_show.setStyleSheet(self._get_input_style())
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

        py_btn = QtWidgets.QPushButton("选择")
        py_btn.setCursor(Qt.PointingHandCursor)
        py_btn.setStyleSheet(self._get_primary_button_style())
        py_btn.setToolTip("选择 Python 可执行文件")
        py_btn.clicked.connect(lambda: self._choose_python(py_show))

        _add_py_container = QtWidgets.QWidget()
        _add_py_layout = QtWidgets.QHBoxLayout(_add_py_container)
        _add_py_layout.setContentsMargins(0, 0, 0, 0)
        _add_py_layout.setSpacing(10)
        _add_py_layout.addWidget(py_show)
        _add_py_layout.addWidget(py_btn)

        self._py_show = py_show

        form_layout.addWidget(py_label, 5, 0)
        form_layout.addWidget(_add_py_container, 5, 1)

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
