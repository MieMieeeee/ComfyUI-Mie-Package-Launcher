
from PyQt5 import QtWidgets, QtCore, QtGui
from ui_qt.theme_manager import ThemeManager

class ProgressDialog(QtWidgets.QDialog):
    """
    一个简单的无边框进度弹窗，支持显示状态文本和进度条（脉冲或确定进度）
    """
    def __init__(self, parent=None, title="处理中", theme_manager=None, show_cancel=True):
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.theme_manager = theme_manager
        self._cancelled = False
        self._on_cancel_callback = None

        # UI Setup
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.container = QtWidgets.QFrame()
        self.container.setObjectName("ProgressContainer")

        # 默认样式，会被 theme_manager 覆盖
        bg = "#1F2937"
        border = "#374151"
        text = "#E5E7EB"
        btn_bg = "#374151"
        btn_hover = "#4B5563"

        if self.theme_manager:
            c = self.theme_manager.colors
            bg = c.get('content_bg', bg)
            border = c.get('group_border', border)
            text = c.get('text', text)
            btn_bg = c.get('btn_secondary_bg', btn_bg)
            btn_hover = c.get('btn_ghost_bg', btn_hover)

        self.container.setStyleSheet(f"""
            QFrame#ProgressContainer {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QLabel {{
                color: {text};
                font: 10pt "Microsoft YaHei UI";
                background: transparent;
            }}
            QPushButton {{
                background-color: {btn_bg};
                color: {text};
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font: 10pt "Microsoft YaHei UI";
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
            }}
        """)

        inner_layout = QtWidgets.QVBoxLayout(self.container)
        inner_layout.setContentsMargins(20, 20, 20, 20)
        inner_layout.setSpacing(15)

        # 标题
        self.lbl_title = QtWidgets.QLabel(title)
        self.lbl_title.setStyleSheet("font: bold 12pt 'Microsoft YaHei UI';")
        self.lbl_title.setAlignment(QtCore.Qt.AlignCenter)
        inner_layout.addWidget(self.lbl_title)

        # 状态文本
        self.lbl_status = QtWidgets.QLabel("正在初始化...")
        self.lbl_status.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)
        inner_layout.addWidget(self.lbl_status)

        # 进度条
        self.pbar = QtWidgets.QProgressBar()
        self.pbar.setFixedHeight(6)
        self.pbar.setTextVisible(False)
        self.pbar.setRange(0, 0) # 默认脉冲模式

        accent = "#6366F1"
        if self.theme_manager:
            accent = self.theme_manager.colors.get('accent', accent)

        self.pbar.setStyleSheet(f"""
            QProgressBar {{
                background-color: rgba(0,0,0,0.1);
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {accent};
                border-radius: 3px;
            }}
        """)
        inner_layout.addWidget(self.pbar)

        # 取消按钮
        self.btn_cancel = None
        if show_cancel:
            self.btn_cancel = QtWidgets.QPushButton("取消")
            self.btn_cancel.setFixedWidth(100)
            self.btn_cancel.clicked.connect(self._on_cancel)
            btn_layout = QtWidgets.QHBoxLayout()
            btn_layout.addStretch()
            btn_layout.addWidget(self.btn_cancel)
            btn_layout.addStretch()
            inner_layout.addLayout(btn_layout)
            self.setFixedSize(350, 190)
        else:
            self.setFixedSize(350, 160)

        layout.addWidget(self.container)

    def _on_cancel(self):
        """取消按钮点击"""
        self._cancelled = True
        if self.btn_cancel:
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("已取消")
        # 调用取消回调
        if self._on_cancel_callback:
            try:
                self._on_cancel_callback()
            except Exception:
                pass
        # 立即关闭弹窗
        self.done(QtWidgets.QDialog.Rejected)

    def set_cancel_callback(self, callback):
        """设置取消回调"""
        self._on_cancel_callback = callback

    def is_cancelled(self):
        """检查是否已取消"""
        return self._cancelled

    def set_status(self, text):
        self.lbl_status.setText(text)
        QtWidgets.QApplication.processEvents()

    def set_progress(self, value, maximum=100):
        if maximum <= 0:
            self.pbar.setRange(0, 0)
        else:
            self.pbar.setRange(0, maximum)
            self.pbar.setValue(value)
        QtWidgets.QApplication.processEvents()
