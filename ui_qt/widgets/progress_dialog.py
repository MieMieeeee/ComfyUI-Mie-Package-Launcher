
from PyQt5 import QtWidgets, QtCore, QtGui
from ui_qt.theme_manager import ThemeManager
from ui_qt.widgets.frameless_draggable_dialog import FramelessDraggableDialog

class ProgressDialog(FramelessDraggableDialog):
    """
    一个简单的无边框进度弹窗，支持显示状态文本和进度条（脉冲或确定进度）
    """
    def __init__(self, parent=None, title="处理中", theme_manager=None, show_cancel=True, show_background=False):
        # Qt.Tool + modal=False：浮在主窗口上、不抢焦点、不进任务栏，
        # 用户在更新时仍可点快捷目录 / 一键启动等。flags / translucent
        # background / 拖拽 都在基类统一处理。
        super().__init__(parent=parent, modal=False, window_type=QtCore.Qt.Tool)
        self.theme_manager = theme_manager
        self._cancelled = False
        self._backgrounded = False
        self._on_cancel_callback = None
        self._on_background_callback = None
        self._on_complete_callback = None
        # 用普通箭头光标（基类 enterEvent 会设 SizeAll 十字暗示可拖，但进度弹窗
        # 主要看进度/点按钮，十字光标会让用户困惑）。仍保留拖拽能力（基类 mousePress/Move）。
        self.setCursor(QtCore.Qt.ArrowCursor)

        # UI Setup
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.container = QtWidgets.QFrame()
        self.container.setObjectName("ProgressContainer")

        # 默认样式，会被 theme_manager 覆盖
        bg = "#1F2937"
        border = "#374151"
        text = "#E5E7EB"
        btn_bg = "#374151"
        btn_hover = "#4B5563"

        if self.theme_manager:
            c = self.theme_manager.colors
            bg = c.get('content_bg', bg)
            border = c.get('group_border', border)
            text = c.get('text', text)
            btn_bg = c.get('btn_secondary_bg', btn_bg)
            btn_hover = c.get('btn_ghost_bg', btn_hover)

        self.container.setStyleSheet(f"""
            QFrame#ProgressContainer {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QLabel {{
                color: {text};
                font: 10pt "Microsoft YaHei UI";
                background: transparent;
            }}
            QPushButton {{
                background-color: {btn_bg};
                color: {text};
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font: 10pt "Microsoft YaHei UI";
            }}
            QPushButton:hover {{
                background-color: {btn_hover};
            }}
        """)

        inner_layout = QtWidgets.QVBoxLayout(self.container)
        inner_layout.setContentsMargins(20, 20, 20, 20)
        inner_layout.setSpacing(15)

        # 标题
        self.lbl_title = QtWidgets.QLabel(title)
        self.lbl_title.setStyleSheet("font: bold 12pt 'Microsoft YaHei UI';")
        self.lbl_title.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setMinimumWidth(380)
        inner_layout.addWidget(self.lbl_title)

        # 状态文本
        self.lbl_status = QtWidgets.QLabel("正在初始化...")
        self.lbl_status.setAlignment(QtCore.Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)
        inner_layout.addWidget(self.lbl_status)

        # 进度条
        self.pbar = QtWidgets.QProgressBar()
        self.pbar.setFixedHeight(6)
        self.pbar.setTextVisible(False)
        self.pbar.setRange(0, 0) # 默认脉冲模式

        accent = "#6366F1"
        if self.theme_manager:
            accent = self.theme_manager.colors.get('accent', accent)

        self.pbar.setStyleSheet(f"""
            QProgressBar {{
                background-color: rgba(0,0,0,0.1);
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {accent};
                border-radius: 3px;
            }}
        """)
        inner_layout.addWidget(self.pbar)

        # 按钮行：取消（中断任务）/ 后台运行（隐藏弹窗、任务继续）
        self.btn_cancel = None
        self.btn_background = None
        has_buttons = show_cancel or show_background
        if has_buttons:
            btn_layout = QtWidgets.QHBoxLayout()
            btn_layout.addStretch()
            # 按钮样式：后台运行=secondary 描边；取消=红色描边（破坏性，且点击会二次确认）
            _btn_style = None
            try:
                if self.theme_manager and hasattr(self.theme_manager, "styles"):
                    _btn_style = self.theme_manager.styles
            except Exception:
                _btn_style = None
            if show_background:
                self.btn_background = QtWidgets.QPushButton("后台运行")
                self.btn_background.setFixedWidth(100)
                try:
                    if _btn_style and hasattr(_btn_style, "secondary_button_style"):
                        self.btn_background.setStyleSheet(_btn_style.secondary_button_style())
                except Exception:
                    pass
                self.btn_background.clicked.connect(self._on_background)
                btn_layout.addWidget(self.btn_background)
            if show_cancel:
                self.btn_cancel = QtWidgets.QPushButton("取消")
                self.btn_cancel.setFixedWidth(100)
                # 取消是破坏性操作 → 红色描边警示（与卸载/退出弹窗的红色统一）
                try:
                    if _btn_style and hasattr(_btn_style, "destructive_outline_button_style"):
                        self.btn_cancel.setStyleSheet(_btn_style.destructive_outline_button_style())
                except Exception:
                    pass
                self.btn_cancel.clicked.connect(self._confirm_cancel)
                btn_layout.addWidget(self.btn_cancel)
            btn_layout.addStretch()
            inner_layout.addLayout(btn_layout)

        # 宽度固定（420 够放进度条 + 多行状态文字 + 按钮行），高度随 set_status 的 adjustSize 自适应。
        # 之前用 setMinimumSize(350,160)+setMaximumWidth(500)，但某些字体/缩放下 minimumSizeHint
        # 宽度算出来超 500 上限，触发 QWindowsWindow::setGeometry 警告。固定宽度后宽高不再打架。
        #
        # v6.1: minimumHeight 从 160 提到 210. 原因: Windows 对 frameless top-level window 有
        # 强制最小高度 (~203px, 不同 DPI 系统会变), 当 show_cancel=False 时初始 resize=160,
        # adjustSize 算出 165 (正好压在 minimum 上), show() 时 Windows 顶到 203 报 "QWindowsWindow::
        # setGeometry Unable to set geometry 420x165 -> 420x203". 设 minimumSize=(420, 210) 比 Windows
        # 强制值高 7px, adjustSize 算出来就 >= 210, Windows 不会再顶也不会警告. (高度还是随 set_status
        # 自适应, 不影响长文本.)
        self.setMinimumSize(420, 210)
        self.setFixedWidth(420)
        self.resize(420, 210)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed,
            QtWidgets.QSizePolicy.Preferred,
        )

        layout.addWidget(self.container)

    def enterEvent(self, event):
        """覆盖基类：保持普通箭头光标（基类会设 SizeAll 十字暗示可拖，进度弹窗不需要）。"""
        super().enterEvent(event)
        self.setCursor(QtCore.Qt.ArrowCursor)

    def _confirm_cancel(self):
        """取消按钮点击 → 二次确认弹窗（破坏性操作，避免误点）。

        用 CustomConfirmDialog 复用主题化样式（红色 destructive 按钮）。
        确认后才调 _on_cancel 真正取消。已确认过则直接取消（防重入）。
        """
        if self._cancelled:
            self._on_cancel()
            return
        try:
            from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
            dlg = CustomConfirmDialog(
                self, title="取消任务",
                content="确定要取消当前任务吗？\n\n取消后正在进行的操作会被中断，可能需要重新运行。",
                buttons=[{"text": "继续运行", "role": "normal"},
                         {"text": "确认取消", "role": "destructive"}],
                default_index=0,
                theme_manager=self.theme_manager,
            )
            if dlg.exec_() == QtWidgets.QDialog.Accepted and (dlg.get_result() or 0) == 1:
                self._on_cancel()
        except Exception:
            # 确认弹窗失败时回退到直接取消（不阻塞用户）
            self._on_cancel()

    def _on_cancel(self):
        """取消按钮点击"""
        self._cancelled = True
        if self.btn_cancel:
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("已取消")
        # 调用取消回调
        if self._on_cancel_callback:
            try:
                self._on_cancel_callback()
            except Exception:
                pass
        # 立即关闭弹窗
        self.done(QtWidgets.QDialog.Rejected)

    def set_cancel_callback(self, callback):
        """设置取消回调"""
        self._on_cancel_callback = callback

    def is_cancelled(self):
        """检查是否已取消"""
        return self._cancelled

    def _on_background(self):
        """后台运行按钮点击：隐藏弹窗、任务继续。"""
        self._backgrounded = True
        self.hide()  # 隐藏但不关闭，任务线程继续跑
        if self._on_background_callback:
            try:
                self._on_background_callback()
            except Exception:
                pass

    def set_background_callback(self, callback):
        """设置后台运行回调（隐藏弹窗时触发）"""
        self._on_background_callback = callback

    def is_backgrounded(self):
        """检查是否已转入后台运行"""
        return self._backgrounded

    def restore(self):
        """从后台恢复显示（侧边栏任务面板「显示」按钮调它）。

        与 hide() 配对：后台运行时只是 hide 保留 widget，这里重新 show + 置顶，
        并重置 _backgrounded 标志（任务仍在跑，进度回调会恢复更新弹窗）。
        """
        self._backgrounded = False
        self.show()
        self.raise_()
        self.activateWindow()

    def mark_complete(self, message="完成 ✓"):
        """标记任务完成：状态文字 + 把按钮区改成只剩「关闭」+ 触发完成回调。

        已完成的任务不需要「取消」（任务都结束了，取消无意义且会触发二次确认），
        也不该再留「后台运行」（任务结束，后台运行毫无意义）。统一改成「关闭」按钮，
        用户看完结果点关闭即可。
        """
        try:
            self.set_status(message)
            self.set_progress(1, maximum=1)
        except Exception:
            pass
        # 隐藏取消按钮
        try:
            if self.btn_cancel is not None:
                self.btn_cancel.setVisible(False)
        except Exception:
            pass
        # 「后台运行」按钮改写成「关闭」——已完成任务唯一合理的操作就是关掉弹窗
        try:
            if self.btn_background is not None:
                self.btn_background.setText("关闭")
                # 断开原来的后台运行连接，改为关闭弹窗
                try:
                    self.btn_background.clicked.disconnect()
                except Exception:
                    pass
                self.btn_background.clicked.connect(self.close)
        except Exception:
            pass
        if self._on_complete_callback:
            try:
                self._on_complete_callback()
            except Exception:
                pass

    def set_complete_callback(self, callback):
        """设置完成回调（区别于取消回调）"""
        self._on_complete_callback = callback

    def set_status(self, text):
        self.lbl_status.setText(text)
        # 状态文字换行后弹窗高度要跟着变，避免文字被切。adjustSize() 会
        # 按布局 minimumSizeHint 重设 size，受 setMaximumWidth 限制。
        self.adjustSize()
        QtWidgets.QApplication.processEvents()

    # 拖拽、hover cursor 等统一在 FramelessDraggableDialog 基类里实现。

    def set_progress(self, value, maximum=100):
        """设置进度条。value 为 None 表示息式 (脉冲)模式。"""
        if value is None or maximum <= 0:
            self.pbar.setRange(0, 0)
        else:
            self.pbar.setRange(0, maximum)
            self.pbar.setValue(max(0, min(int(value), maximum)))
        QtWidgets.QApplication.processEvents()
