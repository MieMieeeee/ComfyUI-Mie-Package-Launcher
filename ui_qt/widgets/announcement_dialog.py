
from PyQt5 import QtWidgets, QtCore, QtGui
from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog

class AnnouncementDialog(CustomConfirmDialog):
    """
    公告弹窗，继承自 CustomConfirmDialog 但专门用于显示长文本公告，
    支持“知道了”（Mark Seen）和“不再弹出”（Mute）操作。
    """
    def __init__(self, parent=None, title="公告", content="", theme_manager=None):
        # 预设按钮
        buttons = [
            {"text": "不再弹出", "role": "destructive"},
            {"text": "知道了", "role": "primary"}
        ]
        
        super().__init__(
            parent=parent,
            title=title,
            content="", # 内容我们自己处理，因为需要滚动区域
            buttons=buttons,
            default_index=1,
            theme_manager=theme_manager
        )
        
        # 移除 CustomConfirmDialog 默认创建的 lbl_content，替换为可滚动的文本区域
        if hasattr(self, "lbl_content"):
            self.lbl_content.setParent(None)
            self.lbl_content.deleteLater()
            
        # 找到布局插入点（在标题之后，按钮之前）
        # inner_layout 的结构是: [Title, Content(Removed), Spacing, ButtonLayout]
        # 我们需要插入到索引 1 的位置
        inner_layout = self.container.layout()
        
        # 文本区域样式
        bg = "#111827"
        text = "#E5E7EB"
        border = "#374151"
        
        if self.theme_manager:
            c = self.theme_manager.colors
            bg = c.get('input_bg', bg)
            text = c.get('text', text)
            border = c.get('input_border', border)
            
        self.text_edit = QtWidgets.QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlainText(content)
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 10px;
                font: 10pt "Microsoft YaHei UI";
                line-height: 1.5;
            }}
        """)
        
        # 插入到布局中 (Title 是 0, 我们插在 1)
        inner_layout.insertWidget(1, self.text_edit, 1) # stretch=1 让它占据剩余空间
        
        # 调整尺寸，公告通常内容较多
        self.setFixedWidth(560)
        self.setFixedHeight(450)
        
    def get_action(self):
        # 0: Mute (Destructive), 1: Acknowledge (Primary)
        res = self.get_result()
        if res == 0:
            return "mute"
        return "ack"
