"""带「原始输出详情」的失败弹窗（cm-cli 崩溃/失败时用）。

背景（issue #111）：插件更新失败时，启动器原本只弹一句「cm-cli update 退出码 1」，
既没有 cm-cli 的报错内容，也没有 traceback —— 用户无从判断是自己环境的问题还是
插件的问题，只能来问开发者。这个弹窗把 cm-cli 的原始输出（尾部，含 traceback）
直接摊在失败弹窗里，并提供「复制详情」按钮，方便用户自己贴给开发者。

约定（AGENTS.md）：
- 走共享弹窗设施，禁原生 QMessageBox；这里继承 CustomConfirmDialog。
- 日志控件用 **QPlainTextEdit**（共享 QSS 选择器是 QPlainTextEdit；写成
  QTextEdit 会让整套日志区样式静默失效 —— openjutsu 页踩过这个坑）。
- 颜色一律走 theme_manager，禁止硬编码 #rrggbb。
"""

from PyQt5 import QtWidgets

from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog


class CmCliErrorDialog(CustomConfirmDialog):
    """错误弹窗 + 只读原始输出框 + 复制详情按钮。

    按钮：["复制详情", "关闭"]（索引 0 = 复制，1 = 关闭，默认焦点在关闭）。
    点「复制详情」只复制、不关闭（用户还要继续看输出）。
    """

    COPY_BUTTON_INDEX = 0

    def __init__(self, parent=None, title="操作失败", content="", detail="",
                 theme_manager=None):
        buttons = [
            {"text": "复制详情", "role": "normal"},
            {"text": "关闭", "role": "destructive"},
        ]
        super().__init__(
            parent=parent,
            title=title,
            content=content,
            buttons=buttons,
            default_index=1,
            theme_manager=theme_manager,
            min_width=680,
        )
        self._detail = str(detail or "")
        self._detail_box = None
        self._copy_status = None
        self._build_detail_box()

    # ---- 详情区 ----
    def _colors(self) -> dict:
        """取主题色（缺 theme_manager 时给中性兜底）。"""
        fallback = {
            "input_readonly_bg": "rgba(0, 0, 0, 0.3)",
            "input_bg": "rgba(0, 0, 0, 0.3)",
            "input_border": "#374151",
            "label_muted": "#9CA3AF",
            "label": "#E5E7EB",
            "accent": "#6366F1",
        }
        if not self.theme_manager:
            return fallback
        try:
            c = self.theme_manager.colors
        except Exception:
            return fallback
        out = dict(fallback)
        for key in fallback:
            try:
                out[key] = c.get(key, fallback[key])
            except Exception:
                pass
        return out

    def _build_detail_box(self):
        """在按钮行之前插入「原始输出」提示 + 只读日志框。"""
        if not self._detail:
            return
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        _px = styles._px if styles else (lambda b: b)
        _pt = styles._pt if styles else (lambda b: b)
        colors = self._colors()

        box = QtWidgets.QWidget(self.container)
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(6)

        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        hint = QtWidgets.QLabel(
            "以下为 ComfyUI-Manager 命令行（cm-cli）的原始输出，可复制后反馈：")
        hint.setStyleSheet(
            f"font: {_pt(9)}pt 'Microsoft YaHe UI'; color: {colors['label_muted']};")
        hint.setWordWrap(True)
        head.addWidget(hint, 1)
        status = QtWidgets.QLabel("")
        status.setStyleSheet(
            f"font: {_pt(9)}pt 'Microsoft YaHe UI'; color: {colors['accent']};")
        head.addWidget(status, 0)
        box_layout.addLayout(head)
        self._copy_status = status

        # 日志控件必须是 QPlainTextEdit（共享 QSS 选择器只认它）
        view = QtWidgets.QPlainTextEdit(box)
        view.setReadOnly(True)
        view.setPlainText(self._detail)
        view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        view.setMinimumHeight(_px(220))
        view.setStyleSheet(
            f"QPlainTextEdit {{"
            f" background-color: {colors['input_readonly_bg']};"
            f" color: {colors['label']};"
            f" border: 1px solid {colors['input_border']};"
            f" border-radius: {_px(8)}px;"
            f" padding: {_px(8)}px;"
            f" font: {_pt(9)}pt 'Consolas', 'Microsoft YaHe UI'; }}"
        )
        box_layout.addWidget(view)
        self._detail_box = view

        # 插到按钮行之前（container 布局的最后一项是按钮行）
        layout = self.container.layout()
        try:
            layout.insertWidget(max(layout.count() - 1, 0), box)
        except Exception:
            layout.addWidget(box)

    # ---- 复制详情 ----
    def _copy_detail(self) -> bool:
        text = self._detail or ""
        if not text:
            return False
        try:
            QtWidgets.QApplication.clipboard().setText(text)
            return True
        except Exception:
            return False

    def _set_copy_status(self, text: str):
        if self._copy_status is not None:
            try:
                self._copy_status.setText(text)
            except Exception:
                pass

    def _on_btn_clicked(self, index):
        if index == self.COPY_BUTTON_INDEX:
            # 只复制、不关闭：用户可能还要继续看输出内容
            if self._copy_detail():
                self._set_copy_status("已复制到剪贴板")
            else:
                self._set_copy_status("复制失败，请手动选中文本复制")
            return
        super()._on_btn_clicked(index)

    def detail_text(self) -> str:
        """弹窗展示的原始输出文本（测试用）。"""
        return self._detail
