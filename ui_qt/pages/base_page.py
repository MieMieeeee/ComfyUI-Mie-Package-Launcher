"""
页面基类
所有页面继承自此，实现统一的生命周期和主题管理
"""

from PyQt5 import QtWidgets
from ui_qt.theme_manager import ThemeManager
from ui_qt.theme_styles import ThemeStyles


class BasePage(QtWidgets.QWidget):
    """页面基类"""

    def __init__(self, theme_manager: ThemeManager, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        # 注册时需要传入初始样式对象
        self.theme_manager.register_listener(self._on_theme_changed)
        # 应用初始主题
        self._apply_initial_theme()

    def _apply_initial_theme(self):
        """应用初始主题样式"""
        styles = self.theme_manager.styles if hasattr(self, "theme_manager") and self.theme_manager else ThemeStyles(self.theme_manager.colors)
        self.setStyleSheet(styles.content_style_dark() if styles.c.dark else styles.content_style_light())

    def _on_theme_changed(self, theme_styles: ThemeStyles):
        """主题变更回调"""
        self.setStyleSheet(theme_styles.content_style_dark() if theme_styles.c.dark else theme_styles.content_style_light())

    def update_theme(self, theme_styles: ThemeStyles = None):
        """更新主题"""
        styles = theme_styles or (self.theme_manager.styles if hasattr(self, "theme_manager") and self.theme_manager else ThemeStyles(self.theme_manager.colors))
        self.setStyleSheet(styles.content_style_dark() if styles.c.dark else styles.content_style_light())
