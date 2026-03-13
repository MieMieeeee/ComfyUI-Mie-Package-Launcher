"""
外置模型库管理页面
"""

from pathlib import Path
from PyQt5 import QtWidgets, QtCore, QtGui
from .base_page import BasePage
from ui_qt.widgets import InfoCard, StyledTableWidget, PrimaryButton
from ui_qt.theme_styles import ThemeStyles
from ui_qt.widgets.dialog_helper import DialogHelper


class ModelsPage(BasePage):
    """外置模型库管理页面"""

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self._page_title_refs = []
        self._setup_ui()

    def _setup_ui(self):
        """设置 UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        # 标题
        title = QtWidgets.QLabel("外置模型库管理")
        title.setStyleSheet(f"""
            font: bold 16pt "Microsoft YaHei UI";
            color: {self.theme_manager.colors.get('label')};
            margin-bottom: 5px;
        """)
        layout.addWidget(title)
        self._page_title_refs.append(title)

        # 配置卡片
        config_card = InfoCard("配置与映射", self.theme_manager.styles)
        layout.addWidget(config_card)

        # 配置内容
        config_layout = config_card.layout()
        config_layout.setSpacing(15)

        # 根路径选择行
        path_row = QtWidgets.QHBoxLayout()
        path_row.setSpacing(10)

        lbl_bp = QtWidgets.QLabel("模型库根路径:")
        lbl_bp.setStyleSheet(f"font-weight: bold; color: {self.theme_manager.colors.get('label')};")

        self.edit_base_path = QtWidgets.QLineEdit()
        self.edit_base_path.setReadOnly(True)
        self.edit_base_path.setStyleSheet(self.theme_manager.styles.input_style())
        self.edit_base_path.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.edit_base_path.setPlaceholderText("未配置")

        btn_sel_bp = QtWidgets.QPushButton("选择目录...")
        btn_sel_bp.setFixedWidth(100)
        btn_sel_bp.clicked.connect(self._select_base_path)

        path_row.addWidget(lbl_bp)
        path_row.addWidget(self.edit_base_path)
        path_row.addWidget(btn_sel_bp)

        config_layout.addLayout(path_row)

        # 动作按钮行
        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(15)

        btn_update = PrimaryButton("更新映射", self.theme_manager.styles)
        btn_update.setFixedWidth(120)
        btn_update.clicked.connect(self._update_mapping)

        btn_open_yaml = PrimaryButton("打开配置文件", self.theme_manager.styles)
        btn_open_yaml.setFixedWidth(120)
        btn_open_yaml.clicked.connect(self._open_yaml_file)

        btn_open_dir = PrimaryButton("打开模型库目录", self.theme_manager.styles)
        btn_open_dir.setFixedWidth(130)
        btn_open_dir.clicked.connect(self._open_model_dir)

        action_row.addWidget(btn_update)
        action_row.addWidget(btn_open_yaml)
        action_row.addWidget(btn_open_dir)
        action_row.addStretch(1)

        config_layout.addLayout(action_row)

        # 信息行
        info_row = QtWidgets.QHBoxLayout()
        info_row.setSpacing(15)

        self.lbl_count = QtWidgets.QLabel("当前已映射子文件夹: 0")
        self.lbl_count.setStyleSheet(f"color: {self.theme_manager.colors.get('label_muted')};")

        info_row.addWidget(self.lbl_count)
        info_row.addStretch(1)

        config_layout.addLayout(info_row)

        # 映射表格（置于卡片内）
        mapping_card = InfoCard("映射列表", self.theme_manager.styles)
        mapping_layout = mapping_card.layout()
        mapping_layout.setSpacing(10)

        self.table = StyledTableWidget(self.theme_manager.styles)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["名称", "路径"])
        self.table.setMinimumHeight(500)
        self.table.setWordWrap(True)
        try:
            self.table.setTextElideMode(QtCore.Qt.ElideNone)
        except Exception:
            pass
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        vheader = self.table.verticalHeader()
        vheader.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

        mapping_layout.addWidget(self.table)
        layout.addWidget(mapping_card)

        # 添加样式组件引用
        self._styled_widgets = [config_card, mapping_card, self.table, btn_update, btn_open_yaml, btn_open_dir]
        self._page_title_refs.append(lbl_bp)
        if hasattr(self.app, "_theme_widgets"):
            self.app._theme_widgets.extend(self._styled_widgets)

        # 初始刷新一次映射表（从映射文件读取）
        try:
            self.refresh_from_config()
        except Exception:
            pass

    def refresh_from_config(self):
        """从映射文件刷新显示（设置根目录后调用）"""
        try:
            # 检查映射文件是否存在
            if hasattr(self.app, 'services') and hasattr(self.app.services, 'model_path'):
                yaml_path = self.app.services.model_path._get_yaml_path()
                if yaml_path.exists():
                    # 映射文件存在，读取 base_path
                    base_path = self.app.services.model_path.get_external_path()
                    self.edit_base_path.setText(base_path or "")
                    # 刷新映射表
                    self._refresh_mapping_table()
                else:
                    # 映射文件不存在，清空显示
                    self.edit_base_path.setText("")
                    self.table.setRowCount(0)
                    self.lbl_count.setText("当前已映射子文件夹: 0")
            else:
                self.edit_base_path.setText("")
                self.table.setRowCount(0)
                self.lbl_count.setText("当前已映射子文件夹: 0")
        except Exception:
            self.edit_base_path.setText("")
            self.table.setRowCount(0)
            self.lbl_count.setText("当前已映射子文件夹: 0")

    def _select_base_path(self):
        """选择根目录"""
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择模型库根目录", self.edit_base_path.text() or ".")
        if d:
            try:
                # 规范化路径显示
                path_str = str(Path(d).resolve())
                self.edit_base_path.setText(path_str)
            except Exception:
                self.edit_base_path.setText(d)
            # 自动更新映射配置
            self._update_mapping()

    def _update_mapping(self):
        """更新映射配置"""
        try:
            path = self.edit_base_path.text().strip()
            if not hasattr(self.app, 'services') or not hasattr(self.app.services, 'model_path'):
                raise RuntimeError("model_path 服务不可用")
            success = self.app.services.model_path.update_mapping(path)
            if success:
                DialogHelper.show_info(self, "成功", "外置模型库映射已更新！\n请重启 ComfyUI 生效。")
            self._refresh_mapping_table()
        except Exception as e:
            DialogHelper.show_warning(self, "失败", f"更新映射配置失败：{e}")

    def _open_yaml_file(self):
        """打开配置文件"""
        try:
            if not hasattr(self.app, 'services') or not hasattr(self.app.services, 'model_path'):
                raise RuntimeError("model_path 服务不可用")
            yaml_path = self.app.services.model_path._get_yaml_path()
            if yaml_path.exists():
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(yaml_path)))
            else:
                DialogHelper.show_info(self, "提示", "配置文件 extra_model_paths.yaml 尚未创建。")
        except Exception as e:
            DialogHelper.show_warning(self, "失败", f"打开配置文件失败：{e}")

    def _open_model_dir(self):
        """打开模型库根目录"""
        base_path = self.edit_base_path.text().strip()
        if not base_path:
            DialogHelper.show_info(self, "提示", "请先设置模型库根目录。")
            return
        import os
        if os.path.isdir(base_path):
            import subprocess
            import platform
            try:
                if platform.system() == "Windows":
                    subprocess.Popen(['explorer', base_path])
                elif platform.system() == "Darwin":
                    subprocess.Popen(['open', base_path])
                else:
                    subprocess.Popen(['xdg-open', base_path])
            except Exception as e:
                DialogHelper.show_warning(self, "失败", f"打开目录失败：{e}")
        else:
            DialogHelper.show_warning(self, "失败", f"目录不存在：{base_path}")

    def _refresh_mapping_table(self):
        """刷新映射表格"""
        base_path = self.edit_base_path.text().strip()
        # 只有设置了根路径且映射文件存在时才显示映射
        if base_path and hasattr(self.app, 'services') and hasattr(self.app.services, 'model_path'):
            yaml_path = self.app.services.model_path._get_yaml_path()
            if yaml_path.exists():
                mappings = self.app.services.model_path.get_mappings_for_base(base_path)
            else:
                mappings = []
        else:
            mappings = []
        self.table.setRowCount(len(mappings))
        for i, (k, v) in enumerate(mappings):
            name_item = QtWidgets.QTableWidgetItem(k)
            name_item.setFlags(name_item.flags() & ~QtCore.Qt.ItemIsEditable)
            name_item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            self.table.setItem(i, 0, name_item)

            path_item = QtWidgets.QTableWidgetItem(v)
            path_item.setFlags(path_item.flags() & ~QtCore.Qt.ItemIsEditable)
            path_item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            path_item.setToolTip(v)
            self.table.setItem(i, 1, path_item)

        self.lbl_count.setText(f"当前已映射子文件夹: {len(mappings)}")

    def update_theme(self, theme_styles=None):
        """更新主题"""
        super().update_theme(theme_styles)
        # 更新标题颜色
        title_color = self.theme_manager.colors.get('label')
        for ref in self._page_title_refs:
            ref.setStyleSheet(ref.styleSheet().replace("color: #1F2937", f"color: {title_color}").replace("color: #FFFFFF", f"color: {title_color}"))

        # 更新配置卡片的样式
        for widget in self._styled_widgets:
            if hasattr(widget, 'update_theme'):
                widget.update_theme(self.theme_manager.styles)
