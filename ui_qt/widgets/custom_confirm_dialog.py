
from PyQt5 import QtWidgets, QtCore, QtGui
from ui_qt.theme_manager import ThemeManager

class CustomConfirmDialog(QtWidgets.QDialog):
    """
    一个美观的确认弹窗，支持自定义标题、内容和多个操作按钮
    """
    def __init__(self, parent=None, title="确认", content="", buttons=None, default_index=0, theme_manager=None):
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.theme_manager = theme_manager
        self._result = None
        
        # UI Setup
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.container = QtWidgets.QFrame()
        self.container.setObjectName("ConfirmContainer")
        
        # 默认样式
        bg = "#1F2937"
        border = "#374151"
        text = "#E5E7EB"
        title_color = "#F3F4F6"
        btn_bg = "#374151"
        btn_hover = "#4B5563"
        accent = "#6366F1"
        accent_hover = "#818CF8"
        
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
            
        self.container.setStyleSheet(f"""
            QFrame#ConfirmContainer {{
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
            QPushButton#DestructiveBtn {{
                background-color: #EF4444;
                color: #FFFFFF;
            }}
            QPushButton#DestructiveBtn:hover {{
                background-color: #DC2626;
            }}
        """)
        
        inner_layout = QtWidgets.QVBoxLayout(self.container)
        inner_layout.setContentsMargins(24, 24, 24, 24)
        inner_layout.setSpacing(20)
        
        # 标题
        self.lbl_title = QtWidgets.QLabel(title)
        self.lbl_title.setStyleSheet(f"font: bold 14pt 'Microsoft YaHei UI'; color: {title_color};")
        self.lbl_title.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        inner_layout.addWidget(self.lbl_title)
        
        # 内容
        self.lbl_content = QtWidgets.QLabel(content)
        self.lbl_content.setStyleSheet(f"font: 10pt 'Microsoft YaHei UI'; color: {text}; line-height: 1.5;")
        self.lbl_content.setWordWrap(True)
        self.lbl_content.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        inner_layout.addWidget(self.lbl_content)
        
        inner_layout.addSpacing(10)
        
        # 按钮区域
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch(1)
        
        if not buttons:
            buttons = [{"text": "确定", "role": "accept"}]
            
        self.button_widgets = []
        for i, btn_cfg in enumerate(buttons):
            text = btn_cfg.get("text", "按钮")
            role = btn_cfg.get("role", "normal") # normal, primary, destructive
            
            btn = QtWidgets.QPushButton(text)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            
            if role == "primary":
                btn.setObjectName("PrimaryBtn")
            elif role == "destructive":
                btn.setObjectName("DestructiveBtn")
            
            # 使用闭包捕获索引
            btn.clicked.connect(lambda _, idx=i: self._on_btn_clicked(idx))
            
            btn_layout.addWidget(btn)
            self.button_widgets.append(btn)
            
            if i == default_index:
                btn.setFocus()
                
        inner_layout.addLayout(btn_layout)
        
        layout.addWidget(self.container)
        
        # 根据内容自适应大小，限制最大宽度
        self.setFixedWidth(480)
        
    def _on_btn_clicked(self, index):
        self._result = index
        self.accept()
        
    def get_result(self):
        return self._result
