from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import Qt


class CircleAvatar(QtWidgets.QLabel):
    """
    自定义圆形头像控件，解决 QSS border-radius 锯齿及大图裁剪问题
    """
    def __init__(self, pixmap=None, size=80, parent=None):
        super().__init__(parent)
        self._pix = pixmap
        # size 由调用方负责 DPI 缩放（传入 _px 后的值）；这里只接受最终像素尺寸。
        self.setFixedSize(size, size)

    def _device_pixel_ratio(self) -> float:
        """当前屏幕 devicePixelRatioF，用于光栅图按物理像素渲染避免模糊。"""
        try:
            from PyQt5.QtGui import QGuiApplication

            return float(QGuiApplication.primaryScreen().devicePixelRatio()) if QGuiApplication.primaryScreen() else 1.0
        except Exception:
            return 1.0

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
        # 按 devicePixelRatio 放大目标尺寸，保证 HiDPI 下不模糊。
        dpr = self._device_pixel_ratio()
        target = self.size()
        if dpr != 1.0:
            from PyQt5.QtCore import QSize

            target = QSize(int(self.width() * dpr), int(self.height() * dpr))
        scaled_pixmap = self._pix.scaled(
            target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        if dpr != 1.0:
            scaled_pixmap.setDevicePixelRatio(dpr)

        x = (self.width() - scaled_pixmap.width()) // 2
        y = (self.height() - scaled_pixmap.height()) // 2
        painter.drawPixmap(x, y, scaled_pixmap)

class NoWheelComboBox(QtWidgets.QComboBox):
    """
    禁用鼠标滚轮切换内容的下拉框
    """
    def wheelEvent(self, event):
        event.ignore()
