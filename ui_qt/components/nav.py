"""
导航组件
侧边栏导航按钮
"""

from PyQt5 import QtWidgets, QtCore
from ui_qt.theme_styles import ThemeStyles


class NavigationButton(QtWidgets.QPushButton):
    """导航按钮"""

    def __init__(self, emoji: str, text: str, theme_styles: ThemeStyles, parent=None):
        super().__init__(f"{emoji} {text}", parent)
        self.theme_styles = theme_styles
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setProperty("full_text", f"{emoji} {text}")
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.nav_button_style())

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self._apply_style()


class Navigation(QtWidgets.QWidget):
    """导航组件"""

    def __init__(self, items: list, theme_styles: ThemeStyles, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self.buttons = []
        self._setup_layout(items)

    def _setup_layout(self, items):
        """设置导航布局"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        for item in items:
            btn = NavigationButton(item['emoji'], item['text'], self.theme_styles, parent=self)
            btn.setToolTip(item.get('tooltip', item['text']))
            btn.clicked.connect(item.get('callback', lambda: None))
            layout.addWidget(btn)
            self.buttons.append(btn)

        layout.addStretch(1)
        self.setLayout(layout)

    def set_selected(self, index: int):
        """设置选中项"""
        if 0 <= index < len(self.buttons):
            for i, btn in enumerate(self.buttons):
                btn.setChecked(i == index)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        for btn in self.buttons:
            btn.update_theme(theme_styles)

    def set_collapsed_text(self, collapsed: bool):
        """设置折叠时的文字（只显示 emoji）"""
        for btn in self.buttons:
            full_text = btn.property("full_text")
            if full_text:
                if collapsed:
                    emoji = full_text.split()[0]
                    btn.setText(emoji)
                else:
                    btn.setText(full_text)
