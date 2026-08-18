"""\u7cfb\u7edf\u8bbe\u7f6e\u9875\u9762

\u96c6\u4e2d\u7ba1\u7406\u542f\u52a8\u5668\u672c\u8eab\u7684\u8bbe\u7f6e\u9879\uff08\u4e0e ComfyUI \u5185\u6838\u3001\u6a21\u578b\u5e93\u7b49\u65e0\u5173\uff09\u3002
\u5f53\u524d\u5305\u542b\uff1a
- \u7a97\u53e3\u4e0e\u6258\u76d8\uff1a\u5173\u95ed\u4e3b\u7a97\u53e3\u65f6\u662f\u5426\u6700\u5c0f\u5316\u5230\u7cfb\u7edf\u6258\u76d8\u3001\u662f\u5426\u6bcf\u6b21\u5173\u95ed\u90fd\u63d0\u9192
"""
from PyQt5 import QtCore, QtWidgets

from .base_page import BasePage
from .environment_manager_section import EnvironmentManagerSection
from ui_qt.widgets import InfoCard
from core.ui_scaling import compute_scale_from_dpi, snap_scale


# 界面大小下拉选项：(显示文案, 持久化值)。None = 自动跟随屏幕 DPI。
_SCALE_OPTIONS = [
    ("自动跟随系统", None),
    ("75%", 0.75),
    ("85%", 0.85),
    ("90%", 0.9),
    ("100%", 1.0),
    ("110%", 1.1),
    ("125%", 1.25),
]


class _ScaleRow(QtWidgets.QFrame):
    """界面缩放选择行：一个下拉框 + 说明文字。改动后即时预览并写回 config。

    与 ``_WindowSizeRow`` 平行——缩放只控制字号/控件尺寸系数（DPI 相关），
    不控制主窗口宽高（后者由 _WindowSizeRow 单独控制）。
    """

    scale_changed = QtCore.pyqtSignal(object)  # 发出新 scale（float 或 None）

    def __init__(self, theme_styles, current_scale, current_override, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self.setObjectName("ScaleRow")
        self.setStyleSheet("QFrame#ScaleRow { background: transparent; border: none; }")
        self._build(current_scale, current_override)

    def _build(self, current_scale, current_override):
        _pt = self.theme_styles._pt
        _px = self.theme_styles._px
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(_px(4), _px(6), _px(4), _px(6))
        layout.setSpacing(_px(12))

        text_col = QtWidgets.QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.lbl_title = QtWidgets.QLabel("界面缩放")
        self.lbl_title.setStyleSheet(
            f"color: {self.theme_styles.c.get('label')}; "
            f"font: bold {_pt(10)}pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        text_col.addWidget(self.lbl_title)

        # current_override=None → 自动；current_scale 是当前生效系数（用于文案）。
        auto_suffix = ""
        if current_override is None:
            auto_suffix = f"（自动，当前 {current_scale * 100:.0f}%）"
        self.lbl_desc = QtWidgets.QLabel(
            f"调整启动器界面整体缩放（字号/控件密度）。自动模式跟随屏幕 DPI；锁定后多显示器切换不再重算。{auto_suffix}"
        )
        self.lbl_desc.setStyleSheet(
            f"color: {self.theme_styles.c.get('label_muted')}; "
            f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        self.lbl_desc.setWordWrap(True)
        text_col.addWidget(self.lbl_desc)

        layout.addLayout(text_col, 1)

        # 控件列：纯下拉框（窗口尺寸/恢复默认拆到下一行 _WindowSizeRow）
        self.combo = QtWidgets.QComboBox()
        self.combo.setCursor(QtCore.Qt.PointingHandCursor)
        for label, _val in _SCALE_OPTIONS:
            self.combo.addItem(label)
        self.combo.setCurrentIndex(self._index_for(current_override))
        self.combo.setStyleSheet(self.theme_styles.input_style())
        self.combo.setFixedWidth(_px(160))
        self.combo.setFixedHeight(_px(30))
        self.combo.currentIndexChanged.connect(self._on_index_changed)
        layout.addWidget(self.combo, 0, QtCore.Qt.AlignTop)

    @staticmethod
    def _index_for(override):
        for i, (_label, val) in enumerate(_SCALE_OPTIONS):
            if val is None and override is None:
                return i
            if val is not None and override is not None:
                try:
                    if abs(float(val) - float(override)) < 1e-3:
                        return i
                except (TypeError, ValueError):
                    pass
        return 0  # 默认「自动」

    def _on_index_changed(self, idx):
        try:
            _label, val = _SCALE_OPTIONS[idx]
        except Exception:
            val = None
        self.scale_changed.emit(val)

    def update_theme(self, theme_styles):
        self.theme_styles = theme_styles
        try:
            _pt = theme_styles._pt
            _px = theme_styles._px
            self.lbl_title.setStyleSheet(
                f"color: {theme_styles.c.get('label')}; "
                f"font: bold {_pt(10)}pt \"Microsoft YaHei UI\"; background: transparent;"
            )
            self.lbl_desc.setStyleSheet(
                f"color: {theme_styles.c.get('label_muted')}; "
                f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
            )
            self.combo.setStyleSheet(theme_styles.input_style())
            self.combo.setFixedWidth(_px(160))
            self.combo.setFixedHeight(_px(30))
        except Exception:
            pass


class _WindowSizeRow(QtWidgets.QFrame):
    """窗口尺寸行：显示当前宽 × 高（像素），支持填写后点「应用」立刻改窗口，
    以及「恢复默认」一键回 1350×900 base × scale 并居中。

    与 _ScaleRow 拆分：这里只改主窗口像素大小，不动 ui_scale。
    """

    apply_size_requested = QtCore.pyqtSignal(int, int)  # (w, h) 像素
    reset_size_defaults_requested = QtCore.pyqtSignal()

    def __init__(self, theme_styles, current_w, current_h, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self.setObjectName("WindowSizeRow")
        self.setStyleSheet("QFrame#WindowSizeRow { background: transparent; border: none; }")
        self._build(int(current_w or 0), int(current_h or 0))

    def _build(self, cur_w, cur_h):
        _pt = self.theme_styles._pt
        _px = self.theme_styles._px
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(_px(4), _px(6), _px(4), _px(6))
        layout.setSpacing(_px(12))

        text_col = QtWidgets.QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.lbl_title = QtWidgets.QLabel("窗口尺寸")
        self.lbl_title.setStyleSheet(
            f"color: {self.theme_styles.c.get('label')}; "
            f"font: bold {_pt(10)}pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        text_col.addWidget(self.lbl_title)

        self.lbl_desc = QtWidgets.QLabel(
            "当前主窗口宽 × 高（像素，关闭时会记忆）。可手动填写后点「应用」立刻调整；"
            "「恢复默认」回到 1350×900 基准大小并居中。"
        )
        self.lbl_desc.setStyleSheet(
            f"color: {self.theme_styles.c.get('label_muted')}; "
            f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        self.lbl_desc.setWordWrap(True)
        text_col.addWidget(self.lbl_desc)

        layout.addLayout(text_col, 1)

        # 控件列：宽 + × + 高 + 应用 + 恢复默认
        ctrl_col = QtWidgets.QHBoxLayout()
        ctrl_col.setContentsMargins(0, 0, 0, 0)
        ctrl_col.setSpacing(_px(6))

        lbl_w = QtWidgets.QLabel("宽")
        lbl_w.setStyleSheet(
            f"color: {self.theme_styles.c.get('label_muted')}; "
            f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        ctrl_col.addWidget(lbl_w)

        self.w_spinbox = QtWidgets.QSpinBox()
        self.w_spinbox.setRange(800, 5120)
        self.w_spinbox.setSingleStep(10)
        self.w_spinbox.setSuffix(" px")
        self.w_spinbox.setValue(max(800, int(cur_w)))
        self.w_spinbox.setFixedWidth(_px(100))
        self.w_spinbox.setFixedHeight(_px(30))
        self.w_spinbox.setStyleSheet(self.theme_styles.input_style())
        self.w_spinbox.installEventFilter(self)  # 防滚轮误触发：只靠 btn_apply 生效
        ctrl_col.addWidget(self.w_spinbox)

        lbl_times = QtWidgets.QLabel("×")
        lbl_times.setStyleSheet(
            f"color: {self.theme_styles.c.get('label_dim')}; "
            f"font: bold {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        ctrl_col.addWidget(lbl_times)

        lbl_h = QtWidgets.QLabel("高")
        lbl_h.setStyleSheet(
            f"color: {self.theme_styles.c.get('label_muted')}; "
            f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        ctrl_col.addWidget(lbl_h)

        self.h_spinbox = QtWidgets.QSpinBox()
        self.h_spinbox.setRange(600, 4096)
        self.h_spinbox.setSingleStep(10)
        self.h_spinbox.setSuffix(" px")
        self.h_spinbox.setValue(max(600, int(cur_h)))
        self.h_spinbox.setFixedWidth(_px(100))
        self.h_spinbox.setFixedHeight(_px(30))
        self.h_spinbox.setStyleSheet(self.theme_styles.input_style())
        self.h_spinbox.installEventFilter(self)  # 防滚轮误触发
        ctrl_col.addWidget(self.h_spinbox)

        self.btn_apply = QtWidgets.QPushButton("应用")
        self.btn_apply.setCursor(QtCore.Qt.PointingHandCursor)
        try:
            self.btn_apply.setStyleSheet(self.theme_styles.secondary_button_style())
        except Exception:
            pass
        self.btn_apply.setFixedHeight(_px(30))
        self.btn_apply.clicked.connect(self._on_apply_clicked)
        ctrl_col.addWidget(self.btn_apply)

        self.btn_reset_default = QtWidgets.QPushButton("恢复默认")
        self.btn_reset_default.setCursor(QtCore.Qt.PointingHandCursor)
        try:
            self.btn_reset_default.setStyleSheet(self.theme_styles.secondary_button_style())
        except Exception:
            pass
        self.btn_reset_default.setFixedHeight(_px(30))
        self.btn_reset_default.clicked.connect(self.reset_size_defaults_requested.emit)
        ctrl_col.addWidget(self.btn_reset_default)

        layout.addLayout(ctrl_col, 0)

    def _on_apply_clicked(self):
        try:
            w = int(self.w_spinbox.value())
            h = int(self.h_spinbox.value())
        except Exception:
            return
        self.apply_size_requested.emit(w, h)

    def eventFilter(self, obj, event):
        """过滤掉 w/h 两个 spinbox 的鼠标滚轮事件，防止焦点内误触就改值。

        用户明确要求：必须点击「应用」才真正应用窗口尺寸，Spinbox 只展示/键盘输入。
        """
        if (obj is self.w_spinbox or obj is self.h_spinbox) and event is not None:
            try:
                et = event.type()
                if et == QtCore.QEvent.Wheel:
                    return True
            except Exception:
                pass
        return super().eventFilter(obj, event)

    def set_current_size(self, w, h):
        """外部（比如页面刚加载）调用时，把当前宽高填回两个 spin，不发射信号。"""
        try:
            blocked_w = self.w_spinbox.blockSignals(True)
            blocked_h = self.h_spinbox.blockSignals(True)
            self.w_spinbox.setValue(max(800, int(w or 0)))
            self.h_spinbox.setValue(max(600, int(h or 0)))
        finally:
            try:
                self.w_spinbox.blockSignals(blocked_w)
            except Exception:
                pass
            try:
                self.h_spinbox.blockSignals(blocked_h)
            except Exception:
                pass

    def update_theme(self, theme_styles):
        self.theme_styles = theme_styles
        try:
            _pt = theme_styles._pt
            _px = theme_styles._px
            self.lbl_title.setStyleSheet(
                f"color: {theme_styles.c.get('label')}; "
                f"font: bold {_pt(10)}pt \"Microsoft YaHei UI\"; background: transparent;"
            )
            self.lbl_desc.setStyleSheet(
                f"color: {theme_styles.c.get('label_muted')}; "
                f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
            )
            self.w_spinbox.setStyleSheet(theme_styles.input_style())
            self.w_spinbox.setFixedWidth(_px(100))
            self.w_spinbox.setFixedHeight(_px(30))
            self.h_spinbox.setStyleSheet(theme_styles.input_style())
            self.h_spinbox.setFixedWidth(_px(100))
            self.h_spinbox.setFixedHeight(_px(30))
            try:
                self.btn_apply.setStyleSheet(theme_styles.secondary_button_style())
                self.btn_apply.setFixedHeight(_px(30))
            except Exception:
                pass
            try:
                self.btn_reset_default.setStyleSheet(theme_styles.secondary_button_style())
                self.btn_reset_default.setFixedHeight(_px(30))
            except Exception:
                pass
        except Exception:
            pass


# 界面渲染模式下拉选项：(显示文案, 持久化值 render_mode)。
_RENDER_MODE_OPTIONS = [
    ("自动模式（硬件加速，推荐）", "auto"),
    ("兼容模式（软件渲染，避免 OpenGL 闪退）", "compat"),
    ("安全模式（无特效+软件渲染，最稳定）", "safe"),
]


class _RenderModeRow(QtWidgets.QFrame):
    """界面渲染模式行：下拉框 + 「应用」按钮（防误触，不即时写）。

    仿 _WindowSizeRow 的「select + 应用」节奏：下拉切换只改 UI，
    显式点「应用」才持久化 render_mode 到 config，并提示需重启生效。
    """

    apply_render_mode_requested = QtCore.pyqtSignal(str)  # (mode)

    def __init__(self, theme_styles, current_mode, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self.setObjectName("RenderModeRow")
        self.setStyleSheet("QFrame#RenderModeRow { background: transparent; border: none; }")
        self._build(current_mode or "auto")

    def _build(self, cur_mode):
        _pt = self.theme_styles._pt
        _px = self.theme_styles._px
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(_px(4), _px(6), _px(4), _px(6))
        layout.setSpacing(_px(12))

        text_col = QtWidgets.QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.lbl_title = QtWidgets.QLabel("界面渲染模式")
        self.lbl_title.setStyleSheet(
            f"color: {self.theme_styles.c.get('label')}; "
            f"font: bold {_pt(10)}pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        text_col.addWidget(self.lbl_title)

        self.lbl_desc = QtWidgets.QLabel(
            "图形驱动有问题时启动器会自动升级到兼容/安全模式（最多 1~2 次闪退）。"
            "手动修改后需重启启动器才会生效。"
        )
        self.lbl_desc.setStyleSheet(
            f"color: {self.theme_styles.c.get('label_muted')}; "
            f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        self.lbl_desc.setWordWrap(True)
        text_col.addWidget(self.lbl_desc)

        layout.addLayout(text_col, 1)

        ctrl_col = QtWidgets.QHBoxLayout()
        ctrl_col.setContentsMargins(0, 0, 0, 0)
        ctrl_col.setSpacing(_px(6))

        self.combo = QtWidgets.QComboBox()
        self.combo.setCursor(QtCore.Qt.PointingHandCursor)
        for label, _val in _RENDER_MODE_OPTIONS:
            self.combo.addItem(label)
        self.combo.setCurrentIndex(self._index_for(cur_mode))
        self.combo.setStyleSheet(self.theme_styles.input_style())
        self.combo.setFixedWidth(_px(300))
        self.combo.setFixedHeight(_px(30))
        ctrl_col.addWidget(self.combo, 0, QtCore.Qt.AlignTop)

        self.btn_apply = QtWidgets.QPushButton("应用")
        self.btn_apply.setCursor(QtCore.Qt.PointingHandCursor)
        try:
            self.btn_apply.setStyleSheet(self.theme_styles.secondary_button_style())
        except Exception:
            pass
        self.btn_apply.setFixedHeight(_px(30))
        self.btn_apply.clicked.connect(self._on_apply_clicked)
        ctrl_col.addWidget(self.btn_apply)

        layout.addLayout(ctrl_col, 0)

    @staticmethod
    def _index_for(mode):
        for i, (_label, val) in enumerate(_RENDER_MODE_OPTIONS):
            if val == mode:
                return i
        return 0

    def _on_apply_clicked(self):
        try:
            _, mode = _RENDER_MODE_OPTIONS[int(self.combo.currentIndex())]
        except Exception:
            mode = "auto"
        self.apply_render_mode_requested.emit(mode)

    def update_theme(self, theme_styles):
        self.theme_styles = theme_styles
        try:
            _pt = theme_styles._pt
            _px = theme_styles._px
            self.lbl_title.setStyleSheet(
                f"color: {theme_styles.c.get('label')}; "
                f"font: bold {_pt(10)}pt \"Microsoft YaHei UI\"; background: transparent;"
            )
            self.lbl_desc.setStyleSheet(
                f"color: {theme_styles.c.get('label_muted')}; "
                f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
            )
            self.combo.setStyleSheet(theme_styles.input_style())
            self.combo.setFixedWidth(_px(300))
            self.combo.setFixedHeight(_px(30))
            try:
                self.btn_apply.setStyleSheet(theme_styles.secondary_button_style())
                self.btn_apply.setFixedHeight(_px(30))
            except Exception:
                pass
        except Exception:
            pass


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
        _pt = self.theme_styles._pt
        _px = self.theme_styles._px
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(_px(4), _px(6), _px(4), _px(6))
        layout.setSpacing(_px(12))

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
            f"font: bold {_pt(10)}pt \"Microsoft YaHei UI\"; background: transparent;"
        )
        self.lbl_title.setWordWrap(True)
        text_col.addWidget(self.lbl_title)

        self.lbl_desc = QtWidgets.QLabel(description)
        self.lbl_desc.setStyleSheet(
            f"color: {self.theme_styles.c.get('label_muted')}; "
            f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
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
            _pt = theme_styles._pt
            self.lbl_title.setStyleSheet(
                f"color: {theme_styles.c.get('label')}; "
                f"font: bold {_pt(10)}pt \"Microsoft YaHei UI\"; background: transparent;"
            )
            self.lbl_desc.setStyleSheet(
                f"color: {theme_styles.c.get('label_muted')}; "
                f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent;"
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

        # 标题
        _pt = self.theme_manager.styles._pt
        title = QtWidgets.QLabel("系统设置")
        title.setStyleSheet(
            f"font: bold {_pt(16)}pt \"Microsoft YaHei UI\"; "
            f"color: {self.theme_manager.colors.get('label')}; margin-bottom: 5px;"
        )
        layout.addWidget(title)
        self._page_title_refs = [title]

        # ----- 环境管理卡片（多环境支持）-----
        env_card = InfoCard("环境管理", self.theme_manager.styles)
        layout.addWidget(env_card)
        env_card_layout = env_card.layout()
        env_card_layout.setSpacing(4)
        self.env_manager_section = EnvironmentManagerSection(
            app_context=self.app,
            theme_manager=self.theme_manager,
        )
        env_card_layout.addWidget(self.env_manager_section)

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

        # ----- 界面与窗口卡片（界面缩放 + 窗口尺寸 拆分）-----
        ui_card = InfoCard("界面与窗口", self.theme_manager.styles)
        layout.addWidget(ui_card)
        ui_card_layout = ui_card.layout()
        ui_card_layout.setSpacing(4)

        # ① 第一行：界面缩放（selector，只改字号/控件密度）
        _current_override = self._read_scale_override()
        _current_scale = getattr(self.app, "_scale", 1.0) or 1.0
        self.row_scale = _ScaleRow(
            theme_styles=self.theme_manager.styles,
            current_scale=_current_scale,
            current_override=_current_override,
        )
        self.row_scale.scale_changed.connect(self._on_scale_changed)
        ui_card_layout.addWidget(self.row_scale)

        # ② 第二行：窗口尺寸（显示/填写宽高 + 应用 + 恢复默认）
        # 读显示初值——**优先使用 config.base × 生效 scale**，不直接读 app.width/height：
        # 启动早期（构造 SystemSettingsPage 瞬间）Qt 窗口还没完成首次 show/resize，
        # width()/height() 经常是 Qt 原生默认 800×600 / 640×480 脏值，会覆盖用户真实记忆尺寸。
        cfg_obj = self.app.config if isinstance(self.app.config, dict) else {}
        ui_obj = cfg_obj.get("ui_settings", {}) if isinstance(cfg_obj, dict) else {}
        eff_for_init = self._compute_effective_scale(self._read_scale_override())
        if eff_for_init <= 0:
            eff_for_init = 1.0
        BASE_W_MIN, BASE_H_MIN = 800, 540  # 小于这个视为老 schema 脏值 base，直接 fall back
        def_from_cfg = None
        try:
            cfg_w = ui_obj.get("window_w")
            cfg_h = ui_obj.get("window_h")
            if isinstance(cfg_w, int) and isinstance(cfg_h, int) and cfg_w >= BASE_W_MIN and cfg_h >= BASE_H_MIN:
                def_from_cfg = (
                    int(round(cfg_w * eff_for_init)),
                    int(round(cfg_h * eff_for_init)),
                )
        except Exception:
            def_from_cfg = None
        if def_from_cfg is not None:
            win_w, win_h = def_from_cfg
        else:
            try:
                # Config 没存有效 base 才读当前窗口——且 < 900×600 的早期脏值直接忽略
                PIXEL_W_MIN, PIXEL_H_MIN = 900, 600
                ww = int(self.app.width())
                wh = int(self.app.height())
                if ww < PIXEL_W_MIN or wh < PIXEL_H_MIN:
                    raise ValueError("early-dirty")
                win_w, win_h = ww, wh
            except Exception:
                DEFAULT_BASE_W, DEFAULT_BASE_H = 1350, 900
                win_w = int(round(DEFAULT_BASE_W * eff_for_init))
                win_h = int(round(DEFAULT_BASE_H * eff_for_init))
        self.row_window_size = _WindowSizeRow(
            theme_styles=self.theme_manager.styles,
            current_w=win_w,
            current_h=win_h,
        )
        self.row_window_size.apply_size_requested.connect(self._on_window_size_apply)
        self.row_window_size.reset_size_defaults_requested.connect(self._on_window_size_reset_defaults)
        ui_card_layout.addWidget(self.row_window_size)

        # ③ 第三行：界面渲染模式（select + 应用按钮，防误触）
        _cur_mode = ui_obj.get("render_mode", "auto")
        if _cur_mode not in {"auto", "compat", "safe"}:
            _cur_mode = "auto"
        self.row_render_mode = _RenderModeRow(
            theme_styles=self.theme_manager.styles,
            current_mode=_cur_mode,
        )
        self.row_render_mode.apply_render_mode_requested.connect(self._on_render_mode_apply)
        ui_card_layout.addWidget(self.row_render_mode)

        # ----- 提示卡片 -----
        tip_card = InfoCard("使用说明", self.theme_manager.styles)
        layout.addWidget(tip_card)
        tip_layout = tip_card.layout()
        tip_label = QtWidgets.QLabel(
            "• 窗口被隐藏后，ComfyUI 服务如果正在运行会继续后台运行，不会被误关。\n"
            "• 从托盘选择「退出启动器」才会真正退出。如果需要同时停止 ComfyUI，"
            "请先在「启动与更新」页面点击停止按钮。\n"
            "• 如果系统不支持托盘（极少见），则「最小化到托盘」选项会自动缩减为退出。"
        )
        tip_label.setStyleSheet(
            f"color: {self.theme_manager.colors.get('label_muted')}; "
            f"font: {_pt(9)}pt \"Microsoft YaHei UI\"; background: transparent; line-height: 160%;"
        )
        tip_label.setWordWrap(True)
        tip_layout.addWidget(tip_label)

        layout.addStretch(1)

        self._styled_widgets = [env_card, card, ui_card, tip_card, self.row_minimize, self.row_ask, self.row_scale, self.row_window_size, self.row_render_mode]

    def _load_from_config(self):
        cfg = self.app.config
        ui = cfg.get("ui_settings", {}) if isinstance(cfg, dict) else {}
        minimize = bool(ui.get("minimize_to_tray_on_close", False))
        ask = bool(ui.get("minimize_to_tray_ask_every_time", True))
        self.row_minimize.set_checked(minimize)
        self.row_ask.set_checked(ask)
        # render_mode 回填下拉框——不传信号。
        try:
            mode = ui.get("render_mode", "auto")
            if mode not in {"auto", "compat", "safe"}:
                mode = "auto"
            idx = self.row_render_mode._index_for(mode)
            blocked = self.row_render_mode.combo.blockSignals(True)
            try:
                self.row_render_mode.combo.setCurrentIndex(idx)
            finally:
                self.row_render_mode.combo.blockSignals(blocked)
        except Exception:
            pass
        self._sync_dependencies()

    def _on_render_mode_apply(self, mode):
        """用户点 render mode 的「应用」：写 config + 重启生效提示。"""
        if mode not in {"auto", "compat", "safe"}:
            mode = "auto"
        self._save_ui_settings(render_mode=mode)
        try:
            from ui_qt.widgets.dialog_helper import DialogHelper
            DialogHelper.show_info(
                self,
                "已保存",
                "界面渲染模式已保存，重启启动器后生效。",
            )
        except Exception:
            pass

    def _sync_dependencies(self):
        # 「每次都提醒」关闭后，则隐藏「最小化到托盘」（不再提醒 = 直接退出）
        _pt = self.theme_manager.styles._pt
        if not self.row_ask.is_checked():
            self.row_minimize.set_checked(False)
            self.row_minimize.checkbox.setEnabled(False)
            self.row_minimize.lbl_title.setStyleSheet(
                f"color: {self.theme_manager.colors.get('label_muted')}; "
                f"font: bold {_pt(10)}pt \"Microsoft YaHei UI\"; background: transparent;"
            )
        else:
            self.row_minimize.checkbox.setEnabled(True)
            self.row_minimize.lbl_title.setStyleSheet(
                f"color: {self.theme_manager.colors.get('label')}; "
                f"font: bold {_pt(10)}pt \"Microsoft YaHei UI\"; background: transparent;"
            )

    def _on_minimize_toggled(self, checked):
        self._save_ui_settings(
            minimize_to_tray_on_close=bool(checked),
            minimize_to_tray_ask_every_time=self.row_ask.is_checked(),
        )

    def _on_ask_toggled(self, checked):
        # \u5173\u95ed\u201c\u6bcf\u6b21\u90fd\u63d0\u9192\u201d = \u76f4\u63a5\u9000\u51fa\uff0c\u4e3a\u4e86\u4e0d\u4e0e\u4e0a\u9762\u4e92\u65a5\u903b\u8f91\u51b2\u7a81\uff0c\u540c\u6b65\u5173\u95ed\u7b2c\u4e00\u9879
        if not checked:
            self.row_minimize.set_checked(False)
        self._save_ui_settings(
            minimize_to_tray_on_close=self.row_minimize.is_checked(),
            minimize_to_tray_ask_every_time=bool(checked),
        )

    def _save_ui_settings(self, **kwargs):
        """通用：写多组 ui_settings 键值 → 持久化 config → logger。

        传什么 kwargs 写什么键（只改传入的 k/v），其他 ui_settings 字段
        （render_mode / window_w / ui_scale 等）保持不变。
        """
        try:
            cfg = self.app.config
            ui = cfg.setdefault("ui_settings", {})
            for k, v in kwargs.items():
                if isinstance(v, bool):
                    ui[k] = bool(v)
                else:
                    ui[k] = v
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
                try:
                    import json
                    safe_args = {
                        k: ("***" if "token" in k.lower() or "secret" in k.lower() else v)
                        for k, v in kwargs.items()
                    }
                    logger.info(
                        "系统设置更新: %s",
                        json.dumps(safe_args, ensure_ascii=False, sort_keys=True),
                    )
                except Exception:
                    logger.info("系统设置更新: %s", sorted(kwargs.keys()))
        except Exception:
            pass

    # ==================== 界面缩放 + 窗口尺寸 ====================
    def _read_scale_override(self):
        """读 config 里的 ui_settings.ui_scale（None=自动）。"""
        try:
            cfg = self.app.config
            ui = cfg.get("ui_settings", {}) if isinstance(cfg, dict) else {}
            return ui.get("ui_scale", None)
        except Exception:
            return None

    def _current_effective_scale(self):
        """拿当前生效的缩放系数（优先级：app._scale > _compute_effective_scale(config)）。"""
        s = getattr(self.app, "_scale", None)
        if isinstance(s, (int, float)):
            return float(s)
        return self._compute_effective_scale(self._read_scale_override())

    def _on_window_size_apply(self, pixel_w, pixel_h):
        """用户填了宽高点击「应用」：立刻 resize + 写 base 到 config。

        这里不改位置——用户指定宽高一般希望维持当前位置，不强制居中。
        """
        try:
            pw = max(800, int(pixel_w or 0))
            ph = max(600, int(pixel_h or 0))
            # 用「当前 ui_override → compute_effective_scale」，不直接读 app._scale
            # （后者在一些构造场景/QWidget stub 下不会随 config.ui_scale 同步更新）。
            eff = self._compute_effective_scale(self._read_scale_override())
            if eff <= 0:
                eff = 1.0
            # 写 base（base = round(pixel / scale)）
            cfg = self.app.config
            ui = cfg.setdefault("ui_settings", {})
            ui["window_w"] = int(round(pw / eff)) if eff > 0 else int(pw)
            ui["window_h"] = int(round(ph / eff)) if eff > 0 else int(ph)
            # 顺便把 x/y 置 None，因为用户明确重设了大小，下次启动按新 base 居中更合理；
            # 但 window_state 不重置（如果用户当前就是最大化，那状态保留也无所谓，关闭时会重写）。
            ui["window_x"] = None
            ui["window_y"] = None
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
            # 最大化先回到正常再改大小
            # 最大化先回到正常再改宽高，避免最大化下 Qt 的 resize() 被忽略。
            try:
                is_max_fn = getattr(self.app, "isMaximized", None)
                show_n_fn = getattr(self.app, "showNormal", None)
                if callable(is_max_fn) and callable(show_n_fn):
                    if bool(is_max_fn()):
                        show_n_fn()
            except Exception:
                pass
            try:
                if callable(getattr(self.app, "resize", None)):
                    self.app.resize(int(pw), int(ph))
            except Exception:
                pass
            # 改完窗口后立刻把两个 spin 填回**实际**的 self.app.width/height（不是请求值）：
            # 当窗口被 minimumSize / 屏幕 clip / 最大化限制到不了用户填的 800×600 时，
            # 显示真实到达的尺寸，避免 spin 显示 800 实际是 960 的误导。
            try:
                if hasattr(self, "row_window_size") and callable(getattr(self.app, "width", None)) and callable(getattr(self.app, "height", None)):
                    act_w = int(self.app.width())
                    act_h = int(self.app.height())
                    if act_w > 0 and act_h > 0:
                        self.row_window_size.set_current_size(act_w, act_h)
                    else:
                        self.row_window_size.set_current_size(pw, ph)
            except Exception:
                try:
                    if hasattr(self, "row_window_size"):
                        self.row_window_size.set_current_size(pw, ph)
                except Exception:
                    pass
            logger = getattr(self.app, "logger", None)
            if logger:
                logger.info(
                    "窗口尺寸手动应用: pixel=%dx%d, scale=%.3f, base=%dx%d",
                    pw, ph, eff, ui.get("window_w"), ui.get("window_h"),
                )
        except Exception:
            if getattr(self.app, "logger", None):
                self.app.logger.info("窗口尺寸应用失败", exc_info=True)

    def _on_window_size_reset_defaults(self):
        """只动窗口几何（不动 ui_scale）：

        - window_w/h/x/y/state → None
        - 立刻 resize 到 1350×900 base × 当前生效 scale + 居中
        - combo scale selector 保持不动（用户仍可能是锁定的 125%）。
        """
        try:
            cfg = self.app.config
            ui = cfg.setdefault("ui_settings", {})
            changed = False
            for k in ("window_w", "window_h", "window_x", "window_y", "window_state"):
                if ui.get(k, "__missing__") is not None:
                    ui[k] = None
                    changed = True
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
            eff = self._compute_effective_scale(self._read_scale_override())
            if eff <= 0:
                eff = 1.0
            DEFAULT_BASE_W, DEFAULT_BASE_H = 1350, 900
            pw = int(round(DEFAULT_BASE_W * eff))
            ph = int(round(DEFAULT_BASE_H * eff))
            try:
                is_max_fn = getattr(self.app, "isMaximized", None)
                show_n_fn = getattr(self.app, "showNormal", None)
                if callable(is_max_fn) and callable(show_n_fn):
                    if bool(is_max_fn()):
                        show_n_fn()
            except Exception:
                pass
            try:
                if callable(getattr(self.app, "resize", None)):
                    self.app.resize(pw, ph)
            except Exception:
                pass
            try:
                screen = None
                if callable(getattr(self.app, "screen", None)):
                    screen = self.app.screen()
                if screen is None and QtWidgets.QApplication.instance():
                    screen = QtWidgets.QApplication.instance().primaryScreen()
                if screen is not None:
                    avail = screen.availableGeometry()
                    aw, ah = avail.width(), avail.height()
                    if aw > 0 and ah > 0:
                        x = avail.x() + max(0, (aw - pw) // 2)
                        y = avail.y() + max(0, (ah - ph) // 2)
                        if callable(getattr(self.app, "move", None)):
                            self.app.move(int(x), int(y))
            except Exception:
                pass
            # 立刻把 spin 更新回**实际的** self.app.width/height（不是默认请求值 pw/ph），
            # 防止被 minimumSize 夹到更小/更大时 spin 显示与实际不一致。
            try:
                if hasattr(self, "row_window_size") and callable(getattr(self.app, "width", None)) and callable(getattr(self.app, "height", None)):
                    act_w = int(self.app.width())
                    act_h = int(self.app.height())
                    if act_w > 0 and act_h > 0:
                        self.row_window_size.set_current_size(act_w, act_h)
                    else:
                        self.row_window_size.set_current_size(pw, ph)
            except Exception:
                try:
                    if hasattr(self, "row_window_size"):
                        self.row_window_size.set_current_size(pw, ph)
                except Exception:
                    pass
            logger = getattr(self.app, "logger", None)
            if logger:
                logger.info(
                    "窗口尺寸恢复默认（changed=%s）：window_w/h/x/y/state 置 None，"
                    "立即 resize %dx%d scale=%.3f 并居中",
                    changed, pw, ph, eff,
                )
        except Exception:
            if getattr(self.app, "logger", None):
                self.app.logger.info("窗口尺寸恢复默认失败", exc_info=True)

    def _on_scale_changed(self, override):
        """用户在缩放下拉里选了新值。即时预览（字号/控件密度）+ 持久化。"""
        try:
            effective = self._compute_effective_scale(override)
            cfg = self.app.config
            ui = cfg.setdefault("ui_settings", {})
            ui["ui_scale"] = override
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
            self.setUpdatesEnabled(False)
            try:
                old_scale = getattr(self.app, "_scale", effective)
                if hasattr(self.app, "_scale"):
                    self.app._scale = effective
                if hasattr(self.app, "theme_manager") and self.app.theme_manager:
                    self.app.theme_manager.set_scale(effective)
                if hasattr(self.app, "_apply_theme") and hasattr(self.app, "_theme_value"):
                    try:
                        self.app._apply_theme(self.app._theme_value)
                    except Exception:
                        pass
                if hasattr(self.app, "_apply_scaled_fixed_sizes"):
                    self.app._apply_scaled_fixed_sizes()
                if hasattr(self.app, "_resize_for_scale"):
                    try:
                        self.app._resize_for_scale(effective, old_scale)
                    except Exception:
                        pass
            finally:
                self.setUpdatesEnabled(True)
            if override is None:
                self.row_scale.lbl_desc.setText(
                    f"调整启动器界面整体缩放（字号/控件密度）。自动模式跟随屏幕 DPI；锁定后多显示器切换不再重算。"
                    f"（自动，当前 {effective * 100:.0f}%）"
                )
            logger = getattr(self.app, "logger", None)
            if logger:
                logger.info("界面缩放更新: override=%s, effective=%.3f", override, effective)
        except Exception:
            if getattr(self.app, "logger", None):
                self.app.logger.info("界面缩放更新失败", exc_info=True)

    def _compute_effective_scale(self, override):
        """算实际生效缩放系数。override=None → 走当前屏幕 DPI 推断。"""
        try:
            from PyQt5.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
            dpi = screen.logicalDotsPerInch() if screen else 96.0
        except Exception:
            dpi = 96.0
        return compute_scale_from_dpi(dpi, user_override=override)

    def update_theme(self, theme_styles=None):
        super().update_theme(theme_styles)
        try:
            _pt = self.theme_manager.styles._pt
            title_color = self.theme_manager.colors.get("label")
            for ref in self._page_title_refs:
                ref.setStyleSheet(
                    f"font: bold {_pt(16)}pt \"Microsoft YaHei UI\"; color: {title_color}; margin-bottom: 5px;"
                )
            self.row_minimize.update_theme(self.theme_manager.styles)
            self.row_ask.update_theme(self.theme_manager.styles)
            if hasattr(self, "row_scale"):
                self.row_scale.update_theme(self.theme_manager.styles)
            if hasattr(self, "row_window_size"):
                self.row_window_size.update_theme(self.theme_manager.styles)
            self._sync_dependencies()
        except Exception:
            pass
