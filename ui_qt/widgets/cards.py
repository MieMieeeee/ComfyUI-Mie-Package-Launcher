"""
卡片组件
包含可复用的卡片类型
"""

from PyQt5 import QtWidgets, QtGui, QtCore
from ui_qt.theme_styles import ThemeStyles
from .custom import CircleAvatar


class ProfileCard(QtWidgets.QFrame):
    """个人资料卡片 - 关于我页面"""

    def __init__(self, name: str, quote: str, theme_styles: ThemeStyles,
                 avatar_pixmap=None, avatar_size: int = 60, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self.avatar_pixmap = avatar_pixmap
        self.avatar_size = avatar_size
        self._min_height_base = 100
        self.setObjectName("ProfileCard")
        self.setMinimumHeight(theme_styles._px(self._min_height_base))
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self._apply_style()
        self._setup_shadow(avatar_pixmap)
        self._setup_content(name, quote)

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.card_style())

    def _setup_shadow(self, pixmap):
        """设置阴影效果"""
        try:
            from core.render_guard import is_safe_ui as _is_safe_ui
            if _is_safe_ui():
                return
        except Exception:
            pass
        if pixmap is not None:
            try:
                glow = QtWidgets.QGraphicsDropShadowEffect(self)
                glow.setBlurRadius(15)
                glow.setOffset(0, 4)
                glow.setColor(QtGui.QColor(0, 0, 0, 30))
                self.setGraphicsEffect(glow)
            except Exception:
                pass

    def _setup_content(self, name: str, quote: str):
        """设置卡片内容"""
        outer = QtWidgets.QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        # 头像（avatar_size 是 base；CircleAvatar 新契约内部自己 _px）
        avatar = CircleAvatar(
            pixmap=self.avatar_pixmap, size=self.avatar_size, theme_styles=self.theme_styles
        )
        outer.addWidget(avatar)
        self._avatar = avatar

        # 信息
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(6)
        info_layout.setAlignment(QtCore.Qt.AlignVCenter)

        # 姓名
        _pt = self.theme_styles._pt
        self._name_label = QtWidgets.QLabel(name)
        self._name_label.setAlignment(QtCore.Qt.AlignCenter)
        self._name_label.setStyleSheet(f"""
            font: bold {_pt(18)}pt "Microsoft YaHei UI";
            color: {self.theme_styles.c.get('sidebar_text')};
            background: transparent;
        """)
        info_layout.addWidget(self._name_label)

        # 诗句
        self._quote_label = QtWidgets.QLabel(quote)
        self._quote_label.setStyleSheet(f"""
            color: {self.theme_styles.c.get('label_muted')};
            font: {_pt(12)}pt "KaiTi", "SimKai", "Microsoft YaHei UI";
            background: transparent;
        """)
        info_layout.addWidget(self._quote_label)

        outer.addLayout(info_layout)
        outer.addStretch(1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.addLayout(outer)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self.setMinimumHeight(self.theme_styles._px(self._min_height_base))
        self._apply_style()
        try:
            _pt = self.theme_styles._pt
            if hasattr(self, "_avatar") and hasattr(self._avatar, "update_theme"):
                self._avatar.update_theme(self.theme_styles)
            if hasattr(self, "_name_label"):
                self._name_label.setStyleSheet(f"font: bold {_pt(18)}pt \"Microsoft YaHei UI\"; color: {self.theme_styles.c.get('sidebar_text')}; background: transparent;")
            if hasattr(self, "_quote_label"):
                self._quote_label.setStyleSheet(f"color: {self.theme_styles.c.get('label_muted')}; font: {_pt(12)}pt \"KaiTi\", \"SimKai\", \"Microsoft YaHei UI\"; background: transparent;")
        except Exception:
            pass

class HeroCard(QtWidgets.QFrame):
    """英雄卡片 - 关于页面顶部大卡片"""

    def __init__(self, title: str, theme_styles: ThemeStyles, title_font_size: int = 40, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        # title_font_size 历史上是 px 单位的裸值（默认 40px）。现在统一转 pt 基准
        # （px * 72/96 = px * 0.75），再交给 ThemeStyles._pt 按 DPI 缩放。
        self._title_font_pt_base = max(6, int(round(title_font_size * 0.75)))
        self.setObjectName("HeroCard")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self._apply_style()
        self._setup_content(title)

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.card_style())

    def _setup_content(self, title: str):
        """设置卡片内容"""
        _pt = self.theme_styles._pt
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setAlignment(QtCore.Qt.AlignCenter)

        # 标题 (字号可定制; 默认对应原 40px, 较长标题如"ComfyUI 启动器"传更小值)
        self._title_label = QtWidgets.QLabel(title)
        self._title_label.setAlignment(QtCore.Qt.AlignCenter)
        self._title_label.setStyleSheet(f"""
            font: bold {_pt(self._title_font_pt_base)}pt "Microsoft YaHei UI";
            color: {self.theme_styles.c.get('sidebar_text')};
            background: transparent;
        """)
        layout.addWidget(self._title_label)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self._apply_style()
        try:
            if hasattr(self, "_title_label"):
                _pt = self.theme_styles._pt
                self._title_label.setStyleSheet(f"font: bold {_pt(self._title_font_pt_base)}pt \"Microsoft YaHei UI\"; color: {self.theme_styles.c.get('sidebar_text')}; background: transparent;")
        except Exception:
            pass


class InfoCard(QtWidgets.QFrame):
    """信息卡片 - 带标题和内容的卡片"""

    def __init__(self, title: str, theme_styles: ThemeStyles, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self.setObjectName("InfoCard")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        # base margins & spacing（DPI 变化时 update_theme 里 _px 折算）
        self._margins_base = (15, 22, 15, 12)
        self._spacing_base = 8
        self._apply_style()
        self._setup_content(title)

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.card_style())

    def _setup_content(self, title: str):
        """设置卡片内容"""
        _px = self.theme_styles._px
        layout = QtWidgets.QVBoxLayout(self)
        ml, mt, mr, mb = self._margins_base
        layout.setContentsMargins(_px(ml), _px(mt), _px(mr), _px(mb))
        layout.setSpacing(_px(self._spacing_base))
        layout.setAlignment(QtCore.Qt.AlignVCenter)
        self._title_labels = []
        _pt = self.theme_styles._pt
        if title and title.strip():
            for txt in title.split('\n'):
                t = txt.strip()
                if not t:
                    continue
                label = QtWidgets.QLabel(t)
                label.setStyleSheet(
                    f"color: {self.theme_styles.c.get('label')}; "
                    f"background: transparent; "
                    f"font: bold {_pt(12)}pt \"Microsoft YaHei UI\";"
                )
                layout.addWidget(label)
                self._title_labels.append(label)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式（含字号/margins/spacing/DPI 缩放重算）"""
        self.theme_styles = theme_styles
        self._apply_style()
        try:
            _px = self.theme_styles._px
            _pt = self.theme_styles._pt
            lo = self.layout()
            if lo is not None:
                ml, mt, mr, mb = self._margins_base
                lo.setContentsMargins(_px(ml), _px(mt), _px(mr), _px(mb))
                lo.setSpacing(_px(self._spacing_base))
            for label in getattr(self, "_title_labels", []):
                label.setStyleSheet(
                    f"color: {self.theme_styles.c.get('label')}; "
                    f"background: transparent; "
                    f"font: bold {_pt(12)}pt \"Microsoft YaHei UI\";"
                )
            for btn in self.findChildren(QtWidgets.QPushButton):
                if hasattr(btn, "update_theme"):
                    btn.update_theme(self.theme_styles)
                else:
                    btn.setStyleSheet(self.theme_styles.link_button_style())
        except Exception:
            pass


