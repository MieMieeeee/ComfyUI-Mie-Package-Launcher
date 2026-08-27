"""
启动器更新对话框
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from ui_qt.theme_manager import ThemeManager
from ui_qt.widgets.frameless_draggable_dialog import FramelessDraggableDialog


class UpdateDialog(FramelessDraggableDialog):
    """启动器更新对话框"""

    # 信号：请求下载
    downloadRequested = QtCore.pyqtSignal()
    # 信号：请求稍后提醒
    laterRequested = QtCore.pyqtSignal()

    def __init__(self, parent=None, update_info: dict = None, theme_manager=None):
        # 默认 modal=True, window_type=Qt.Dialog，flags / 透明背景 / 拖拽 都在基类
        super().__init__(parent=parent)
        self.theme_manager = theme_manager
        self._update_info = update_info or {}
        # DPI 缩放 helper
        _styles = theme_manager.styles if theme_manager else None
        _px = _styles._px if _styles else (lambda b: b)
        _pt = _styles._pt if _styles else (lambda b: b)

        # UI Setup
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.container = QtWidgets.QFrame()
        self.container.setObjectName("UpdateContainer")

        # 默认样式
        bg = "#1F2937"
        border = "#374151"
        text = "#E5E7EB"
        title_color = "#F3F4F6"
        btn_bg = "#374151"
        btn_hover = "#4B5563"
        accent = "#6366F1"
        accent_hover = "#818CF8"
        badge_bg = "#374151"
        badge_text = "#9CA3AF"

        if self.theme_manager:
            c = self.theme_manager.colors
            bg = c.get('content_bg', bg)
            border = c.get('group_border', border)
            text = c.get('text', text)
            title_color = c.get('label', title_color)
            btn_bg = c.get('btn_secondary_bg', btn_bg)
            btn_hover = c.get('btn_ghost_bg', btn_hover)
            accent = c.get('btn_primary_bg', accent)
            accent_hover = c.get('btn_primary_hover', accent_hover)
            badge_bg = c.get('badge_bg', badge_bg)
            badge_text = c.get('badge_text', badge_text)

        self.container.setStyleSheet(f"""
            QFrame#UpdateContainer {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {_px(16)}px;
            }}
            QLabel {{
                background: transparent;
            }}
            QPushButton {{
                background-color: {btn_bg};
                color: {text};
                border: none;
                border-radius: {_px(8)}px;
                padding: {_px(10)}px {_px(20)}px;
                font: bold {_pt(10)}pt "Microsoft YaHei UI";
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
            }}
            QPushButton#PrimaryBtn {{
                background-color: {accent};
                color: #FFFFFF;
            }}
            QPushButton#PrimaryBtn:hover {{
                background-color: {accent_hover};
            }}
            QPushButton:disabled {{
                background-color: {btn_bg};
                color: {badge_text};
            }}
        """)

        inner_layout = QtWidgets.QVBoxLayout(self.container)
        inner_layout.setContentsMargins(24, 24, 24, 24)
        inner_layout.setSpacing(16)

        # 标题
        self.lbl_title = QtWidgets.QLabel("发现新版本")
        self.lbl_title.setStyleSheet(f"font: bold {_pt(16)}pt 'Microsoft YaHei UI'; color: {title_color};")
        self.lbl_title.setAlignment(QtCore.Qt.AlignCenter)
        inner_layout.addWidget(self.lbl_title)

        # 版本信息
        current_ver = self._update_info.get("current", "?")
        latest_ver = self._update_info.get("latest", "?")
        release_date = self._update_info.get("release_date", "")

        version_widget = QtWidgets.QWidget()
        version_layout = QtWidgets.QHBoxLayout(version_widget)
        version_layout.setContentsMargins(0, 0, 0, 0)
        version_layout.setSpacing(_px(8))

        self.current_label = QtWidgets.QLabel(f"当前: {current_ver}")
        self.current_label.setStyleSheet(f"color: {badge_text}; font: {_pt(10)}pt 'Microsoft YaHei UI';")

        self.arrow_label = QtWidgets.QLabel("→")
        self.arrow_label.setStyleSheet(f"color: {text}; font: {_pt(10)}pt 'Microsoft YaHei UI';")

        self.latest_label = QtWidgets.QLabel(f"最新: {latest_ver}")
        self.latest_label.setStyleSheet(f"color: {accent}; font: bold {_pt(10)}pt 'Microsoft YaHei UI';")

        version_layout.addStretch()
        version_layout.addWidget(self.current_label)
        version_layout.addWidget(self.arrow_label)
        version_layout.addWidget(self.latest_label)
        self.date_label = None
        if release_date:
            self.date_label = QtWidgets.QLabel(f"  ({release_date})")
            self.date_label.setStyleSheet(f"color: {badge_text}; font: {_pt(9)}pt 'Microsoft YaHei UI';")
            version_layout.addWidget(self.date_label)
        version_layout.addStretch()

        inner_layout.addWidget(version_widget)

        self.changelog_label = None

        # 更新日志
        changelog = self._update_info.get("changelog", "")
        if changelog:
            self.changelog_label = QtWidgets.QLabel("更新日志")
            self.changelog_label.setStyleSheet(f"color: {badge_text}; font: {_pt(9)}pt 'Microsoft YaHei UI';")
            inner_layout.addWidget(self.changelog_label)

            self.changelog_edit = QtWidgets.QTextEdit()
            self.changelog_edit.setReadOnly(True)
            self.changelog_edit.setPlainText(changelog)
            self.changelog_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: rgba(0,0,0,0.2);
                    color: {text};
                    border: 1px solid {border};
                    border-radius: {_px(8)}px;
                    padding: {_px(10)}px;
                    font: {_pt(9)}pt "Microsoft YaHei UI";
                }}
            """)
            self.changelog_edit.setFixedHeight(_px(150))
            inner_layout.addWidget(self.changelog_edit)

        # 进度区域（初始隐藏）
        self.progress_widget = QtWidgets.QWidget()
        progress_layout = QtWidgets.QVBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)

        self.lbl_status = QtWidgets.QLabel("准备下载...")
        self.lbl_status.setStyleSheet(f"color: {text}; font: {_pt(10)}pt 'Microsoft YaHei UI';")
        self.lbl_status.setAlignment(QtCore.Qt.AlignCenter)
        progress_layout.addWidget(self.lbl_status)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedHeight(_px(6))
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: rgba(0,0,0,0.2);
                border-radius: {_px(3)}px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {accent};
                border-radius: {_px(3)}px;
            }}
        """)
        progress_layout.addWidget(self.progress_bar)

        self.progress_widget.setVisible(False)
        inner_layout.addWidget(self.progress_widget)

        # 按钮区域
        self.btn_layout = QtWidgets.QHBoxLayout()
        self.btn_layout.setSpacing(12)

        # issue 8（无障碍）：btn_later 从 QLabel 改 QPushButton，Tab 可聚焦 + Space/Enter 触发
        self.btn_later = QtWidgets.QPushButton("稍后提醒")
        self.btn_later.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_later.setFlat(True)  # 视觉上仍像标签，无边框背景
        self.btn_later.clicked.connect(self._on_later)

        self.btn_update = QtWidgets.QPushButton("立即更新")
        self.btn_update.setObjectName("PrimaryBtn")
        self.btn_update.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_update.clicked.connect(self._on_update)

        self.btn_layout.addStretch()
        self.btn_layout.addWidget(self.btn_later)
        self.btn_layout.addWidget(self.btn_update)
        self.btn_layout.addStretch()

        inner_layout.addLayout(self.btn_layout)

        layout.addWidget(self.container)

        self.setFixedWidth(_px(480))
        self.adjustSize()

        # 注册主题切换监听（issue 6：切深/浅主题时 UpdateDialog 颜色刷新）
        if self.theme_manager:
            try:
                # ThemeManager 用 _theme_listeners + register_listener（自定义）
                # 不是 pyqtSignal，所以 theme_changed.connect 不可用。
                self.theme_manager.register_listener(self.update_theme)
            except AttributeError:
                pass  # 老 theme_manager 没 register_listener，忽略

    def update_theme(self, theme_styles=None):
        """重新应用主题样式（theme_changed 信号触发）。

        重构自原 __init__ 内的颜色 / QSS 块：构造时一次性取色导致切主题后颜色冻结，
        违反 AGENTS.md 主题规范。

        Args:
            theme_styles: 可选 ThemeStyles 实例；不传则用 self.theme_manager.styles。
        """
        if not self.theme_manager:
            return  # 调试场景无 theme_manager，跳过刷新
        styles = theme_styles or self.theme_manager.styles
        try:
            _px = styles._px
            _pt = styles._pt
        except AttributeError:
            _px = lambda b: b
            _pt = lambda b: b
        c = self.theme_manager.colors
        bg = c.get("content_bg", "#1F2937")
        border = c.get("group_border", "#374151")
        text = c.get("text", "#E5E7EB")
        btn_bg = c.get("btn_secondary_bg", "#374151")
        btn_hover = c.get("btn_ghost_bg", "#4B5563")
        accent = c.get("btn_primary_bg", "#6366F1")
        accent_hover = c.get("btn_primary_hover", "#818CF8")
        badge_text = c.get("badge_text", "#9CA3AF")
        # container + btn_update（#PrimaryBtn 在 container QSS 里覆盖）
        self.container.setStyleSheet(
            "QFrame#UpdateContainer { background-color: " + bg + "; border: 1px solid " + border + "; border-radius: " + str(_px(16)) + "px; }"
            + " QLabel { background: transparent; }"
            + " QPushButton { background-color: " + btn_bg + "; color: " + text + "; border: none; border-radius: " + str(_px(8)) + "px; padding: " + str(_px(10)) + "px " + str(_px(20)) + "px; font: bold " + str(_pt(10)) + "pt \"Microsoft YaHei UI\"; }"
            + " QPushButton:hover { background-color: " + btn_hover + "; }"
            + " QPushButton#PrimaryBtn { background-color: " + accent + "; color: #FFFFFF; }"
            + " QPushButton#PrimaryBtn:hover { background-color: " + accent_hover + "; }"
            + " QPushButton:disabled { background-color: " + btn_bg + "; color: " + badge_text + "; }"
        )

        # title（review 遗留 1：必须重刷，否则冻结）
        self.lbl_title.setStyleSheet(
            "font: bold " + str(_pt(16)) + "pt 'Microsoft YaHei UI'; color: " + c.get("label", "#F3F4F6") + ";"
        )

        # 版本信息三个 label（review 遗留 1）
        self.current_label.setStyleSheet(
            "color: " + badge_text + "; font: " + str(_pt(10)) + "pt 'Microsoft YaHei UI';"
        )
        self.arrow_label.setStyleSheet(
            "color: " + text + "; font: " + str(_pt(10)) + "pt 'Microsoft YaHei UI';"
        )
        self.latest_label.setStyleSheet(
            "color: " + accent + "; font: bold " + str(_pt(10)) + "pt 'Microsoft YaHei UI';"
        )
        if self.date_label is not None:
            self.date_label.setStyleSheet(
                "color: " + badge_text + "; font: " + str(_pt(9)) + "pt 'Microsoft YaHei UI';"
            )

        # 更新日志标题 + 输入框（review 遗留 1：QTextEdit 必须刷）
        if self.changelog_label is not None:
            self.changelog_label.setStyleSheet(
                "color: " + badge_text + "; font: " + str(_pt(9)) + "pt 'Microsoft YaHei UI';"
            )
        if hasattr(self, "changelog_edit") and self.changelog_edit is not None:
            self.changelog_edit.setStyleSheet(
                "QTextEdit {"
                " background-color: rgba(0,0,0,0.2);"
                " color: " + text + ";"
                " border: 1px solid " + border + ";"
                " border-radius: " + str(_px(8)) + "px;"
                " padding: " + str(_px(10)) + "px;"
                " font: " + str(_pt(9)) + "pt \"Microsoft YaHei UI\";"
                " }"
            )

        # 进度条 + 状态文字（review 遗留 1：之前未刷）
        self.lbl_status.setStyleSheet(
            "color: " + text + "; font: " + str(_pt(10)) + "pt 'Microsoft YaHei UI';"
        )
        self.progress_bar.setStyleSheet(
            "QProgressBar {"
            " background-color: rgba(0,0,0,0.2);"
            " border-radius: " + str(_px(3)) + "px;"
            " border: none;"
            " }"
            " QProgressBar::chunk {"
            " background-color: " + accent + ";"
            " border-radius: " + str(_px(3)) + "px;"
            " }"
        )

    def _on_update(self):
        """立即更新"""
        self.btn_update.setEnabled(False)
        self.btn_later.setVisible(False)
        self.progress_widget.setVisible(True)
        self.downloadRequested.emit()

    def _on_later(self):
        """稍后提醒"""
        self.laterRequested.emit()
        self.reject()

    def set_status(self, text: str):
        """设置状态文本"""
        self.lbl_status.setText(text)
        QtWidgets.QApplication.processEvents()

    def set_progress(self, current: int, total: int):
        """设置进度"""
        if total > 0:
            percent = int(current * 100 / total)
            self.progress_bar.setValue(percent)
            self.lbl_status.setText(f"下载中... {percent}%")
        QtWidgets.QApplication.processEvents()

    def show_complete(self):
        """显示下载完成状态"""
        self.progress_bar.setValue(100)
        self.lbl_status.setText("下载完成！请重启启动器以完成更新")
        self.btn_update.setText("重启启动器")
        self.btn_update.setEnabled(True)
        self.btn_update.clicked.disconnect()
        self.btn_update.clicked.connect(self.accept)

    def show_error(self, error_msg: str):
        """显示错误状态"""
        self.lbl_status.setText(f"下载失败: {error_msg}")
        self.btn_update.setText("重试")
        self.btn_update.setEnabled(True)
        self.btn_update.clicked.disconnect()
        self.btn_update.clicked.connect(self._on_update)
        self.btn_later.setVisible(True)
