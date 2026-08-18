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
        prefix = "★ " if lib.get("is_default") else "  "
        flag = "" if lib.get("enabled") else " (停用)"
        item.setText(f"{prefix}{lib.get('name', '(未命名)')}{flag}")
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
        if not lib_id:
            return
        if self._model_path:
            self._model_path.enable_library(lib_id, bool(self.editor_panel["enable_check"].isChecked()))
        self.refresh_from_config()

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
        if self._model_path.apply_libraries():
            self._save_config()
        self.refresh_from_config()

    def _on_add_library(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择模型库根目录", ".")
        if not d:
            return
        try:
            p = Path(d).resolve()
            if p.name.lower() == "models":
                pass
        except Exception:
            p = Path(d)
        name = p.name or "library"
        lib = self._model_path.add_library(str(p), name=name) if self._model_path else None
        if lib:
            if self._model_path:
                self._model_path.apply_libraries()
            self._save_config()
            self.select_library(lib["id"])
            self.refresh_from_config()
            DialogHelper.show_info(self, "已添加",
                f"已添加库: {lib['name']}\n请重启 ComfyUI 生效。\n\n后续在外置库目录下新建或删除子文件夹，\n需要再次点击「应用更改」刷新映射。")

    def _on_remove_library(self):
        lib_id = self.selected_library_id()
        if not lib_id:
            return
        if not self._model_path:
            return
        if not DialogHelper.show_confirmation(self, "确认", "移除所选模型库？此操作不会删除磁盘文件。"):
            return
        self._model_path.remove_library(lib_id)
        if self._model_path.apply_libraries():
            self._save_config()
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
        if os.path.isdir(base_path):
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

    def _refresh_mapping_table(self):
        lib_id = self.selected_library_id()
        lib = self._find_lib_by_id(lib_id) if lib_id else None
        if not lib or not self._model_path:
            self.mapping_table.setRowCount(0)
            return
        try:
            mappings = self._model_path.get_mappings_for_base(lib.get("base_path", ""))
        except Exception:
            mappings = []
        self.mapping_table.setRowCount(len(mappings))
        for i, (k, v) in enumerate(mappings):
            name_item = QtWidgets.QTableWidgetItem(k)
            name_item.setFlags(name_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.mapping_table.setItem(i, 0, name_item)
            path_item = QtWidgets.QTableWidgetItem(v)
            path_item.setFlags(path_item.flags() & ~QtCore.Qt.ItemIsEditable)
            path_item.setToolTip(v)
            self.mapping_table.setItem(i, 1, path_item)

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
