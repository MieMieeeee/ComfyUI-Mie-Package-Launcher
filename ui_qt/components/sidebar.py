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
        self._margin_base = 15
        self._spacing_base = 15

        self.setObjectName("SideBar")
        self._apply_style()
        self._setup_layout()
        # 按当前状态设置初始宽度
        self.set_collapsed(self.collapsed)

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.sidebar_style())

    def _setup_layout(self):
        """设置侧边栏布局"""
        _px = self.theme_styles._px
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(
            _px(self._margin_base), _px(self._margin_base),
            _px(self._margin_base), _px(self._margin_base))
        layout.setSpacing(_px(self._spacing_base))
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
        """更新主题样式；同时按新 scale 重算 margin/spacing/当前固定宽度"""
        self.theme_styles = theme_styles
        self._apply_style()
        try:
            _px = self.theme_styles._px
            lo = self.layout()
            if lo is not None:
                lo.setContentsMargins(
                    _px(self._margin_base), _px(self._margin_base),
                    _px(self._margin_base), _px(self._margin_base))
                lo.setSpacing(_px(self._spacing_base))
            # 同步当前折叠/展开态的固定宽度
            self.setFixedWidth(_px(
                self._collapsed_base if self.collapsed else self._expanded_base))
            # 级联通知 header/content 子组件（SidebarHeader 等）
            for ch in self.findChildren(QtWidgets.QWidget):
                upd = getattr(ch, "update_theme", None)
                if callable(upd) and upd is not getattr(type(self), "update_theme", None):
                    try:
                        upd(self.theme_styles)
                    except Exception:
                        pass
        except Exception:
            pass


class SidebarHeader(QtWidgets.QWidget):
    """侧边栏头部"""

    def __init__(self, title: str, author: str, theme_styles: ThemeStyles, avatar_pixmap=None, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self._title_font_pt_base = 18
        self._author_font_pt_base = 9
        self._spacing_base = 8

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme_styles._px(self._spacing_base))

        # 头像（size=60 是 base；CircleAvatar 新契约内部自己 _px）
        avatar = CircleAvatar(
            pixmap=avatar_pixmap, size=60, theme_styles=theme_styles
        )
        layout.addWidget(avatar)
        self._avatar = avatar

        # 标题区域
        title_layout = QtWidgets.QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)

        # 大标题
        title_label = QtWidgets.QLabel(title)
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        title_label.setStyleSheet(f"""
            font: bold {theme_styles._pt(self._title_font_pt_base)}pt "Microsoft YaHei";
            color: {theme_styles.c.get('sidebar_text')};
            background: transparent;
        """)
        self._title_label = title_label

        try:
            from core.render_guard import is_safe_ui as _is_safe_ui
            if _is_safe_ui():
                pass
            else:
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
            font: {theme_styles._pt(self._author_font_pt_base)}pt "Microsoft YaHei";
            background: transparent;
        """)
        self._author_label = author_label

        title_layout.addWidget(title_label)
        title_layout.addWidget(author_label)

        layout.addLayout(title_layout)
        layout.addStretch(1)

        self.setLayout(layout)

    def update_theme(self, theme_styles: ThemeStyles):
        """缩放/主题变化时：字号、avatar 尺寸、spacing 重算"""
        self.theme_styles = theme_styles
        try:
            _pt = self.theme_styles._pt
            _px = self.theme_styles._px
            # spacing
            lo = self.layout()
            if lo is not None:
                lo.setSpacing(_px(self._spacing_base))
            # avatar
            if hasattr(self, "_avatar") and hasattr(self._avatar, "update_theme"):
                self._avatar.update_theme(self.theme_styles)
            # 标题 & 作者
            if hasattr(self, "_title_label"):
                self._title_label.setStyleSheet(f"""
                    font: bold {_pt(self._title_font_pt_base)}pt "Microsoft YaHei";
                    color: {self.theme_styles.c.get('sidebar_text')};
                    background: transparent;
                """)
            if hasattr(self, "_author_label"):
                self._author_label.setStyleSheet(f"""
                    color: {self.theme_styles.c.get('sidebar_text_muted')};
                    font: {_pt(self._author_font_pt_base)}pt "Microsoft YaHei";
                    background: transparent;
                """)
        except Exception:
            pass


# 从 widgets.custom 导入 CircleAvatar
from ui_qt.widgets.custom import CircleAvatar
