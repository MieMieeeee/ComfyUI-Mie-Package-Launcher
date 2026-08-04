"""
侧边栏组件
"""

from PyQt5 import QtWidgets, QtCore
from ui_qt.theme_styles import ThemeStyles


class Sidebar(QtWidgets.QWidget):
    """侧边栏组件"""

    def __init__(self, theme_styles: ThemeStyles, on_collapse=None, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self.on_collapse = on_collapse
        self.collapsed = False
        # base 宽度（按 DPI 缩放，与 qt_app 主窗口侧边栏一致）
        self._expanded_base = 240
        self._collapsed_base = 60

        self.setObjectName("SideBar")
        self._apply_style()
        self._setup_layout()

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.sidebar_style())

    def _setup_layout(self):
        """设置侧边栏布局"""
        _px = self.theme_styles._px
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(_px(15), _px(15), _px(15), _px(15))
        layout.setSpacing(_px(15))
        self.setLayout(layout)

    def set_collapsed(self, collapsed: bool):
        """设置折叠/展开状态"""
        self.collapsed = collapsed
        _px = self.theme_styles._px
        self.setFixedWidth(_px(self._collapsed_base if collapsed else self._expanded_base))

    def add_header(self, widget):
        """添加头部"""
        if hasattr(self, 'layout'):
            self.layout().insertWidget(0, widget)

    def add_content(self, widget):
        """添加内容"""
        if hasattr(self, 'layout'):
            self.layout().addWidget(widget)

    def add_spacer(self):
        """添加弹簧"""
        if hasattr(self, 'layout'):
            self.layout().addStretch(1)

    def add_bottom(self, widget):
        """添加底部内容（主题选择等）"""
        if hasattr(self, 'layout'):
            self.layout().addWidget(widget)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self._apply_style()


class SidebarHeader(QtWidgets.QWidget):
    """侧边栏头部"""

    def __init__(self, title: str, author: str, theme_styles: ThemeStyles, avatar_pixmap=None, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 头像
        avatar = CircleAvatar(pixmap=avatar_pixmap, size=60)
        layout.addWidget(avatar)

        # 标题区域
        title_layout = QtWidgets.QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)

        # 大标题
        title_label = QtWidgets.QLabel(title)
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        title_label.setStyleSheet(f"""
            font: bold {theme_styles._pt(18)}pt "Microsoft YaHei";
            color: {theme_styles.c.get('sidebar_text')};
            background: transparent;
        """)

        try:
            glow = QtWidgets.QGraphicsDropShadowEffect(title_label)
            glow.setBlurRadius(15)
            glow.setOffset(0, 0)
            glow.setColor(QtGui.QColor(158, 119, 237, 150))
            title_label.setGraphicsEffect(glow)
        except Exception:
            pass

        # 作者
        author_label = QtWidgets.QLabel(author)
        author_label.setAlignment(QtCore.Qt.AlignCenter)
        author_label.setStyleSheet(f"""
            color: {theme_styles.c.get('sidebar_text_muted')};
            font: {theme_styles._pt(9)}pt "Microsoft YaHei";
            background: transparent;
        """)

        title_layout.addWidget(title_label)
        title_layout.addWidget(author_label)

        layout.addLayout(title_layout)
        layout.addStretch(1)

        self.setLayout(layout)


# 从 widgets.custom 导入 CircleAvatar
from ui_qt.widgets.custom import CircleAvatar
