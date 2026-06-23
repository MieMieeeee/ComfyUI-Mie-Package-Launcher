"""
\u7cfb\u7edf\u6258\u76d8\u63a7\u5236\u5668 (LauncherTray)

\u63d0\u4f9b QSystemTrayIcon \u5c01\u88c5\u3001\u83dc\u5355\u3001\u9996\u6b21\u6c14\u6ce1\u63d0\u793a\u3001\u4e0e\u4e3b\u7a97\u53e3\u7684\u4fe1\u53f7\u89e3\u8026\u3002

- show_window_requested: \u6258\u76d8\u83dc\u5355\u201c\u663e\u793a\u4e3b\u7a97\u53e3\u201d\u6216\u53cc\u51fb\u6258\u76d8\u56fe\u6807\u65f6\u89e6\u53d1
- quit_requested: \u6258\u76d8\u83dc\u5355\u201c\u9000\u51fa\u542f\u52a8\u5668\u201d\u65f6\u89e6\u53d1
- update_comfyui_status(running): \u5916\u90e8\uff085s \u72b6\u6001\u5b9a\u65f6\u5668\uff09\u8c03\u7528\u4ee5\u66f4\u65b0\u83dc\u5355\u72b6\u6001\u6587\u6848
- show_first_time_hint(): \u7b2c\u4e00\u6b21\u6700\u5c0f\u5316\u5230\u6258\u76d8\u65f6\u8c03\u7528\uff0c\u5f39\u51fa\u6c14\u6ce1\u63d0\u793a
- available: \u5f53\u524d\u5e73\u53f0\u662f\u5426\u652f\u6301\u7cfb\u7edf\u6258\u76d8
"""
from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets


class LauncherTray(QtCore.QObject):
    """QSystemTrayIcon \u63a7\u5236\u5668\uff0c\u4e0e PyQtLauncher \u901a\u8fc7\u4fe1\u53f7\u89e3\u8026\u3002"""

    show_window_requested = QtCore.pyqtSignal()
    quit_requested = QtCore.pyqtSignal()  # 退出启动器（保留 ComfyUI 后台运行）
    quit_and_stop_requested = QtCore.pyqtSignal()  # 退出启动器并关闭 ComfyUI

    def __init__(self, app, theme_manager=None, parent=None):
        super().__init__(parent)
        self._app = app
        self._theme_manager = theme_manager
        self._tray = None
        self._menu = None
        self._status_action = None
        self._show_action = None
        self._quit_action = None
        self._quit_and_stop_action = None  # 退出并关闭 ComfyUI 菜单项
        self._hint_shown = False
        self._available = False
        self._icon = self._load_icon()

    @staticmethod
    def _load_icon():
        """\u4ece assets \u76ee\u5f55\u52a0\u8f7d\u56fe\u6807\u3002ico/png \u90fd\u5c1d\u8bd5\uff0c\u6700\u540e\u56de\u9000\u5230\u7a7a QIcon\u3002"""
        try:
            from ui import assets_helper as ASSETS

            for name in ("rabbit.ico", "rabbit.png"):
                p = ASSETS.resolve_asset(name)
                try:
                    if p and p.exists():
                        icn = QtGui.QIcon(str(p))
                        if not icn.isNull():
                            return icn
                except Exception:
                    pass
        except Exception:
            pass
        return QtGui.QIcon()

    def init(self):
        """\u521d\u59cb\u5316\u6258\u76d8\u3002\u8fd4\u56de True \u8868\u793a\u7cfb\u7edf\u652f\u6301\u6258\u76d8\u4e14\u521d\u59cb\u5316\u6210\u529f\u3002"""
        if self._tray is not None:
            return self._available

        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            try:
                if getattr(self._app, "logger", None):
                    self._app.logger.info("\u7cfb\u7edf\u4e0d\u652f\u6301\u6258\u76d8 (isSystemTrayAvailable=False)")
            except Exception:
                pass
            self._available = False
            return False

        self._tray = QtWidgets.QSystemTrayIcon(self._icon, self.parent())
        self._tray.setToolTip("ComfyUI \u542f\u52a8\u5668")

        self._menu = QtWidgets.QMenu()

        self._show_action = self._menu.addAction("\u663e\u793a\u4e3b\u7a97\u53e3")
        self._show_action.triggered.connect(self.show_window_requested)

        self._status_action = self._menu.addAction("ComfyUI \u72b6\u6001: \u68c0\u6d4b\u4e2d")
        self._status_action.setEnabled(False)

        self._menu.addSeparator()
        self._quit_action = self._menu.addAction("\u9000\u51fa\u542f\u52a8\u5668")
        self._quit_action.setToolTip("\u9000\u51fa\u542f\u52a8\u5668\uff0cComfyUI \u5982\u5728\u8fd0\u884c\u4f1a\u7ee7\u7eed\u540e\u53f0\u8fd0\u884c")
        self._quit_action.triggered.connect(self.quit_requested)
        # 第二项：退出并关闭 ComfyUI。ComfyUI 未运行时禁用，避免无效操作。
        self._quit_and_stop_action = self._menu.addAction("\u9000\u51fa\u5e76\u5173\u95ed ComfyUI")
        self._quit_and_stop_action.setToolTip("\u5148\u505c\u6b62 ComfyUI \u670d\u52a1\u518d\u9000\u51fa\u542f\u52a8\u5668")
        self._quit_and_stop_action.setEnabled(False)
        self._quit_and_stop_action.triggered.connect(self.quit_and_stop_requested)

        self._apply_menu_style()

        self._tray.setContextMenu(self._menu)

        def _on_activated(reason):
            try:
                if reason in (
                    QtWidgets.QSystemTrayIcon.DoubleClick,
                    QtWidgets.QSystemTrayIcon.Trigger,
                ):
                    self.show_window_requested.emit()
            except Exception:
                pass

        self._tray.activated.connect(_on_activated)

        self._tray.show()
        self._available = True
        try:
            if getattr(self._app, "logger", None):
                self._app.logger.info("\u7cfb\u7edf\u6258\u76d8\u5df2\u521d\u59cb\u5316")
        except Exception:
            pass
        return True

    def _apply_menu_style(self):
        """\u6839\u636e theme_manager \u8c03\u6574\u83dc\u5355\u6837\u5f0f\u3002"""
        if not self._menu:
            return
        try:
            if self._theme_manager and getattr(self._theme_manager, "colors", None):
                c = self._theme_manager.colors
                bg = c.get("content_bg", "#1F2937")
                text = c.get("text", "#E5E7EB")
                border = c.get("group_border", "#374151")
                hover = c.get("btn_ghost_bg", "#4B5563")
                self._menu.setStyleSheet(
                    f"QMenu {{ background-color: {bg}; color: {text}; "
                    f"border: 1px solid {border}; padding: 4px; }}"
                    f"QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}"
                    f"QMenu::item:selected {{ background-color: {hover}; }}"
                    f"QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}"
                )
        except Exception:
            pass

    def update_comfyui_status(self, running):
        """\u66f4\u65b0\u83dc\u5355\u4e2d ComfyUI \u72b6\u6001\u7684\u6587\u6848\uff0c\u5e76\u540c\u6b65\u9000\u51fa\u5e76\u5173\u95ed\u9879\u7684\u53ef\u7528\u6027\u3002"""
        if self._status_action:
            try:
                self._status_action.setText(
                    "ComfyUI \u72b6\u6001: \u8fd0\u884c\u4e2d" if running else "ComfyUI \u72b6\u6001: \u672a\u542f\u52a8"
                )
            except Exception:
                pass
        if self._quit_and_stop_action:
            try:
                self._quit_and_stop_action.setEnabled(bool(running))
            except Exception:
                pass

    def show_first_time_hint(self):
        """\u7b2c\u4e00\u6b21\u7f29\u5230\u6258\u76d8\u65f6\u5f39\u51fa\u6c14\u6ce1\u63d0\u793a\u3002\u91cd\u590d\u8c03\u7528\u53ea\u89e6\u53d1\u4e00\u6b21\u3002"""
        if self._hint_shown or not self._tray:
            return
        self._hint_shown = True
        try:
            self._tray.showMessage(
                "ComfyUI \u542f\u52a8\u5668",
                "\u5df2\u6700\u5c0f\u5316\u5230\u7cfb\u7edf\u6258\u76d8\u3002\n\u53f3\u952e\u6258\u76d8\u56fe\u6807\u53ef\u9000\u51fa\u6216\u663e\u793a\u4e3b\u7a97\u53e3\u3002",
                QtWidgets.QSystemTrayIcon.Information,
                4000,
            )
        except Exception:
            pass

    def hide(self):
        """\u9690\u85cf\u6258\u76d8\u56fe\u6807\uff08\u4ec5\u5728\u4e0d\u53ef\u7528\u6216\u4e3b\u52a8\u7981\u7528\u65f6\u4f7f\u7528\uff09\u3002"""
        if self._tray:
            try:
                self._tray.hide()
            except Exception:
                pass

    def shutdown(self):
        """\u6700\u7ec8\u6e05\u7406\uff1a\u4ece\u7cfb\u7edf\u6258\u76d8\u79fb\u9664\u56fe\u6807\u5e76\u65ad\u5f00\u4fe1\u53f7\u3002"""
        if not self._tray:
            return
        try:
            self._tray.hide()
        except Exception:
            pass
        try:
            self._tray.deleteLater()
        except Exception:
            pass
        self._tray = None
        self._menu = None
        self._status_action = None
        self._show_action = None
        self._quit_action = None
        self._quit_and_stop_action = None
        self._available = False

    @property
    def available(self):
        return self._available
