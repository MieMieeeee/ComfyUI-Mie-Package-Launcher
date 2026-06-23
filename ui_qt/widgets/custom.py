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
        # 按 devicePixelRatio 放大到物理像素，避免高 DPI 下头像发糊
        dpr = self.devicePixelRatioF() or 1.0
        phys_w = max(1, int(round(self.width() * dpr)))
        phys_h = max(1, int(round(self.height() * dpr)))
        scaled_pixmap = self._pix.scaled(
            phys_w, phys_h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        scaled_pixmap.setDevicePixelRatio(dpr)

        # drawPixmap(int,int,QPixmap) 按逻辑坐标绘制；设了 dpr 后 pixmap.width() 是物理像素，
        # 居中需换算回逻辑尺寸（物理 / dpr）
        logical_w = scaled_pixmap.width() / dpr
        logical_h = scaled_pixmap.height() / dpr
        x = int(round((self.width() - logical_w) / 2))
        y = int(round((self.height() - logical_h) / 2))
        painter.drawPixmap(x, y, scaled_pixmap)

class NoWheelComboBox(QtWidgets.QComboBox):
    """
    禁用鼠标滚轮切换内容的下拉框
    """
    def wheelEvent(self, event):
        event.ignore()
