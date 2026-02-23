from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import Qt


class CircleAvatar(QtWidgets.QLabel):
    """
    自定义圆形头像控件，解决 QSS border-radius 锯齿及大图裁剪问题
    """
    def __init__(self, pixmap=None, size=80, parent=None):
        super().__init__(parent)
        self._pix = pixmap
        self.setFixedSize(size, size)

    def set_pixmap(self, pix):
        self._pix = pix
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)

        if not self._pix or self._pix.isNull():
            # 绘制占位底色
            painter.setBrush(QtGui.QColor("#EEF2F7"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(0, 0, self.width(), self.height())
            return

        path = QtGui.QPainterPath()
        d = min(self.width(), self.height())
        path.addEllipse(0, 0, d, d)
        painter.setClipPath(path)

        # 比例模式填满圆形区域 (类似 CSS object-fit: cover)
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
