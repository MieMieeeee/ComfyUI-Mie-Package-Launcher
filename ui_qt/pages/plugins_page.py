"""插件（custom_nodes）管理页面 —— 纯 UI + 信号。

页面职责：展示已装插件列表 + 勾选 + 通过信号请求操作。
- populate(plugins)：填充列表（plugins 来自 PluginService.list_installed）
- 信号 update_all_requested / update_selected_requested(list) / refresh_requested
  由控制器（qt_app）接线到 PluginService（后台线程 + 进度）。

页面不直接调 PluginService，也不 import qt_app —— 这样可在 offscreen 下单测。
"""
from PyQt5 import QtCore, QtWidgets

from .base_page import BasePage


class PluginsPage(BasePage):
    """插件管理页面：列已装、勾选、请求更新全部/选中/刷新。"""

    update_all_requested = QtCore.pyqtSignal()
    update_selected_requested = QtCore.pyqtSignal(list)
    refresh_requested = QtCore.pyqtSignal()

    def __init__(self, app=None, theme_manager=None, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("插件管理（custom_nodes）")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # 按钮行：刷新 / 更新全部 / 更新选中
        btn_row = QtWidgets.QHBoxLayout()
        self.refresh_btn = QtWidgets.QPushButton("刷新列表")
        self.update_all_btn = QtWidgets.QPushButton("更新全部")
        self.update_selected_btn = QtWidgets.QPushButton("更新选中")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        self.update_all_btn.clicked.connect(self.update_all_requested.emit)
        self.update_selected_btn.clicked.connect(self._emit_update_selected)
        for b in (self.refresh_btn, self.update_all_btn, self.update_selected_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 插件列表（可勾选）
        self.list_widget = QtWidgets.QListWidget()
        layout.addWidget(self.list_widget)

    def _emit_update_selected(self):
        self.update_selected_requested.emit(self.selected_names())

    def populate(self, plugins):
        """用 PluginService.list_installed() 的结果填充列表。每项可勾选。"""
        self.list_widget.clear()
        for p in plugins:
            item = QtWidgets.QListWidgetItem(p.get("name", "?"))
            item.setCheckState(QtCore.Qt.Unchecked)
            item.setData(QtCore.Qt.UserRole, p)
            self.list_widget.addItem(item)

    def plugin_names(self):
        return [self.list_widget.item(i).text() for i in range(self.list_widget.count())]

    def selected_names(self):
        """返回当前勾选的插件名。"""
        names = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                names.append(item.text())
        return names


class PluginController:
    """把 PluginsPage 的信号编排到 PluginService（可单测）。

    依赖注入：run_in_background(fn) 把 fn 丢到工作线程；post_to_ui(fn) 把 fn
    派回 UI 线程。qt_app 侧注入真实现（QThread + signal），测试注入同步替身。
    页面信号→服务调用→更新后刷新 的编排都在这里，故不依赖 qt_app、可 offscreen 测。
    """

    def __init__(self, page, plugin_service, run_in_background, post_to_ui):
        self.page = page
        self.svc = plugin_service
        self._run_in_background = run_in_background
        self._post_to_ui = post_to_ui
        page.refresh_requested.connect(self._on_refresh)
        page.update_all_requested.connect(self._on_update_all)
        page.update_selected_requested.connect(self._on_update_selected)

    def _on_refresh(self):
        self._run_in_background(self._refresh_work)

    def _refresh_work(self):
        self._populate_from_service()

    def _on_update_all(self):
        self._run_in_background(self._update_all_work)

    def _update_all_work(self):
        self.svc.update_all()
        self._populate_from_service()

    def _on_update_selected(self, names):
        self._run_in_background(lambda: self._update_selected_work(names))

    def _update_selected_work(self, names):
        self.svc.update_selected(names)
        self._populate_from_service()

    def _populate_from_service(self):
        """取最新已装列表并派回 UI 线程填充页面（刷新 / 更新后都用）。"""
        plugins = self.svc.list_installed()
        self._post_to_ui(lambda: self.page.populate(plugins))
