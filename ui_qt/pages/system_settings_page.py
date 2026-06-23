"""\u7cfb\u7edf\u8bbe\u7f6e\u9875\u9762

\u96c6\u4e2d\u7ba1\u7406\u542f\u52a8\u5668\u672c\u8eab\u7684\u8bbe\u7f6e\u9879\uff08\u4e0e ComfyUI \u5185\u6838\u3001\u6a21\u578b\u5e93\u7b49\u65e0\u5173\uff09\u3002
\u5f53\u524d\u5305\u542b\uff1a
- \u7a97\u53e3\u4e0e\u6258\u76d8\uff1a\u5173\u95ed\u4e3b\u7a97\u53e3\u65f6\u662f\u5426\u6700\u5c0f\u5316\u5230\u7cfb\u7edf\u6258\u76d8\u3001\u662f\u5426\u6bcf\u6b21\u5173\u95ed\u90fd\u63d0\u9192
"""
from PyQt5 import QtCore, QtWidgets

from .base_page import BasePage
from ui_qt.widgets import InfoCard


class _CheckRow(QtWidgets.QFrame):
    """\u4e00\u884c\u9009\u9879\uff1a\u590d\u9009\u6846 + \u6807\u9898 + \u8bf4\u660e\u6587\u5b57\u3002"""

    toggled = QtCore.pyqtSignal(bool)

    def __init__(self, title, description, theme_styles, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self.setObjectName("CheckRow")
        self.setStyleSheet("QFrame#CheckRow { background: transparent; border: none; }")
        self._build(title, description)

    def _build(self, title, description):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(12)

        self.checkbox = QtWidgets.QCheckBox()
        self.checkbox.setCursor(QtCore.Qt.PointingHandCursor)
        self.checkbox.toggled.connect(self.toggled.emit)
        layout.addWidget(self.checkbox, 0, QtCore.Qt.AlignTop)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.lbl_title = QtWidgets.QLabel(title)
        self.lbl_title.setStyleSheet(
            f"color: {self.theme_styles.c.get('label')}; "
            f"font: bold 10pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        self.lbl_title.setWordWrap(True)
        text_col.addWidget(self.lbl_title)

        self.lbl_desc = QtWidgets.QLabel(description)
        self.lbl_desc.setStyleSheet(
            f"color: {self.theme_styles.c.get('label_muted')}; "
            f"font: 9pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        self.lbl_desc.setWordWrap(True)
        text_col.addWidget(self.lbl_desc)

        layout.addLayout(text_col, 1)

    def set_checked(self, value):
        try:
            blocked = self.checkbox.blockSignals(True)
            self.checkbox.setChecked(bool(value))
            self.checkbox.blockSignals(blocked)
        except Exception:
            pass

    def is_checked(self):
        return bool(self.checkbox.isChecked())

    def update_theme(self, theme_styles):
        self.theme_styles = theme_styles
        try:
            self.lbl_title.setStyleSheet(
                f"color: {theme_styles.c.get('label')}; "
                f"font: bold 10pt \"Microsoft YaHei UI\"; background: transparent;"
            )
            self.lbl_desc.setStyleSheet(
                f"color: {theme_styles.c.get('label_muted')}; "
                f"font: 9pt \"Microsoft YaHei UI\"; background: transparent;"
            )
            self._apply_checkbox_style()
        except Exception:
            pass

    def _apply_checkbox_style(self):
        try:
            c = self.theme_styles.c
            accent = c.get("btn_primary_bg", "#6366F1")
            accent_hover = c.get("btn_primary_hover", "#818CF8")
            border = c.get("input_border", "#4B5563")
            bg = c.get("input_bg", "rgba(0, 0, 0, 0.3)")
            self.checkbox.setStyleSheet(
                f"QCheckBox {{ background: transparent; }}"
                f"QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {border}; "
                f"border-radius: 4px; background-color: {bg}; }}"
                f"QCheckBox::indicator:hover {{ border: 1px solid {accent}; }}"
                f"QCheckBox::indicator:checked {{ background-color: {accent}; border: 1px solid {accent}; image: none; }}"
                f"QCheckBox::indicator:checked:hover {{ background-color: {accent_hover}; border: 1px solid {accent_hover}; }}"
            )
        except Exception:
            pass


class SystemSettingsPage(BasePage):
    """\u542f\u52a8\u5668\u7cfb\u7edf\u8bbe\u7f6e\u9875\u9762"""

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self._setup_ui()
        self._load_from_config()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        # \u6807\u9898
        title = QtWidgets.QLabel("\u7cfb\u7edf\u8bbe\u7f6e")
        title.setStyleSheet(
            f"font: bold 16pt \"Microsoft YaHei UI\"; "
            f"color: {self.theme_manager.colors.get('label')}; margin-bottom: 5px;"
        )
        layout.addWidget(title)
        self._page_title_refs = [title]

        # ----- \u7a97\u53e3\u4e0e\u6258\u76d8\u5361\u7247 -----
        card = InfoCard("\u7a97\u53e3\u4e0e\u6258\u76d8", self.theme_manager.styles)
        layout.addWidget(card)

        card_layout = card.layout()
        card_layout.setSpacing(4)

        self.row_minimize = _CheckRow(
            title="\u5173\u95ed\u4e3b\u7a97\u53e3\u65f6\u6700\u5c0f\u5316\u5230\u7cfb\u7edf\u6258\u76d8",
            description=(
                "\u542f\u7528\u540e\uff0c\u70b9\u51fb\u6807\u9898\u680f\u53f3\u4e0a\u89d2\u7684\u201c\u5173\u95ed\u201d\u6309\u94ae\u4f1a\u5c06\u542f\u52a8\u5668\u9690\u85cf\u5230\u7cfb\u7edf\u6258\u76d8\uff0c"
                "\u800c\u4e0d\u662f\u76f4\u63a5\u9000\u51fa\u3002\u53ef\u4ece\u6258\u76d8\u56fe\u6807\u53f3\u952e\u83dc\u5355\u9000\u51fa\u3002"
            ),
            theme_styles=self.theme_manager.styles,
        )
        self.row_minimize.toggled.connect(self._on_minimize_toggled)
        card_layout.addWidget(self.row_minimize)

        self.row_ask = _CheckRow(
            title="\u6bcf\u6b21\u5173\u95ed\u65f6\u90fd\u63d0\u9192",
            description=(
                "\u542f\u7528\u540e\uff0c\u6bcf\u6b21\u70b9\u51fb\u5173\u95ed\u6309\u94ae\u90fd\u4f1a\u5f39\u51fa\u4e00\u4e2a\u786e\u8ba4\u5bf9\u8bdd\u6846\uff0c"
                "\u91cc\u9762\u6709\u300c\u8bb0\u4f4f\u6211\u7684\u9009\u62e9\u300d\u590d\u9009\u6846\u3002\u53ea\u6709\u540c\u65f6\u5173\u95ed\u8be5\u9009\u9879\uff0c"
                "\u624d\u4f1a\u540e\u7eed\u4e0d\u518d\u63d0\u9192\u3002"
            ),
            theme_styles=self.theme_manager.styles,
        )
        self.row_ask.toggled.connect(self._on_ask_toggled)
        card_layout.addWidget(self.row_ask)

        # \u4e24\u4e2a\u9009\u9879\u662f\u4e92\u65a5\u7684\uff1a\u5173\u95ed\u201c\u6bcf\u6b21\u90fd\u63d0\u9192\u201d\u540e\uff0c\u52a9\u624b\u4e0d\u4f1a\u81ea\u52a8\u52fe\u9009\u7b2c\u4e00\u9879
        self.row_minimize.toggled.connect(self._sync_dependencies)
        self.row_ask.toggled.connect(self._sync_dependencies)

        # ----- \u63d0\u793a\u5361\u7247 -----
        tip_card = InfoCard("\u4f7f\u7528\u8bf4\u660e", self.theme_manager.styles)
        layout.addWidget(tip_card)
        tip_layout = tip_card.layout()
        tip_layout.setContentsMargins(15, 12, 15, 12)
        tip_label = QtWidgets.QLabel(
            "\u2022 \u7a97\u53e3\u88ab\u9690\u85cf\u540e\uff0cComfyUI \u670d\u52a1\u5982\u679c\u6b63\u5728\u8fd0\u884c\u4f1a\u7ee7\u7eed\u540e\u53f0\u8fd0\u884c\uff0c\u4e0d\u4f1a\u88ab\u8bef\u5173\u3002\n"
            "\u2022 \u4ece\u6258\u76d8\u9009\u62e9\u300c\u9000\u51fa\u542f\u52a8\u5668\u300d\u624d\u4f1a\u771f\u6b63\u9000\u51fa\u3002\u5982\u679c\u9700\u8981\u540c\u65f6\u505c\u6b62 ComfyUI\uff0c"
            "\u8bf7\u5148\u5728\u300c\u542f\u52a8\u4e0e\u66f4\u65b0\u300d\u9875\u9762\u70b9\u51fb\u505c\u6b62\u6309\u94ae\u3002\n"
            "\u2022 \u5982\u679c\u7cfb\u7edf\u4e0d\u652f\u6301\u6258\u76d8\uff08\u6781\u5c11\u89c1\uff09\uff0c\u5219\u300c\u6700\u5c0f\u5316\u5230\u6258\u76d8\u300d\u9009\u9879\u4f1a\u81ea\u52a8\u7f29\u51cf\u4e3a\u9000\u51fa\u3002"
        )
        tip_label.setStyleSheet(
            f"color: {self.theme_manager.colors.get('label_muted')}; "
            f"font: 9pt \"Microsoft YaHei UI\"; background: transparent; line-height: 160%;"
        )
        tip_label.setWordWrap(True)
        tip_layout.addWidget(tip_label)

        layout.addStretch(1)

        self._styled_widgets = [card, tip_card, self.row_minimize, self.row_ask]

    def _load_from_config(self):
        cfg = self.app.config
        ui = cfg.get("ui_settings", {}) if isinstance(cfg, dict) else {}
        minimize = bool(ui.get("minimize_to_tray_on_close", False))
        ask = bool(ui.get("minimize_to_tray_ask_every_time", True))
        self.row_minimize.set_checked(minimize)
        self.row_ask.set_checked(ask)
        self._sync_dependencies()

    def _sync_dependencies(self):
        # \u201c\u6bcf\u6b21\u90fd\u63d0\u9192\u201d\u5173\u95ed\u540e\uff0c\u5219\u9690\u85cf\u201c\u6700\u5c0f\u5316\u5230\u6258\u76d8\u201d\uff08\u4e0d\u518d\u63d0\u9192 = \u76f4\u63a5\u9000\u51fa\uff09
        if not self.row_ask.is_checked():
            self.row_minimize.set_checked(False)
            self.row_minimize.checkbox.setEnabled(False)
            self.row_minimize.lbl_title.setStyleSheet(
                f"color: {self.theme_manager.colors.get('label_muted')}; "
                f"font: bold 10pt \"Microsoft YaHei UI\"; background: transparent;"
            )
        else:
            self.row_minimize.checkbox.setEnabled(True)
            self.row_minimize.lbl_title.setStyleSheet(
                f"color: {self.theme_manager.colors.get('label')}; "
                f"font: bold 10pt \"Microsoft YaHei UI\"; background: transparent;"
            )

    def _on_minimize_toggled(self, checked):
        self._save_to_config(
            minimize_to_tray_on_close=bool(checked),
            minimize_to_tray_ask_every_time=self.row_ask.is_checked(),
        )

    def _on_ask_toggled(self, checked):
        # \u5173\u95ed\u201c\u6bcf\u6b21\u90fd\u63d0\u9192\u201d = \u76f4\u63a5\u9000\u51fa\uff0c\u4e3a\u4e86\u4e0d\u4e0e\u4e0a\u9762\u4e92\u65a5\u903b\u8f91\u51b2\u7a81\uff0c\u540c\u6b65\u5173\u95ed\u7b2c\u4e00\u9879
        if not checked:
            self.row_minimize.set_checked(False)
        self._save_to_config(
            minimize_to_tray_on_close=self.row_minimize.is_checked(),
            minimize_to_tray_ask_every_time=bool(checked),
        )

    def _save_to_config(self, minimize_to_tray_on_close, minimize_to_tray_ask_every_time):
        try:
            cfg = self.app.config
            ui = cfg.setdefault("ui_settings", {})
            ui["minimize_to_tray_on_close"] = bool(minimize_to_tray_on_close)
            ui["minimize_to_tray_ask_every_time"] = bool(minimize_to_tray_ask_every_time)
            # \u540c\u6b65\u56de\u5199\u5230 app.config \u4e0a\uff0c\u540c\u65f6\u8c03 services.config.save \u6301\u4e45\u5316
            try:
                self.app.config = cfg
            except Exception:
                pass
            services = getattr(self.app, "services", None)
            if services and getattr(services, "config", None):
                try:
                    services.config.save(cfg)
                except Exception:
                    pass
            logger = getattr(self.app, "logger", None)
            if logger:
                logger.info(
                    "\u7cfb\u7edf\u8bbe\u7f6e\u66f4\u65b0: minimize_to_tray_on_close=%s, ask=%s",
                    minimize_to_tray_on_close,
                    minimize_to_tray_ask_every_time,
                )
        except Exception:
            pass

    def update_theme(self, theme_styles=None):
        super().update_theme(theme_styles)
        try:
            title_color = self.theme_manager.colors.get("label")
            for ref in self._page_title_refs:
                ref.setStyleSheet(
                    f"font: bold 16pt \"Microsoft YaHei UI\"; color: {title_color}; margin-bottom: 5px;"
                )
            self.row_minimize.update_theme(self.theme_manager.styles)
            self.row_ask.update_theme(self.theme_manager.styles)
            self._sync_dependencies()
        except Exception:
            pass
