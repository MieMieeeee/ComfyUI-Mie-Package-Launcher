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
        # 子类 __init__ 末尾向此列表追加 (widget, setter_name, base_int_or_tuple)；
        # 每一次 update_theme 末尾都会自动按新 scale 重算并重设。
        # setter_name 必须是 widget 存在的方法名（如 'setFixedWidth' / 'setMinimumHeight' / 'setFixedSize'），
        # typo 直接 AttributeError，不静默。
        self._dpi_sized_widgets: list = []
        # 注册时需要传入初始样式对象
        self.theme_manager.register_listener(self._on_theme_changed)
        # 应用初始主题
        self._apply_initial_theme()

    def _apply_initial_theme(self):
        """应用初始主题样式"""
        styles = self.theme_manager.styles if hasattr(self, "theme_manager") and self.theme_manager else ThemeStyles(self.theme_manager.colors)
        self.setStyleSheet(styles.content_style_dark() if styles.c.dark else styles.content_style_light())
        # 初始化尺寸：子类在 __init__ 末尾注册了 widgets 后，这些尺寸会在首次 update_theme（下一行）时应用。
        # 但有些子类在 __init__ 构造时已经手动设过尺寸，这里再跑一次确保一致。
        self._reapply_dpi_sizes()

    def _reapply_dpi_sizes(self):
        """按 theme_manager.styles 的当前 scale 重算并应用 _dpi_sized_widgets 中所有登记的固定尺寸。

        setter_name 对应 Qt 原生方法，不造字符串枚举：
          int base: setMinimumWidth / setMinimumHeight / setFixedWidth / setFixedHeight / setMaximumWidth / setMaximumHeight
          (w,h) tuple base: setMinimumSize / setFixedSize / setMaximumSize
        typo -> AttributeError（不吞异常，防止 P0 期间 typo 静默漏重算）。
        """
        _px = self.theme_manager.styles._px
        for widget, setter_name, base in getattr(self, "_dpi_sized_widgets", []):
            setter = getattr(widget, setter_name)
            if isinstance(base, tuple):
                setter(_px(base[0]), _px(base[1]))
            else:
                setter(_px(base))

    def _on_theme_changed(self, theme_styles: ThemeStyles):
        """主题变更回调"""
        self.setStyleSheet(theme_styles.content_style_dark() if theme_styles.c.dark else theme_styles.content_style_light())
        self._reapply_dpi_sizes()

    def update_theme(self, theme_styles: ThemeStyles = None):
        """更新主题"""
        styles = theme_styles or (self.theme_manager.styles if hasattr(self, "theme_manager") and self.theme_manager else ThemeStyles(self.theme_manager.colors))
        self.setStyleSheet(styles.content_style_dark() if styles.c.dark else styles.content_style_light())
        self._reapply_dpi_sizes()
