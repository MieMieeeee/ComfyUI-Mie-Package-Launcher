"""环境管理区块（设置页用）。

多环境支持：列表展示所有 ComfyUI 环境，支持新增 / 编辑 / 删除 / 设为激活。
至少保留 1 个环境（删最后一个会被拒绝）。

一个环境 = 一个 comfyui_root + 一个 python_path 的组合。
数据存在 config["environments"] 数组里，config["active_env_id"] 指向当前激活的。
"""
from pathlib import Path

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt, pyqtSignal

from config.migrations import make_env_id
from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
from ui_qt.widgets.frameless_draggable_dialog import FramelessDraggableDialog


class EnvironmentManagerSection(QtWidgets.QWidget):
    """环境管理控件：列表 + 增删改 + 设为激活。

    修改后直接写回 config["environments"] 并落盘（走 services.config.save）。
    不负责切换激活环境后刷新启动页显示——那是 LaunchPage 的职责。
    """

    # 环境列表发生变化（新增/编辑/删除/设为激活）后发出。
    # 由 qt_app 连接到启动页 EnvironmentSelector.reload()，让下拉框同步。
    environments_changed = pyqtSignal()
    # 激活环境被切换（_on_activate）后发出。
    # 由 qt_app 连接到 app.refresh_after_env_switch()，集中刷新所有依赖环境路径的页面。
    # 与 environments_changed 分开：增删改环境不需要全页刷新（耗时的插件/模型重扫），
    # 只有切换激活环境才需要。
    active_env_changed = pyqtSignal()

    def __init__(self, app_context, theme_manager=None, parent=None):
        super().__init__(parent)
        self.app = app_context
        self.theme_manager = theme_manager
        # DPI-aware token helpers (scale by current DPI factor).
        _styles = theme_manager.styles if theme_manager else None
        self._px = _styles._px if _styles else (lambda b: b)
        self._pt = _styles._pt if _styles else (lambda b: b)
        self._setup_ui()
        self.reload()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 主题色：和 models_page 的 library_list 保持一致，确保深/浅色都可读
        c = self.theme_manager.colors if self.theme_manager else {}
        self._label_color = c.get("label", "#E5E7EB")
        self._label_muted_color = c.get("label_muted", "#9CA3AF")
        content_bg = c.get("content_bg", "#1F2937")
        sidebar_border = c.get("sidebar_border", "#374151")

        # 说明文字
        hint = QtWidgets.QLabel(
            "一个环境 = 一个 ComfyUI 根目录 + python 路径的组合。"
            "启动页顶部的下拉可快速切换激活环境。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {self._label_muted_color}; font-size: {self._pt(9)}pt; background: transparent;"
        )
        layout.addWidget(hint)

        # 环境列表 —— 样式与 models_page 的 library_list 完全一致
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setMinimumHeight(self._px(120))
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setStyleSheet(
            "QListWidget {"
            " background: " + content_bg + ";"
            " border: 1px solid " + sidebar_border + ";"
            " color: " + self._label_color + ";"
            " padding: 4px;"
            " outline: none;"
            "}"
            "QListWidget::item {"
            " color: " + self._label_color + ";"
            " padding: 6px 4px;"
            "}"
            "QListWidget::item:selected {"
            " background: rgba(120, 110, 220, 0.35);"
            " color: " + self._label_color + ";"
            "}"
            "QListWidget::item:hover {"
            " background: rgba(120, 110, 220, 0.18);"
            "}"
        )
        layout.addWidget(self.list_widget)

        # 按钮行 —— 统一用主题样式（secondary / destructive_outline）
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(8)
        secondary_style = ""
        destructive_style = ""
        try:
            if self.theme_manager and hasattr(self.theme_manager, "styles"):
                secondary_style = self.theme_manager.styles.secondary_button_style()
                destructive_style = self.theme_manager.styles.destructive_outline_button_style()
        except Exception:
            pass

        btn_add = QtWidgets.QPushButton("新增环境")
        btn_add.setCursor(Qt.PointingHandCursor)
        if secondary_style:
            btn_add.setStyleSheet(secondary_style)
        btn_add.clicked.connect(self._on_add)
        btn_row.addWidget(btn_add)

        btn_edit = QtWidgets.QPushButton("编辑选中")
        btn_edit.setCursor(Qt.PointingHandCursor)
        if secondary_style:
            btn_edit.setStyleSheet(secondary_style)
        btn_edit.clicked.connect(self._on_edit)
        btn_row.addWidget(btn_edit)

        btn_activate = QtWidgets.QPushButton("设为激活")
        btn_activate.setCursor(Qt.PointingHandCursor)
        if secondary_style:
            btn_activate.setStyleSheet(secondary_style)
        btn_activate.clicked.connect(self._on_activate)
        btn_row.addWidget(btn_activate)

        btn_delete = QtWidgets.QPushButton("删除选中")
        btn_delete.setCursor(Qt.PointingHandCursor)
        if destructive_style:
            btn_delete.setStyleSheet(destructive_style)
        btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(btn_delete)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    # ---------- 数据读写 ----------

    def _get_envs(self):
        cfg = getattr(self.app, "config", None) or {}
        envs = cfg.get("environments") if isinstance(cfg, dict) else None
        if not isinstance(envs, list):
            envs = []
        return envs

    def _get_active_id(self):
        cfg = getattr(self.app, "config", None) or {}
        return cfg.get("active_env_id") if isinstance(cfg, dict) else None

    def _save_envs(self, envs, active_id=None):
        """写回 environments（和可选的 active_env_id）并落盘。"""
        cfg = self.app.config
        cfg["environments"] = envs
        if active_id is not None:
            cfg["active_env_id"] = active_id
        elif cfg.get("active_env_id") not in {e.get("id") for e in envs}:
            # active 失配，指向第一个
            cfg["active_env_id"] = envs[0].get("id") if envs else None
        services = getattr(self.app, "services", None)
        if services is not None and getattr(services, "config", None) is not None:
            saved = services.config.save(cfg)
            if saved is not None:
                self.app.config = saved
        # 通知启动页环境选择器：环境列表变了，重新加载下拉项
        self.environments_changed.emit()

    def reload(self):
        """从 config 重新加载列表。"""
        self.list_widget.clear()
        envs = self._get_envs()
        active_id = self._get_active_id()
        # 主题色（per-item 前景色，确保文字可读，和 models_page 做法一致）
        accent = ""
        try:
            if self.theme_manager and hasattr(self.theme_manager, "colors"):
                accent = self.theme_manager.colors.get("accent", "#6366F1")
        except Exception:
            pass
        for env in envs:
            name = env.get("name") or env.get("id") or "未命名"
            root = env.get("comfyui_root", "?")
            label = f"{name}  —  {root}"
            is_active = env.get("id") == active_id
            if is_active:
                label = f"★ {label}  (当前激活)"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(Qt.UserRole, env.get("id"))
            # 设前景色：激活行用 accent 色加粗感，其他用 label 色
            color_str = accent if (is_active and accent) else self._label_color
            try:
                from PyQt5 import QtGui
                item.setForeground(QtGui.QColor(color_str))
            except Exception:
                pass
            self.list_widget.addItem(item)

    # ---------- 操作 ----------

    def _selected_env(self):
        """返回当前选中的 (index, env_dict)，没选中返回 (None, None)。"""
        row = self.list_widget.currentRow()
        if row < 0:
            return None, None
        envs = self._get_envs()
        if row >= len(envs):
            return None, None
        return row, envs[row]

    def _on_add(self):
        envs = self._get_envs()
        existing_ids = {e.get("id") for e in envs}
        data = _EnvEditDialog.edit(
            self,
            title="新增环境",
            initial_name="",
            initial_root="",
            initial_python="",
            existing_ids=existing_ids,
            theme_manager=self.theme_manager,
        )
        if data is None:
            return
        new_env = {
            "id": make_env_id(data["name"], existing_ids),
            "name": data["name"],
            "comfyui_root": data["root"],
            "python_path": data["python"],
        }
        envs.append(new_env)
        self._save_envs(envs)
        self.reload()
        # 选中新加的
        self.list_widget.setCurrentRow(len(envs) - 1)

    def _on_edit(self):
        row, env = self._selected_env()
        if env is None:
            CustomConfirmDialog(
                parent=self, title="提示", content="请先在列表中选择一个环境。",
                buttons=[{"text": "知道了", "role": "primary"}],
                theme_manager=self.theme_manager,
            ).exec_()
            return
        envs = self._get_envs()
        existing_ids = {e.get("id") for e in envs}
        existing_ids.discard(env.get("id"))  # 编辑自己时不算冲突
        data = _EnvEditDialog.edit(
            self,
            title=f"编辑环境：{env.get('name', '')}",
            initial_name=env.get("name", ""),
            initial_root=env.get("comfyui_root", ""),
            initial_python=env.get("python_path", ""),
            existing_ids=existing_ids,
            theme_manager=self.theme_manager,
        )
        if data is None:
            return
        envs[row] = {
            "id": env.get("id") or make_env_id(data["name"], existing_ids),
            "name": data["name"],
            "comfyui_root": data["root"],
            "python_path": data["python"],
        }
        self._save_envs(envs)
        self.reload()
        self.list_widget.setCurrentRow(row)

    def _on_activate(self):
        row, env = self._selected_env()
        if env is None:
            CustomConfirmDialog(
                parent=self, title="提示", content="请先在列表中选择一个环境。",
                buttons=[{"text": "知道了", "role": "primary"}],
                theme_manager=self.theme_manager,
            ).exec_()
            return
        # 切换激活前检查：有进行中的后台任务 → 直接阻止（不能强杀 git/cm-cli 子进程）
        if self._has_active_background_tasks():
            CustomConfirmDialog(
                parent=self,
                title="无法切换环境",
                content="有后台任务正在进行（更新内核 / 更新插件 / 检查更新等）。\n"
                        "请等待任务完成，或在「后台任务」页面取消后再切换环境。",
                buttons=[{"text": "知道了", "role": "primary"}],
                theme_manager=self.theme_manager,
            ).exec_()
            return
        # 切换激活前检查是否在跑 → 确认是否自动停止后切换
        if self._is_running():
            dlg = CustomConfirmDialog(
                parent=self,
                title="切换环境",
                content="当前已有 ComfyUI 服务正在运行，切换激活环境会关闭当前服务。\n是否继续？",
                buttons=[
                    {"text": "取消", "role": "normal"},
                    {"text": "切换", "role": "primary"},
                ],
                default_index=0,
                theme_manager=self.theme_manager,
            )
            if not (dlg.exec_() == QtWidgets.QDialog.Accepted and dlg.get_result() == 1):
                return
            # 用户确认：自动停止；失败则放弃切换，保持原环境
            if not self._stop_service():
                CustomConfirmDialog(
                    parent=self,
                    title="切换已取消",
                    content="停止当前 ComfyUI 服务失败，已取消激活环境切换。\n请稍后在启动页手动停止服务后再切换。",
                    buttons=[{"text": "知道了", "role": "primary"}],
                    theme_manager=self.theme_manager,
                ).exec_()
                return
        self._save_envs(self._get_envs(), active_id=env.get("id"))
        self.reload()
        # 同步 app.python_exec
        self._sync_python_exec(env)
        # 通知 app 刷新所有依赖环境路径的页面（版本/插件/模型/日志等）
        self.active_env_changed.emit()
        CustomConfirmDialog(
            parent=self, title="已切换",
            content=f"激活环境已切换为：{env.get('name', '')}",
            buttons=[{"text": "知道了", "role": "primary"}],
            theme_manager=self.theme_manager,
        ).exec_()

    def _on_delete(self):
        row, env = self._selected_env()
        if env is None:
            CustomConfirmDialog(
                parent=self, title="提示", content="请先在列表中选择一个环境。",
                buttons=[{"text": "知道了", "role": "primary"}],
                theme_manager=self.theme_manager,
            ).exec_()
            return
        envs = self._get_envs()
        if len(envs) <= 1:
            CustomConfirmDialog(
                parent=self, title="无法删除", content="至少需要保留一个环境。",
                buttons=[{"text": "知道了", "role": "destructive"}],
                theme_manager=self.theme_manager,
            ).exec_()
            return
        dlg = CustomConfirmDialog(
            parent=self,
            title="确认删除",
            content=f"确定删除环境「{env.get('name', '')}」吗？此操作不可撤销。",
            buttons=[
                {"text": "取消", "role": "normal"},
                {"text": "删除", "role": "destructive"},
            ],
            default_index=0,
            theme_manager=self.theme_manager,
        )
        if not (dlg.exec_() == QtWidgets.QDialog.Accepted and dlg.get_result() == 1):
            return
        del envs[row]
        # 如果删的是激活环境，指向新的第一个
        active_id = self._get_active_id()
        if active_id == env.get("id"):
            active_id = envs[0].get("id") if envs else None
        self._save_envs(envs, active_id=active_id)
        self.reload()

    def _is_running(self):
        pm = getattr(self.app, "process_manager", None)
        try:
            if pm is not None and hasattr(pm, "is_running_fast"):
                return bool(pm.is_running_fast())
        except Exception:
            pass
        return False

    def _has_active_background_tasks(self):
        """是否有进行中的后台任务（环境切换前检查，有则阻止切换）。"""
        try:
            if hasattr(self.app, "has_active_background_tasks"):
                return bool(self.app.has_active_background_tasks())
        except Exception:
            pass
        return False

    def _stop_service(self):
        """同步停止当前 ComfyUI 服务（阻塞最多 ~3s）。

        返回 True 表示停止成功。切换激活环境前用：失败就放弃切换，保持原环境，
        避免「环境切了一半、服务没停」的混乱状态。
        """
        pm = getattr(self.app, "process_manager", None)
        if pm is None or not hasattr(pm, "stop_comfyui_sync"):
            return False
        try:
            return bool(pm.stop_comfyui_sync())
        except Exception:
            return False

    def _sync_python_exec(self, env):
        """切换激活后同步 app.python_exec（启动页 _py_show 显示用它）。"""
        try:
            from utils import paths as PATHS
            base = Path(env.get("comfyui_root", ".")).resolve()
            comfy_root = (base / "ComfyUI").resolve()
            py = PATHS.resolve_python_exec(
                comfy_root, env.get("python_path", "python_embeded/python.exe")
            )
            self.app.python_exec = str(py)
        except Exception:
            pass


class _EnvEditDialog(FramelessDraggableDialog):
    """环境编辑对话框：填 name / comfyui_root / python_path。

    对齐项目弹窗风格：继承 FramelessDraggableDialog（无边框 + 圆角 + 拖拽），
    套用与 CustomConfirmDialog 一致的容器 QSS（16px 圆角、content_bg、主题色按钮）。
    """

    @staticmethod
    def edit(parent, title, initial_name, initial_root, initial_python, existing_ids=None, theme_manager=None):
        dlg = _EnvEditDialog(parent, title, initial_name, initial_root, initial_python, existing_ids, theme_manager)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            return dlg.result_data
        return None

    def __init__(self, parent, title, initial_name, initial_root, initial_python, existing_ids=None, theme_manager=None):
        super().__init__(parent=parent)
        self.theme_manager = theme_manager
        self.existing_ids = existing_ids or set()
        self.result_data = None
        # DPI-aware token helpers (scale by current DPI factor).
        _styles = theme_manager.styles if theme_manager else None
        self._px = _styles._px if _styles else (lambda b: b)
        self._pt = _styles._pt if _styles else (lambda b: b)
        self._build(title, initial_name, initial_root, initial_python)

    def _theme_colors(self):
        """从 theme_manager 取色，带深色主题回退值（与 CustomConfirmDialog 一致）。"""
        c = {}
        if self.theme_manager and hasattr(self.theme_manager, "colors"):
            c = self.theme_manager.colors
        return {
            "bg": c.get("content_bg", "#1F2937"),
            "border": c.get("group_border", "#374151"),
            "text": c.get("text", "#E5E7EB"),
            "title_color": c.get("label", "#F3F4F6"),
            "label_muted": c.get("label_muted", "#9CA3AF"),
            "btn_bg": c.get("btn_secondary_bg", "#374151"),
            "btn_hover": c.get("btn_ghost_bg", "#4B5563"),
            "accent": c.get("btn_primary_bg", "#6366F1"),
            "accent_hover": c.get("btn_primary_hover", "#818CF8"),
            "input_bg": c.get("input_bg", "rgba(0, 0, 0, 0.3)"),
            "input_border": c.get("input_border", "#374151"),
        }

    def _build(self, title, name, root, python):
        col = self._theme_colors()

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 圆角容器（与 CustomConfirmDialog 的 ConfirmContainer 同款）
        self.container = QtWidgets.QFrame()
        self.container.setObjectName("EditContainer")
        self.container.setStyleSheet(f"""
            QFrame#EditContainer {{
                background-color: {col['bg']};
                border: 1px solid {col['border']};
                border-radius: 16px;
            }}
            QLabel {{
                background: transparent;
            }}
            QLineEdit {{
                background-color: {col['input_bg']};
                color: {col['text']};
                border: 1px solid {col['input_border']};
                border-radius: 8px;
                padding: 8px 10px;
                font: {self._pt(10)}pt "Microsoft YaHei UI";
            }}
            QLineEdit:focus {{
                border: 1px solid {col['accent']};
            }}
            QPushButton {{
                background-color: {col['btn_bg']};
                color: {col['text']};
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font: bold {self._pt(10)}pt "Microsoft YaHei UI";
            }}
            QPushButton:hover {{
                background-color: {col['btn_hover']};
            }}
            QPushButton#PrimaryBtn {{
                background-color: {col['accent']};
                color: #FFFFFF;
            }}
            QPushButton#PrimaryBtn:hover {{
                background-color: {col['accent_hover']};
            }}
        """)
        outer.addWidget(self.container)

        inner = QtWidgets.QVBoxLayout(self.container)
        inner.setContentsMargins(24, 24, 24, 24)
        inner.setSpacing(16)

        # 标题
        lbl_title = QtWidgets.QLabel(title)
        lbl_title.setStyleSheet(f"font: bold {self._pt(14)}pt 'Microsoft YaHei UI'; color: {col['title_color']};")
        inner.addWidget(lbl_title)

        # 表单
        form = QtWidgets.QFormLayout()
        form.setSpacing(12)
        form.setContentsMargins(0, 0, 0, 0)
        # label 左对齐 + 垂直居中，field 占满剩余宽度
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        label_style = f"color: {col['text']}; font: {self._pt(10)}pt 'Microsoft YaHei UI';"

        self.name_edit = QtWidgets.QLineEdit(name)
        self.name_edit.setPlaceholderText("如：ComfyUI V8 生产环境")

        lbl_name = QtWidgets.QLabel("环境名称")
        lbl_name.setStyleSheet(label_style)
        form.addRow(lbl_name, self.name_edit)

        # root 选择行
        self.root_edit = QtWidgets.QLineEdit(root)
        self.root_edit.setPlaceholderText("ComfyUI 安装的父目录（包含 ComfyUI/ 的那个目录）")
        btn_root = QtWidgets.QPushButton("浏览…")
        btn_root.setCursor(Qt.PointingHandCursor)
        btn_root.clicked.connect(self._choose_root)
        root_row = QtWidgets.QHBoxLayout()
        root_row.setContentsMargins(0, 0, 0, 0)
        root_row.setSpacing(8)
        root_row.addWidget(self.root_edit)
        root_row.addWidget(btn_root)
        root_container = QtWidgets.QWidget()
        root_container.setLayout(root_row)
        lbl_root = QtWidgets.QLabel("ComfyUI 根目录")
        lbl_root.setStyleSheet(label_style)
        form.addRow(lbl_root, root_container)

        # python 选择行
        self.py_edit = QtWidgets.QLineEdit(python)
        self.py_edit.setPlaceholderText("python.exe 的绝对路径（留空则自动探测 python_embeded）")
        btn_py = QtWidgets.QPushButton("浏览…")
        btn_py.setCursor(Qt.PointingHandCursor)
        btn_py.clicked.connect(self._choose_python)
        py_row = QtWidgets.QHBoxLayout()
        py_row.setContentsMargins(0, 0, 0, 0)
        py_row.setSpacing(8)
        py_row.addWidget(self.py_edit)
        py_row.addWidget(btn_py)
        py_container = QtWidgets.QWidget()
        py_container.setLayout(py_row)
        lbl_py = QtWidgets.QLabel("Python 路径")
        lbl_py.setStyleSheet(label_style)
        form.addRow(lbl_py, py_container)

        inner.addLayout(form)

        # 按钮行（右对齐，确定用 PrimaryBtn 高亮）
        inner.addSpacing(8)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.setSpacing(12)

        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_ok = QtWidgets.QPushButton("确定")
        btn_ok.setObjectName("PrimaryBtn")
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.clicked.connect(self._on_accept)
        btn_row.addWidget(btn_ok)

        inner.addLayout(btn_row)

        self.setMinimumWidth(self._px(520))

    def _choose_root(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择 ComfyUI 根目录", self.root_edit.text() or str(Path.cwd())
        )
        if d:
            self.root_edit.setText(d)
            # 尝试联动 python 路径（如果根目录下有 python_embeded/python.exe）
            try:
                py_candidate = Path(d) / "python_embeded" / "python.exe"
                if py_candidate.exists() and not self.py_edit.text().strip():
                    self.py_edit.setText(str(py_candidate))
            except Exception:
                pass

    def _choose_python(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 Python 可执行文件",
            self.py_edit.text() or str(Path.cwd()),
            "可执行文件 (*.exe);;所有文件 (*.*)",
        )
        if p:
            self.py_edit.setText(p)

    def _on_accept(self):
        name = self.name_edit.text().strip()
        root = self.root_edit.text().strip()
        python = self.py_edit.text().strip()
        if not name:
            CustomConfirmDialog(
                parent=self, title="信息不完整", content="请填写环境名称。",
                buttons=[{"text": "知道了", "role": "primary"}],
                theme_manager=self.theme_manager,
            ).exec_()
            return
        if not root:
            CustomConfirmDialog(
                parent=self, title="信息不完整", content="请选择 ComfyUI 根目录。",
                buttons=[{"text": "知道了", "role": "primary"}],
                theme_manager=self.theme_manager,
            ).exec_()
            return
        self.result_data = {"name": name, "root": root, "python": python}
        self.accept()
