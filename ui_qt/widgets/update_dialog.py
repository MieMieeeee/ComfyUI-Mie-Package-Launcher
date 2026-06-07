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
                border-radius: 16px;
            }}
            QLabel {{
                background: transparent;
            }}
            QPushButton {{
                background-color: {btn_bg};
                color: {text};
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font: bold 10pt "Microsoft YaHei UI";
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
        self.lbl_title.setStyleSheet(f"font: bold 16pt 'Microsoft YaHei UI'; color: {title_color};")
        self.lbl_title.setAlignment(QtCore.Qt.AlignCenter)
        inner_layout.addWidget(self.lbl_title)

        # 版本信息
        current_ver = self._update_info.get("current", "?")
        latest_ver = self._update_info.get("latest", "?")
        release_date = self._update_info.get("release_date", "")

        version_widget = QtWidgets.QWidget()
        version_layout = QtWidgets.QHBoxLayout(version_widget)
        version_layout.setContentsMargins(0, 0, 0, 0)
        version_layout.setSpacing(8)

        current_label = QtWidgets.QLabel(f"当前: {current_ver}")
        current_label.setStyleSheet(f"color: {badge_text}; font: 10pt 'Microsoft YaHei UI';")

        arrow_label = QtWidgets.QLabel("→")
        arrow_label.setStyleSheet(f"color: {text}; font: 10pt 'Microsoft YaHei UI';")

        latest_label = QtWidgets.QLabel(f"最新: {latest_ver}")
        latest_label.setStyleSheet(f"color: {accent}; font: bold 10pt 'Microsoft YaHei UI';")

        version_layout.addStretch()
        version_layout.addWidget(current_label)
        version_layout.addWidget(arrow_label)
        version_layout.addWidget(latest_label)
        if release_date:
            date_label = QtWidgets.QLabel(f"  ({release_date})")
            date_label.setStyleSheet(f"color: {badge_text}; font: 9pt 'Microsoft YaHei UI';")
            version_layout.addWidget(date_label)
        version_layout.addStretch()

        inner_layout.addWidget(version_widget)

        # 更新日志
        changelog = self._update_info.get("changelog", "")
        if changelog:
            changelog_label = QtWidgets.QLabel("更新日志")
            changelog_label.setStyleSheet(f"color: {badge_text}; font: 9pt 'Microsoft YaHei UI';")
            inner_layout.addWidget(changelog_label)

            self.changelog_edit = QtWidgets.QTextEdit()
            self.changelog_edit.setReadOnly(True)
            self.changelog_edit.setPlainText(changelog)
            self.changelog_edit.setStyleSheet(f"""
                QTextEdit {{
                    background-color: rgba(0,0,0,0.2);
                    color: {text};
                    border: 1px solid {border};
                    border-radius: 8px;
                    padding: 10px;
                    font: 9pt "Microsoft YaHei UI";
                }}
            """)
            self.changelog_edit.setFixedHeight(150)
            inner_layout.addWidget(self.changelog_edit)

        # 进度区域（初始隐藏）
        self.progress_widget = QtWidgets.QWidget()
        progress_layout = QtWidgets.QVBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(8)

        self.lbl_status = QtWidgets.QLabel("准备下载...")
        self.lbl_status.setStyleSheet(f"color: {text}; font: 10pt 'Microsoft YaHei UI';")
        self.lbl_status.setAlignment(QtCore.Qt.AlignCenter)
        progress_layout.addWidget(self.lbl_status)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: rgba(0,0,0,0.2);
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {accent};
                border-radius: 3px;
            }}
        """)
        progress_layout.addWidget(self.progress_bar)

        self.progress_widget.setVisible(False)
        inner_layout.addWidget(self.progress_widget)

        # 按钮区域
        self.btn_layout = QtWidgets.QHBoxLayout()
        self.btn_layout.setSpacing(12)

        self.btn_later = QtWidgets.QLabel("稍后提醒")
        self.btn_later.setStyleSheet(f"""
            QLabel {{
                color: {badge_text};
                font: 10pt "Microsoft YaHei UI";
                padding: 10px 20px;
            }}
            QLabel:hover {{
                color: {text};
            }}
        """)
        self.btn_later.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_later.mousePressEvent = lambda e: self._on_later()

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

        self.setFixedWidth(480)
        self.adjustSize()

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
