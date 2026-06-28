"""插件（custom_nodes）管理页面 —— 纯 UI + 信号。

页面职责：展示已装插件列表 + 勾选 + 通过信号请求操作。
- populate(plugins)：填充列表（plugins 来自 PluginService.list_installed）
- 信号由控制器（PluginController）接线到 PluginService（后台线程 + 进度）：
    update_all_requested / update_selected_requested(list) / refresh_requested
    disable_selected_requested(list) / enable_selected_requested(list)
    uninstall_selected_requested(list) / install_requested(str)
    check_updates_requested / outdated_reported(list) / force_update_suggested(list)

页面不直接调 PluginService，也不 import qt_app —— 这样可在 offscreen 下单测。

字段约定（plugins 来自 PluginService.list_installed）：
- name:     展示用纯名（已刻掉 .disabled 后缀）
- dir_name: 磁盘真实目录名（禁用插件带 .disabled 后缀），操作一律传它
- enabled:  是否启用（据 dir_name 是否以 .disabled 结尾判断）
- is_git/version/remote_url: git 元信息
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from .base_page import BasePage


# UserRole+2：标记「有更新」，由 mark_outdated 写入，delegate 读它画紫色徽章
# （item.text() 仍保留「🔄 ... [可更新]」兼容测试断言，但绘制走这个标志）。
_OUTDATED_ROLE = QtCore.Qt.UserRole + 2
# UserRole+3：远端 commit 日期（YYYY-MM-DD），仅 outdated 插件有，delegate 读它画远端日期列。
_REMOTE_DATE_ROLE = QtCore.Qt.UserRole + 3
# UserRole+4：标记「已检查更新」。mark_outdated 后所有插件都置 True；
# delegate 据此区分「有更新/无更新/未检查/无法检查」四态。
_CHECKED_ROLE = QtCore.Qt.UserRole + 4


def _column_geometry(width, px):
    """列表各列的 x 起点 / 宽度（delegate 与表头共用同一份真相，保证对齐）。

    width: item/content 区域可用宽度（已扣除 list padding/border）。
    px: theme_styles._px 缩放函数。
    列顺序（左→右）：复选框 | 图标+名称 | 可更新 | 版本 | 远端日期 | 类型 | 状态。
    名称列吃掉中间剩余空间（update_col_x 左边界即名称列右边界）。
    """
    right_margin = px(14)
    status_w = px(58)    # 状态列：启用/禁用 胶囊
    type_w = px(48)      # 类型列：Git/CNR/本地
    local_w = px(92)     # 版本（pyproject 版本号 / git hash）
    remote_w = px(92)    # 远端日期
    update_w = px(72)    # 可更新徽章列（仅 outdated 显示徽章，否则空）
    cb_x, cb_w = px(10), px(16)
    icon_x, icon_w = px(38), px(22)
    name_x = icon_x + icon_w + px(2)
    # 右侧五列从右往左排：status | type | remote | local(version) | update
    status_x = width - right_margin - status_w
    type_x = status_x - type_w
    remote_x = type_x - remote_w
    local_x = remote_x - local_w
    update_x = local_x - update_w
    return {
        "cb_x": cb_x, "cb_w": cb_w,
        "icon_x": icon_x, "icon_w": icon_w,
        "name_x": name_x, "name_right": update_x,
        "update_x": update_x, "update_w": update_w,
        "local_x": local_x, "local_w": local_w,
        "remote_x": remote_x, "remote_w": remote_w,
        "type_x": type_x, "type_w": type_w,
        "status_x": status_x, "status_w": status_w,
        "right_margin": right_margin,
    }


class PluginItemDelegate(QtWidgets.QStyledItemDelegate):
    """插件列表行的自定义绘制：多列卡片 / 图标 / 类型/日期列 / 状态徽章 / 柔和选中态 + 左紫条。

    纯绘制（不创建子 widget）：所有交互（勾选/选中）仍由 QListWidget 的
    setCheckState / 选中模型驱动，本类只负责「怎么画」。这样 controller、qt_app、
    selected_dir_names 全部不用改，测试也不用改。

    列结构（横向，自左向右）—— 对齐 ComfyUI-Manager 的列设计：
        [复选框][类型徽章 Git/本地][🧩][名称(粗体,弹性)][本地日期][远端日期][有更新徽章]
    - 本地日期：git 插件的 HEAD commit 日期（YYYY-MM-DD），无网络开销。
    - 远端日期：仅「检查更新」后对落后插件填充（需 origin ref），未检查时为空。
    """

    def __init__(self, theme_manager, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._px = lambda v: theme_manager.styles._px(v)
        self._pt = lambda v: theme_manager.styles._pt(v)

    def _colors(self):
        return self.theme_manager.colors

    def paint(self, painter, option, index):
        c = self._colors()
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        rect = option.rect
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hover = bool(option.state & QtWidgets.QStyle.State_MouseOver)

        # ---- 1. 行背景 ----
        if selected:
            painter.fillRect(rect, QtGui.QColor(127, 86, 217, 64))  # ≈0.25 alpha 柔和紫底
        elif hover:
            painter.fillRect(rect, QtGui.QColor(c.get("group_bg", "rgba(0,0,0,0.2)")))

        if selected:  # 左侧 3px 紫色指示条
            bar = c.get("btn_primary_bg", "#7F56D9")
            painter.fillRect(QtCore.QRect(rect.left(), rect.top(), self._px(3), rect.height()),
                             QtGui.QColor(bar))
        elif not selected:  # 底部极弱分割线
            div = QtGui.QColor(255, 255, 255, 13) if c.get("dark") else QtGui.QColor(0, 0, 0, 13)
            painter.fillRect(QtCore.QRect(rect.left(), rect.bottom() - self._px(1),
                                          rect.width(), self._px(1)), div)

        # ---- 2. 读数据 ----
        plugin = index.data(QtCore.Qt.UserRole) or {}
        outdated = bool(index.data(_OUTDATED_ROLE))
        checked_update = bool(index.data(_CHECKED_ROLE))  # 是否已点过「检查更新」
        remote_date = index.data(_REMOTE_DATE_ROLE) or ""
        enabled = plugin.get("enabled", True)
        name = plugin.get("name", index.data(QtCore.Qt.DisplayRole) or "")
        kind = plugin.get("kind", "local")  # git / cnr / local
        # 版本：优先 pyproject 版本号（CNR/git 插件都有），回退 git commit 日期
        version = plugin.get("version", "") or plugin.get("local_date", "")

        # ---- 列几何（与表头共用 _column_geometry，保证对齐）----
        g = _column_geometry(rect.width(), self._px)

        # ---- 3. 复选框（原生绘制，必须手动把 check state 设进 opt.state 才有视觉反馈）----
        style = option.widget.style()
        opt_cb = QtWidgets.QStyleOptionButton()
        opt_cb.rect = QtCore.QRect(rect.left() + g["cb_x"],
                                   rect.center().y() - self._px(8),
                                   g["cb_w"], self._px(16))
        # option.state 只含 Selected/Enabled/MouseOver，不含勾选态。
        # PE_IndicatorCheckBox 靠 State_On/State_Off 画选中/未选中外观，
        # 必须从 index 读 CheckStateRole 并或进 opt_cb.state，否则勾选了框也不变。
        checked = (index.data(QtCore.Qt.CheckStateRole) == QtCore.Qt.Checked)
        opt_cb.state = option.state | (QtWidgets.QStyle.State_On if checked
                                       else QtWidgets.QStyle.State_Off)
        style.drawPrimitive(QtWidgets.QStyle.PE_IndicatorCheckBox, opt_cb, painter, option.widget)

        # ---- 4. 🧩 图标（紧跟复选框）----
        icon_x = rect.left() + g["icon_x"]
        painter.setFont(QtGui.QFont("Microsoft YaHei UI", self._pt(11)))
        painter.setPen(QtGui.QColor(c.get("label_muted", "#9CA3AF")))
        painter.drawText(QtCore.QRect(icon_x, rect.top(), g["icon_w"], rect.height()),
                         QtCore.Qt.AlignCenter, "🧩")

        # ---- 5. 名称（粗体；禁用态灰。「可更新」标记移到独立列，名称区不加前缀）----
        name_x = rect.left() + g["name_x"]
        name_right = rect.left() + g["name_right"]
        name_font = QtGui.QFont("Microsoft YaHei UI", self._pt(10))
        name_font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(name_font)
        if not enabled:
            painter.setPen(QtGui.QColor(c.get("label_dim", "#6B7280")))
        else:
            painter.setPen(QtGui.QColor(c.get("text", "#FFFFFF")))
        name_rect = QtCore.QRect(name_x, rect.top(), max(0, name_right - name_x), rect.height())
        fm = QtGui.QFontMetrics(name_font)
        elided = fm.elidedText(name, QtCore.Qt.ElideRight, name_rect.width())
        painter.drawText(name_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, elided)

        # ---- 6. 可更新列（四态：有更新/无更新/无法检查/未检查）----
        update_rect = QtCore.QRect(rect.left() + g["update_x"], rect.top(),
                                   g["update_w"], rect.height())
        uf = QtGui.QFont("Microsoft YaHei UI", self._pt(8))
        uf.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(uf)
        px_margin = self._px(2)
        pill_h = self._px(20)
        pill_w = g["update_w"] - px_margin * 2
        pill_x = update_rect.center().x() - pill_w // 2
        pill_y = update_rect.center().y() - pill_h // 2
        pill = QtCore.QRect(pill_x, pill_y, pill_w, pill_h)
        accent = c.get("btn_primary_hover", "#9E77ED")
        muted = c.get("label_muted", "#9CA3AF")
        dim = c.get("label_dim", "#6B7280")
        success = "#22C55E"
        if outdated:
            # 有更新：紫色药丸
            painter.setBrush(QtGui.QColor(127, 86, 217, 50))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(pill, pill_h // 2, pill_h // 2)
            painter.setPen(QtGui.QColor(accent))
            painter.drawText(pill, QtCore.Qt.AlignCenter, "有更新")
        elif checked_update and kind in ("git", "cnr"):
            # 已检查且非 outdated：无更新（绿色淡底）
            painter.setBrush(QtGui.QColor(34, 197, 94, 35))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(pill, pill_h // 2, pill_h // 2)
            painter.setPen(QtGui.QColor(success))
            painter.drawText(pill, QtCore.Qt.AlignCenter, "无更新")
        elif checked_update and kind == "local":
            # 已检查但 local：无法检查更新源
            painter.setPen(QtGui.QColor(dim))
            painter.drawText(update_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter, "无法检查")
        else:
            # 未检查（点检查更新前）
            painter.setPen(QtGui.QColor(dim))
            painter.drawText(update_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter, "—")

        # ---- 7. 版本列（优先 pyproject 版本号；无则 git 日期；都没有 —）----
        date_font = QtGui.QFont("Microsoft YaHei UI", self._pt(8))
        painter.setFont(date_font)
        local_rect = QtCore.QRect(rect.left() + g["local_x"], rect.top(), g["local_w"], rect.height())
        if version:
            painter.setPen(QtGui.QColor(c.get("label_muted", "#9CA3AF")))
            painter.drawText(local_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter, version)
        else:
            painter.setPen(QtGui.QColor(c.get("label_dim", "#6B7280")))
            painter.drawText(local_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter, "—")

        # ---- 8. 远端日期（检查更新后才有；落后时用强调色）----
        remote_rect = QtCore.QRect(rect.left() + g["remote_x"], rect.top(), g["remote_w"], rect.height())
        if remote_date:
            painter.setPen(QtGui.QColor(c.get("btn_primary_hover", "#9E77ED")) if outdated
                           else QtGui.QColor(c.get("label_muted", "#9CA3AF")))
            painter.drawText(remote_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter, remote_date)
        else:
            painter.setPen(QtGui.QColor(c.get("label_dim", "#6B7280")))
            painter.drawText(remote_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter, "—")

        # ---- 9. 类型列（Git / CNR / 本地，三态纯文字）----
        type_rect = QtCore.QRect(rect.left() + g["type_x"], rect.top(), g["type_w"], rect.height())
        type_font = QtGui.QFont("Microsoft YaHei UI", self._pt(8))
        type_font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(type_font)
        # git=紫（可 pull 更新）/ cnr=蓝（registry 发布版）/ local=灰（无更新源）
        if kind == "git":
            type_text, type_color = "Git", QtGui.QColor(c.get("btn_primary_hover", "#9E77ED"))
        elif kind == "cnr":
            type_text, type_color = "CNR", QtGui.QColor("#60A5FA")
        else:
            type_text, type_color = "本地", QtGui.QColor(c.get("label_muted", "#9CA3AF"))
        painter.setPen(type_color)
        painter.drawText(type_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter, type_text)

        # ---- 10. 状态列（胶囊+圆点：启用=绿，禁用=灰）----
        status_rect = QtCore.QRect(rect.left() + g["status_x"], rect.top(),
                                   g["status_w"], rect.height())
        status_font = QtGui.QFont("Microsoft YaHei UI", self._pt(8))
        status_font.setWeight(QtGui.QFont.DemiBold)
        painter.setFont(status_font)
        # 胶囊尺寸：居中于 status_rect
        pill_w, pill_h = self._px(54), self._px(20)
        pill_x = status_rect.center().x() - pill_w // 2
        pill_y = status_rect.center().y() - pill_h // 2
        pill_rect = QtCore.QRect(pill_x, pill_y, pill_w, pill_h)
        if enabled:
            dot_color = QtGui.QColor("#22C55E")
            pill_bg = QtGui.QColor(34, 197, 94, 40)   # 绿 15% alpha
            text_color = QtGui.QColor("#4ADE80")
            text = "启用"
        else:
            dot_color = QtGui.QColor(c.get("label_dim", "#6B7280"))
            pill_bg = QtGui.QColor(107, 114, 128, 40)  # 灰 15% alpha
            text_color = QtGui.QColor(c.get("label_muted", "#9CA3AF"))
            text = "禁用"
        # 胶囊底
        painter.setBrush(pill_bg)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRoundedRect(pill_rect, pill_h // 2, pill_h // 2)
        # 圆点（胶囊内左侧）
        dot_r = self._px(4)
        dot_cx = pill_x + self._px(10)
        dot_cy = pill_rect.center().y()
        painter.setBrush(dot_color)
        painter.drawEllipse(QtCore.QPoint(dot_cx, dot_cy), dot_r, dot_r)
        # 文字（圆点右侧）
        painter.setPen(text_color)
        text_rect = QtCore.QRect(dot_cx + dot_r + self._px(4), pill_y,
                                 pill_w - self._px(14), pill_h)
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, text)

        painter.restore()

    def sizeHint(self, option, index):
        return QtCore.QSize(0, self.theme_manager.styles._px(42))

    def editorEvent(self, event, model, option, index):
        """自绘 checkbox 后，点击→toggle 完全由本 delegate 接管。

        关键坑：QStyledItemDelegate 基类的 editorEvent 在 MouseButtonRelease 时会
        对 checkable item 再 toggle 一次。若我们只在 Press 处理、Release fallthrough
        到 super()，就会「Press toggle + Release toggle = 抵消」，用户看到没反应。
        所以 Press 命中 checkbox → toggle；**Release 一律返回 True 消费掉**，阻断基类。

        点击落在 checkbox 矩形内才 toggle，点名称/日期区不响应。
        """
        etype = event.type()
        if etype == QtCore.QEvent.MouseButtonRelease:
            return True  # 阻断基类在 Release 时重复 toggle（无论是否命中 checkbox）
        if etype == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            g = _column_geometry(option.rect.width(), self._px)
            cb_rect = QtCore.QRect(option.rect.left() + g["cb_x"],
                                   option.rect.center().y() - self._px(8),
                                   g["cb_w"], self._px(16))
            if cb_rect.contains(event.pos()):
                checked = (index.data(QtCore.Qt.CheckStateRole) == QtCore.Qt.Checked)
                model.setData(index, QtCore.Qt.Unchecked if checked else QtCore.Qt.Checked,
                              QtCore.Qt.CheckStateRole)
        return super().editorEvent(event, model, option, index)


class _PluginListHeader(QtWidgets.QWidget):
    """插件列表的表头行。

    用 paintEvent + _column_geometry 自绘。为与下方 delegate 的列严格对齐，
    持有 list_widget 引用，paint 时直接读 item 的实际绘制 rect（option.rect）宽度，
    保证表头和内容用「同一份宽度」算列位，杜绝错位。
    不在 QListWidget 内部（那样会被当成一行），而是固定在列表上方。
    """

    def __init__(self, theme_manager, list_widget=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._list_widget = list_widget  # 弱引用，paint 时读它的 item rect 宽度
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        c = theme_manager.colors
        self.setStyleSheet(f"""
            _PluginListHeader {{
                background-color: {c.get('group_bg', 'rgba(0,0,0,0.2)')};
                border: 1px solid {c.get('input_border', '#4B5563')};
                border-bottom: 1px solid {c.get('divider', '#374151')};
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
        """)
        self.setFixedHeight(theme_manager.styles._px(30))

    def _content_width(self):
        """取与 delegate 完全一致的列内容区宽度：读 list_widget 第一个 item 的 rect.width()。

        delegate 的 option.rect 就是这个值（list viewport 内 item 的实际绘制宽度，
        已含 padding/滚动条扣除）。表头用同一个值算 _column_geometry，列位天然对齐。
        list_widget 不可用或为空时回退到自身宽度近似。
        """
        lw = self._list_widget
        if lw is not None:
            try:
                # 取第一个可见 item 的 rect（和 delegate 用的 option.rect 同源）
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
        px = self.theme_manager.styles._px
        pt = self.theme_manager.styles._pt
        # 与 delegate 同口径的列内容区宽度
        w = self._content_width()
        g = _column_geometry(w, px)
        # ox 偏移：表头自身 border(1)。delegate 用 rect.left()（已含 list padding），
        # 这里表头没有 list 的内 padding，用自身 border 偏移 + list 的 padding 对齐。
        lw = self._list_widget
        pad = 0
        if lw is not None:
            try:
                # list 的 contentsMargins/padding —— QListWidget 的 viewport 起点
                item = lw.item(0)
                if item is not None:
                    r = lw.visualItemRect(item)
                    # 表头左边到 item rect 左边的偏移
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

        # 复选框列：留白（不画标题，留给复选框区域）
        # 名称列（左对齐，覆盖 icon + name 区）
        name_x = g["icon_x"]
        name_w = g["name_right"] - name_x
        draw_label(name_x, name_w, "插件", QtCore.Qt.AlignLeft)
        # 可更新 / 版本 / 远端日期 / 类型 / 状态
        draw_label(g["update_x"], g["update_w"], "可更新")
        draw_label(g["local_x"], g["local_w"], "版本")
        draw_label(g["remote_x"], g["remote_w"], "远端日期")
        draw_label(g["type_x"], g["type_w"], "类型")
        draw_label(g["status_x"], g["status_w"], "状态")
        painter.end()


class PluginsPage(BasePage):
    """插件管理页面：列已装、勾选、请求更新/卸载/启用禁用/安装/检查更新。"""

    # ---- 信号：页面 → 控制器（再由控制器调 service）----
    update_all_requested = QtCore.pyqtSignal()
    update_selected_requested = QtCore.pyqtSignal(list)
    refresh_requested = QtCore.pyqtSignal()
    force_update_suggested = QtCore.pyqtSignal(list)  # 正常更新后仍有失败 → 建议强制更新（带名字）

    # 新增操作信号：disable/enable 传 dir_name list；uninstall 走二次确认（见 controller/qt_app）
    disable_selected_requested = QtCore.pyqtSignal(list)
    enable_selected_requested = QtCore.pyqtSignal(list)
    uninstall_selected_requested = QtCore.pyqtSignal(list)  # 由 qt_app 弹确认框
    install_requested = QtCore.pyqtSignal(str)              # git URL / CNR id
    check_updates_requested = QtCore.pyqtSignal()           # 批量 ls-remote
    outdated_reported = QtCore.pyqtSignal(list, dict)        # 控制器回推：(落后 dir_name 列表, {dir_name: 远端日期})

    def __init__(self, app=None, theme_manager=None, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self._outdated_dir_names = set()  # 当前标记为「有更新」的 dir_name（populate 时清空）
        self._setup_ui()

    def _setup_ui(self):
        c = self.theme_manager.colors
        s = self.theme_manager.styles
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("插件管理")
        title.setStyleSheet(f"""
            font: bold 16pt "Microsoft YaHei UI";
            color: {c.get('label')};
            margin-bottom: 2px;
        """)
        layout.addWidget(title)

        # 一级按钮区（单行）：刷新(ghost)  安装插件(ghost)  ←stretch→  检查更新(primary) 更新全部(primary)
        # 三级视觉权重：ghost 弱、primary 强。依赖勾选的操作收纳到下方 ActionBar。
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        self.refresh_btn = QtWidgets.QPushButton("刷新列表")
        self.install_btn = QtWidgets.QPushButton("安装插件")
        self.check_updates_btn = QtWidgets.QPushButton("检查更新")
        self.update_all_btn = QtWidgets.QPushButton("更新全部")
        try:
            self.refresh_btn.setStyleSheet(s.secondary_button_style())
            self.install_btn.setStyleSheet(s.secondary_button_style())
            self.check_updates_btn.setStyleSheet(s.primary_button_style())
            self.update_all_btn.setStyleSheet(s.primary_button_style())
        except Exception:
            pass
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        # install_btn.clicked 不在 page 内连 —— qt_app 直接连它弹输入框（install 需要用户输入 URL）。
        self.check_updates_btn.clicked.connect(self.check_updates_requested.emit)
        self.update_all_btn.clicked.connect(self.update_all_requested.emit)
        # 左：刷新 / 安装；右：检查更新 / 更新全部
        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(self.install_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.check_updates_btn)
        toolbar.addWidget(self.update_all_btn)
        layout.addLayout(toolbar)

        # ActionBar：勾选任意项时浮现操作条。为避免显隐导致下方表格上下抖动，
        # ActionBar 始终占固定高度（不隐藏）：未勾选时显示淡色提示、隐藏操作按钮；
        # 勾选时显示操作按钮 + 计数。这样表格位置永远固定。
        self._action_bar = QtWidgets.QWidget()
        self._action_bar.setObjectName("PluginActionBar")
        self._action_bar.setStyleSheet(f"""
            QWidget#PluginActionBar {{
                background-color: {c.get('group_bg', 'rgba(0,0,0,0.2)')};
                border: 1px solid {c.get('input_border', '#4B5563')};
                border-radius: 6px;
            }}
        """)
        self._action_bar.setFixedHeight(44)  # 固定高度，杜绝表格抖动
        ab_layout = QtWidgets.QHBoxLayout(self._action_bar)
        ab_layout.setContentsMargins(10, 6, 10, 6)
        ab_layout.setSpacing(8)
        # 未勾选时的提示文字（默认显示）
        self._ab_hint_label = QtWidgets.QLabel("勾选插件以显示批量操作")
        self._ab_hint_label.setStyleSheet(
            f"color: {c.get('label_dim', '#6B7280')}; font: 9pt 'Microsoft YaHei UI';")
        # 勾选时的标签 + 计数
        ab_label = QtWidgets.QLabel("已选中：")
        ab_label.setStyleSheet(f"color: {c.get('label_muted', '#9CA3AF')}; font: 9pt 'Microsoft YaHei UI';")
        self._ab_count_label = QtWidgets.QLabel("0")
        self._ab_count_label.setStyleSheet(
            f"color: {c.get('btn_primary_hover', '#9E77ED')}; font: bold 9pt 'Microsoft YaHei UI';")
        self.update_selected_btn = QtWidgets.QPushButton("更新选中")
        self.enable_btn = QtWidgets.QPushButton("启用选中")
        self.disable_btn = QtWidgets.QPushButton("禁用选中")
        self.uninstall_btn = QtWidgets.QPushButton("卸载选中")
        try:
            self.update_selected_btn.setStyleSheet(s.secondary_button_style())
            self.enable_btn.setStyleSheet(s.secondary_button_style())
            self.disable_btn.setStyleSheet(s.destructive_outline_button_style())
            self.uninstall_btn.setStyleSheet(s.destructive_outline_button_style())
        except Exception:
            pass
        self.update_selected_btn.clicked.connect(self._emit_update_selected)
        self.enable_btn.clicked.connect(lambda: self.enable_selected_requested.emit(self.selected_dir_names()))
        self.disable_btn.clicked.connect(lambda: self.disable_selected_requested.emit(self.selected_dir_names()))
        self.uninstall_btn.clicked.connect(lambda: self.uninstall_selected_requested.emit(self.selected_dir_names()))
        # 装入布局：提示文字（默认可见）+ 勾选态组件（默认隐藏）
        ab_layout.addWidget(self._ab_hint_label)
        ab_layout.addStretch()
        ab_layout.addWidget(ab_label)
        ab_label.hide()
        ab_layout.addWidget(self._ab_count_label)
        ab_layout.addSpacing(12)
        for b in (self.update_selected_btn, self.enable_btn, self.disable_btn, self.uninstall_btn):
            ab_layout.addWidget(b)
            b.hide()
        ab_layout.addStretch()
        # 记录勾选态组件，便于 _refresh_action_bar 切换显隐
        self._ab_active_widgets = [ab_label, self._ab_count_label,
                                   self.update_selected_btn, self.enable_btn,
                                   self.disable_btn, self.uninstall_btn]
        layout.addWidget(self._action_bar)

        # 表头 + 列表包进同一容器（spacing=0），消除两者间的视觉断层。
        list_container = QtWidgets.QVBoxLayout()
        list_container.setSpacing(0)
        list_container.setContentsMargins(0, 0, 0, 0)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setItemDelegate(PluginItemDelegate(self.theme_manager, self.list_widget))
        # 表头在列表上方，传 list_widget 引用以便 paint 时读 item rect 宽度，列位与内容严格对齐
        self.list_header = _PluginListHeader(self.theme_manager, list_widget=self.list_widget, parent=self)
        list_container.addWidget(self.list_header)
        # QSS 只保留外层背景 + 滚动条（item/indicator/选中态全由 delegate 绘制）。
        # 顶部 border 去掉（表头压在上面接管顶部），底部保留圆角，形成「表头 + 列表」一体的容器观感。
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {c.get('input_bg')};
                color: {c.get('text')};
                border: 1px solid {c.get('input_border')};
                border-top: none;
                border-bottom-left-radius: 6px;
                border-bottom-right-radius: 6px;
                padding: 4px;
                font: 10pt "Microsoft YaHei UI";
                outline: none;
            }}
            /* 列表内部滚动条：紫色半透明 handle（外层 wrap_in_scroll 的 QSS 不继承进来，故单设） */
            QScrollBar:vertical {{
                background: transparent; width: 8px; margin: 2px;
                border: none; border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {c.get('scroll_handle', '#6366F1')};
                border-radius: 4px; min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {c.get('scroll_handle_hover', '#5258CF')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)
        list_container.addWidget(self.list_widget)
        # 勾选状态变化 → 刷新 ActionBar 显隐 + 选中计数
        self.list_widget.itemChanged.connect(lambda _item: self._refresh_action_bar())
        layout.addLayout(list_container)

    def _refresh_action_bar(self):
        """勾选状态变化 → 切换 ActionBar 内容（提示文字 ↔ 操作按钮），ActionBar 本身始终占位。

        关键：ActionBar 高度固定不变（44px），只切换内部组件显隐，杜绝勾选导致表格抖动。
        """
        n = len(self.selected_dir_names())
        self._ab_count_label.setText(str(n))
        if n > 0:
            self._ab_hint_label.hide()
            for w in self._ab_active_widgets:
                w.show()
        else:
            self._ab_hint_label.show()
            for w in self._ab_active_widgets:
                w.hide()

    def _emit_update_selected(self):
        self.update_selected_requested.emit(self.selected_dir_names())

    def populate(self, plugins):
        """用 PluginService.list_installed() 的结果填充列表。每项可勾选。

        显示规则：
        - item 文本 = 纯 name（保持 selected_* 返回可对照的标识，禁用项加后缀区分）
        - 禁用项：文本加「（已禁用）」、前景灰
        - git 插件：tooltip 显示版本/来源
        - 全量重填时清空 outdated 标记（需重新点「检查更新」）
        """
        self._outdated_dir_names = set()
        self.list_widget.clear()
        for p in plugins:
            name = p.get("name", "?")
            dir_name = p.get("dir_name", name)
            enabled = p.get("enabled", True)
            is_git = p.get("is_git", False)
            display = name if enabled else f"{name}（已禁用）"
            item = QtWidgets.QListWidgetItem(display)
            item.setData(QtCore.Qt.UserRole, p)
            item.setData(QtCore.Qt.UserRole + 1, dir_name)  # dir_name 单独存，便于 selected_dir_names
            # 必须显式加 ItemIsUserCheckable，否则 setCheckState 后用户点击无法切换勾选态。
            # QListWidgetItem 默认 flags 只含 IsEnabled|IsSelectable，不含可勾选。
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked)
            # tooltip
            tip_lines = [f"{name}"]
            if not enabled:
                tip_lines.append("状态: 已禁用")
            if is_git:
                ver = (p.get("version") or "")[:12]
                remote = p.get("remote_url") or ""
                tip_lines.append(f"版本: {ver or '(未知)'}")
                tip_lines.append(f"来源: {remote or '(未知)'}")
            else:
                tip_lines.append("（非 git 插件，无法更新/强制更新）")
            item.setToolTip("\n".join(tip_lines))
            # 禁用项灰字
            if not enabled:
                item.setForeground(QtGui.QBrush(QtGui.QColor(
                    self.theme_manager.colors.get("label_dim", "#9CA3AF"))))
            self.list_widget.addItem(item)

    def mark_outdated(self, dir_names, remote_dates=None):
        """controller 通过 outdated_reported 推回 → 标记对应项并重排（可更新置顶）。

        - UserRole+2 写 True：PluginItemDelegate 读它画「可更新」徽章列。
        - UserRole+3 写远端日期（若有）：delegate 读它画「远端日期」列。
        - item.text() 仍写「🔄 ... [可更新]」兼容测试断言（绘制不依赖 text）。
        - 重排：outdated 项移到列表顶部，便于一眼看到需更新的插件。
        重新 populate 会重置（新 item 默认无这些标志，恢复 name 排序）。
        """
        self._outdated_dir_names = {str(d) for d in dir_names}
        remote_dates = remote_dates or {}
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            dir_name = item.data(QtCore.Qt.UserRole + 1)
            is_outdated = dir_name in self._outdated_dir_names
            item.setData(_OUTDATED_ROLE, is_outdated)
            item.setData(_CHECKED_ROLE, True)  # 标记「已检查」，delegate 据此画无更新/无法检查
            # 远端日期仅对 outdated 且查到了的插件写入
            item.setData(_REMOTE_DATE_ROLE, remote_dates.get(dir_name, "") if is_outdated else "")
            if is_outdated:
                accent = self.theme_manager.colors.get("btn_primary_bg", "#6366F1")
                base = item.data(QtCore.Qt.UserRole) or {}
                name = base.get("name", item.text())
                enabled = base.get("enabled", True)
                display = name if enabled else f"{name}（已禁用）"
                item.setText(f"🔄 {display}  [可更新]")
                item.setForeground(QtGui.QBrush(QtGui.QColor(accent)))
        # 重排：outdated 项移到顶部（保留各自组内原有的 name 排序）
        self._reorder_outdated_first()

    def _reorder_outdated_first(self):
        """把 outdated 项移到列表顶部，其余按原顺序跟在后面。

        用 takeItem/insertItem 物理重排，保留每个 item 的所有 data/状态。
        不重排时（无 outdated 或全部 outdated）直接返回。
        """
        lw = self.list_widget
        if not self._outdated_dir_names:
            return
        outdated_items = []
        other_items = []
        for i in range(lw.count()):
            item = lw.item(i)
            dn = item.data(QtCore.Qt.UserRole + 1)
            (outdated_items if dn in self._outdated_dir_names else other_items).append(item)
        if not outdated_items or len(outdated_items) == lw.count():
            return
        # 全部 take 出来再按新顺序插回（保留选中/勾选态）
        for item in outdated_items + other_items:
            lw.takeItem(lw.row(item))
        for item in outdated_items + other_items:
            lw.addItem(item)

    def plugin_names(self):
        """返回所有项的纯 name（向后兼容旧测试）。"""
        return [self._item_name(self.list_widget.item(i)) for i in range(self.list_widget.count())]

    def _item_name(self, item):
        """从 item 取展示用的纯 name（剥掉 🔄 前缀和状态后缀）。"""
        p = item.data(QtCore.Qt.UserRole) or {}
        return p.get("name", item.text())

    def selected_names(self):
        """返回当前勾选项的纯 name 列表（向后兼容）。"""
        names = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                names.append(self._item_name(item))
        return names

    def selected_dir_names(self):
        """返回当前勾选项的 dir_name 列表（操作一律用这个，禁用项带 .disabled 后缀）。"""
        dir_names = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                dn = item.data(QtCore.Qt.UserRole + 1)
                if dn is None:
                    dn = self._item_name(item)
                dir_names.append(str(dn))
        return dir_names


class PluginController:
    """把 PluginsPage 的信号编排到 PluginService（可单测）。

    依赖注入：run_in_background(fn) 把 fn 丢到工作线程；post_to_ui(fn) 把 fn
    派回 UI 线程。qt_app 侧注入真实现（QThread + signal），测试注入同步替身。
    页面信号→服务调用→更新后刷新 的编排都在这里，故不依赖 qt_app、可 offscreen 测。

    disable/enable/uninstall 的 service 方法接收**单个** target（不是 list），
    这里在 _*_work 里循环逐个调用，与 service 既定 _lifecycle 契约一致。
    """

    def __init__(self, page, plugin_service, run_in_background, post_to_ui, sync_deps=None):
        self.page = page
        self.svc = plugin_service
        self._run_in_background = run_in_background
        self._post_to_ui = post_to_ui
        # 强制更新后复用普通更新的「同步依赖库」流程；qt_app 注入（按 auto_update_deps_var
        # 网关调 update_service.sync_requirements_files）。None 则跳过。
        self._sync_deps = sync_deps
        page.refresh_requested.connect(self._on_refresh)
        page.update_all_requested.connect(self._on_update_all)
        page.update_selected_requested.connect(self._on_update_selected)
        page.disable_selected_requested.connect(self._on_disable_selected)
        page.enable_selected_requested.connect(self._on_enable_selected)
        page.check_updates_requested.connect(self._on_check_updates)

    def _on_refresh(self):
        self._run_in_background(self._refresh_work)

    def _refresh_work(self):
        self._populate_from_service()

    def _on_update_all(self):
        self._run_in_background(self._update_all_work)

    def run_update_all(self, on_status=None, on_done=None):
        """qt_app 触发：带进度回调的「更新全部」。on_status(str)/on_done() 派回 UI 线程。"""
        def work():
            try:
                if on_status:
                    self._post_to_ui(lambda: on_status("正在更新全部插件（cm-cli update all，含 pip 依赖修复）..."))
                self.svc.update_all()
            finally:
                self._populate_from_service()
                if on_done:
                    self._post_to_ui(on_done)
        self._run_in_background(work)

    def _update_all_work(self):
        self.svc.update_all()
        self._populate_from_service()

    def _on_update_selected(self, names):
        self._run_in_background(lambda: self._update_selected_work(names))

    def _update_selected_work(self, names):
        self.svc.update_selected(names)
        failed = self.svc.outdated_plugins(names)
        if failed:
            self._post_to_ui(lambda: self.page.force_update_suggested.emit(failed))
        else:
            self._populate_from_service()

    # ---- disable / enable（service 单 target，循环调用）----
    def _on_disable_selected(self, dir_names):
        self._run_in_background(lambda: self._lifecycle_work("disable", dir_names))

    def _on_enable_selected(self, dir_names):
        self._run_in_background(lambda: self._lifecycle_work("enable", dir_names))

    def _lifecycle_work(self, op, dir_names):
        for dn in dir_names:
            getattr(self.svc, op)(dn)
        self._populate_from_service()

    # ---- uninstall（破坏性，需 qt_app 二次确认后调 apply_uninstall）----
    def apply_uninstall(self, dir_names):
        """用户在二次确认弹窗里同意后调用：卸载这些插件。"""
        self._run_in_background(lambda: self._uninstall_work(dir_names))

    def _uninstall_work(self, dir_names):
        for dn in dir_names:
            self.svc.uninstall(dn)
        self._populate_from_service()

    # ---- install（qt_app 输入框拿到 spec 后调 request_install）----
    def request_install(self, spec):
        """qt_app 输入弹窗拿到 git URL/CNR id 后调用。"""
        self._run_in_background(lambda: self._install_work(spec))

    def _install_work(self, spec):
        self.svc.install(spec)
        self._populate_from_service()

    # ---- 检查更新（批量 ls-remote，结果回推页面标记）----
    def _on_check_updates(self):
        self._run_in_background(self._check_updates_work)

    def run_check_updates(self, on_progress=None, on_done=None):
        """qt_app 触发：带逐插件进度的「检查更新」。

        on_progress(current, total, name)：每个插件查完回调（派回 UI 线程）。
        on_done(outdated_list, remote_dates_dict)：全部完成回调（派回 UI 线程）。
        """
        def work():
            # 进度回调包一层派回 UI 线程
            def svc_progress(cur, tot, name):
                if on_progress:
                    self._post_to_ui(lambda c=cur, t=tot, n=name: on_progress(c, t, n))
            outdated = self.svc.check_updates(on_progress=svc_progress)
            remote_dates = self.svc.remote_dates(outdated) if outdated else {}
            if on_done:
                self._post_to_ui(lambda: on_done(list(outdated), remote_dates))
            else:
                self._post_to_ui(lambda: self.page.outdated_reported.emit(list(outdated), remote_dates))
        self._run_in_background(work)

    def _check_updates_work(self):
        outdated = self.svc.check_updates()
        # 对落后的插件取远端 commit 日期（数量少，控制网络成本），随结果一起回推
        remote_dates = self.svc.remote_dates(outdated) if outdated else {}
        self._post_to_ui(lambda: self.page.outdated_reported.emit(list(outdated), remote_dates))

    # ---- force-update（qt_app 二次确认后调 apply_force_update）----
    def apply_force_update(self, names):
        """用户在二次确认弹窗里同意后调用：强制更新这些插件。"""
        self._run_in_background(lambda: self._force_update_work(names))

    def _force_update_work(self, names):
        self.svc.force_update_selected(names)
        # 复用普通更新的「同步依赖库」流程（与内核更新同一套，按 checkbox 网关）
        if self._sync_deps:
            try:
                self._sync_deps()
            except Exception:
                pass
        self._populate_from_service()

    def _populate_from_service(self):
        """取最新已装列表并派回 UI 线程填充页面（刷新 / 更新后都用）。"""
        plugins = self.svc.list_installed()
        self._post_to_ui(lambda: self.page.populate(plugins))
