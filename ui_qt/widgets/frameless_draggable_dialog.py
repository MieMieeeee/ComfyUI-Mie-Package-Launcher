"""Base class for frameless, draggable dialogs.

Centralizes the common bits our popup dialogs share:
- FramelessWindowHint + WindowStaysOnTopHint window flags
- WA_TranslucentBackground (for rounded corners)
- Mouse-event drag (press / move / release) so the user can drag
  the dialog with the body (children consume their own events)
- SizeAllCursor on hover to hint at draggability

Subclasses pass ``modal`` and ``window_type`` to control whether the
dialog blocks the parent (Qt.Dialog + modal=True) or floats as a
non-blocking tool window (Qt.Tool + modal=False).

Used by:
- ProgressDialog (Qt.Tool, modal=False) - keep main window clickable
- UpdateDialog (Qt.Dialog, modal=True) - block parent for update
- CustomConfirmDialog (Qt.Dialog, modal=True) - confirmations
"""

from PyQt5 import QtCore, QtWidgets


class FramelessDraggableDialog(QtWidgets.QDialog):
    """Frameless + always-on-top + draggable dialog base."""

    def __init__(
        self,
        parent=None,
        modal: bool = True,
        window_type: QtCore.Qt.WindowType = QtCore.Qt.Dialog,
    ):
        super().__init__(parent)
        # window_type | frameless | on-top covers all 3 subclasses.
        self.setWindowFlags(
            window_type
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
        )
        # Translucent background lets the rounded border on the
        # inner QFrame show through.
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setModal(modal)
        # 拖拽状态。press 时记录 globalPos - frameTopLeft,
        # move 时按差值平移, release 时清空。
        self._drag_pos = None

    # --- 拖拽支持 ----------------------------------------------------

    def mousePressEvent(self, event):
        """左键按下时记录拖拽起点。

        子控件（按钮）会自己消费 mousePressEvent，不会冒泡到
        弹窗的 mousePressEvent，所以点按钮不会触发拖拽。
        """
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = (
                event.globalPos() - self.frameGeometry().topLeft()
            )
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """按住左键移动时，把弹窗搬到鼠标当前位置。"""
        if (
            self._drag_pos is not None
            and event.buttons() & QtCore.Qt.LeftButton
        ):
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """松开左键时清掉拖拽状态。"""
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        """鼠标进入时给 SizeAll cursor，暗示这里可以拖。"""
        try:
            self.setCursor(QtCore.Qt.SizeAllCursor)
        except Exception:
            pass
        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开时还原 cursor。"""
        try:
            self.unsetCursor()
        except Exception:
            pass
        super().leaveEvent(event)
