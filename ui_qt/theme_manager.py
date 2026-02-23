"""
主题管理器
负责管理当前主题和主题切换
"""

from ui_qt.theme_styles import ThemeColors, ThemeStyles


class ThemeManager:
    """主题管理器"""

    def __init__(self, dark: bool = True, scale: float = 1.0):
        self.colors = ThemeColors(dark=dark)
        try:
            v = float(scale)
        except Exception:
            v = 1.0
        if v < 0.75:
            v = 0.75
        if v > 1.25:
            v = 1.25
        self._scale = v
        self.styles = ThemeStyles(self.colors, self._scale)
        self._theme_listeners = []

    @property
    def is_dark(self) -> bool:
        """当前是否为深色主题"""
        return self.colors.dark

    def set_theme(self, dark: bool):
        """切换主题"""
        old_dark = self.colors.dark
        # 只有当主题真的改变时才更新
        if old_dark != dark:
            self.colors.set_theme(dark)
            # 更新样式对象
            self.styles = ThemeStyles(self.colors, self._scale)
            # 通知所有监听器
            for listener in self._theme_listeners:
                try:
                    listener(self.styles)
                except Exception:
                    pass

    def register_listener(self, listener):
        """注册主题变更监听器"""
        if listener not in self._theme_listeners:
            self._theme_listeners.append(listener)

    def unregister_listener(self, listener):
        """注销主题变更监听器"""
        if listener in self._theme_listeners:
            self._theme_listeners.remove(listener)
