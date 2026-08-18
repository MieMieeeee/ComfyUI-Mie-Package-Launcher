from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import Qt


class CircleAvatar(QtWidgets.QLabel):
    """
    自定义圆形头像控件，解决 QSS border-radius 锯齿及大图裁剪问题

    新契约（DPI 跟随）：
      - 构造参数 size 传 base 尺寸（像素数，按 1x = 1.0 scale）；
      - 内部按传入的 ThemeStyles._px 折算到当前 DPI 并 setFixedSize；
      - 暴露 update_theme(theme_styles) 方法，主题/缩放变化时重算尺寸并重绘。
    """
    def __init__(self, pixmap=None, size=80, theme_styles=None, parent=None):
        super().__init__(parent)
        self._pix = pixmap
        self._base_size = size
        self._theme_styles = theme_styles
        # 若传入 theme_styles 就按 scale 折算；否则兼容旧调用方（传已 _px 后的值）
        if self._theme_styles is not None:
            s = self._theme_styles._px(size)
        else:
            s = size
        self.setFixedSize(s, s)

    def set_pixmap(self, pix):
        self._pix = pix
        self.update()

    def update_theme(self, theme_styles):
        """主题/缩放变化时：重算尺寸 + 重绘。"""
        self._theme_styles = theme_styles
        s = theme_styles._px(self._base_size)
        self.setFixedSize(s, s)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

        if not self._pix or self._pix.isNull():
            painter.setBrush(QtGui.QColor("#EEF2F7"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(0, 0, self.width(), self.height())
            return

        path = QtGui.QPainterPath()
        d = min(self.width(), self.height())
        path.addEllipse(0, 0, d, d)
        painter.setClipPath(path)

        scaled_pixmap = self._pix.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        x = (self.width() - scaled_pixmap.width()) // 2
        y = (self.height() - scaled_pixmap.height()) // 2
        painter.drawPixmap(x, y, scaled_pixmap)

class NoWheelComboBox(QtWidgets.QComboBox):
    """
    禁用鼠标滚轮切换内容的下拉框
    """
    def wheelEvent(self, event):
        event.ignore()
