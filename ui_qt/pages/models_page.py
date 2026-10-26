"""
Multi-library external models page.
"""


from pathlib import Path
from PyQt5 import QtCore, QtGui, QtWidgets

from .base_page import BasePage
from ui_qt.widgets import (
    InfoCard, PrimaryButton, SecondaryButton, DestructiveButton,
    StyledLineEdit, StyledTableWidget,
)
from ui_qt.widgets.dialog_helper import DialogHelper


class _ProbeSignals(QtCore.QObject):
    """跨线程回传结果的信号载体。

    必须挂在 GUI 线程里的 QObject 上：连接建立时 PyQt 才会按「接收方所在
    线程」排队投递，槽函数也才会回到 GUI 线程执行。用 lambda 直连的话
    PyQt 走的是 DirectConnection，槽会在子线程里碰 UI 控件 —— 轻则更新
    不生效，重则整个窗口僵住。
    """

    probe_done = QtCore.pyqtSignal(object, object, object, object)  # token, lib_id, mappings, status


class _ApplySignals(QtCore.QObject):
    apply_done = QtCore.pyqtSignal(bool, object)  # ok, report


class _MappingProbeTask(QtCore.QRunnable):
    """后台扫描外置库目录。

    外置库可能指向局域网共享：目录大时扫描要几十秒，对端关机时又会等到
    SMB 超时。放在 GUI 线程里做，用户看到的就是「切到模型库管理页整窗
    无响应」。这里把它挪到线程池，结果通过信号回主线程刷新表格。
    """

    def __init__(self, service, token, lib_id, base_path, force, signals):
        super().__init__()
        self._service = service
        self._token = token
        self._lib_id = lib_id
        self._base_path = base_path
        self._force = force
        self._signals = signals

    def run(self):
        status = {}
        try:
            status = self._service.library_status(self._base_path, force=self._force)
        except Exception:
            status = {"base_path": self._base_path, "remote": False,
                      "reachable": True, "offline": False}
        mappings = []
        try:
            mappings = self._service.get_mappings_for_base(self._base_path)
        except Exception:
            mappings = []
        self._signals.probe_done.emit(self._token, self._lib_id, mappings, status)


class _ApplyTask(QtCore.QRunnable):
    """后台重写 extra_model_paths.yaml。

    写 yaml 前要扫描每个启用库的真实目录（网络库很慢），不能占着 GUI
    线程，否则「刷新/应用更改」按钮按下去整个窗口就没反应了。
    """

    def __init__(self, service, force, signals):
        super().__init__()
        self._service = service
        self._force = force
        self._signals = signals

    def run(self):
        ok = False
        try:
            try:
                ok = bool(self._service.apply_libraries(force=self._force))
            except TypeError:
                ok = bool(self._service.apply_libraries())
        except Exception:
            ok = False
        report = {"ok": ok, "skipped": []}
        try:
            report = self._service.get_apply_report() or report
        except Exception:
            pass
        self._signals.apply_done.emit(ok, report)


class ModelsPage(BasePage):
    """Multi-library external models page."""

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self._page_title_refs = []

        # DPI-aware token helpers (scale by current DPI factor).
        _styles = theme_manager.styles if theme_manager else None
        self._px = _styles._px if _styles else (lambda b: b)
        self._pt = _styles._pt if _styles else (lambda b: b)

        # Convenience handles
        self._model_path = getattr(self.app.services, "model_path", None)
        self._is_silent = False  # suppress listbox signal during bulk refresh
        # 后台任务：映射扫描 / yaml 重写都不在 GUI 线程做（网络库会卡死整窗）
        self._probe_token = 0
        self._probe_signals = None
        self._apply_busy = False
        self._apply_callback = None
        self._apply_pending = False
        self._apply_signals = None
        self._offline_ids = set()

        self.library_list = QtWidgets.QListWidget()
        self._library_list_min_width_base = 220
        self.library_list.setMinimumWidth(self._px(self._library_list_min_width_base))
        self._dpi_sized_widgets.append((self.library_list, "setMinimumWidth", self._library_list_min_width_base))
        self.library_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.library_list.setUniformItemSizes(True)
        # Theme-driven colors so the items stay legible in both light and dark modes.
        # Default PyQt palette paints near-black on the launcher's dark surfaces,
        # which is unreadable — we set the widget stylesheet + per-item foreground.
        c = self.theme_manager.colors
        label_color = c.get("label")
        label_muted_color = c.get("label_muted")
        content_bg = c.get("content_bg")
        sidebar_border = c.get("sidebar_border")
        self.library_list.setStyleSheet(
            "QListWidget {"
            " background: " + content_bg + ";"
            " border: 1px solid " + sidebar_border + ";"
            " color: " + label_color + ";"
            " padding: 4px;"
            "}"
            "QListWidget::item {"
            " color: " + label_color + ";"
            " padding: 6px 4px;"
            "}"
            "QListWidget::item:selected {"
            " background: rgba(120, 110, 220, 0.35);"
            " color: " + label_color + ";"
            "}"
            "QListWidget::item:hover {"
            " background: rgba(120, 110, 220, 0.18);"
            "}"
        )
        self._label_color = label_color
        self._label_muted_color = label_muted_color

        self.editor_panel = self._build_editor_panel()
        self.mapping_table = StyledTableWidget(self.theme_manager.styles)
        self.mapping_table.setColumnCount(2)
        self.mapping_table.setHorizontalHeaderLabels(["名称", "路径"])
        self._mapping_table_min_height_base = 360
        self.mapping_table.setMinimumHeight(self._px(self._mapping_table_min_height_base))
        self._dpi_sized_widgets.append((self.mapping_table, "setMinimumHeight", self._mapping_table_min_height_base))
        self.mapping_table.setWordWrap(True)
        try:
            self.mapping_table.setTextElideMode(QtCore.Qt.ElideNone)
        except Exception:
            pass
        header = self.mapping_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)

        # Persistent hint: the mapping table is a snapshot of disk. When the user
        # adds or removes folders inside the external library directory, the yaml
        # needs to be rewritten via "Apply Changes" to pick them up.
        self.mapping_hint_label = QtWidgets.QLabel(
            "提示：在外置库目录下新建或删除子文件夹后，请点击「应用更改」刷新映射并重写 yaml。"
        )
        self.mapping_hint_label.setWordWrap(True)
        self.mapping_hint_label.setStyleSheet(
            f"color: {self.theme_manager.colors.get('label_muted')};"
            " background: transparent;"
            f" font: {self._pt(9)}pt \"Microsoft YaHei UI\";"
            " padding-top: 4px;"
        )

        self.status_label = QtWidgets.QLabel("外置模型库: 0 / 启用: 0 / 默认: -")
        self.status_label.setStyleSheet(
            f"color: {self.theme_manager.colors.get('label_muted')};"
        )

        # 网络库状态行：显示「正在检测…」/「对端不可达」等。放在映射卡片里，
        # 不动 _global_actions_card 的既有布局（状态行 → 按钮 → 提示）。
        self.net_status_label = QtWidgets.QLabel("")
        self.net_status_label.setWordWrap(True)
        self.net_status_label.setStyleSheet(
            f"color: {self.theme_manager.colors.get('label_muted')};"
            " background: transparent;"
            f" font: {self._pt(9)}pt \"Microsoft YaHei UI\";"
        )
        self.net_status_label.setVisible(False)

        # Global action buttons. They live in _global_actions_card (top of page)
        # rather than in the per-library editor, because they manage either the
        # global library list (添加库 / 移除所选) or the shared
        # extra_model_paths.yaml (应用更改 / 打开 yaml) or the
        # recovery actions (仅使用内置 / 恢复配置) — none of
        # which depend on the currently selected library.
        self._btn_save = PrimaryButton("\u5237\u65b0/\u5e94\u7528\u66f4\u6539", self.theme_manager.styles)
        self._btn_open_yaml = PrimaryButton("\u6253\u5f00YAML\u6587\u4ef6", self.theme_manager.styles)
        self._btn_add = PrimaryButton("\u6dfb\u52a0\u5e93", self.theme_manager.styles)
        # \u79fb\u9664\u6240\u9009 is destructive \u2014 solid red, matching the \u9000\u51fa\u542f\u52a8\u5668
        # button in CustomConfirmDialog. Same color tokens as elsewhere in the app.
        self._btn_remove = DestructiveButton("\u79fb\u9664\u6240\u9009", self.theme_manager.styles)
        self._btn_builtin = PrimaryButton("\u4ec5\u4f7f\u7528\u5185\u7f6e", self.theme_manager.styles)
        self._btn_restore = PrimaryButton("\u6062\u590d\u914d\u7f6e", self.theme_manager.styles)
        self._btn_save.clicked.connect(self._save_current)
        self._btn_open_yaml.clicked.connect(self._open_yaml_file)
        self._btn_add.clicked.connect(self._on_add_library)
        self._btn_remove.clicked.connect(self._on_remove_library)
        self._btn_builtin.clicked.connect(self._on_use_builtin_only)
        self._btn_restore.clicked.connect(self._on_restore_config)

        self._styled_widgets = [self.editor_panel["card"], self.mapping_table]
        self._setup_layout()

        self.library_list.currentItemChanged.connect(self._on_library_selected)
        self.editor_panel["enable_check"].stateChanged.connect(self._on_enable_changed)
        self.editor_panel["default_check"].toggled.connect(self._on_default_toggled)
        self.editor_panel["name_edit"].editingFinished.connect(self._on_name_changed)
        self.editor_panel["open_dir_btn"].clicked.connect(self._open_model_dir)



        # status_label is now inside _global_actions_card (top of page); it uses
        # label_muted so it does not need to be in _page_title_refs (which tracks
        # label-color widgets for theme updates).

        # 移除所选 starts disabled if no library is registered yet.
        try:
            has_lib = bool(self._model_path and self._model_path.get_libraries())
        except Exception:
            has_lib = False
        self._btn_remove.setEnabled(has_lib)

        # First refresh.
        try:
            self.refresh_from_config()
        except Exception:
            pass

    def _setup_layout(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("外置模型库")
        title.setStyleSheet(
            f'font: bold {self._pt(16)}pt "Microsoft YaHei UI"; color: {self.theme_manager.colors.get("label")};'
        )
        layout.addWidget(title)
        self._page_title_refs.append(title)

        # Global actions card: groups the refresh hint together with the
        # buttons that read/write the shared extra_model_paths.yaml.
        # Same visual pattern as the kernel version management page'"'"'s
        # "当前版本信息" InfoCard.
        self._global_actions_card = InfoCard("全局操作", self.theme_manager.styles)
        global_layout = self._global_actions_card.layout()
        global_layout.setSpacing(10)
        # Status row goes first: at-a-glance current state (total / enabled /
        # default). The button row follows, then the hint sits BELOW the buttons
        # so the hint reads as a follow-up ("if you don't see what you expect,
        # click the button above").
        global_layout.addWidget(self.status_label)

        # Single button row in the order the user specified:
        # [刷新/应用更改] [打开YAML文件] [仅使用内置] [恢复配置] [添加库] [移除所选]
        # 5 primary (purple, same shape as elsewhere in the app) + 1 destructive
        # (solid red, same shape as the 退出启动器 confirm button).
        global_btn_row = QtWidgets.QHBoxLayout()
        global_btn_row.setSpacing(8)
        for b in (self._btn_save, self._btn_open_yaml,
                  self._btn_builtin, self._btn_restore,
                  self._btn_add, self._btn_remove):
            b.setFixedHeight(self._px(28))
            global_btn_row.addWidget(b)
        global_btn_row.addStretch(1)
        global_layout.addLayout(global_btn_row)

        global_layout.addWidget(self.mapping_hint_label)
        layout.addWidget(self._global_actions_card)

        # Main split
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.addWidget(self.library_list)
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        right_layout.addWidget(self.editor_panel["container"])
        mapping_card = InfoCard("映射列表", self.theme_manager.styles)
        mapping_card.layout().addWidget(self.net_status_label)
        mapping_card.layout().addWidget(self.mapping_table)
        right_layout.addWidget(mapping_card)
        split.addWidget(right_widget)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 740])
        layout.addWidget(split)

        # Theme widgets managed at app level
        if hasattr(self.app, "_theme_widgets"):
            self.app._theme_widgets.extend(self._styled_widgets)

    def _build_editor_panel(self):
        """Construct the right-side editor card; return dict of named child widgets."""
        card = InfoCard("库配置", self.theme_manager.styles)
        layout = card.layout()
        layout.setSpacing(8)

        # Name row
        name_row = QtWidgets.QHBoxLayout()
        name_row.addWidget(QtWidgets.QLabel("名称:"))
        name_edit = StyledLineEdit("", self.theme_manager.styles)
        name_edit.setPlaceholderText("库名（便于识别）")
        name_row.addWidget(name_edit, 1)
        layout.addLayout(name_row)

        # base_path row
        bp_row = QtWidgets.QHBoxLayout()
        bp_row.addWidget(QtWidgets.QLabel("路径:"))
        base_path_edit = StyledLineEdit("", self.theme_manager.styles)
        base_path_edit.setReadOnly(True)
        bp_row.addWidget(base_path_edit, 1)
        layout.addLayout(bp_row)

        # toggles
        toggle_row = QtWidgets.QHBoxLayout()
        enable_check = QtWidgets.QCheckBox("启用此库")
        default_check = QtWidgets.QCheckBox("作为默认库")
        toggle_row.addWidget(enable_check)
        toggle_row.addWidget(default_check)
        toggle_row.addStretch(1)
        layout.addLayout(toggle_row)

        # Per-library action button. All other action buttons (添加库 /
        # 移除所选 / 应用更改 / 打开 yaml) live in the top
        # _global_actions_card because they manage the global library list or
        # the shared extra_model_paths.yaml.
        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(8)
        open_dir_btn = SecondaryButton("打开目录", self.theme_manager.styles)
        action_row.addWidget(open_dir_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        return {
            "container": card,
            "card": card,
            "name_edit": name_edit,
            "base_path_edit": base_path_edit,
            "enable_check": enable_check,
            "default_check": default_check,
            "open_dir_btn": open_dir_btn,
        }

    # ---------- public API ----------

    def refresh_from_config(self):
        """Re-read app.services.model_path and repopulate the UI."""
        libs = []
        try:
            libs = self._model_path.get_libraries() if self._model_path else []
        except Exception:
            libs = []

        self._is_silent = True
        try:
            self.library_list.clear()
            for lib in libs:
                self._append_library_row(lib)
        finally:
            self._is_silent = False

        # Select default or first
        target = None
        for i, lib in enumerate(libs):
            if lib.get("is_default"):
                target = i
                break
        if target is None and libs:
            target = 0
        if target is not None:
            self.library_list.setCurrentRow(target)

        self._refresh_mapping_table()
        self._update_status(libs)

    def select_library(self, library_id):
        for i in range(self.library_list.count()):
            item = self.library_list.item(i)
            if item.data(QtCore.Qt.UserRole) == library_id:
                self.library_list.setCurrentRow(i)
                return True
        return False

    def selected_library_id(self):
        item = self.library_list.currentItem()
        if item is None:
            return None
        return item.data(QtCore.Qt.UserRole)

    def update_theme(self, theme_styles=None):
        super().update_theme(theme_styles)
        for w in self._styled_widgets:
            try:
                if hasattr(w, "update_theme"):
                    w.update_theme(self.theme_manager.styles)
            except Exception:
                pass

    # ---------- internal slots ----------

    def _append_library_row(self, lib):
        item = QtWidgets.QListWidgetItem()
        item.setText(self._row_text(lib, lib.get("id") in self._offline_ids))
        item.setData(QtCore.Qt.UserRole, lib["id"])
        # Per-item foreground so the row reads regardless of palette.
        color = self._label_muted_color if not lib.get("enabled") else self._label_color
        item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
        tip = lib.get("base_path", "")
        item.setToolTip(tip)
        self.library_list.addItem(item)

    def _on_library_selected(self, current, _previous):
        if self._is_silent or current is None:
            return
        lib = self._find_lib_by_id(current.data(QtCore.Qt.UserRole))
        self._populate_editor(lib)
        self._refresh_mapping_table()

    def _find_lib_by_id(self, library_id):
        if not self._model_path:
            return None
        for lib in self._model_path.get_libraries():
            if lib.get("id") == library_id:
                return lib
        return None

    def _populate_editor(self, lib):
        self._is_silent = True
        try:
            # All remaining global action buttons (应用更改 / 添加库 /
            # 打开 yaml / 仅使用内置 / 恢复配置) live in
            # _global_actions_card and stay enabled regardless of selection.
            # 移除所选 needs a selection, so it is toggled here.
            per_lib_keys = ("name_edit", "base_path_edit", "enable_check", "default_check",
                            "open_dir_btn")
            if lib is None:
                self.editor_panel["name_edit"].setText("")
                self.editor_panel["base_path_edit"].setText("")
                self.editor_panel["enable_check"].setChecked(False)
                self.editor_panel["default_check"].setChecked(False)
                for k in per_lib_keys:
                    self.editor_panel[k].setEnabled(False)
                self._btn_remove.setEnabled(False)
                return
            for k in per_lib_keys:
                self.editor_panel[k].setEnabled(True)
            self._btn_remove.setEnabled(True)
            self.editor_panel["name_edit"].setText(lib.get("name", ""))
            self.editor_panel["base_path_edit"].setText(lib.get("base_path", ""))
            self.editor_panel["enable_check"].setChecked(bool(lib.get("enabled")))
            self.editor_panel["default_check"].setChecked(bool(lib.get("is_default")))
        finally:
            self._is_silent = False

    def _on_enable_changed(self, _state):
        if self._is_silent:
            return
        lib_id = self.selected_library_id()
        if not lib_id or not self._model_path:
            return
        self._model_path.enable_library(lib_id, bool(self.editor_panel["enable_check"].isChecked()))
        # 勾选框就是「应用更改」的语义：写完 config 必须立刻重写 yaml，
        # 否则 config 说禁用、ComfyUI 仍读着旧块加载该库的路径（静默失败）。
        # 只重写被勾选的那个库（only_ids），其余库沿用 yaml 里已有的块 ——
        # 免得每勾一次就去重扫所有共享（网络库扫一次好几秒）。
        try:
            ok = self._model_path.apply_libraries(only_ids=[lib_id])
        except TypeError:
            ok = self._model_path.apply_libraries()
        if ok:
            try:
                self._model_path.clear_drift_notice()
            except Exception:
                pass
            self._save_config()
        self.refresh_from_config()

    # ---------- 后台重写 yaml ----------

    def _apply_libraries_async(self, on_done=None, force=False):
        """后台重写 extra_model_paths.yaml，完成后回到主线程收尾。"""
        if not self._model_path:
            return
        if self._apply_busy:
            # 已经在写了：记一笔，等这一轮结束后再补一次（用户连点时不能丢）
            self._apply_pending = True
            return
        self._apply_busy = True
        self._apply_callback = on_done
        self._set_busy(True)
        signals = _ApplySignals(self)
        self._apply_signals = signals
        signals.apply_done.connect(self._on_apply_done)
        task = _ApplyTask(self._model_path, force, signals)
        QtCore.QThreadPool.globalInstance().start(task)

    def _on_apply_done(self, ok, report):
        callback = self._apply_callback
        self._apply_callback = None
        self._apply_busy = False
        self._set_busy(False)
        skipped = (report or {}).get("skipped") or []
        if ok:
            try:
                self._model_path.clear_drift_notice()
            except Exception:
                pass
            self._save_config()
        self.refresh_from_config()
        # 强制重探一次可达性：NAS 可能刚刚开机，映射表要跟着更新
        try:
            self._refresh_mapping_table(force=True)
        except Exception:
            pass
        if skipped:
            names = "、".join(
                lib.get("name") or lib.get("base_path", "") for lib in skipped
            )
            DialogHelper.show_warning(
                self, "部分库未刷新",
                f"以下外置模型库当前无法访问（对端未开机或共享不可用）：\n\n{names}\n\n"
                "已保留它们原有的配置，本次没有刷新映射。\n等对方机器开机后再点「刷新/应用更改」即可。")
        if callback:
            try:
                callback(ok, report)
            except Exception:
                pass
        if self._apply_pending:
            self._apply_pending = False
            self._apply_libraries_async()

    def _set_busy(self, busy):
        for b in (self._btn_save, self._btn_open_yaml, self._btn_add,
                  self._btn_remove, self._btn_builtin, self._btn_restore):
            try:
                b.setEnabled(not busy)
            except Exception:
                pass
        if busy:
            self._btn_save.setText("应用中…")
        else:
            self._btn_save.setText("刷新/应用更改")
            # 「移除所选」依赖当前选中项，别被 busy 收尾时顺手打开
            try:
                self._btn_remove.setEnabled(bool(self.selected_library_id()))
            except Exception:
                pass

    def _on_default_toggled(self, checked):
        if self._is_silent:
            return
        lib_id = self.selected_library_id()
        if not lib_id or not checked:
            return
        if self._model_path:
            self._model_path.set_default_library(lib_id)
        self.refresh_from_config()

    def _on_name_changed(self):
        if self._is_silent:
            return
        lib_id = self.selected_library_id()
        if not lib_id or not self._model_path:
            return
        new_name = self.editor_panel["name_edit"].text().strip()
        if not new_name:
            return
        self._model_path.update_library(lib_id, name=new_name)
        self._save_config()
        self.refresh_from_config()

    def _save_current(self):
        """Apply current form state to the model and persist."""
        lib_id = self.selected_library_id()
        if not lib_id or not self._model_path:
            return
        name = self.editor_panel["name_edit"].text().strip() or None
        enabled = self.editor_panel["enable_check"].isChecked()
        is_default = self.editor_panel["default_check"].isChecked()
        kwargs = {}
        if name is not None:
            kwargs["name"] = name
        kwargs["enabled"] = enabled
        kwargs["is_default"] = is_default
        self._model_path.update_library(lib_id, **kwargs)
        if is_default:
            self._model_path.set_default_library(lib_id)
        # 写 yaml 要扫描各库目录（网络库可能很慢），后台做，页面不卡。
        # force=True：绕过可达性缓存重新探一次（用户可能刚把 NAS 开机）。
        self._apply_libraries_async(force=True)
        self.refresh_from_config()

    def _on_add_library(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择模型库根目录", ".")
        if not d:
            return
        try:
            # 网络路径不做 Path.resolve()（Windows 上会真的去问网络，对端关机即卡死）
            resolved = self._model_path._safe_resolve(d) if self._model_path else str(Path(d).resolve())
            p = Path(resolved)
        except Exception:
            p = Path(d)
        name = p.name or "library"
        lib = self._model_path.add_library(str(p), name=name) if self._model_path else None
        if lib:
            self.select_library(lib["id"])
            self.refresh_from_config()

            def _added(ok, _report):
                DialogHelper.show_info(self, "已添加",
                    f"已添加库: {lib['name']}\n请重启 ComfyUI 生效。\n\n后续在外置库目录下新建或删除子文件夹，\n需要再次点击「应用更改」刷新映射。")

            # 写 yaml 要扫描各库目录（网络库可能很慢），后台做，页面不卡。
            self._apply_libraries_async(on_done=_added)

    def _on_remove_library(self):
        lib_id = self.selected_library_id()
        if not lib_id:
            return
        if not self._model_path:
            return
        if not DialogHelper.show_confirmation(self, "确认", "移除所选模型库？此操作不会删除磁盘文件。"):
            return
        self._model_path.remove_library(lib_id)
        self._apply_libraries_async()
        self.refresh_from_config()

    def _on_use_builtin_only(self):
        """Toggle all libs to disabled and persist (legacy UX)."""
        if not self._model_path:
            return
        for lib in self._model_path.get_libraries():
            self._model_path.enable_library(lib["id"], enabled=False)
        bak = self._model_path._get_yaml_path()
        if bak.exists():
            import shutil
            shutil.copy2(bak, bak.with_suffix(".yaml.disabled_bak"))
            bak.unlink()
        self.app.config.setdefault("models", {})["disable_external"] = True
        self._save_config()
        self.refresh_from_config()
        DialogHelper.show_info(self, "已切换", "已切换为仅使用内置模型库，\n原配置已备份。")

    def _on_restore_config(self):
        if not self._model_path:
            return
        yp = self._model_path._get_yaml_path()
        bak = yp.with_suffix(".yaml.disabled_bak")
        if bak.exists():
            import shutil
            shutil.copy2(bak, yp)
            bak.unlink()
        self.app.config["models"]["disable_external"] = False
        if hasattr(self._model_path, "clear_drift_notice"):
            self._model_path.clear_drift_notice()
        self._save_config()
        self.refresh_from_config()
        DialogHelper.show_info(self, "已恢复", "外置模型库配置已恢复。")

    def _open_yaml_file(self):
        if not self._model_path:
            return
        yp = self._model_path._get_yaml_path()
        if yp.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(yp)))
        else:
            DialogHelper.show_info(self, "提示", "配置文件 extra_model_paths.yaml 尚未创建。")

    def _open_model_dir(self):
        lib_id = self.selected_library_id()
        lib = self._find_lib_by_id(lib_id) if lib_id else None
        base_path = lib.get("base_path", "") if lib else ""
        if not base_path:
            DialogHelper.show_info(self, "提示", "请先选择一个库再打开目录。")
            return
        import os, subprocess, platform
        # 有界检查：网络库对端关机时 os.path.isdir 会等 SMB 超时，卡住整个窗口
        try:
            exists = self._model_path._path_is_dir(base_path) if self._model_path \
                else os.path.isdir(base_path)
        except Exception:
            exists = False
        if exists:
            try:
                if platform.system() == "Windows":
                    subprocess.Popen(["explorer", base_path])
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", base_path])
                else:
                    subprocess.Popen(["xdg-open", base_path])
            except Exception as e:
                DialogHelper.show_warning(self, "失败", f"打开目录失败: {e}")
        else:
            DialogHelper.show_warning(self, "失败", f"目录不存在: {base_path}")

    def _refresh_mapping_table(self, force=False):
        lib_id = self.selected_library_id()
        lib = self._find_lib_by_id(lib_id) if lib_id else None
        if not lib or not self._model_path:
            self.mapping_table.setRowCount(0)
            self._set_net_status(None)
            return
        base_path = lib.get("base_path", "")
        if not base_path:
            self.mapping_table.setRowCount(0)
            self._set_net_status(None)
            return

        # 网络路径：目录扫描放到后台线程。对端关机时扫描要等 SMB 超时，
        # 放 GUI 线程里就是「切到这一页整窗没反应」。
        try:
            remote = bool(self._model_path.is_remote_path(base_path))
        except Exception:
            remote = False
        if remote:
            self._start_probe(lib_id, base_path, force=force)
            return

        try:
            mappings = self._model_path.get_mappings_for_base(base_path)
        except Exception:
            mappings = []
        self._populate_mapping_table(mappings)
        self._set_net_status({"base_path": base_path, "remote": False,
                               "reachable": True, "offline": False})
        self._mark_offline(lib_id, False)

    def _populate_mapping_table(self, mappings):
        self.mapping_table.setRowCount(len(mappings))
        for i, (k, v) in enumerate(mappings):
            name_item = QtWidgets.QTableWidgetItem(k)
            name_item.setFlags(name_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.mapping_table.setItem(i, 0, name_item)
            path_item = QtWidgets.QTableWidgetItem(v)
            path_item.setFlags(path_item.flags() & ~QtCore.Qt.ItemIsEditable)
            path_item.setToolTip(v)
            self.mapping_table.setItem(i, 1, path_item)

    # ---------- 网络库后台探测 ----------

    def _start_probe(self, lib_id, base_path, force=False):
        self._probe_token += 1
        token = self._probe_token
        self._set_net_status({"base_path": base_path, "remote": True,
                               "checking": True, "offline": False})
        # 信号载体挂在页面（GUI 线程）上 → 结果会排队回到 GUI 线程再刷新 UI
        signals = _ProbeSignals(self)
        self._probe_signals = signals
        signals.probe_done.connect(self._on_probe_done)
        task = _MappingProbeTask(self._model_path, token, lib_id, base_path,
                                 force, signals)
        QtCore.QThreadPool.globalInstance().start(task)

    def _on_probe_done(self, token, lib_id, mappings, status):
        if token != self._probe_token:
            return  # 过期结果：用户已经切到别的库了
        self._populate_mapping_table(mappings)
        self._set_net_status(status)
        self._mark_offline(lib_id, bool(status.get("offline")))

    def _set_net_status(self, status):
        if not status:
            self.net_status_label.setText("")
            self.net_status_label.setVisible(False)
            return
        base_path = status.get("base_path", "")
        if status.get("checking"):
            text = f"正在检测网络库 {base_path} …（对端较慢时可能需要几秒）"
            color = self.theme_manager.colors.get("label_muted")
        elif status.get("offline"):
            text = (f"⚠ {base_path} 当前无法访问（对端未开机 / 共享不可用）。"
                    f"已保留原有配置，未刷新该库的映射。")
            color = self.theme_manager.colors.get("warning")
        elif status.get("remote"):
            text = f"已连接 {base_path}"
            color = self.theme_manager.colors.get("label_muted")
        else:
            text = ""
            color = self.theme_manager.colors.get("label_muted")
        self.net_status_label.setStyleSheet(
            f"color: {color}; background: transparent;"
            f" font: {self._pt(9)}pt \"Microsoft YaHei UI\";"
        )
        self.net_status_label.setText(text)
        self.net_status_label.setVisible(bool(text))

    def _mark_offline(self, lib_id, offline):
        if not lib_id:
            return
        if offline:
            self._offline_ids.add(lib_id)
        else:
            self._offline_ids.discard(lib_id)
        lib = self._find_lib_by_id(lib_id)
        if not lib:
            return
        for i in range(self.library_list.count()):
            item = self.library_list.item(i)
            if item.data(QtCore.Qt.UserRole) == lib_id:
                item.setText(self._row_text(lib, offline))
                break

    def _row_text(self, lib, offline=False):
        prefix = "★ " if lib.get("is_default") else "  "
        flag = "" if lib.get("enabled") else " (停用)"
        if offline:
            flag += " ⚠离线"
        return f"{prefix}{lib.get('name', '(未命名)')}{flag}"

    def _update_status(self, libs):
        total = len(libs)
        enabled = sum(1 for l in libs if l.get("enabled"))
        default = next((l.get("name", "-") for l in libs if l.get("is_default")), "-")
        self.status_label.setText(f"外置模型库: {total} | 启用: {enabled} | 默认: {default}")

    def _save_config(self):
        try:
            cfg = getattr(self.app.services, "config", None)
            if cfg and hasattr(cfg, "save"):
                cfg.save(self.app.config)
        except Exception:
            pass
