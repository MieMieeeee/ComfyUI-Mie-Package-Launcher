"""环境选择器（启动页顶部下拉）。

多环境支持：一个 ComfyUI 根目录 + python 路径的组合 = 一个环境。
这个组件放在启动页顶部，让用户快速切换当前激活环境。

切换规则（与 CLI 一致）：
- 同时只能运行一个环境。
- 若当前环境正在运行，切换被阻止，提示先停止。
- 切换后写回 config["active_env_id"] 并刷新所有依赖路径的 UI 显示。
"""
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, pyqtSignal

from ui_qt.widgets.custom import NoWheelComboBox
from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
from config.migrations import resolve_active_paths


class EnvironmentSelector(QtWidgets.QWidget):
    """环境下拉选择器。

    发出 ``env_switched`` 信号通知 LaunchPage 刷新下游显示（版本信息、
    路径输入框等）。本组件只负责选环境 + 持久化 active_env_id，
    不负责刷下游 UI（那由 LaunchPage 的槽函数协调）。
    """

    # 切换成功后发出，参数是新的 env_id
    env_switched = pyqtSignal(str)
    # 用户点"管理…"按钮时发出，请求跳转到设置页的环境管理
    manage_requested = pyqtSignal()

    def __init__(self, app_context, theme_manager=None, parent=None):
        super().__init__(parent)
        self.app = app_context
        self.theme_manager = theme_manager
        self._guard = False  # 阻止程序化 setCurrentIndex 触发用户回调
        self._setup_ui()
        self.reload()

    def _setup_ui(self):
        """构建环境栏 UI。

        视觉层级：比普通表单强（独立容器 + accent 色左边框 + 浅高亮背景），
        比启动按钮弱（不做大块实心色）。目的是让用户一眼看出这是「全局上下文」，
        而不是某个普通配置字段。
        """
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 环境栏容器（带高亮背景 + 左边框）----
        # 内部垂直两行：第一行是环境选择控件，第二行是路径摘要（都在框里）
        bar = QtWidgets.QFrame()
        bar.setObjectName("EnvBar")
        bar.setStyleSheet(self._bar_style())
        bar_outer = QtWidgets.QVBoxLayout(bar)
        bar_outer.setContentsMargins(12, 8, 12, 8)
        bar_outer.setSpacing(4)
        outer.addWidget(bar)

        # 第一行：图标 + 标题 + 下拉 + 提示 + 管理按钮
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(10)
        bar_outer.addLayout(top_row)

        # 左：图标 + 「当前环境」标签
        icon_lbl = QtWidgets.QLabel("🧩")
        icon_lbl.setStyleSheet("font-size: 12pt; background: transparent; border: none;")
        top_row.addWidget(icon_lbl)

        title_lbl = QtWidgets.QLabel("当前环境")
        title_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 10pt; color: {self._color('label', '#E5E7EB')};"
            " background: transparent; border: none;"
        )
        top_row.addWidget(title_lbl)

        # 中：环境下拉（更宽，体现重要性）
        self.combo = NoWheelComboBox()
        self.combo.setMinimumWidth(240)
        self.combo.setStyleSheet(self._combo_style())
        self.combo.currentIndexChanged.connect(self._on_index_changed)
        top_row.addWidget(self.combo)

        # 「全局」小 badge（review：长说明句缩成 badge，不占第一视觉层）
        badge = QtWidgets.QLabel("全局")
        badge.setStyleSheet(self._badge_style())
        badge.setToolTip("环境是全局设置，会影响当前页面的启动参数、路径、Python 与代理配置")
        top_row.addWidget(badge)

        top_row.addStretch(1)

        # 右：管理环境按钮
        self.manage_btn = QtWidgets.QPushButton("管理环境")
        self.manage_btn.setCursor(Qt.PointingHandCursor)
        self.manage_btn.setToolTip("打开设置页管理环境（新增 / 编辑 / 删除）")
        self.manage_btn.setStyleSheet(self._manage_btn_style())
        self.manage_btn.clicked.connect(self.manage_requested.emit)
        top_row.addWidget(self.manage_btn)

        # 第二行：路径摘要（只读，在框里）
        # 显示当前环境的根目录 + python 路径，切环境跟着变。
        # 不可编辑，改路径走「管理环境」弹窗。
        self.path_summary = QtWidgets.QLabel("")
        self.path_summary.setStyleSheet(
            f"color: {self._color('label_muted', '#9CA3AF')}; font-size: 8pt;"
            " padding: 0 2px 0 28px; background: transparent; border: none;"
        )
        self.path_summary.setWordWrap(True)
        bar_outer.addWidget(self.path_summary)

    # ---- 样式辅助 ----

    def _color(self, key, default):
        try:
            if self.theme_manager and hasattr(self.theme_manager, "colors"):
                return self.theme_manager.colors.get(key, default)
        except Exception:
            pass
        return default

    def _bar_style(self):
        """环境栏容器样式：轻量状态栏风格。

        review 反馈：整块紫色填充太抢视觉，和启动按钮争焦点。
        改成 group_bg（比页面底色亮一点）+ 细 group_border + 左边一条淡紫强调线，
        让它「独立但不喧宾夺主」。
        """
        accent = self._color("accent", "#6366F1")
        group_bg = self._color("group_bg", "rgba(0, 0, 0, 0.2)")
        group_border = self._color("group_border", "#374151")
        return f"""
        QFrame#EnvBar {{
            background-color: {group_bg};
            border: 1px solid {group_border};
            border-left: 3px solid {accent};
            border-radius: 8px;
        }}
        """

    def _combo_style(self):
        """下拉框样式：唯一的紫色强调点（局部紫），宽度收紧。

        review 反馈：下拉框太宽太实，像可编辑输入框。改成宽度适中、
        只保留淡紫边框作为「这是主要切换控件」的提示。
        """
        accent = self._color("accent", "#6366F1")
        label = self._color("label", "#E5E7EB")
        border = self._color("card_border", "#374151")
        input_bg = self._color("input_bg", "rgba(0, 0, 0, 0.3)")
        return f"""
        QComboBox {{
            min-height: 28px;
            max-width: 220px;
            border: 1px solid {accent};
            border-radius: 6px;
            padding: 2px 10px;
            color: {label};
            background-color: {input_bg};
            font-weight: bold;
        }}
        QComboBox:hover {{
            background-color: rgba(99, 102, 241, 0.18);
        }}
        QComboBox::drop-down {{
            border: none; width: 20px;
        }}
        QComboBox QAbstractItemView {{
            background-color: #1F2937;
            color: {label};
            selection-background-color: {accent};
            border: 1px solid {border};
        }}
        """

    def _badge_style(self):
        """「全局」小 badge：淡紫胶囊，不抢眼但可识别。"""
        return f"""
        QLabel {{
            background-color: rgba(99, 102, 241, 0.18);
            color: {self._color('badge_text', '#A5B4FC')};
            border: 1px solid rgba(99, 102, 241, 0.4);
            border-radius: 9px;
            padding: 1px 8px;
            font-size: 8pt;
            font-weight: bold;
        }}
        """

    def _manage_btn_style(self):
        """管理按钮样式：描边次按钮（review：不要实心紫大按钮，降级）。

        弱化成 secondary 风格的描边按钮，hover 时才带一点紫 tint，
        让视觉重心留在「识别当前环境」而不是「点管理」。
        """
        label = self._color("label", "#E5E7EB")
        muted = self._color("label_muted", "#9CA3AF")
        border = self._color("group_border", "#374151")
        accent = self._color("accent", "#6366F1")
        return f"""
        QPushButton {{
            min-height: 28px;
            padding: 2px 14px;
            color: {muted};
            background-color: transparent;
            border: 1px solid {border};
            border-radius: 6px;
        }}
        QPushButton:hover {{
            color: {label};
            border: 1px solid {accent};
            background-color: rgba(99, 102, 241, 0.12);
        }}
        """

    def reload(self):
        """从 config 重新加载环境下拉项，选中当前激活环境。

        在初始化、外部修改 environments 后调用。用 _guard 避免触发切换回调。
        """
        self._guard = True
        try:
            self.combo.clear()
            envs = self._get_envs()
            active_id = self._get_active_id()
            active_idx = 0
            for idx, env in enumerate(envs):
                name = env.get("name") or env.get("id") or f"环境{idx + 1}"
                # 用 data 存 id，display 用 name
                self.combo.addItem(name, env.get("id"))
                if env.get("id") == active_id:
                    active_idx = idx
            if self.combo.count() > 0:
                self.combo.setCurrentIndex(active_idx)
        finally:
            self._guard = False
        self._refresh_path_summary()

    def _refresh_path_summary(self):
        """刷新路径摘要行：显示当前激活环境的根目录 + python 路径。

        review：去掉 emoji 图标，改成低权重摘要格式「根目录：xxx    Python：xxx」，
        字号小、颜色灰，作为附属信息而非主内容。
        """
        try:
            paths = resolve_active_paths(getattr(self.app, "config", {}) or {})
            root = paths.get("comfyui_root", "") or ""
            py = paths.get("python_path", "") or ""
            parts = []
            if root:
                parts.append(f"根目录：{root}")
            if py:
                parts.append(f"Python：{py}")
            self.path_summary.setText("    ".join(parts) if parts else "（未配置路径）")
        except Exception:
            pass

    def _get_envs(self):
        cfg = getattr(self.app, "config", None) or {}
        envs = cfg.get("environments") if isinstance(cfg, dict) else None
        if isinstance(envs, list) and envs:
            return envs
        # 未迁移的兜底：构造一个虚拟环境
        paths = cfg.get("paths", {}) if isinstance(cfg, dict) else {}
        return [{
            "id": "env_default",
            "name": "默认环境",
            "comfyui_root": paths.get("comfyui_root", "."),
            "python_path": paths.get("python_path", "python_embeded/python.exe"),
        }]

    def _get_active_id(self):
        cfg = getattr(self.app, "config", None) or {}
        return cfg.get("active_env_id") if isinstance(cfg, dict) else None

    def _is_running(self):
        """快速检查 ComfyUI 是否在跑（非阻塞，供 UI 线程用）。"""
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
        """同步停止当前 ComfyUI 服务。

        调用 process_manager.stop_comfyui_sync()（阻塞最多 ~3s 等进程退出）。
        返回 True 表示停止成功（进程已退出），False 表示停止失败（进程仍存活
        或 process_manager 不可用）。切换环境前用：失败就放弃切换，保持原环境。
        """
        pm = getattr(self.app, "process_manager", None)
        if pm is None or not hasattr(pm, "stop_comfyui_sync"):
            return False
        try:
            return bool(pm.stop_comfyui_sync())
        except Exception:
            return False

    def _on_index_changed(self, index):
        """用户在下拉里选了另一个环境。"""
        if self._guard or index < 0:
            return
        new_id = self.combo.itemData(index)
        if not new_id:
            return
        current_active = self._get_active_id()
        if new_id == current_active:
            return

        # 切换前检查：有进行中的后台任务 → 直接阻止（不能强杀 git/cm-cli 子进程）
        if self._has_active_background_tasks():
            CustomConfirmDialog(
                parent=self,
                title="无法切换环境",
                content="有后台任务正在进行（更新内核 / 更新插件 / 检查更新等）。\n"
                        "请等待任务完成，或在「后台任务」页面取消后再切换环境。",
                buttons=[{"text": "知道了", "role": "primary"}],
                theme_manager=self.theme_manager,
            ).exec_()
            self.reload()
            return

        # 切换前检查：当前环境在跑 → 确认是否自动停止后切换
        if self._is_running():
            dlg = CustomConfirmDialog(
                parent=self,
                title="切换环境",
                content="当前已有 ComfyUI 服务正在运行，切换环境会关闭当前服务。\n是否继续？",
                buttons=[
                    {"text": "取消", "role": "normal"},
                    {"text": "切换", "role": "primary"},
                ],
                default_index=0,
                theme_manager=self.theme_manager,
            )
            if not (dlg.exec_() == QtWidgets.QDialog.Accepted and dlg.get_result() == 1):
                # 用户取消：下拉回弹到原环境
                self.reload()
                return
            # 用户确认：自动停止当前服务；失败则放弃切换，保持原环境
            if not self._stop_service():
                CustomConfirmDialog(
                    parent=self,
                    title="切换已取消",
                    content="停止当前 ComfyUI 服务失败，已取消环境切换。\n请稍后在启动页手动停止服务后再切换。",
                    buttons=[{"text": "知道了", "role": "primary"}],
                    theme_manager=self.theme_manager,
                ).exec_()
                self.reload()
                return

        # 写回 active_env_id 并落盘
        try:
            cfg = self.app.config
            cfg["active_env_id"] = new_id
            services = getattr(self.app, "services", None)
            if services is not None and getattr(services, "config", None) is not None:
                saved = services.config.save(cfg)
                if saved is not None:
                    self.app.config = saved
        except Exception as e:
            CustomConfirmDialog(
                parent=self,
                title="切换失败",
                content=f"保存环境切换失败：{e}",
                buttons=[{"text": "知道了", "role": "primary"}],
                theme_manager=self.theme_manager,
            ).exec_()
            self.reload()
            return

        # 同步更新 app.python_exec（下游 build_launch_params 会用 get_active_paths，
        # 但 environment_section 的 _py_show 显示读的是 app.python_exec）
        try:
            paths = resolve_active_paths(self.app.config)
            from pathlib import Path
            from utils import paths as PATHS
            base = Path(paths.get("comfyui_root") or ".").resolve()
            comfy_root = (base / "ComfyUI").resolve()
            py = PATHS.resolve_python_exec(
                comfy_root, paths.get("python_path", "python_embeded/python.exe")
            )
            self.app.python_exec = str(py)
        except Exception:
            pass

        # 刷新顶部路径摘要（显示新环境的路径）
        self._refresh_path_summary()

        # 通知 LaunchPage 刷新下游
        self.env_switched.emit(new_id)
