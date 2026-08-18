"""
按钮组件
包含所有可复用的按钮类型
"""

from PyQt5 import QtWidgets, QtCore, QtGui
from ui_qt.theme_styles import ThemeStyles


class PrimaryButton(QtWidgets.QPushButton):
    """主要按钮 - 紫色渐变"""

    def __init__(self, text: str, theme_styles: ThemeStyles, parent=None):
        super().__init__(text, parent)
        self.theme_styles = theme_styles
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.primary_button_style())

    def update_theme(self, theme_styles: ThemeStyles):
        self.theme_styles = theme_styles
        self._apply_style()

class SecondaryButton(QtWidgets.QPushButton):
    """次级按钮 - 半透明背景"""

    def __init__(self, text: str, theme_styles: ThemeStyles, parent=None):
        super().__init__(text, parent)
        self.theme_styles = theme_styles
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.secondary_button_style())

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self._apply_style()


class DestructiveButton(QtWidgets.QPushButton):
    """破坏性按钮 - 实色红色与 CustomConfirmDialog 中的
    退出启动器按钮一致，用于应用内必须明确
    标记为高风险的操作。"""

    def __init__(self, text: str, theme_styles: ThemeStyles, parent=None):
        super().__init__(text, parent)
        self.theme_styles = theme_styles
        self.setObjectName("DestructiveBtn")
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.destructive_button_style())

    def update_theme(self, theme_styles: ThemeStyles):
        self.theme_styles = theme_styles
        self._apply_style()


class LinkButton(QtWidgets.QPushButton):
    """链接按钮 - 用于导航卡片"""

    def __init__(self, text: str, theme_styles: ThemeStyles, parent=None):
        super().__init__(text, parent)
        self.theme_styles = theme_styles
        self.setObjectName("LinkButton")
        self._min_height_base = 40
        self.setMinimumHeight(theme_styles._px(self._min_height_base))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        try:
            self.setFlat(False)
        except Exception:
            pass
        try:
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        except Exception:
            pass
        self._apply_style()
        self._setup_hover_effect()

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.link_button_style())

    def _setup_hover_effect(self):
        """创建 hover effect 并挂上. 默认 disabled, enterEvent 翻 enabled.

        旧实现: enterEvent 每次都 new 一个 QGraphicsDropShadowEffect, leaveEvent
        又 setGraphicsEffect(None) 把它拆掉. 鼠标每 hover 一次就触发一次完整
        重绘 + 内存分配 + 释放, 是界面卡顿的最大单一原因. 改成一次创建, 用
        setEnabled 切换可见性, hover 期间 Qt 不必重新分配 effect 也不必重算
        graphics scene 拓扑.
        """
        try:
            from core.render_guard import is_safe_ui as _is_safe_ui
            if _is_safe_ui():
                return
        except Exception:
            pass
        try:
            effect = QtWidgets.QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(15)
            effect.setOffset(0, 4)
            alpha = 35 if getattr(self.theme_styles.c, "dark", True) else 60
            effect.setColor(QtGui.QColor(99, 102, 241, alpha))
            effect.setEnabled(False)
            self.setGraphicsEffect(effect)
        except Exception:
            pass

    def update_theme(self, theme_styles: ThemeStyles):
        self.theme_styles = theme_styles
        self.setMinimumHeight(self.theme_styles._px(self._min_height_base))
        self._apply_style()

    def _set_effect(self, show: bool):
        """切换 hover effect 的启用状态.

        effect 在 _setup_hover_effect 里已经创建好挂在 widget 上了, 这里只
        翻 enabled. 不要再 setGraphicsEffect(None) —— 那会把刚创建的
        effect 直接拆掉, 跟最初那种每 hover 一次就重建的 bug 一样慢.
        """
        try:
            effect = self.graphicsEffect()
            if effect is not None:
                effect.setEnabled(bool(show))
        except Exception:
            pass

    def enterEvent(self, event):
        try:
            self._set_effect(True)
        except Exception:
            pass
        try:
            super().enterEvent(event)
        except Exception:
            pass

    def leaveEvent(self, event):
        try:
            self._set_effect(False)
        except Exception:
            pass
        try:
            super().leaveEvent(event)
        except Exception:
            pass


class ThemeButton(QtWidgets.QPushButton):
    """主题切换按钮"""

    def __init__(self, emoji: str, label: str, theme_value: str, theme_styles: ThemeStyles, parent=None):
        super().__init__(f"{emoji} {label}", parent)
        self.theme_styles = theme_styles
        self.theme_value = theme_value
        self.setObjectName("ThemeBtn")
        self.setCheckable(True)
        self._width_base = 70
        self._min_height_base = 60
        self.setFixedWidth(theme_styles._px(self._width_base))
        self.setMinimumHeight(theme_styles._px(self._min_height_base))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setProperty("theme_value", theme_value)
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.theme_button_style())

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self.setFixedWidth(self.theme_styles._px(self._width_base))
        self.setMinimumHeight(self.theme_styles._px(self._min_height_base))
        self._apply_style()


class IconButton(QtWidgets.QPushButton):
    """图标按钮 - 小尺寸图标按钮"""

    def __init__(self, text: str, theme_styles: ThemeStyles, size: int = 24, parent=None):
        super().__init__(text, parent)
        self.theme_styles = theme_styles
        self._size = size  # 保留原始 base size，_apply_style 里按 scale 重算
        self.setFixedSize(theme_styles._px(size), theme_styles._px(size))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._apply_style()

    def _apply_style(self):
        _px = self.theme_styles._px
        _pt = self.theme_styles._pt
        self.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                color: {self.theme_styles.c.get('sidebar_text')};
                border-radius: {_px(8)}px;
                font-size: {_pt(self._size // 2)}pt;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.2);
                color: {self.theme_styles.c.get('sidebar_text')};
            }}
        """)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式，按 scale 重算几何尺寸 & 字号 & 圆角"""
        self.theme_styles = theme_styles
        self.setFixedSize(self.theme_styles._px(self._size), self.theme_styles._px(self._size))
        self._apply_style()
