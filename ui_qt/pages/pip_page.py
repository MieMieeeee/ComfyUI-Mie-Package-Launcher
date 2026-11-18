"""Python 库管理页面 —— 管理当前环境 pip 包（视觉与插件管理页同源）。

模块级约定（与 plugins_page.py 一致）：
- 页面**不直接调 PipService、不 import qt_app**（可 offscreen 单测）；
  PipController 把页面信号编排到 PipService，qt_app 注入线程设施。
- 视觉组件复用插件页：_StatCard 直接 import；标题栏 / 搜索框 / 圆角列表
  容器 / 表头 / 自绘 delegate 的结构与 QSS 构造逐段对齐 plugins_page，
  色 token 全走 theme_manager.colors，禁硬编码 #rrggbb。
- 行内「升级 / 卸载」是 delegate 绘制的胶囊按钮（纯绘制不建子 widget），
  editorEvent 命中检测后 emit 页面信号——与插件页 checkbox 的 P1-2 修法同款
  （Press 记录命中、Release 才消费，防 Press/Release 抵消与双击双触发）。
"""

from PyQt5 import QtCore, QtGui, QtWidgets

from ui_qt.pages.base_page import BasePage
# 复用插件页的统计卡组件（自带 theme listener，保证像素级一致）
from ui_qt.pages.plugins_page import _StatCard
from ui_qt.widgets.dialog_helper import DialogHelper

# item 角色：UserRole = 包 dict {name, version}；UserRole+1 = 包名（str）
_PKG_ROLE = QtCore.Qt.UserRole
_NAME_ROLE = QtCore.Qt.UserRole + 1


def _column_geometry(width, px):
    """pip 列表各列的 x 起点 / 宽度（delegate 与表头共用同一份真相）。

    列顺序（左→右）：图标 | 名称（弹性）| 版本 | 操作（升级/卸载）。
    """
    right_margin = px(16)
    actions_w = px(152)   # 操作列：两个 62px 胶囊 + 8px 间距 + 余留
    version_w = px(120)   # 版本列（版本号普遍 < 20 字符）
    icon_x, icon_w = px(12), px(24)
    name_x = icon_x + icon_w + px(4)
    actions_x = width - right_margin - actions_w
    version_x = actions_x - version_w
    return {
        "icon_x": icon_x, "icon_w": icon_w,
        "name_x": name_x, "name_right": version_x,
        "version_x": version_x, "version_w": version_w,
        "actions_x": actions_x, "actions_w": actions_w,
        "right_margin": right_margin,
    }


def _action_rects(g, rect, px):
    """操作列里「升级 / 卸载」两个胶囊的矩形（paint 与 editorEvent 共用）。"""
    ah = px(24)
    aw = px(62)
    gap = px(8)
    total = aw * 2 + gap
    ax = rect.left() + g["actions_x"] + max(0, (g["actions_w"] - total) // 2)
    ay = rect.center().y() - ah // 2
    return (
        QtCore.QRect(ax, ay, aw, ah),
        QtCore.QRect(ax + aw + gap, ay, aw, ah),
    )


class PipItemDelegate(QtWidgets.QStyledItemDelegate):
    """pip 库列表行的自绘：行背景/选中态与插件页同款，行内画「升级/卸载」胶囊按钮。

    纯绘制（不创建子 widget）：升级/卸载按钮由 paint 画、editorEvent 命中检测
    触发页面信号。busy 期间按钮画成置灰且不响应点击。
    """

    def __init__(self, theme_manager, page=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._page = page  # 命中按钮时向它 emit 信号
        self._font_cache = {}
        self._busy = False
        self._pressed_action = None  # ("upgrade"|"uninstall", name) —— Press 命中记录

    def _px(self, v):
        return self.theme_manager.styles._px(v)

    def _pt(self, v):
        return self.theme_manager.styles._pt(v)

    def set_busy(self, busy: bool):
        self._busy = bool(busy)

    def _build_fonts(self):
        try:
            DemiBold = QtGui.QFont.DemiBold
            self._font_cache = {
                "icon_text": QtGui.QFont("Microsoft YaHei UI"),
                "name": QtGui.QFont("Microsoft YaHei UI"),
                "small": QtGui.QFont("Microsoft YaHei UI"),
                "small_bold": QtGui.QFont("Microsoft YaHei UI"),
            }
            f = self._font_cache
            f["icon_text"].setPointSize(self._pt(8))
            f["icon_text"].setWeight(DemiBold)
            f["name"].setPointSize(self._pt(10))
            f["name"].setWeight(DemiBold)
            f["small"].setPointSize(self._pt(8))
            f["small_bold"].setPointSize(self._pt(8))
            f["small_bold"].setWeight(DemiBold)
        except Exception:
            pass

    def update_theme(self, theme_styles=None):
        """theme / DPI 变化时重建字体（字号会变）。"""
        self._build_fonts()

    def _colors(self):
        return self.theme_manager.colors

    def paint(self, painter, option, index):
        c = self._colors()
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        fc = self._font_cache
        if not fc:
            try:
                self._build_fonts()
                fc = self._font_cache or {}
            except Exception:
                fc = {}

        def _font(k, pt, bold=False):
            f = fc.get(k)
            if f is not None:
                return f
            f = QtGui.QFont("Microsoft YaHei UI", pt)
            if bold:
                f.setBold(True)
            return f

        rect = option.rect
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hover = bool(option.state & QtWidgets.QStyle.State_MouseOver)

        # ---- 1. 行背景（与插件页同款：柔和紫选中 / hover 底 / 斑马纹 / 底部分割线）----
        dark_mode = bool(c.get("dark", True))
        if selected:
            painter.fillRect(rect, QtGui.QColor(127, 86, 217, 55))
        elif hover:
            painter.fillRect(rect, QtGui.QColor(c.get("group_bg", "rgba(0,0,0,0.25)")))
        elif index.row() % 2 == 1:
            if dark_mode:
                painter.fillRect(rect, QtGui.QColor(255, 255, 255, 8))
            else:
                painter.fillRect(rect, QtGui.QColor(0, 0, 0, 8))
        if selected:
            bar = c.get("btn_primary_bg", "#7F56D9")
            painter.fillRect(QtCore.QRect(rect.left() + self._px(1), rect.top() + self._px(6),
                                          self._px(3), rect.height() - self._px(12)),
                             QtGui.QColor(bar))
        if not selected:
            div = QtGui.QColor(255, 255, 255, 16) if dark_mode else QtGui.QColor(0, 0, 0, 18)
            painter.fillRect(
                QtCore.QRect(
                    rect.left() + self._px(16),
                    rect.bottom() - self._px(1),
                    max(0, rect.width() - self._px(32)),
                    self._px(1),
                ),
                div,
            )

        # ---- 2. 读数据 + 列几何 ----
        pkg = index.data(_PKG_ROLE) or {}
        name = pkg.get("name", index.data(QtCore.Qt.DisplayRole) or "")
        version = pkg.get("version", "") or ""
        g = _column_geometry(rect.width(), self._px)

        # ---- 3. 图标：圆角方块 + "Py"（与插件页方块图标同风格，避免 emoji 渲染差异）----
        icon_x = rect.left() + g["icon_x"]
        icon_cy = rect.center().y()
        icon_w = g["icon_w"]
        muted_color = QtGui.QColor(c.get("label_muted", "#9CA3AF"))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(muted_color)
        r = QtCore.QRect(icon_x + icon_w // 2 - self._px(9),
                         int(icon_cy - self._px(9)),
                         self._px(18), self._px(18))
        painter.drawRoundedRect(r, self._px(4), self._px(4))
        painter.setPen(QtGui.QColor(c.get("input_bg", "#111827")))
        painter.setFont(_font("icon_text", self._pt(8), True))
        painter.drawText(r, QtCore.Qt.AlignCenter, "Py")

        # ---- 4. 名称（粗体，超长省略）----
        name_x = rect.left() + g["name_x"]
        name_right = rect.left() + g["name_right"]
        name_font = _font("name", self._pt(10.5), True)
        painter.setFont(name_font)
        painter.setPen(QtGui.QColor(c.get("text", "#FFFFFF")))
        name_rect = QtCore.QRect(name_x, rect.top(), max(0, name_right - name_x), rect.height())
        fm = QtGui.QFontMetrics(name_font)
        elided = fm.elidedText(name, QtCore.Qt.ElideRight, name_rect.width())
        painter.drawText(name_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, elided)

        # ---- 5. 版本列（居中，muted）----
        painter.setFont(_font("small", self._pt(8)))
        ver_rect = QtCore.QRect(rect.left() + g["version_x"], rect.top(),
                                g["version_w"], rect.height())
        if version:
            painter.setPen(QtGui.QColor(c.get("label_muted", "#9CA3AF")))
            painter.drawText(ver_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter, version)
        else:
            painter.setPen(QtGui.QColor(c.get("label_dim", "#6B7280")))
            painter.drawText(ver_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter, "—")

        # ---- 6. 操作列：升级（紫）/ 卸载（红描边）胶囊，busy 时置灰 ----
        upg_rect, unl_rect = _action_rects(g, rect, self._px)
        pill_h = self._px(24)
        accent = c.get("btn_primary_hover", "#9E77ED")
        dim = c.get("label_dim", "#6B7280")
        err = c.get("error", "#F04438")
        bf = _font("small_bold", self._pt(8), True)

        # 升级：紫底淡胶囊（同插件页「有更新」徽章配色）
        painter.setFont(bf)
        if self._busy:
            painter.setBrush(QtGui.QColor(107, 114, 128, 32))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(upg_rect, pill_h // 2, pill_h // 2)
            painter.setPen(QtGui.QColor(dim))
        else:
            painter.setBrush(QtGui.QColor(127, 86, 217, 50))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(upg_rect, pill_h // 2, pill_h // 2)
            painter.setPen(QtGui.QColor(accent))
        painter.drawText(upg_rect, QtCore.Qt.AlignCenter, "升级")

        # 卸载：红描边胶囊（同 destructive_outline 按钮）
        if self._busy:
            painter.setBrush(QtGui.QColor(107, 114, 128, 32))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(unl_rect, pill_h // 2, pill_h // 2)
            painter.setPen(QtGui.QColor(dim))
        else:
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor(err), 1))
            painter.drawRoundedRect(unl_rect, pill_h // 2, pill_h // 2)
            painter.setPen(QtGui.QColor(err))
        painter.drawText(unl_rect, QtCore.Qt.AlignCenter, "卸载")

        painter.restore()

    def sizeHint(self, option, index):
        try:
            return QtCore.QSize(0, self._px(52))
        except Exception:
            return QtCore.QSize(0, 52)

    def editorEvent(self, event, model, option, index):
        """升级/卸载按钮的点击接管（Press 记录、Release 消费——P1-2 同款修法）。"""
        etype = event.type()

        def _hit_rects():
            g = _column_geometry(option.rect.width(), self._px)
            return _action_rects(g, option.rect, self._px)

        name = ""
        try:
            name = str(index.data(_NAME_ROLE) or "")
        except Exception:
            name = ""

        if etype == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            upg, unl = _hit_rects()
            pos = event.pos()
            if not self._busy and name:
                if upg.contains(pos):
                    self._pressed_action = ("upgrade", name)
                    return True
                if unl.contains(pos):
                    self._pressed_action = ("uninstall", name)
                    return True
            self._pressed_action = None
            return super().editorEvent(event, model, option, index)

        if etype == QtCore.QEvent.MouseButtonRelease:
            pressed = getattr(self, "_pressed_action", None)
            self._pressed_action = None
            if pressed and not self._busy:
                action, pkg_name = pressed
                if self._page is not None and pkg_name:
                    if action == "upgrade":
                        self._page.upgrade_requested.emit(pkg_name)
                    else:
                        self._page.uninstall_requested.emit(pkg_name)
                return True
            return super().editorEvent(event, model, option, index)

        if etype == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.LeftButton:
            upg, unl = _hit_rects()
            if (not self._busy) and name and (upg.contains(event.pos()) or unl.contains(event.pos())):
                return True  # 消费双击，防 Press 已触发后基类再处理
            return super().editorEvent(event, model, option, index)

        return super().editorEvent(event, model, option, index)


class _PipListHeader(QtWidgets.QWidget):
    """pip 列表的表头行（结构与插件页 _PluginListHeader 同款）。

    paintEvent + _column_geometry 自绘；持有 list_widget 引用，paint 时读
    item 的实际绘制 rect 宽度，保证表头和内容用「同一份宽度」算列位。
    裸 QWidget（非 BasePage），需要自己 register_listener。
    """

    def __init__(self, theme_manager, list_widget=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._list_widget = list_widget
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.update_theme()
        if self.theme_manager:
            self.theme_manager.register_listener(lambda _s: self.update_theme())

    def _px(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._px(base) if styles else base

    def _pt(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._pt(base) if styles else base

    def _build_header_qss(self):
        c = getattr(self.theme_manager, "colors", {}) if self.theme_manager else {}
        px = self._px
        return (f"_PipListHeader {{"
                f" background-color: {c.get('group_bg', 'rgba(0,0,0,0.25)')};"
                f" border: none;"
                f" border-bottom: 1px solid {c.get('input_border', '#4B5563')};"
                f" border-top-left-radius: {px(11)}px;"
                f" border-top-right-radius: {px(11)}px;"
                f"}}")

    def update_theme(self, _theme_styles=None):
        try:
            self.setStyleSheet(self._build_header_qss())
        except Exception:
            pass
        try:
            self.setFixedHeight(self._px(36))
        except Exception:
            pass
        try:
            self.update()
        except Exception:
            pass

    def _content_width(self):
        lw = self._list_widget
        if lw is not None:
            try:
                item = lw.item(0)
                if item is not None:
                    r = lw.visualItemRect(item)
                    if r.width() > 0:
                        return r.width()
            except Exception:
                pass
        return max(0, self.width() - 2)

    def paintEvent(self, _event):
        c = self.theme_manager.colors
        styles = getattr(self.theme_manager, "styles", None)
        if styles is None:
            return
        px = styles._px
        pt = styles._pt
        w = self._content_width()
        g = _column_geometry(w, px)
        lw = self._list_widget
        pad = 0
        if lw is not None:
            try:
                item = lw.item(0)
                if item is not None:
                    r = lw.visualItemRect(item)
                    pad = max(0, r.left() - 1)
            except Exception:
                pass
        ox = pad + 1

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        label_font = QtGui.QFont("Microsoft YaHei UI", pt(8))
        label_font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(label_font)
        painter.setPen(QtGui.QColor(c.get("label_muted", "#9CA3AF")))

        def draw_label(x, wdt, text, align=QtCore.Qt.AlignCenter):
            painter.drawText(QtCore.QRect(ox + x, 0, wdt, self.height()),
                             QtCore.Qt.AlignVCenter | align, text)

        name_x = g["icon_x"]
        name_w = g["name_right"] - name_x
        draw_label(name_x, name_w, "包名", QtCore.Qt.AlignLeft)
        draw_label(g["version_x"], g["version_w"], "版本")
        draw_label(g["actions_x"], g["actions_w"], "操作")
        painter.end()


class _TextStatCard(_StatCard):
    """_StatCard 变体：set_value 接受任意文本（Python / pip 版本号）。"""

    def set_value(self, value):
        self._lbl_value.setText("—" if value in (None, "") else str(value))


class PipPage(BasePage):
    """Python 库管理页面：列已装、安装（包名或完整 pip 命令）、升级、卸载。"""

    # ---- 信号：页面 → 控制器（再由控制器调 service）----
    refresh_requested = QtCore.pyqtSignal()
    install_input_requested = QtCore.pyqtSignal(str)   # 输入框内容（包名或完整命令）
    upgrade_requested = QtCore.pyqtSignal(str)         # 单包升级（delegate 行内按钮）
    uninstall_requested = QtCore.pyqtSignal(str)       # 单包卸载（delegate 行内按钮）

    def __init__(self, app=None, theme_manager=None, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self._busy = False
        self._loader = None  # 由 PipController.set_loader 注入；showEvent 据它触发首次加载
        self._all_packages_cache = []
        self._setup_ui()
        # 构造末尾显式 update_theme：BasePage._apply_theme 在页面构造前已跑、
        # register_listener 不立即回调——不自调的话内联 QSS 控件要等第一次切主题才有样式
        # （AGENTS.md 坑 9）。
        self.update_theme()

    # DPI 缩放 helper —— 每次调用读 theme_manager.styles 的【当前】实例
    def _px(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._px(base) if styles else base

    def _pt(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._pt(base) if styles else base

    def _get_colors(self):
        """按当前 theme_manager.colors 取色（兜底默认值）。每次 update_theme 重走。"""
        c = getattr(self.theme_manager, "colors", {}) if self.theme_manager else {}
        return {
            "label": c.get("label", "#E5E7EB"),
            "label_muted": c.get("label_muted", "#9CA3AF"),
            "label_dim": c.get("label_dim", "#6B7280"),
            "group_bg": c.get("group_bg", "rgba(0,0,0,0.2)"),
            "input_bg": c.get("input_bg", "#111827"),
            "input_border": c.get("input_border", "#4B5563"),
            "text": c.get("text", "#E5E7EB"),
            "error": c.get("error", "#F04438"),
            "btn_primary_bg": c.get("btn_primary_bg", "#7F56D9"),
            "btn_primary_hover": c.get("btn_primary_hover", "#9E77ED"),
            "scroll_handle": c.get("scroll_handle", "#6366F1"),
            "scroll_handle_hover": c.get("scroll_handle_hover", "#5258CF"),
            "divider": c.get("divider", "#374151"),
        }

    def set_loader(self, loader):
        """PipController 构造时注入 BackgroundLoader，供 showEvent 触发首次加载。"""
        self._loader = loader

    def showEvent(self, event):
        """首次切到本页 → 触发列表加载（若还没加载过）。"""
        super().showEvent(event)
        if self._loader is not None:
            self._loader.load_if_not_loaded()

    def set_subtitle(self, text: str):
        try:
            self._subtitle_label.setText(text or "")
        except Exception:
            pass

    def set_loading_state(self, loading: bool):
        """加载中显示占位 item；populate() 开头的 clear() 会自然清掉它。"""
        try:
            if loading and self.list_widget.count() == 0:
                item = QtWidgets.QListWidgetItem("正在获取已安装库列表…")
                item.setForeground(QtGui.QBrush(QtGui.QColor(
                    self.theme_manager.colors.get("label_dim", "#9CA3AF"))))
                self.list_widget.addItem(item)
        except Exception:
            pass

    # ---- UI 构建（段结构与插件页 _setup_ui 对齐）----
    def _setup_ui(self):
        c = self._get_colors()
        s = self.theme_manager.styles if self.theme_manager else None
        _px, _pt = self._px, self._pt
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(_px(28), _px(24), _px(28), _px(24))
        layout.setSpacing(_px(16))

        # ---- 1. 标题 + 右上操作 ----
        titlebar = QtWidgets.QHBoxLayout()
        titlebar.setSpacing(0)
        title_v = QtWidgets.QVBoxLayout()
        title_v.setSpacing(_px(2))
        title_v.setContentsMargins(0, 0, 0, 0)
        title = QtWidgets.QLabel("Python 库管理")
        title.setStyleSheet(f"""
            font: bold {_pt(18)}pt "Microsoft YaHei UI";
            color: {c['label']};
            letter-spacing: 0.2px;
        """)
        self._title_label = title
        subtitle = QtWidgets.QLabel("管理当前环境的 pip 包")
        subtitle.setStyleSheet(
            f"color: {c['label_muted']}; font: {_pt(9)}pt 'Microsoft YaHei UI';"
        )
        self._subtitle_label = subtitle
        title_v.addWidget(title)
        title_v.addWidget(subtitle)
        titlebar.addLayout(title_v)
        titlebar.addStretch()
        top_ops = QtWidgets.QHBoxLayout()
        top_ops.setSpacing(_px(8))
        self.refresh_btn = QtWidgets.QPushButton("刷新列表")
        try:
            self.refresh_btn.setStyleSheet(s.secondary_button_style())
        except Exception:
            pass
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        top_ops.addWidget(self.refresh_btn)
        titlebar.addLayout(top_ops)
        layout.addLayout(titlebar)

        # ---- 2. 统计卡片（3 张：已安装库 / Python 版本 / pip 版本）----
        self._stat_total = _StatCard(
            theme_manager=self.theme_manager, label="已安装库",
            dot_color="#7F56D9", accent_color=c["label"])
        self._stat_python = _TextStatCard(
            theme_manager=self.theme_manager, label="Python",
            dot_color="#22C55E", accent_color="#22C55E")
        self._stat_pip = _TextStatCard(
            theme_manager=self.theme_manager, label="pip",
            dot_color="#9E77ED", accent_color="#9E77ED")
        stat_row = QtWidgets.QHBoxLayout()
        stat_row.setSpacing(_px(12))
        for card in (self._stat_total, self._stat_python, self._stat_pip):
            stat_row.addWidget(card, 1)
        layout.addLayout(stat_row)

        # ---- 3. 安装行：包名 / 完整 pip 命令 智能输入框 ----
        install_row = QtWidgets.QHBoxLayout()
        install_row.setSpacing(_px(8))
        self._install_edit = QtWidgets.QLineEdit()
        self._install_edit.setPlaceholderText(
            "输入包名（如 nvidia-vfx）或粘贴完整 pip 命令，如 "
            "python -m pip install -U --no-build-isolation nvidia-vfx --index-url https://pypi.nvidia.com")
        self._install_edit.setClearButtonEnabled(True)
        self._install_btn = QtWidgets.QPushButton("安装")
        try:
            self._install_btn.setStyleSheet(s.primary_button_style())
        except Exception:
            pass
        self._install_edit.returnPressed.connect(self._emit_install)
        self._install_btn.clicked.connect(self._emit_install)
        install_row.addWidget(self._install_edit, 1)
        install_row.addWidget(self._install_btn)
        layout.addLayout(install_row)

        # ---- 4. 搜索行 + 计数 ----
        search_row = QtWidgets.QHBoxLayout()
        search_row.setSpacing(_px(12))
        self._search_edit = QtWidgets.QLineEdit()
        self._search_edit.setPlaceholderText("搜索包名 / 版本…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(lambda _t: QtCore.QTimer.singleShot(
            200, self._apply_filters))
        search_row.addWidget(self._search_edit, 1)
        self._count_label = QtWidgets.QLabel("共 0 个库")
        self._count_label.setStyleSheet(
            f"color: {c['label_muted']}; font: {_pt(9)}pt 'Microsoft YaHei UI';"
        )
        search_row.addWidget(self._count_label)
        layout.addLayout(search_row)

        # ---- 5. 表头 + 列表包进同一容器（圆角一体卡，与插件页同款）----
        list_container = QtWidgets.QWidget()
        list_container.setObjectName("PipListContainer")
        lc_l = QtWidgets.QVBoxLayout(list_container)
        lc_l.setContentsMargins(0, 0, 0, 0)
        lc_l.setSpacing(0)
        self.list_widget = QtWidgets.QListWidget()
        self._delegate = PipItemDelegate(self.theme_manager, page=self,
                                         parent=self.list_widget)
        self.list_widget.setItemDelegate(self._delegate)
        self.list_header = _PipListHeader(self.theme_manager, list_widget=self.list_widget,
                                          parent=self)
        lc_l.addWidget(self.list_header)
        lc_l.addWidget(self.list_widget)
        layout.addWidget(list_container, 1)
        self._list_container = list_container
        self._root_layout = layout

        # DPI 尺寸清单（min_text 类型由本页覆写的 _reapply_dpi_sizes 处理）
        self._dpi_sized_widgets = [
            (self.refresh_btn, "min_text", "刷新列表"),
            (self._install_btn, "min_text", "安装"),
        ]
        self._reapply_dpi_sizes()

    def _emit_install(self):
        if self._busy:
            return
        text = self._install_edit.text().strip()
        if not text:
            return
        self.install_input_requested.emit(text)

    # ---- 数据填充 / 过滤 ----
    def populate(self, packages):
        """全量填充（BackgroundLoader on_loaded 回调）。保留当前搜索关键字。"""
        self._all_packages_cache = list(packages or [])
        self._refresh_stats()
        self._apply_filters()

    def set_env_info(self, python_version=None, pip_version=None):
        """刷新 Python / pip 版本卡（loader 后台一并取回；失败显示 —）。"""
        try:
            self._stat_python.set_value(python_version or "—")
            self._stat_pip.set_value(pip_version or "—")
        except Exception:
            pass

    def _refresh_stats(self):
        try:
            self._stat_total.set_value(len(self._all_packages_cache))
        except Exception:
            pass

    def _apply_filters(self):
        """按搜索关键字从 _all_packages_cache 过滤并渲染（纯本地）。"""
        try:
            cache = list(getattr(self, "_all_packages_cache", []))
        except Exception:
            cache = []
        kw = ""
        try:
            kw = (self._search_edit.text() if self._search_edit else "").strip().lower()
        except Exception:
            kw = ""
        if kw:
            cache = [
                p for p in cache
                if kw in (p.get("name") or "").lower()
                or kw in (p.get("version") or "").lower()
            ]
        self._render_from_list(cache)
        total = len(getattr(self, "_all_packages_cache", []))
        try:
            self._count_label.setText(
                f"命中 {len(cache)} / {total} 个库" if kw else f"共 {total} 个库")
        except Exception:
            pass

    def _render_from_list(self, packages):
        lw = self.list_widget
        lw.clear()
        for p in packages:
            name = p.get("name", "?")
            version = p.get("version", "") or ""
            item = QtWidgets.QListWidgetItem(name)
            item.setData(_PKG_ROLE, {"name": name, "version": version})
            item.setData(_NAME_ROLE, name)
            tip_lines = [name]
            if version:
                tip_lines.append(f"版本: {version}")
            item.setToolTip("\n".join(tip_lines))
            lw.addItem(item)

    def set_busy(self, busy: bool):
        """操作进行中：禁用按钮/输入框，行内操作胶囊置灰。"""
        self._busy = bool(busy)
        try:
            self._delegate.set_busy(self._busy)
            self.list_widget.viewport().update()
        except Exception:
            pass
        for w in (self.refresh_btn, self._install_btn, self._install_edit):
            try:
                w.setEnabled(not self._busy)
            except Exception:
                pass

    # ---- 主题 QSS 构造（与插件页同名方法逐段对齐）----
    def _build_title_qss(self, c):
        return (f"font: bold {self._pt(18)}pt 'Microsoft YaHei UI';"
                f" color: {c['label']};"
                f" letter-spacing: 0.2px;")

    def _build_subtitle_qss(self, c):
        return (f"color: {c['label_muted']};"
                f" font: {self._pt(9)}pt 'Microsoft YaHei UI';")

    def _build_input_qss(self, c):
        """安装输入框 / 搜索框共用（同插件页 _build_search_qss）。"""
        px, pt = self._px, self._pt
        return f"""
            QLineEdit {{
                background-color: {c['input_bg']}; color: {c['text']};
                border: 1px solid {c['input_border']};
                border-radius: {px(10)}px;
                padding: {px(7)}px {px(12)}px;
                font: {pt(9.5)}pt "Microsoft YaHei UI";
            }}
            QLineEdit:focus {{ border: 1px solid {c['btn_primary_hover']}; }}
            QLineEdit:disabled {{ color: {c['label_dim']}; }}
        """

    def _build_list_container_qss(self, c):
        return (f"QWidget#PipListContainer {{"
                f" background-color: {c['input_bg']};"
                f" border: 1px solid {c['input_border']};"
                f" border-radius: {self._px(12)}px; }}")

    def _build_list_qss(self, c):
        _px, _pt = self._px, self._pt
        return f"""
            QListWidget {{
                background-color: transparent;
                color: {c['text']};
                border: none;
                padding: {_px(6)}px;
                font: {_pt(10)}pt "Microsoft YaHei UI";
                outline: none;
            }}
            QScrollBar:vertical {{
                background: transparent; width: {_px(8)}px; margin: {_px(4)}px;
                border: none; border-radius: {_px(4)}px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {c['scroll_handle']};
                border-radius: {_px(4)}px; min-height: {_px(40)}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {c['scroll_handle_hover']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """

    def _reapply_dpi_sizes(self):
        """DPI / UI scale 变化时重算尺寸（含本页自定义的 min_text 按钮）。"""
        _px = self._px
        try:
            self._root_layout.setContentsMargins(
                _px(28), _px(24), _px(28), _px(24))
        except Exception:
            pass
        try:
            self._root_layout.setSpacing(_px(16))
        except Exception:
            pass
        # 每个按钮 minWidth：测当前文本和 aux 文本两者 sizeHint，取大的
        for w, kind, aux in getattr(self, "_dpi_sized_widgets", []):
            try:
                if kind == "min_text":
                    cur = w.text()
                    w1 = w.sizeHint().width()
                    w.setText(aux)
                    w2 = w.sizeHint().width()
                    w.setText(cur)
                    w.setMinimumWidth(max(w1, w2))
            except Exception:
                pass
        # 统计卡片自身有 theme listener；这里保险重算字级
        try:
            for card in (getattr(self, "_stat_total", None),
                         getattr(self, "_stat_python", None),
                         getattr(self, "_stat_pip", None)):
                if card is not None and getattr(card, "update_theme", None):
                    card.update_theme()
        except Exception:
            pass

    # ---- 主题 & DPI 变化：重取颜色 token + 重建 QSS + 重算尺寸 ----
    # 注意：BasePage.__init__ 已经 register_listener(self._on_theme_changed)，
    # 这里**不要**再次注册！否则会双监听、双次调用。
    def _on_theme_changed(self, theme_styles):
        self.update_theme(theme_styles)

    def update_theme(self, theme_styles=None):
        """BasePage 的 update_theme 只重应用基础 content_style；这里补子控件的内联 QSS。"""
        try:
            super().update_theme(theme_styles)
        except Exception:
            pass
        try:
            c = self._get_colors()
            s = self.theme_manager.styles if self.theme_manager else None
            try:
                self._title_label.setStyleSheet(self._build_title_qss(c))
            except Exception:
                pass
            try:
                self._subtitle_label.setStyleSheet(self._build_subtitle_qss(c))
            except Exception:
                pass
            try:
                self._install_edit.setStyleSheet(self._build_input_qss(c))
            except Exception:
                pass
            try:
                self._search_edit.setStyleSheet(self._build_input_qss(c))
            except Exception:
                pass
            try:
                self._count_label.setStyleSheet(
                    f"color: {c['label_muted']};"
                    f" font: {self._pt(9)}pt 'Microsoft YaHei UI';")
            except Exception:
                pass
            try:
                self._list_container.setStyleSheet(self._build_list_container_qss(c))
            except Exception:
                pass
            try:
                self.list_widget.setStyleSheet(self._build_list_qss(c))
            except Exception:
                pass
            # 按钮 builder 样式重应用
            try:
                if s is not None:
                    self.refresh_btn.setStyleSheet(s.secondary_button_style())
                    self._install_btn.setStyleSheet(s.primary_button_style())
            except Exception:
                pass
            # DPI 尺寸重算
            self._reapply_dpi_sizes()
            # 通知子 delegate / 表头各自 update_theme
            try:
                self._delegate.update_theme(theme_styles)
            except Exception:
                pass
            try:
                self.list_header.update_theme(theme_styles)
            except Exception:
                pass
        except Exception:
            pass


class PipController:
    """把 PipPage 的信号编排到 PipService（可单测）。

    依赖注入：run_in_background(fn) 把 fn 丢到工作线程；post_to_ui(fn) 把 fn
    派回 UI 线程。qt_app 侧注入真实现（daemon Thread + UiInvoker），测试注入
    同步替身。确认弹窗经 DialogHelper（测试 patch 掉即可 offscreen 跑）。
    """

    def __init__(self, page, pip_service, run_in_background, post_to_ui,
                 registry=None, is_comfyui_running=None, resolve_index_url=None):
        import threading
        self._threading = threading
        self.page = page
        self.svc = pip_service
        self._run_in_background = run_in_background
        self._post_to_ui = post_to_ui
        self._registry = registry
        self._is_comfyui_running = is_comfyui_running or (lambda: False)
        self._resolve_index_url = resolve_index_url or (lambda: None)
        self._op_lock = threading.Lock()
        from ui_qt.background_loader import BackgroundLoader
        self._loader = BackgroundLoader(
            load_fn=self._load_all,
            on_loaded=self._on_loaded,
            run_in_background=run_in_background,
            post_to_ui=post_to_ui,
            on_error=self._on_load_error,
            on_state_change=self.page.set_loading_state,
        )
        page.set_loader(self._loader)
        page.refresh_requested.connect(self._on_refresh)
        page.install_input_requested.connect(self.run_install_input)
        page.upgrade_requested.connect(self.run_upgrade)
        page.uninstall_requested.connect(self.run_uninstall)

    # ---- 列表加载（顺带取 python / pip 版本给统计卡）----
    def _load_all(self, _report):
        packages = self.svc.list_installed()
        py_ver = None
        pip_ver = None
        try:
            py_ver = self.svc.python_version()
            pip_ver = self.svc.pip_version()
        except Exception:
            pass
        return {"packages": packages, "python_version": py_ver, "pip_version": pip_ver}

    def _on_loaded(self, data):
        try:
            self.page.populate(data.get("packages") or [])
            self.page.set_env_info(data.get("python_version"), data.get("pip_version"))
        except Exception:
            pass
        try:
            py = self.svc.python_exec()
            if py:
                self.page.set_subtitle(f"当前环境 Python：{py}")
        except Exception:
            pass

    def _on_load_error(self, exc):
        def _show():
            try:
                DialogHelper.show_error(
                    self.page, "加载失败", f"获取已安装库列表失败：{exc}")
            except Exception:
                pass
        self._post_to_ui(_show)

    def _on_refresh(self):
        self._loader.load()

    # ---- 风险包判定（CUDA 耦合库，升级/卸载前警告）----
    @staticmethod
    def _spec_name(spec: str) -> str:
        import re
        return re.split(r"[><=!~\[\s]", str(spec).strip(), 1)[0].lower()

    def _frozen_specs(self, specs):
        try:
            from services.dependency_policy import is_frozen
            return [s for s in specs if is_frozen(self._spec_name(s))]
        except Exception:
            return []

    def _risk_lines(self, specs, action_label):
        """确认框里的警告行（冻结包 / ComfyUI 在跑）。无警告返回 ""。"""
        lines = []
        frozen = self._frozen_specs(specs)
        if frozen:
            lines.append(
                f"⚠ {'、'.join(frozen)} 是 CUDA 耦合库，{action_label}可能导致环境不可用，请确认确实需要。")
        try:
            if self._is_comfyui_running():
                lines.append(
                    "⚠ ComfyUI 正在运行，操作可能因文件占用失败，建议停止 ComfyUI 后再执行。")
        except Exception:
            pass
        if lines:
            return "\n\n" + "\n".join(lines)
        return ""

    # ---- 操作编排（确认 → 进度框 + 注册表 → 后台跑 → 收尾）----
    def _start_op(self, title, work):
        """work(cancel_event, progress_cb, finish) 在后台线程执行。

        progress_cb(text) 可从工作线程直接调（内部 post 回 UI）；finish(kind, msg)
        kind ∈ {"ok","fail","cancel"}，也只应从工作线程调（内部 post 回 UI）。
        """
        if not self._op_lock.acquire(blocking=False):
            DialogHelper.show_info(
                self.page, "提示", "已有 pip 任务正在进行，请等它完成后再操作。")
            return
        cancel_event = self._threading.Event()
        task_id = None
        pd = None
        if self._registry is not None:
            try:
                task_id = self._registry.register(title)
            except Exception:
                task_id = None
        try:
            from ui_qt.widgets.progress_dialog import ProgressDialog
            pd = ProgressDialog(
                self.page, title=title,
                theme_manager=getattr(self.page, "theme_manager", None),
                show_cancel=True, show_background=True)
            pd.show()
            QtWidgets.QApplication.processEvents()
            # ProgressDialog 自带「确认取消」二次弹窗（含破坏性提示），直接接事件即可
            pd.set_cancel_callback(cancel_event.set)
            if self._registry is not None and task_id:
                self._registry.set_dialog(task_id, pd)
        except Exception:
            pd = None

        try:
            self.page.set_busy(True)
        except Exception:
            pass

        done_flag = {"done": False}

        def progress_cb(text):
            def _apply():
                try:
                    if pd is not None:
                        pd.set_status(str(text))
                        pd.set_progress(None)  # 脉冲
                except Exception:
                    pass
                try:
                    if self._registry is not None and task_id:
                        self._registry.update(task_id, status=str(text), progress=(0, 0))
                except Exception:
                    pass
            self._post_to_ui(_apply)

        def finish(kind, msg):
            if done_flag["done"]:
                return
            done_flag["done"] = True

            def _do():
                ok = (kind == "ok")
                try:
                    if pd is not None:
                        pd.mark_complete("完成 ✓" if ok else ("已取消" if kind == "cancel" else "完成（有失败）"))
                        pd.close()
                except Exception:
                    pass
                try:
                    if self._registry is not None and task_id:
                        self._registry.complete(task_id, error=(kind == "fail"))
                        self._registry.remove(task_id)
                except Exception:
                    pass
                try:
                    self.page.set_busy(False)
                except Exception:
                    pass
                self._op_lock.release()
                # 操作完成后刷列表（装/卸/升级都会改变包列表）
                try:
                    self._loader.load()
                except Exception:
                    pass
                try:
                    if msg:
                        if kind == "fail":
                            DialogHelper.show_error(self.page, title + "失败", msg)
                        else:
                            DialogHelper.show_info(self.page, title + (
                                "完成" if kind == "ok" else "已取消"), msg)
                except Exception:
                    pass
            self._post_to_ui(_do)

        def _work():
            try:
                work(cancel_event, progress_cb, finish)
            except Exception as e:
                finish("fail", f"操作失败：{e}")

        self._run_in_background(_work)

    # ---- 升级 / 卸载（行内按钮）----
    def run_upgrade(self, name: str):
        self._confirm_and_install_specs([str(name)], title=f"升级 {name}")

    def run_uninstall(self, name: str):
        self._confirm_and_uninstall([str(name)])

    def run_install_input(self, text: str):
        """输入框提交：normalize 分流（specs / install / uninstall / error）。"""
        from services.pip_service import normalize_pip_command
        norm = normalize_pip_command(text or "")
        kind = norm.get("kind")
        if kind == "error":
            DialogHelper.show_error(self.page, "无法识别的命令",
                                    norm.get("error") or "无法识别的命令")
            return
        if kind == "specs":
            self._confirm_and_install_specs(norm["args"], title="安装 Python 库",
                                            has_index_flag=norm.get("has_index_flag"))
        elif kind == "install":
            self._confirm_and_run_args(["install", *norm["args"]], title="安装 Python 库")
        elif kind == "uninstall":
            # 只取非 flag token 当包名（-y 由 utils.uninstall_packages 强制补；
            # 用户粘贴的其它 uninstall flag 一律丢弃，避免被当包名传给 pip）
            names = [a for a in norm["args"] if not str(a).startswith("-")]
            if not names:
                DialogHelper.show_error(self.page, "无法识别的命令",
                                        "uninstall 缺少包名")
                return
            self._confirm_and_uninstall(names)

    def _confirm_and_install_specs(self, specs, title, has_index_flag=False):
        """裸包名/spec：统一走 python -m pip install -U <specs>（单次调用）。"""
        idx = None
        if not has_index_flag:
            try:
                idx = self._resolve_index_url()
            except Exception:
                idx = None
        preview = self.svc.preview_command(["install", "-U", *specs] +
                                           (["-i", idx] if idx else []))
        mirror_note = (f"索引源：{idx}" if idx else "索引源：pip 默认配置（pip.ini）")
        content = (f"将执行：\n{preview}\n\n{mirror_note}"
                   + self._risk_lines(specs, "升级"))
        if not DialogHelper.show_confirmation(self.page, title, content, yes_text="安装"):
            return

        def work(cancel_event, progress, finish):
            args = ["install", "-U", *specs]
            if idx:
                args += ["-i", idx]
            res = self.svc.run_args(args, on_progress=progress, cancel_event=cancel_event)
            self._finish_from_result(res, finish, ok_msg=f"已安装：{' '.join(specs)}")

        self._start_op(title, work)

    def _confirm_and_run_args(self, pip_args, title):
        """完整命令（install 通道）：确认框预览替换 python 前缀后的完整 argv。

        不注入镜像——尊重用户命令里的显式 --index-url 与 python 根下 pip.ini。
        """
        preview = self.svc.preview_command(pip_args)
        specs = [a for a in pip_args[1:] if not str(a).startswith("-")] if pip_args else []
        content = (f"将执行：\n{preview}\n\n索引源：以命令内参数与 pip.ini 为准"
                   + self._risk_lines(specs, "升级"))
        if not DialogHelper.show_confirmation(self.page, title, content, yes_text="执行"):
            return

        def work(cancel_event, progress, finish):
            res = self.svc.run_args(pip_args, on_progress=progress, cancel_event=cancel_event)
            self._finish_from_result(res, finish, ok_msg="命令执行完成")

        self._start_op(title, work)

    def _confirm_and_uninstall(self, names):
        names = [str(n) for n in names if str(n).strip()]
        if not names:
            return
        content = (f"将从当前环境卸载：\n{'、'.join(names)}\n\n此操作不可撤销。"
                   + self._risk_lines(names, "卸载"))
        if not DialogHelper.show_confirmation(self.page, "卸载 Python 库", content,
                                              yes_text="卸载", destructive=True):
            return

        def work(cancel_event, progress, finish):
            res = self.svc.uninstall(names, on_progress=progress, cancel_event=cancel_event)
            self._finish_from_result(res, finish, ok_msg=f"已卸载：{'、'.join(names)}")

        self._start_op(f"卸载 {', '.join(names)}", work)

    @staticmethod
    def _finish_from_result(res, finish, ok_msg):
        if res.get("cancelled"):
            finish("cancel", "已取消（中途取消可能留下不完整安装，可重新安装修复）")
            return
        if res.get("success"):
            finish("ok", ok_msg)
            return
        msg = res.get("error") or "操作失败"
        tail = (res.get("stderr") or "")[-800:]
        if tail:
            msg = f"{msg}\n\n{tail}"
        finish("fail", msg)
