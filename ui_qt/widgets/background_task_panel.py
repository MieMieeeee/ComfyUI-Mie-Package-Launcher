"""后台任务页面 + 任务行。

「后台任务」作为左侧导航的一个标签页存在（和「插件管理」并列），不再是弹出面板。
- BackgroundTasksPage：放进 stacked widget 的页面，标签页分「进行中」/「已完成」。
- _TaskRow：单个任务行卡片。
- BackgroundTaskPanel：保留兼容（旧弹出面板，已不再用作主入口，但保留以防其他地方引用）。
连 BackgroundTaskRegistry 的信号实时刷新。
"""
from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from ui_qt.widgets.frameless_draggable_dialog import FramelessDraggableDialog


class _TaskRow(QtWidgets.QFrame):
    """单个任务行卡片（状态点 + 标题 + 状态/进度 + 操作按钮）。"""

    def __init__(self, task, page, theme_manager=None):
        super().__init__()
        self.task = task
        self._page = page
        c = theme_manager.colors if theme_manager else {}
        styles = theme_manager.styles if theme_manager else None
        muted = c.get("label_muted", "#9CA3AF")
        dim = c.get("label_dim", "#6B7280")
        card_bg = c.get("input_bg", "rgba(0,0,0,0.3)")
        border = c.get("input_border", "#4B5563")
        accent = c.get("btn_primary_hover", "#9E77ED")
        success = "#22C55E"
        error_color = c.get("error", "#EF4444")
        # DPI 缩放 helper
        _px = styles._px if styles else (lambda b: b)
        _pt = styles._pt if styles else (lambda b: b)

        self.setStyleSheet(f"""
            _TaskRow {{
                background-color: {card_bg};
                border: 1px solid {border};
                border-radius: {_px(10)}px;
            }}
        """)
        rl = QtWidgets.QHBoxLayout(self)
        rl.setContentsMargins(_px(16), _px(14), _px(16), _px(14))
        rl.setSpacing(_px(12))

        # 状态色点
        dot_color = accent if task.is_active() else (error_color if task.error else success)
        dot = QtWidgets.QLabel("●")
        dot.setStyleSheet(f"color: {dot_color}; font: {_pt(16)}pt 'Microsoft YaHei UI'; border: none;")
        dot.setFixedWidth(_px(18))
        rl.addWidget(dot)

        # 标题 + 状态/进度
        info = QtWidgets.QVBoxLayout()
        info.setSpacing(_px(4))
        title_lbl = QtWidgets.QLabel(task.title)
        title_lbl.setStyleSheet(
            f"color: {c.get('label', '#E5E7EB')}; font: bold {_pt(11)}pt 'Microsoft YaHei UI'; border: none;")
        info.addWidget(title_lbl)

        status_text = task.status or ("已完成" if task.done else ("失败" if task.error else "等待中..."))
        status_lbl = QtWidgets.QLabel(status_text)
        status_lbl.setStyleSheet(f"color: {muted}; font: {_pt(9)}pt 'Microsoft YaHei UI'; border: none;")
        status_lbl.setWordWrap(True)
        info.addWidget(status_lbl)

        # 进度条（仅活动任务）
        if task.is_active():
            pb = QtWidgets.QProgressBar()
            cur, tot = task.progress
            if tot and tot > 0:
                pb.setMaximum(tot)
                pb.setValue(cur)
            else:
                pb.setRange(0, 0)  # 脉冲
            pb.setTextVisible(False)
            pb.setFixedHeight(_px(5))
            pb.setStyleSheet(f"""
                QProgressBar {{
                    background-color: rgba(255,255,255,0.08); border: none; border-radius: {_px(3)}px;
                }}
                QProgressBar::chunk {{ background-color: {accent}; border-radius: {_px(3)}px; }}
            """)
            info.addWidget(pb)
        rl.addLayout(info, 1)

        # 操作按钮
        show_btn = QtWidgets.QPushButton("显示")
        self._style_btn(show_btn, styles, "secondary")
        show_btn.setFixedWidth(_px(64))
        show_btn.clicked.connect(lambda: self._page._restore_task(task.task_id))
        if task.dialog is None:
            show_btn.setEnabled(False)
        rl.addWidget(show_btn)
        # 已完成/失败：额外「清除」
        if not task.is_active():
            clear_btn = QtWidgets.QPushButton("清除")
            self._style_btn(clear_btn, styles, "destructive_outline")
            clear_btn.setFixedWidth(_px(64))
            clear_btn.clicked.connect(lambda: self._page.registry.remove(task.task_id))
            rl.addWidget(clear_btn)

    @staticmethod
    def _style_btn(btn, styles, kind):
        try:
            if styles is None:
                return
            if kind == "secondary" and hasattr(styles, "secondary_button_style"):
                btn.setStyleSheet(styles.secondary_button_style())
            elif kind == "destructive_outline" and hasattr(styles, "destructive_outline_button_style"):
                btn.setStyleSheet(styles.destructive_outline_button_style())
        except Exception:
            pass


class BackgroundTasksPage(QtWidgets.QWidget):
    """「后台任务」导航页：标签页分进行中/已完成，常驻主界面。

    作为左侧导航的一个标签页存在（不再是弹出面板）。复用 BackgroundTaskRegistry，
    连信号实时刷新。registry 由 qt_app 注入（构造时传）。
    """

    def __init__(self, registry, theme_manager=None, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.theme_manager = theme_manager
        self._build_ui()
        self.refresh()
        registry.task_added.connect(self.refresh)
        registry.task_updated.connect(self.refresh)
        registry.task_removed.connect(self.refresh)

    def _build_ui(self):
        c = self.theme_manager.colors if self.theme_manager else {}
        styles = self.theme_manager.styles if self.theme_manager else None
        _px = styles._px if styles else (lambda b: b)
        _pt = styles._pt if styles else (lambda b: b)
        self._btp_px = _px  # 供 _make_list_page 复用
        self._btp_pt = _pt
        label = c.get("label", "#E5E7EB")
        muted = c.get("label_muted", "#9CA3AF")
        accent = c.get("btn_primary_hover", "#9E77ED")
        tab_bg = c.get("input_bg", "rgba(0,0,0,0.3)")
        tab_border = c.get("input_border", "#4B5563")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("后台任务")
        title.setStyleSheet(f"font: bold {_pt(16)}pt 'Microsoft YaHei UI'; color: {label};")
        layout.addWidget(title)

        hint = QtWidgets.QLabel("查看正在运行和已完成的任务。后台运行的任务可点「显示」找回进度弹窗。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {muted}; font: {_pt(9)}pt 'Microsoft YaHei UI';")
        layout.addWidget(hint)

        # 标签页（进行中 / 已完成）
        self._tabs = QtWidgets.QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {tab_border};
                border-radius: {_px(8)}px;
                background-color: {tab_bg};
                top: -1px;
            }}
            QTabBar::tab {{
                background-color: transparent;
                color: {muted};
                border: 1px solid {tab_border};
                border-bottom: none;
                border-top-left-radius: {_px(8)}px;
                border-top-right-radius: {_px(8)}px;
                /* 14px horizontal padding + 96px min-width keeps Chinese
                   titles (and count badges) readable even when the page
                   is narrow; previous 20px padding squeezed tabs past their
                   text sizeHint and clipped half-width. */
                padding: {_px(8)}px {_px(14)}px;
                min-width: {_px(96)}px;
                margin-right: {_px(4)}px;
                font: {_pt(10)}pt 'Microsoft YaHei UI';
            }}
            QTabBar::tab:selected {{
                background-color: {tab_bg};
                color: {accent};
                font-weight: bold;
            }}
            QTabBar::tab:hover:!selected {{ color: {label}; }}
        """)
        self._active_page = self._make_list_page("当前没有正在运行的任务")
        self._done_page = self._make_list_page("还没有已完成的任务")
        self._tab_active = self._tabs.addTab(self._active_page, "进行中")
        self._tab_done = self._tabs.addTab(self._done_page, "已完成")
        # Lock tab sizing: keep each tab at its own sizeHint (no auto
        # stretching), disable text eliding so Chinese titles always render
        # in full, and pin a sane minimum width for the tab strip itself
        # (two ~110px tabs + page chrome must fit even on narrow sidebars).
        from PyQt5 import QtCore as _QtCore
        self._tabs.tabBar().setExpanding(False)
        self._tabs.setElideMode(_QtCore.Qt.TextElideMode.ElideNone)
        self._tabs.setMinimumSize(_QtCore.QSize(_px(260), 0))
        self._tabs.setCurrentIndex(0)
        layout.addWidget(self._tabs, 1)

    def _make_list_page(self, empty_text):
        page = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(page)
        pl.setContentsMargins(4, 8, 4, 4)
        pl.setSpacing(8)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        try:
            sc = self.theme_manager.colors.get("scroll_handle", "#6366F1")
            scroll.setStyleSheet(f"""
                QScrollArea {{ background-color: transparent; border: none; }}
                QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; border: none; border-radius: 4px; }}
                QScrollBar::handle:vertical {{ background-color: {sc}; border-radius: 4px; min-height: 30px; }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            """)
        except Exception:
            scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")
        content = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(content)
        vbox.setContentsMargins(6, 6, 6, 6)
        vbox.setSpacing(8)
        vbox.addStretch(1)
        scroll.setWidget(content)
        pl.addWidget(scroll, 1)
        empty = QtWidgets.QLabel(empty_text)
        muted = self.theme_manager.colors.get("label_muted", "#9CA3AF") if self.theme_manager else "#9CA3AF"
        _pt = getattr(self, "_btp_pt", None) or (lambda b: b)
        _px = getattr(self, "_btp_px", None) or (lambda b: b)
        empty.setStyleSheet(f"color: {muted}; font: {_pt(10)}pt 'Microsoft YaHei UI'; padding: {_px(40)}px;")
        empty.setAlignment(QtCore.Qt.AlignCenter)
        pl.addWidget(empty)
        page._list_vbox = vbox
        page._empty_label = empty
        page._rows = []  # 持有任务行引用，refresh 时显式销毁（避免 deleteLater 异步残留）
        return page

    def refresh(self, *args):
        tasks = self.registry.get_all()
        active_tasks = [t for t in tasks if t.is_active()]
        done_tasks = [t for t in tasks if not t.is_active()]
        self._fill_page(self._active_page, active_tasks)
        self._fill_page(self._done_page, done_tasks)
        self._tabs.setTabText(self._tab_active, f"进行中 ({len(active_tasks)})" if active_tasks else "进行中")
        self._tabs.setTabText(self._tab_done, f"已完成 ({len(done_tasks)})" if done_tasks else "已完成")
        if active_tasks and self._tabs.currentIndex() != self._tab_active:
            self._tabs.setCurrentIndex(self._tab_active)

    def _fill_page(self, page, tasks):
        """清空并填充某标签页的任务列表。

        用 page._rows 显式持有行引用，refresh 时从布局移除并 sip.delete 同步销毁，
        避免多次 refresh 累积残留行（deleteLater 异步，快速连续 refresh 会重叠）。
        """
        vbox = page._list_vbox
        # 销毁旧行（同步删除，防残留）
        for old in page._rows:
            try:
                vbox.removeWidget(old)
                old.setParent(None)
                import sip
                sip.delete(old)
            except Exception:
                try:
                    old.deleteLater()
                except Exception:
                    pass
        page._rows = []
        # 填充新行（插在 stretch 之前，顶部对齐）
        for t in tasks:
            row = _TaskRow(t, self, theme_manager=self.theme_manager)
            vbox.insertWidget(vbox.count() - 1, row)
            page._rows.append(row)
        page._empty_label.setVisible(not tasks)

    def _restore_task(self, task_id: str):
        t = self.registry.get(task_id)
        if t is not None and t.dialog is not None:
            try:
                t.dialog.restore()
            except Exception:
                pass


# 兼容保留：旧的弹出面板（已不再用作主入口）。新代码用 BackgroundTasksPage。
class BackgroundTaskPanel(FramelessDraggableDialog):
    """[已废弃] 后台任务弹出面板。新代码用 BackgroundTasksPage（导航页）。

    保留是为了避免其他可能引用它的地方报错；内部委托给一个 BackgroundTasksPage 实例。
    """

    def __init__(self, parent, registry, theme_manager=None):
        super().__init__(parent=parent, modal=False, window_type=QtCore.Qt.Tool)
        self.setWindowTitle("后台任务")
        self.setCursor(QtCore.Qt.ArrowCursor)
        _styles = theme_manager.styles if theme_manager else None
        _px = _styles._px if _styles else (lambda b: b)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._page = BackgroundTasksPage(registry, theme_manager=theme_manager, parent=self)
        layout.addWidget(self._page)
        self.setFixedWidth(_px(560))
        self.setMinimumHeight(_px(440))

    def refresh(self, *args):
        self._page.refresh(*args)

    def _restore_task(self, task_id):
        self._page._restore_task(task_id)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.setCursor(QtCore.Qt.ArrowCursor)

    def closeEvent(self, event):
        self.hide()
        event.ignore()
