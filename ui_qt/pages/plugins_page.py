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
from typing import Any  # B8 CR：run_force_update 里用了局部注解 `Any`，不跑运行时求值但
                         # 一旦移到模块级或加 from __future__ import annotations 前就会
                         # NameError，提前 import 消除隐患。
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
        # P0-1 同源 bug（与 PluginsPage/plugin_search_dialog 同款）：
        # __init__ 期 theme_manager.styles 是当时的实例，set_scale 会创建新 ThemeStyles，
        # 这里改实例方法每次读 live styles。与 P0-1 修法一致。
        # P2-3：5 个 QFont 不再每次 paint new，_build_fonts 预建，set_scale 后重调。
        self._font_cache = {}
        self._cb_hit_last_press = False  # P1-2：最近一次 Press 是否命中 checkbox（Release/DblClick 判断消费）

    def _px(self, v):
        return self.theme_manager.styles._px(v)

    def _pt(self, v):
        return self.theme_manager.styles._pt(v)

    def _build_fonts(self):
        """P2-3 meta-review：paint 里每次 new QFont 是轻量对象但一屏 50 行 = 250 次构造，
        也会造成 GC 压力。预建 4 档（原 deep-review 是 7 档，实际 paint 只用了 icon/name/small/
        small_bold 四个，删掉 ver/date/badge 三个死键，保持整洁）。
        B7 CR：name/small_bold 两处字重改回 DemiBold（63），不是 Bold（75）—— 原代码是
        setWeight(QtGui.QFont.DemiBold)，改成 setBold(True) 会让 名称/徽章/类型/状态 四列更粗，
        非有意变更。"""
        try:
            DemiBold = QtGui.QFont.DemiBold
            self._font_cache = {
                "icon": QtGui.QFont("Microsoft YaHei UI"),
                "name": QtGui.QFont("Microsoft YaHei UI"),
                "small": QtGui.QFont("Microsoft YaHei UI"),
                "small_bold": QtGui.QFont("Microsoft YaHei UI"),
            }
            f = self._font_cache
            f["icon"].setPointSize(self._pt(11))
            f["name"].setPointSize(self._pt(10))
            f["name"].setWeight(DemiBold)
            f["small"].setPointSize(self._pt(8))
            f["small_bold"].setPointSize(self._pt(8))
            f["small_bold"].setWeight(DemiBold)
        except Exception:
            pass

    def update_theme(self, theme_styles=None):
        """P2-3: theme/DPI 变化时重建字体（字号会变）。"""
        self._build_fonts()

    def _colors(self):
        return self.theme_manager.colors

    def paint(self, painter, option, index):
        c = self._colors()
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        # P2-3: 字体缓存。若 cache 没构建好（update_theme 未调过）就临时 new，保证 paint 不崩
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
        painter.setFont(_font("icon", self._pt(11)))
        painter.setPen(QtGui.QColor(c.get("label_muted", "#9CA3AF")))
        painter.drawText(QtCore.QRect(icon_x, rect.top(), g["icon_w"], rect.height()),
                         QtCore.Qt.AlignCenter, "🧩")

        # ---- 5. 名称（粗体；禁用态灰。「可更新」标记移到独立列，名称区不加前缀）----
        name_x = rect.left() + g["name_x"]
        name_right = rect.left() + g["name_right"]
        name_font = _font("name", self._pt(10), True)
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
        uf = _font("small_bold", self._pt(8), True)
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
        painter.setFont(_font("small", self._pt(8)))
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
        tf = _font("small_bold", self._pt(8), True)
        painter.setFont(tf)
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
        sf = _font("small_bold", self._pt(8), True)
        painter.setFont(sf)
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

        P1-2 meta-review：原实现 Release 一律返回 True（消费）= 点行非 checkbox 区也
        不会触发行选中；且双击时 Press + DblClick → 两个 Press（各 toggle 一次）抵消，
        用户看到没反应。修法：
        - Press 命中 checkbox → 记 _cb_hit_last_press=True，执行 toggle。
        - Release 只在 _cb_hit_last_press 时返回 True（消费），否则 False（让基类执行
          行选中）。
        - DblClick（双击）命中 checkbox 时也消费（避免基类再 toggle），否则 False。
        """
        etype = event.type()
        # 计算 checkbox 命中矩形（共用）
        def _hit_cb():
            g = _column_geometry(option.rect.width(), self._px)
            cb_rect = QtCore.QRect(option.rect.left() + g["cb_x"],
                                   option.rect.center().y() - self._px(8),
                                   g["cb_w"], self._px(16))
            return cb_rect.contains(event.pos())

        if etype == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            if _hit_cb():
                self._cb_hit_last_press = True
                checked = (index.data(QtCore.Qt.CheckStateRole) == QtCore.Qt.Checked)
                model.setData(index, QtCore.Qt.Unchecked if checked else QtCore.Qt.Checked,
                              QtCore.Qt.CheckStateRole)
                return True
            self._cb_hit_last_press = False
            return super().editorEvent(event, model, option, index)

        if etype == QtCore.QEvent.MouseButtonRelease:
            # Release 只在最近一次 Press 命中 checkbox 时消费，否则给基类处理行选中
            hit = getattr(self, "_cb_hit_last_press", False)
            self._cb_hit_last_press = False
            return True if hit else super().editorEvent(event, model, option, index)

        if etype == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.LeftButton:
            if _hit_cb():
                # 命中 checkbox：消费双击，避免基类再 toggle。Press 已经在第一次时 toggled 过了。
                return True
            return super().editorEvent(event, model, option, index)

        return super().editorEvent(event, model, option, index)


class _PluginListHeader(QtWidgets.QWidget):
    """插件列表的表头行。

    用 paintEvent + _column_geometry 自绘。为与下方 delegate 的列严格对齐，
    持有 list_widget 引用，paint 时直接读 item 的实际绘制 rect（option.rect）宽度，
    保证表头和内容用「同一份宽度」算列位，杜绝错位。
    不在 QListWidget 内部（那样会被当成一行），而是固定在列表上方。

    注意：这是裸 QWidget（不是 BasePage），所以需要自己显式 register_listener，
    不要与 PluginsPage（BasePage 子类）搞混。
    """

    def __init__(self, theme_manager, list_widget=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._list_widget = list_widget  # 弱引用，paint 时读它的 item rect 宽度
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        # 与 PluginsPage 同款：_px/_pt 每次重读 live styles，set_scale 换新 ThemeStyles 也正确
        # （见 PluginsPage._px 的注释，同源 bug）
        self.update_theme()
        # BasePage 没注册过，这里必须自己显式注册
        if self.theme_manager:
            self.theme_manager.register_listener(lambda _s: self.update_theme())

    # DPI helper（与 PluginsPage._px 同款）
    def _px(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._px(base) if styles else base

    def _pt(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._pt(base) if styles else base

    def _build_header_qss(self):
        c = getattr(self.theme_manager, "colors", {}) if self.theme_manager else {}
        px = self._px
        return (f"_PluginListHeader {{"
                f" background-color: {c.get('group_bg', 'rgba(0,0,0,0.2)')};"
                f" border: 1px solid {c.get('input_border', '#4B5563')};"
                f" border-bottom: 1px solid {c.get('divider', '#374151')};"
                f" border-top-left-radius: {px(6)}px;"
                f" border-top-right-radius: {px(6)}px;"
                f"}}")

    def update_theme(self, _theme_styles=None):
        """主题 / DPI 变化：重建 QSS + 重算固定高度。"""
        try:
            self.setStyleSheet(self._build_header_qss())
        except Exception:
            pass
        try:
            self.setFixedHeight(self._px(30))
        except Exception:
            pass
        # paintEvent 内部的 px/pt 每次动态取，不需要刷新缓存；但 repaint 一下保险
        try:
            self.update()
        except Exception:
            pass

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
    install_requested = QtCore.pyqtSignal(str)              # git URL / CNR id（保留，URL 安装旧路径）
    search_install_requested = QtCore.pyqtSignal()          # 打开搜索安装弹窗
    check_updates_requested = QtCore.pyqtSignal()           # 批量 ls-remote
    outdated_reported = QtCore.pyqtSignal(list, dict)        # 控制器回推：(落后 dir_name 列表, {dir_name: 远端日期})

    def __init__(self, app=None, theme_manager=None, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self._outdated_dir_names = set()  # 当前标记为「有更新」的 dir_name（populate 时清空）
        self._loader = None  # 由 PluginController.set_loader 注入；showEvent 据它触发首次加载
        self._setup_ui()

    # DPI 缩放 helper —— 每次调用读 theme_manager.styles 的【当前】实例。
    # set_scale 会新建 ThemeStyles 替换 .styles（见 theme_manager.py）；
    # 若在 __init__ 把 _px/_pt 绑到当时实例的 bound method，DPI 变化后永远停在首建 scale
    # （与 plugin_search_dialog / 三个 launch section 的旧代码同族 bug）。
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
            "btn_primary_bg": c.get("btn_primary_bg", "#6366F1"),
            "btn_primary_hover": c.get("btn_primary_hover", "#818CF8"),
            "scroll_handle": c.get("scroll_handle", "#6366F1"),
            "scroll_handle_hover": c.get("scroll_handle_hover", "#5258CF"),
            "divider": c.get("divider", "#374151"),
        }

    def set_loader(self, loader):
        """PluginController 构造时注入 BackgroundLoader，供 showEvent 触发首次加载。"""
        self._loader = loader

    def showEvent(self, event):
        """首次切到本页 → 触发列表加载（若还没加载过）。已加载过则跳过。

        仿 version_page / log_viewer 的 showEvent 范式。配合 qt_app 的兜底定时器
        （15s 后若用户一直没进过本页则兜底扫一次），实现「切到才扫 + 不进也兜底」。
        """
        super().showEvent(event)
        if self._loader is not None:
            self._loader.load_if_not_loaded()

    def set_loading_state(self, loading: bool):
        """加载中显示占位 item；populate() 开头的 clear() 会自然清掉它。

        on_state_change 回调（BackgroundLoader 注入）。只在列表为空时插入占位，
        避免覆盖已有的列表内容（如刷新已有数据时不应闪占位）。
        """
        try:
            if loading and self.list_widget.count() == 0:
                item = QtWidgets.QListWidgetItem("正在获取插件列表…")
                item.setForeground(QtGui.QBrush(QtGui.QColor(
                    self.theme_manager.colors.get("label_dim", "#9CA3AF"))))
                self.list_widget.addItem(item)
        except Exception:
            pass

    def _setup_ui(self):
        c = self._get_colors()
        s = self.theme_manager.styles if self.theme_manager else None
        _px, _pt = self._px, self._pt
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(_px(25), _px(25), _px(25), _px(25))
        layout.setSpacing(_px(12))

        title = QtWidgets.QLabel("插件管理")
        title.setStyleSheet(f"""
            font: bold {_pt(16)}pt "Microsoft YaHei UI";
            color: {c['label']};
            margin-bottom: {_px(2)}px;
        """)
        self._title_label = title
        layout.addWidget(title)

        # 一级按钮区（单行）：刷新(ghost)  安装插件(ghost)  ←stretch→  检查更新(primary) 更新全部(primary)
        # 三级视觉权重：ghost 弱、primary 强。依赖勾选的操作收纳到下方 ActionBar。
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(_px(8))
        self.refresh_btn = QtWidgets.QPushButton("刷新列表")
        self.install_btn = QtWidgets.QPushButton("安装插件")
        self.search_install_btn = QtWidgets.QPushButton("搜索安装")
        self.check_updates_btn = QtWidgets.QPushButton("检查更新")
        self.update_all_btn = QtWidgets.QPushButton("更新全部")
        try:
            self.refresh_btn.setStyleSheet(s.secondary_button_style())
            self.install_btn.setStyleSheet(s.secondary_button_style())
            self.search_install_btn.setStyleSheet(s.secondary_button_style())
            self.check_updates_btn.setStyleSheet(s.primary_button_style())
            self.update_all_btn.setStyleSheet(s.primary_button_style())
        except Exception:
            pass
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        # install_btn.clicked 不在 page 内连 —— qt_app 直接连它弹输入框（install 需要用户输入 URL）。
        self.search_install_btn.clicked.connect(self.search_install_requested.emit)
        self.check_updates_btn.clicked.connect(self.check_updates_requested.emit)
        self.update_all_btn.clicked.connect(self.update_all_requested.emit)
        # 左：刷新 / 安装插件 / 搜索安装；右：检查更新 / 更新全部
        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(self.install_btn)
        toolbar.addWidget(self.search_install_btn)
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
                background-color: {c['group_bg']};
                border: 1px solid {c['input_border']};
                border-radius: {_px(6)}px;
            }}
        """)
        self._action_bar.setFixedHeight(_px(44))  # 固定高度，杜绝表格抖动
        ab_layout = QtWidgets.QHBoxLayout(self._action_bar)
        ab_layout.setContentsMargins(_px(10), _px(6), _px(10), _px(6))
        ab_layout.setSpacing(_px(8))
        # 未勾选时的提示文字（默认显示）
        self._ab_hint_label = QtWidgets.QLabel("勾选插件以显示批量操作")
        self._ab_hint_label.setStyleSheet(
            f"color: {c['label_dim']}; font: {_pt(9)}pt 'Microsoft YaHei UI';")
        # 勾选时的标签 + 计数
        ab_label = QtWidgets.QLabel("已选中：")
        ab_label.setStyleSheet(f"color: {c['label_muted']}; font: {_pt(9)}pt 'Microsoft YaHei UI';")
        self._ab_label = ab_label
        self._ab_count_label = QtWidgets.QLabel("0")
        self._ab_count_label.setStyleSheet(
            f"color: {c['btn_primary_hover']}; font: bold {_pt(9)}pt 'Microsoft YaHei UI';")
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
        ab_layout.addSpacing(_px(12))
        for b in (self.update_selected_btn, self.enable_btn, self.disable_btn, self.uninstall_btn):
            ab_layout.addWidget(b)
            b.hide()
        ab_layout.addStretch()
        # 记录勾选态组件，便于 _refresh_action_bar 切换显隐
        self._ab_active_widgets = [ab_label, self._ab_count_label,
                                   self.update_selected_btn, self.enable_btn,
                                   self.disable_btn, self.uninstall_btn]
        self._ab_layout = ab_layout
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
        self.list_widget.setStyleSheet(self._build_list_qss(c))
        list_container.addWidget(self.list_widget)
        # 勾选状态变化 → 刷新 ActionBar 显隐 + 选中计数
        self.list_widget.itemChanged.connect(lambda _item: self._refresh_action_bar())
        layout.addLayout(list_container)
        self._root_layout = layout

        # DPI 尺寸清单：DPI / 主题变化时由 _reapply_dpi_sizes 重算
        self._dpi_sized_widgets = [
            (self.refresh_btn, "min_text", "刷新列表"),
            (self.install_btn, "min_text", "安装插件"),
            (self.search_install_btn, "min_text", "搜索安装"),
            (self.check_updates_btn, "min_text", "检查更新"),
            (self.update_all_btn, "min_text", "更新全部"),
            (self.update_selected_btn, "min_text", "更新选中"),
            (self.enable_btn, "min_text", "启用选中"),
            (self.disable_btn, "min_text", "禁用选中"),
            (self.uninstall_btn, "min_text", "卸载选中"),
        ]
        self._reapply_dpi_sizes()

    # ---- 主题 QSS 构造（与 P0-2 update_theme 共享）----
    def _build_title_qss(self, c):
        return (f"font: bold {self._pt(16)}pt 'Microsoft YaHei UI';"
                f" color: {c['label']}; margin-bottom: {self._px(2)}px;")

    def _build_actionbar_qss(self, c):
        return (f"QWidget#PluginActionBar {{"
                f" background-color: {c['group_bg']};"
                f" border: 1px solid {c['input_border']};"
                f" border-radius: {self._px(6)}px;"
                f"}}")

    def _build_list_qss(self, c):
        _px, _pt = self._px, self._pt
        return f"""
            QListWidget {{
                background-color: {c['input_bg']};
                color: {c['text']};
                border: 1px solid {c['input_border']};
                border-top: none;
                border-bottom-left-radius: {_px(6)}px;
                border-bottom-right-radius: {_px(6)}px;
                padding: {_px(4)}px;
                font: {_pt(10)}pt "Microsoft YaHei UI";
                outline: none;
            }}
            QScrollBar:vertical {{
                background: transparent; width: {_px(8)}px; margin: {_px(2)}px;
                border: none; border-radius: {_px(4)}px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {c['scroll_handle']};
                border-radius: {_px(4)}px; min-height: {_px(30)}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {c['scroll_handle_hover']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """

    def _reapply_dpi_sizes(self):
        """DPI / UI scale 变化时重算尺寸。"""
        _px = self._px
        # 根 layout 边距 & 间距
        try:
            self._root_layout.setContentsMargins(
                _px(25), _px(25), _px(25), _px(25))
        except Exception:
            pass
        try:
            self._root_layout.setSpacing(_px(12))
        except Exception:
            pass
        # ActionBar: 固定高度 + 内部 layout margins/spacing/addSpacing(12)
        try:
            self._action_bar.setFixedHeight(_px(44))
        except Exception:
            pass
        try:
            self._ab_layout.setContentsMargins(
                _px(10), _px(6), _px(10), _px(6))
        except Exception:
            pass
        try:
            self._ab_layout.setSpacing(_px(8))
        except Exception:
            pass
        # ActionBar 中间的 addSpacing(12) 不好改（已经插入 index）；忽略（间距相对次要）
        # 每个按钮 minWidth：测当前文本和 "最长状态文本" 两者 sizeHint，取大的
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

    # ---- 主题 & DPI 变化：重取颜色 token + 重建 QSS + 重算尺寸 ----
    # 注意：BasePage.__init__ 已经 register_listener(self._on_theme_changed)，
    # 这里**不要**再次注册！否则会双监听、双次调用。
    def _on_theme_changed(self, theme_styles):
        self.update_theme(theme_styles)

    def update_theme(self, theme_styles=None):
        """BasePage 的 update_theme 只重应用基础 content_style；这里补子控件的内联 QSS。"""
        # 1. BasePage 重应用 content_style
        try:
            super().update_theme(theme_styles)
        except Exception:
            pass
        # 2. 重取颜色 token + 重建 QSS
        try:
            c = self._get_colors()
            # 标题
            try:
                self._title_label.setStyleSheet(self._build_title_qss(c))
            except Exception:
                pass
            # ActionBar 容器
            try:
                self._action_bar.setStyleSheet(self._build_actionbar_qss(c))
            except Exception:
                pass
            # ActionBar 内三个标签（颜色 + pt 字号）
            try:
                self._ab_hint_label.setStyleSheet(
                    f"color: {c['label_dim']}; font: {self._pt(9)}pt 'Microsoft YaHei UI';")
            except Exception:
                pass
            try:
                self._ab_label.setStyleSheet(
                    f"color: {c['label_muted']}; font: {self._pt(9)}pt 'Microsoft YaHei UI';")
            except Exception:
                pass
            try:
                self._ab_count_label.setStyleSheet(
                    f"color: {c['btn_primary_hover']}; font: bold {self._pt(9)}pt 'Microsoft YaHei UI';")
            except Exception:
                pass
            # List + scrollbar
            try:
                self.list_widget.setStyleSheet(self._build_list_qss(c))
            except Exception:
                pass
            # 3. DPI 尺寸重算（margin/spacing/高度/按钮 minWidth）
            self._reapply_dpi_sizes()
            # 4. 通知子 delegate / 子控件各自 update_theme
            #   - delegate：QAbstractItemDelegate（PluginItemDelegate）
            #   - 表头：_PluginListHeader（裸 QWidget，额外保险再调一次）
            try:
                dlg = self.list_widget.itemDelegate()
                upd = getattr(dlg, "update_theme", None)
                if callable(upd):
                    upd(theme_styles)
            except Exception:
                pass
            try:
                self.list_header.update_theme(theme_styles)
            except Exception:
                pass
        except Exception:
            pass

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

        P2-4 meta-review：强制用 [takeItem(0) for _ in range(n)] 从头摘干净，
        再按新序逐个 addItem。**绝对不用 list_widget.clear()**（clear 会释放
        item 对象，与 QListWidgetItem 外部引用或测试 fixture 冲突时直接崩溃）。
        摘出过程 row 单调不变，避免边走边删导致 row 错位。
        """
        lw = self.list_widget
        n = lw.count()
        if not self._outdated_dir_names or n < 2:
            return
        # 先确定每个 item 的新位置（在原始引用还能定位时先拿）
        outdated_items = []
        other_items = []
        for i in range(n):
            item = lw.item(i)
            dn = item.data(QtCore.Qt.UserRole + 1)
            (outdated_items if dn in self._outdated_dir_names else other_items).append(item)
        if not outdated_items or len(outdated_items) == n:
            return
        # 从头连续摘出：takeItem(0) 执行 n 次，稳定清空列表但不释放 items
        _ = [lw.takeItem(0) for _ in range(n)]
        # 按新顺序逐个插回（先 outdated 再 other，各自保留原相对顺序）
        for item in outdated_items:
            lw.addItem(item)
        for item in other_items:
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
        # 列表加载走通用 BackgroundLoader：后台跑 list_installed → post 回 UI 填充，
        # 内置防重入 + loaded_once + 加载态回调（页面据此显隐「获取中」占位）。
        from ui_qt.background_loader import BackgroundLoader
        self._loader = BackgroundLoader(
            load_fn=lambda _report: self.svc.list_installed(),
            on_loaded=lambda plugins: self.page.populate(plugins),
            run_in_background=run_in_background,
            post_to_ui=post_to_ui,
            on_state_change=self.page.set_loading_state,
        )
        # 把 loader 暴露给页面：showEvent 用 load_if_not_loaded 做首次进入触发
        page.set_loader(self._loader)
        page.refresh_requested.connect(self._on_refresh)
        page.update_all_requested.connect(self._on_update_all)
        page.update_selected_requested.connect(self._on_update_selected)
        page.disable_selected_requested.connect(self._on_disable_selected)
        page.enable_selected_requested.connect(self._on_enable_selected)
        page.check_updates_requested.connect(self._on_check_updates)

    def _on_refresh(self):
        self._loader.load()

    def _on_update_all(self):
        self._run_in_background(self._update_all_work)

    def run_update_all(self, on_status=None, on_done=None):
        """qt_app 触发：带进度回调的「更新全部」。on_status(str)/on_done(success, message) 派回 UI 线程。"""
        def work():
            failed = []
            try:
                if on_status:
                    self._post_to_ui(lambda: on_status("正在更新全部插件（cm-cli update all，含 pip 依赖修复）..."))
                self.svc.update_all()
                # P1-4 meta-review：update_selected 会再跑 outdated_plugins 检测 cm-cli 没更新的
                # 插件（脏树/冲突）并发 force_update_suggested；update_all 缺这一步，漏网
                # 插件永远不被提出来。现在对齐 selected 的行为。
                names = [p["dir_name"] for p in self.svc.list_installed()]
                # B4 CR：P1-3 TTL 缓存并不覆盖这里的 list_installed —— update_all() 内部
                # 已经整表 evict 过缓存（必须的，HEAD 动了），所以 list_installed() 是全量
                # cache miss，照常跑 ~150 个 git 进程；最终 populate() 吃到这次的热缓存，
                # 实际净增量 +~100 git 子进程，可接受但不是 0。注释别误导后来者。
                failed = self.svc.outdated_plugins(names)
                if failed:
                    self._post_to_ui(lambda f=list(failed): self.page.force_update_suggested.emit(f))
                msg = "插件更新全部完成" + (f"（{len(failed)} 个建议强制更新）" if failed else "")
                ok = True
            except Exception as e:
                ok = False
                msg = f"更新全部失败：{e}"
            finally:
                self._populate_from_service()
                if on_done:
                    # 兼容旧 on_done() 零参数 / 新 on_done(ok, message) 两参数签名。
                    # meta-review 前的测试用 lambda: done_called.append(True)（零参），
                    # 改漏 2 后加了两参数，直接调用会 TypeError。先试两参失败再兜底。
                    def _safe_on_done(o=bool(ok), m=msg):
                        try:
                            on_done(o, m)
                        except TypeError:
                            try:
                                on_done()
                            except Exception:
                                pass
                        except Exception:
                            pass
                    self._post_to_ui(_safe_on_done)
        self._run_in_background(work)

    def _update_all_work(self):
        self.svc.update_all()
        # P1-4 meta-review：页面内「更新全部」按钮也做二次检测（与 run_update_all 同模式），
        # 脏树/冲突的插件被提出来，用户能直接看到「有 N 个需要强制更新」提示。
        plugins_list = None
        try:
            plugins_list = self.svc.list_installed()
            names = [p["dir_name"] for p in plugins_list]
            failed = self.svc.outdated_plugins(names)
            if failed:
                self._post_to_ui(lambda f=list(failed): self.page.force_update_suggested.emit(f))
        except Exception:
            pass
        # 刷新列表：二次检测已经拿到过最新 plugins_list，直接用它 populate，
        # 避免 loader.load() 再调一次 svc.list_installed（P1-4 新二次检测导致双重调用）。
        if plugins_list is not None:
            snapshot = list(plugins_list)
            self._post_to_ui(lambda: self.page.populate(snapshot))
        else:
            self._populate_from_service()

    def run_update_selected(self, names, on_status=None, on_done=None):
        """qt_app 触发: 带进度回调的「更新选中」。

        on_status(str): 任务起始时回调一次, 派回 UI 线程.
        on_done(success, message): 任务收尾 (包括异常路径) 都会调, 派回 UI 线程.
          - success: 本次 svc 调用未抛异常（不代表每个插件都成功，已逐个调用 cm-cli）
          - message: 一行人类文案（含建议强制更新数 / 失败异常）
        """
        def work():
            failed = []
            msg = f"选中插件更新完成 ({len(names)} 个)"
            ok = True
            try:
                if on_status:
                    label = f"正在更新选中插件 ({len(names)} 个)"
                    self._post_to_ui(lambda: on_status(label))
                self.svc.update_selected(names)
                failed = self.svc.outdated_plugins(names)
                if failed:
                    self._post_to_ui(lambda f=list(failed): self.page.force_update_suggested.emit(f))
                    msg = msg + f"（{len(failed)} 个建议强制更新）"
            except Exception as e:
                # 漏 2 meta-review：原 except:pass 把所有异常吞掉，finally 里 on_done()
                # 永远按成功流程走。现在存 error，on_done 带 (False, 异常文案)，
                # 让 qt_app 弹 show_error（非取消）或 registry 标错。
                ok = False
                msg = f"更新选中失败：{e}"
            finally:
                self._populate_from_service()
                if on_done:
                    def _safe_on_done(o=bool(ok), m=msg):
                        try:
                            on_done(o, m)
                        except TypeError:
                            try:
                                on_done()
                            except Exception:
                                pass
                        except Exception:
                            pass
                    self._post_to_ui(_safe_on_done)
        self._run_in_background(work)


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
        # P2-6 meta-review：默认信号连接入口。生产环境 qt_app 会 disconnect 此默认
        # 连接改连自己的 _do_plugin_disable_selected（带进度 + 后台注册）；
        # 测试 / 无 qt_app 环境则保留默认薄包装：调 run_disable(on_done=None)。
        # 不再直接裸调 _lifecycle_work，统一走新 run_* 路径，保证错误处理一致。
        self.run_disable(list(dir_names))

    def _on_enable_selected(self, dir_names):
        # P2-6 meta-review：同 _on_disable_selected，薄包装 run_enable(on_done=None)
        self.run_enable(list(dir_names))

    def _lifecycle_work(self, op, dir_names):
        for dn in dir_names:
            getattr(self.svc, op)(dn)
        self._populate_from_service()

    # ---- uninstall（破坏性，需 qt_app 二次确认后调 apply_uninstall）----
    def apply_uninstall(self, dir_names):
        """P2-6 meta-review：保留兼容性。生产代码 qt_app 二次确认后应调
        ctrl.run_uninstall（带进度 + 后台注册 + 成功/失败反馈）；旧代码/测试仍
        可用此入口（旧静默实现：_run_in_background → _uninstall_work）。
        保持与老版本完全一致的 svc.uninstall 调用契约，不破坏测试。
        """
        self._run_in_background(lambda: self._uninstall_work(dir_names))

    def _uninstall_work(self, dir_names):
        for dn in dir_names:
            self.svc.uninstall(dn)
        self._populate_from_service()

    # ---- install（qt_app 输入框拿到 spec 后调 request_install）----
    def request_install(self, spec):
        """P2-6 meta-review：保留兼容性。生产代码 qt_app 弹框拿 URL/CNR id
        后应调 ctrl.run_install（带 cm-cli 阶段进度流 + cancel 可树杀）；旧代码/
        测试仍可用此入口（旧静默实现：_run_in_background → _install_work）。
        保持 svc.install（单命令无 streaming）的调用契约，不破坏测试。
        """
        self._run_in_background(lambda: self._install_work(spec))

    def _install_work(self, spec):
        self.svc.install(spec)
        self._populate_from_service()

    # ---- 带反馈版本（qt_app 编排用）：接收 service 返回值，回调 (ok, message) ----
    # 旧 request_install/apply_uninstall/_on_disable_selected/_on_enable_selected 丢弃了
    # service 的 {ok, log, error} 返回值且无 UI 反馈；这些 run_* 把结果组装成
    # (ok, message) 派回 UI 线程，让 qt_app 弹成功/失败提示（仿 run_update_selected）。
    def run_install(self, spec, on_status=None, on_progress=None, on_done=None,
                    cancel_event=None):
        """qt_app 触发：带进度回调的安装。

        on_status(str): 起始状态，派回 UI 线程。
        on_progress(str): cm-cli 输出映射出的阶段文案（克隆/收集依赖/下载/安装/完成），派回 UI 线程。
        on_done(ok, message): 完成回调，派回 UI 线程。
        cancel_event(threading.Event): 透传给 install_streaming，用户取消时 kill cm-cli。
        """
        def work():
            res = {"ok": False, "error": "未执行", "log": ""}
            try:
                if on_status:
                    self._post_to_ui(lambda: on_status(f"正在安装 {spec}（cm-cli install，可能需要几分钟）..."))

                def _on_stage(stage):
                    if on_progress:
                        self._post_to_ui(lambda s=stage: on_progress(s))

                res = self.svc.install_streaming(spec, on_stage=_on_stage,
                                                 cancel_event=cancel_event)
            except Exception as e:
                res = {"ok": False, "error": str(e), "log": ""}
            finally:
                try:
                    self._populate_from_service()
                except Exception:
                    pass
                if on_done:
                    ok = bool(res.get("ok"))
                    err = res.get("error")
                    if ok:
                        msg = f"插件安装完成：{spec}"
                    else:
                        msg = f"插件安装失败：{spec}" + (f"\n{err}" if err else "")
                    def _safe_on_done(o=ok, m=msg):
                        try:
                            on_done(o, m)
                        except TypeError:
                            try:
                                on_done()
                            except Exception:
                                pass
                        except Exception:
                            pass
                    self._post_to_ui(_safe_on_done)
        self._run_in_background(work)

    def run_uninstall(self, dir_names, on_status=None, on_done=None):
        """qt_app 触发：带进度回调的卸载（批量逐项）。on_status(str)/on_done(ok, message) 派回 UI 线程。"""
        self._run_batch_with_feedback("uninstall", "卸载", dir_names, on_status, on_done)

    def run_disable(self, dir_names, on_status=None, on_done=None):
        """qt_app 触发：带进度回调的禁用（批量逐项）。on_status(str)/on_done(ok, message) 派回 UI 线程。"""
        self._run_batch_with_feedback("disable", "禁用", dir_names, on_status, on_done)

    def run_enable(self, dir_names, on_status=None, on_done=None):
        """qt_app 触发：带进度回调的启用（批量逐项）。on_status(str)/on_done(ok, message) 派回 UI 线程。"""
        self._run_batch_with_feedback("enable", "启用", dir_names, on_status, on_done)

    def _run_batch_with_feedback(self, op, op_label, dir_names, on_status, on_done):
        """uninstall/disable/enable 共用：逐项执行 service.<op> + 逐项进度 + 结果汇总。"""
        def work():
            results = []
            try:
                for i, dn in enumerate(dir_names, 1):
                    if on_status:
                        self._post_to_ui(lambda i=i, dn=dn: on_status(
                            f"正在{op_label} ({i}/{len(dir_names)}) {dn}..."))
                    try:
                        r = getattr(self.svc, op)(dn)
                    except Exception as e:
                        r = {"ok": False, "error": str(e)}
                    results.append((dn, r))
            finally:
                try:
                    self._populate_from_service()
                except Exception:
                    pass
                if on_done:
                    # r 可能是 None（mock 默认返回值或旧 svc 实现无返回），(r or {}) 防 None
                    failed = [(dn, r) for dn, r in results if not (r or {}).get("ok")]
                    ok = len(failed) == 0 and len(results) == len(dir_names)
                    if ok:
                        msg = f"已{op_label} {len(dir_names)} 个插件"
                    else:
                        detail = "; ".join(
                            f"{dn}: {(r or {}).get('error', '无返回结果')}" for dn, r in failed
                        )
                        msg = f"{op_label}完成，{len(failed)}/{len(dir_names)} 失败：{detail}"
                    def _safe_on_done(o=bool(ok), m=msg):
                        try:
                            on_done(o, m)
                        except TypeError:
                            try:
                                on_done()
                            except Exception:
                                pass
                        except Exception:
                            pass
                    self._post_to_ui(_safe_on_done)
        self._run_in_background(work)

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
        results = self.svc.force_update_selected(names)
        # 复用普通更新的「同步依赖库」流程（与内核更新同一套，按 checkbox 网关）
        if self._sync_deps:
            try:
                self._sync_deps()
            except Exception:
                pass
        self._populate_from_service()
        return results

    # ---- 漏 1 meta-review：强制更新带反馈版（仿 run_update_selected 契约）----
    def run_force_update(self, names, on_status=None, on_done=None):
        """qt_app 触发: 带进度回调的「强制更新选中」。

        on_status(str): 起始回调, 派回 UI 线程.
        on_done(ok, summary, per_plugin): 收尾 (含异常路径) 都会调, 派回 UI 线程.
          - ok: bool, 全部成功 (即所有结果 ok=True 或 skipped=True)
          - summary: 一行人类文案
          - per_plugin: [{name, ok, skipped, detail}]，逐插件明细（来自 service.force_update_selected）
        """
        def work():
            results: list[dict[str, Any]] = []
            err_msg = None
            try:
                if on_status:
                    label = f"正在强制更新插件 ({len(names)} 个，git stash + pull --ff-only)..."
                    self._post_to_ui(lambda: on_status(label))
                results = list(self.svc.force_update_selected(names) or [])
                # 复用普通更新的「同步依赖库」
                if self._sync_deps:
                    try:
                        self._sync_deps()
                    except Exception as e:
                        err_msg = f"同步依赖失败：{e}"
                ok_all = all(r.get("ok", False) or r.get("skipped", False) for r in results)
                ok_count = sum(1 for r in results if r.get("ok", False) and not r.get("skipped", False))
                skip_count = sum(1 for r in results if r.get("skipped", False))
                fail_count = sum(1 for r in results if not r.get("ok", False) and not r.get("skipped", False))
                summary = f"强制更新完成：成功 {ok_count} 个，跳过 {skip_count} 个，失败 {fail_count} 个"
                if err_msg:
                    summary = summary + f"；{err_msg}"
                # B5 CR：GUI 用户必须能看到 per_plugin 的 [警告] 和失败 detail。
                # 原先 qt_app._adapted_done 会把 per_plugin 整个丢掉，强制更新 stash 冲突时
                # 用户看不到任何冲突提示（以为成功了）。这里把 failed + 有警告的 detail
                # 追加到 summary 文本里，保证 show_error / mark_complete 里能一眼看到。
                notable: list[str] = []
                for r in results:
                    name = r.get("name") or "?"
                    detail = r.get("detail") or ""
                    if not detail:
                        continue
                    if not r.get("ok", False) and not r.get("skipped", False):
                        notable.append(f"{name}（失败）: {detail.strip()}")
                    elif "[警告]" in detail:
                        notable.append(f"{name}（有告警）: {detail.strip()}")
                if notable:
                    joined = "\n".join("· " + s for s in notable)
                    summary = f"{summary}\n\n{joined}"
                if on_done:
                    self._post_to_ui(lambda o=bool(ok_all), s=summary, p=list(results): on_done(o, s, p))
            except Exception as e:
                ok_all = False
                summary = f"强制更新异常：{e}"
                if on_done:
                    self._post_to_ui(lambda o=False, s=summary, p=list(results): on_done(o, s, p))
            finally:
                self._populate_from_service()
        self._run_in_background(work)

    def _populate_from_service(self):
        """取最新已装列表并派回 UI 线程填充页面（刷新 / 更新后都用）。

        走 loader.load()：复用通用加载路径，自带防重入（用户连点不会并发起多次扫描）。
        注意：load() 的防重入对「操作刚完成想立即刷新」也生效——正常情况下操作串行执行，
        调用时前一次加载已完成（is_loading=False），load() 会照常执行。
        """
        self._loader.load()
