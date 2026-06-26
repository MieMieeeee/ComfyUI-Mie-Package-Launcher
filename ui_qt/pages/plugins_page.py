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
    force_update_suggested = QtCore.pyqtSignal(list)  # 正常更新后仍有失败 → 建议强制更新（带名字）

    def __init__(self, app=None, theme_manager=None, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self._setup_ui()

    def _setup_ui(self):
        c = self.theme_manager.colors
        s = self.theme_manager.styles
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("插件管理（custom_nodes）")
        title.setStyleSheet(f"""
            font: bold 16pt "Microsoft YaHei UI";
            color: {c.get('label')};
            margin-bottom: 2px;
        """)
        layout.addWidget(title)

        hint = QtWidgets.QLabel(
            "勾选插件后可「更新选中」，或「更新全部」。从仓库直接同步的插件（如 MieNodes）"
            "正常更新失败时，会弹窗询问是否强制更新。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {c.get('label_dim')}; font: 9pt 'Microsoft YaHei UI';")
        layout.addWidget(hint)

        # 按钮行：刷新 / 更新全部 / 更新选中
        btn_row = QtWidgets.QHBoxLayout()
        self.refresh_btn = QtWidgets.QPushButton("刷新列表")
        self.update_all_btn = QtWidgets.QPushButton("更新全部")
        self.update_selected_btn = QtWidgets.QPushButton("更新选中")
        try:
            self.refresh_btn.setStyleSheet(s.secondary_button_style())
            self.update_all_btn.setStyleSheet(s.primary_button_style())
            self.update_selected_btn.setStyleSheet(s.primary_button_style())
        except Exception:
            pass
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        self.update_all_btn.clicked.connect(self.update_all_requested.emit)
        self.update_selected_btn.clicked.connect(self._emit_update_selected)
        for b in (self.refresh_btn, self.update_all_btn, self.update_selected_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 插件列表（可勾选）
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {c.get('input_bg')};
                color: {c.get('text')};
                border: 1px solid {c.get('input_border')};
                border-radius: 6px;
                padding: 4px;
                font: 10pt "Microsoft YaHei UI";
                outline: none;
            }}
            QListWidget::item {{ padding: 6px 8px; border-radius: 4px; }}
            QListWidget::item:hover {{ background-color: {c.get('group_bg')}; }}
            QListWidget::item:selected {{ background-color: {c.get('btn_primary_bg')}; color: #FFFFFF; }}
        """)
        layout.addWidget(self.list_widget)

    def _emit_update_selected(self):
        self.update_selected_requested.emit(self.selected_names())

    def populate(self, plugins):
        """用 PluginService.list_installed() 的结果填充列表。每项可勾选。"""
        self.list_widget.clear()
        for p in plugins:
            name = p.get("name", "?")
            item = QtWidgets.QListWidgetItem(name)
            item.setCheckState(QtCore.Qt.Unchecked)
            item.setData(QtCore.Qt.UserRole, p)
            if p.get("is_git"):
                ver = (p.get("version") or "")[:12]
                remote = p.get("remote_url") or ""
                tip = f"{name}\n版本: {ver or '(未知)'}\n来源: {remote or '(未知)'}"
            else:
                tip = f"{name}\n（非 git 插件，无法强制更新）"
            item.setToolTip(tip)
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
        failed = self.svc.outdated_plugins(names)
        if failed:
            self._post_to_ui(lambda: self.page.force_update_suggested.emit(failed))
        else:
            self._populate_from_service()

    def apply_force_update(self, names):
        """用户在二次确认弹窗里同意后调用：强制更新这些插件。"""
        self._run_in_background(lambda: self._force_update_work(names))

    def _force_update_work(self, names):
        self.svc.force_update_selected(names)
        self._populate_from_service()

    def _populate_from_service(self):
        """取最新已装列表并派回 UI 线程填充页面（刷新 / 更新后都用）。"""
        plugins = self.svc.list_installed()
        self._post_to_ui(lambda: self.page.populate(plugins))
