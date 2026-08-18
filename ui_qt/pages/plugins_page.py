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
    2026-08-18 升级：各列宽度整体放大一码，避免长 hash / 日期 / 徽章挤在一起。
    """
    right_margin = px(16)
    status_w = px(64)    # 状态列：启用/禁用 胶囊（54 宽 + 10 边距余留）
    type_w = px(56)      # 类型列：Git/CNR/本地
    local_w = px(110)    # 版本（pyproject 版本号 / git hash 短）
    remote_w = px(110)   # 远端日期（YYYY-MM-DD 10 字 + 余留）
    update_w = px(82)    # 可更新徽章列（"有更新"3 字 + 药丸 padding）
    cb_x, cb_w = px(12), px(16)
    icon_x, icon_w = px(42), px(24)
    name_x = icon_x + icon_w + px(4)
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

        # ---- 1. 行背景（轻微卡片质感：每两行一组，极淡交替底色，避免整屏密集时失焦）----
        dark_mode = bool(c.get("dark", True))
        if selected:
            painter.fillRect(rect, QtGui.QColor(127, 86, 217, 55))  # ≈0.215 alpha 柔和紫底
        elif hover:
            painter.fillRect(rect, QtGui.QColor(c.get("group_bg", "rgba(0,0,0,0.25)")))
        elif index.row() % 2 == 1:
            # 奇数行（第 2/4/6...行）给极浅一点底（<5% alpha），做斑马纹分区，但保持极简
            if dark_mode:
                painter.fillRect(rect, QtGui.QColor(255, 255, 255, 8))
            else:
                painter.fillRect(rect, QtGui.QColor(0, 0, 0, 8))

        if selected:  # 左侧 3px 紫色指示条
            bar = c.get("btn_primary_bg", "#7F56D9")
            painter.fillRect(QtCore.QRect(rect.left() + self._px(1), rect.top() + self._px(6),
                                          self._px(3), rect.height() - self._px(12)),
                             QtGui.QColor(bar))
        # 不选中小行才画底部分割线，选中行用左边紫条 + 整块紫底，视觉权重更高，不需要分割线打断
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

        # ---- 4. 🧩 图标（紧跟复选框）。不使用 emoji 渲染（不同平台 emoji 字重不一、抗锯齿差），
        # 改成 QPainter 画的纯色「方块+小十字」图标，在深/浅主题上都统一。
        icon_x = rect.left() + g["icon_x"]
        icon_cy = rect.center().y()
        icon_w = g["icon_w"]
        icon_h = self._px(24)
        icon_cx = icon_x + icon_w // 2
        # 方块底（圆角 4px）
        muted_color = QtGui.QColor(c.get("label_muted", "#9CA3AF"))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(muted_color)
        r = QtCore.QRect(icon_x + icon_w // 2 - self._px(9),
                         int(icon_cy - self._px(9)),
                         self._px(18), self._px(18))
        painter.drawRoundedRect(r, self._px(4), self._px(4))
        # 十字凹口（让方块看起来像「插件/拼图块」）—— 挖掉上/下/左/右四个小方块的中心小块？
        # 简化方案：方块上叠加一个透明圆形凹口 = 画一个 6px 的小圆，用背景色盖住（因为背景色透明无法 cover，
        # 改用在方块四角画 4 个小圆点，像拼图凸块，视觉含义等同"插件"）
        painter.setBrush(QtGui.QColor(c.get("input_bg", "#111827")))
        dot_r = self._px(2)
        # 四个凸点：上下左右中心
        painter.drawEllipse(QtCore.QPoint(icon_cx, r.top() - 1), dot_r, dot_r)
        painter.drawEllipse(QtCore.QPoint(icon_cx, r.bottom() + 1), dot_r, dot_r)
        painter.drawEllipse(QtCore.QPoint(r.left() - 1, icon_cy), dot_r, dot_r)
        painter.drawEllipse(QtCore.QPoint(r.right() + 1, icon_cy), dot_r, dot_r)

        # ---- 5. 名称（粗体；禁用态灰。「可更新」标记移到独立列，名称区不加前缀）----
        name_x = rect.left() + g["name_x"]
        name_right = rect.left() + g["name_right"]
        name_font = _font("name", self._pt(10.5), True)
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
            # 未检查（点检查更新前）：用淡药丸状半透明背景 + "未检查"提示，
            # 代替原来的 "—" 单字，让用户知道这列是"还没查"不是"没有更新"。
            painter.setBrush(QtGui.QColor(107, 114, 128, 32))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(pill, pill_h // 2, pill_h // 2)
            painter.setPen(QtGui.QColor(dim))
            painter.drawText(pill, QtCore.Qt.AlignCenter, "未检查")

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
        # 48 → 52：行高加大一码，每行多 4px，name 粗体 + emoji 上下有呼吸
        return QtCore.QSize(0, self.theme_manager.styles._px(52))

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
                f" background-color: {c.get('group_bg', 'rgba(0,0,0,0.25)')};"
                f" border: none;"
                f" border-bottom: 1px solid {c.get('input_border', '#4B5563')};"
                f" border-top-left-radius: {px(11)}px;"
                f" border-top-right-radius: {px(11)}px;"
                f"}}")

    def update_theme(self, _theme_styles=None):
        """主题 / DPI 变化：重建 QSS + 重算固定高度。"""
        try:
            self.setStyleSheet(self._build_header_qss())
        except Exception:
            pass
        try:
            # 30 → 36：表头加高一码，顶部呼吸感更好
            self.setFixedHeight(self._px(36))
        except Exception:
            pass
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


class _StatCard(QtWidgets.QFrame):
    """状态统计卡片：左侧小圆点 + 右侧大号数字 + 下方语义标签。

    4 张一组：总数 / 可更新 / 已启用 / 已禁用。风格参考 Apple Settings/Arc Sidebar：
    - 卡片底：比页面背景浅一档半透明磨砂（group_bg）
    - 圆角 12px，1px border（弱描边）
    - 数字使用 accent/dot 颜色（每张卡的主题色），粗体大号
    - 下方 9pt muted 标签，数字和标签纵向间距极小，视觉紧凑但不挤
    """

    def __init__(self, theme_manager, label: str, dot_color: str, accent_color: str,
                 parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self._label_text = label
        self._dot_color = dot_color
        self._accent_color = accent_color
        self.setObjectName("PluginStatCard")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        self._px = lambda v: (theme_manager.styles._px(v)
                              if theme_manager and getattr(theme_manager, "styles", None)
                              else v)
        self._pt = lambda v: (theme_manager.styles._pt(v)
                              if theme_manager and getattr(theme_manager, "styles", None)
                              else v)

        vl = QtWidgets.QVBoxLayout(self)
        vl.setContentsMargins(self._px(16), self._px(12), self._px(16), self._px(12))
        vl.setSpacing(self._px(2))

        # 顶部一行：语义圆点 + 标签（左侧一排小语义，不要占太多视线）
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(self._px(8))
        self._dot = QtWidgets.QFrame()
        self._dot.setObjectName("PluginStatDot")
        self._dot.setFixedSize(self._px(8), self._px(8))
        self._dot.setStyleSheet(
            f"QFrame#PluginStatDot {{ background-color: {dot_color};"
            f" border-radius: {self._px(4)}px; }}")
        self._lbl_label = QtWidgets.QLabel(label)
        top.addWidget(self._dot)
        top.addWidget(self._lbl_label)
        top.addStretch()
        vl.addLayout(top)

        # 大号数字
        self._lbl_value = QtWidgets.QLabel("0")
        vl.addWidget(self._lbl_value)

        self.update_theme()
        if theme_manager:
            theme_manager.register_listener(lambda _s: self.update_theme())

    def update_theme(self, _theme_styles=None):
        c = getattr(self.theme_manager, "colors", {}) if self.theme_manager else {}
        px, pt = self._px, self._pt
        self._lbl_label.setStyleSheet(
            f"color: {c.get('label_muted', '#9CA3AF')};"
            f" font: {pt(9)}pt 'Microsoft YaHei UI';")
        self._lbl_value.setStyleSheet(
            f"color: {self._accent_color};"
            f" font: bold {pt(18)}pt 'Microsoft YaHei UI';"
            f" letter-spacing: 0.2px;")
        self.setStyleSheet(
            f"QFrame#PluginStatCard {{"
            f" background-color: {c.get('group_bg', 'rgba(0,0,0,0.2)')};"
            f" border: 1px solid {c.get('input_border', '#4B5563')};"
            f" border-radius: {px(12)}px; }}")

    def set_value(self, value: int):
        self._lbl_value.setText(str(int(value)))


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
        layout.setContentsMargins(_px(28), _px(24), _px(28), _px(24))
        layout.setSpacing(_px(16))

        # ---- 1. 标题 + 右上主操作（标题+一排主按钮，左右对齐，Apple 风格）----
        titlebar = QtWidgets.QHBoxLayout()
        titlebar.setSpacing(0)
        # 左：标题 + 副标题
        title_v = QtWidgets.QVBoxLayout()
        title_v.setSpacing(_px(2))
        title_v.setContentsMargins(0, 0, 0, 0)
        title = QtWidgets.QLabel("插件管理")
        title.setStyleSheet(f"""
            font: bold {_pt(18)}pt "Microsoft YaHei UI";
            color: {c['label']};
            letter-spacing: 0.2px;
        """)
        self._title_label = title
        subtitle = QtWidgets.QLabel("已安装 custom_nodes，支持勾选后批量操作")
        subtitle.setStyleSheet(
            f"color: {c['label_muted']}; font: {_pt(9)}pt 'Microsoft YaHei UI';"
        )
        self._subtitle_label = subtitle
        title_v.addWidget(title)
        title_v.addWidget(subtitle)
        titlebar.addLayout(title_v)
        titlebar.addStretch()
        # 右：主操作按钮（按权重排：刷新 · 搜索安装 · URL安装插件 ·  检查更新 · 更新全部）
        # 前三 = 浅灰 secondary（信息密度低），后二 = accent primary（高权重动作）
        top_ops = QtWidgets.QHBoxLayout()
        top_ops.setSpacing(_px(8))
        self.refresh_btn = QtWidgets.QPushButton("刷新列表")
        self.search_install_btn = QtWidgets.QPushButton("搜索安装")
        self.install_btn = QtWidgets.QPushButton("URL安装插件")
        self.check_updates_btn = QtWidgets.QPushButton("检查更新")
        self.update_all_btn = QtWidgets.QPushButton("更新全部")
        try:
            self.refresh_btn.setStyleSheet(s.secondary_button_style())
            self.search_install_btn.setStyleSheet(s.secondary_button_style())
            self.install_btn.setStyleSheet(s.secondary_button_style())
            self.check_updates_btn.setStyleSheet(s.primary_button_style())
            self.update_all_btn.setStyleSheet(s.primary_button_style())
        except Exception:
            pass
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        self.search_install_btn.clicked.connect(self.search_install_requested.emit)
        self.check_updates_btn.clicked.connect(self.check_updates_requested.emit)
        self.update_all_btn.clicked.connect(self.update_all_requested.emit)
        for b in (self.refresh_btn, self.search_install_btn, self.install_btn,
                  self.check_updates_btn, self.update_all_btn):
            top_ops.addWidget(b)
        titlebar.addLayout(top_ops)
        layout.addLayout(titlebar)

        # ---- 2. 状态统计卡片（4 张：总数 / 可更新 / 已启用 / 已禁用）----
        # 每张卡片 = 一行大字数字 + 下方小字语义 + 左侧语义小圆点
        self._stat_total = _StatCard(
            theme_manager=self.theme_manager, label="插件总数",
            dot_color="#7F56D9", accent_color=c["label"])
        self._stat_outdated = _StatCard(
            theme_manager=self.theme_manager, label="可更新",
            dot_color="#9E77ED", accent_color="#9E77ED")
        self._stat_enabled = _StatCard(
            theme_manager=self.theme_manager, label="已启用",
            dot_color="#22C55E", accent_color="#22C55E")
        self._stat_disabled = _StatCard(
            theme_manager=self.theme_manager, label="已禁用",
            dot_color="#9CA3AF", accent_color="#9CA3AF")
        stat_row = QtWidgets.QHBoxLayout()
        stat_row.setSpacing(_px(12))
        for card in (self._stat_total, self._stat_outdated,
                     self._stat_enabled, self._stat_disabled):
            stat_row.addWidget(card, 1)
        layout.addLayout(stat_row)

        # ---- 3. Tab 筛选栏（全部 / Git / CNR / 本地 / 可更新 / 已禁用） + 搜索框 ----
        filter_row = QtWidgets.QHBoxLayout()
        filter_row.setSpacing(_px(12))
        # Tab：QPushButton 自绘（radio-style pill tab），选中 = accent 填充，未选中 = 透明 ghost
        self._filter_tabs = {}  # key -> btn
        tabs = [
            ("all", "全部"),
            ("git", "Git"),
            ("cnr", "CNR"),
            ("local", "本地"),
            ("outdated", "可更新"),
            ("disabled", "已禁用"),
        ]
        self._tab_container = QtWidgets.QWidget()
        self._tab_container.setObjectName("PluginFilterTabs")
        self._tab_container.setFixedHeight(_px(34))
        tab_l = QtWidgets.QHBoxLayout(self._tab_container)
        tab_l.setContentsMargins(_px(4), 0, _px(4), 0)
        tab_l.setSpacing(_px(4))
        self._tab_layout = tab_l
        self._current_filter = "all"
        for k, label in tabs:
            btn = QtWidgets.QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            if k == "all":
                btn.setChecked(True)
            btn.clicked.connect(lambda _c, _k=k: self._set_filter(_k))
            self._filter_tabs[k] = btn
            tab_l.addWidget(btn)
        tab_l.addStretch()
        filter_row.addWidget(self._tab_container, 3)

        # 搜索框（本地 name/description/author/version 过滤）
        self._search_edit = QtWidgets.QLineEdit()
        self._search_edit.setPlaceholderText("搜索插件名 / 作者 / 版本…")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(lambda _t: QtCore.QTimer.singleShot(
            200, self._apply_filters))
        filter_row.addWidget(self._search_edit, 2)

        layout.addLayout(filter_row)

        # ---- 4. ActionBar：勾选任意项时浮现操作条；高度固定不抖动 ----
        self._action_bar = QtWidgets.QWidget()
        self._action_bar.setObjectName("PluginActionBar")
        self._action_bar.setStyleSheet(f"""
            QWidget#PluginActionBar {{
                background-color: {c['group_bg']};
                border: 1px solid {c['input_border']};
                border-radius: {_px(10)}px;
            }}
        """)
        self._action_bar.setFixedHeight(_px(46))
        ab_layout = QtWidgets.QHBoxLayout(self._action_bar)
        ab_layout.setContentsMargins(_px(14), _px(6), _px(14), _px(6))
        ab_layout.setSpacing(_px(8))
        # 未勾选：提示文字胶囊 + 占位
        self._ab_hint_label = QtWidgets.QLabel("勾选插件以显示批量操作")
        self._ab_hint_label.setStyleSheet(
            f"color: {c['label_dim']}; font: {_pt(9.5)}pt 'Microsoft YaHei UI';"
        )
        ab_label = QtWidgets.QLabel("已选中")
        ab_label.setStyleSheet(
            f"color: {c['label_muted']}; font: {_pt(9.5)}pt 'Microsoft YaHei UI';"
        )
        self._ab_label = ab_label
        # 计数 badge（accent pill）
        self._ab_count_label = QtWidgets.QLabel("0")
        self._ab_count_label.setObjectName("PluginCountBadge")
        self._ab_count_label.setFixedWidth(_px(34))
        self._ab_count_label.setAlignment(QtCore.Qt.AlignCenter)
        self._ab_count_label.setStyleSheet(
            f"QFrame, QWidget, QLabel#PluginCountBadge {{ "
            f" background-color: {c['btn_primary_bg']}; color: #FFFFFF;"
            f" border-radius: {_px(8)}px;"
            f" font: bold {_pt(9)}pt 'Microsoft YaHei UI'; }}")
        # 按钮
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
        self.enable_btn.clicked.connect(
            lambda: self.enable_selected_requested.emit(self.selected_dir_names()))
        self.disable_btn.clicked.connect(
            lambda: self.disable_selected_requested.emit(self.selected_dir_names()))
        self.uninstall_btn.clicked.connect(
            lambda: self.uninstall_selected_requested.emit(self.selected_dir_names()))

        # --- 默认态：显示「勾选插件…」提示，勾选态组件隐藏 ---
        ab_layout.addWidget(self._ab_hint_label)
        ab_layout.addStretch()
        # 勾选态组件
        ab_layout.addWidget(ab_label)
        ab_label.hide()
        ab_layout.addWidget(self._ab_count_label)
        ab_layout.addSpacing(_px(14))
        for b in (self.update_selected_btn, self.enable_btn,
                  self.disable_btn, self.uninstall_btn):
            ab_layout.addWidget(b)
            b.hide()
        self._ab_active_widgets = [ab_label, self._ab_count_label,
                                   self.update_selected_btn, self.enable_btn,
                                   self.disable_btn, self.uninstall_btn]
        self._ab_layout = ab_layout
        layout.addWidget(self._action_bar)

        # ---- 5. 表头 + 列表包进同一容器（圆角一体卡）----
        list_container = QtWidgets.QWidget()
        list_container.setObjectName("PluginListContainer")
        list_container.setStyleSheet(f"""
            QWidget#PluginListContainer {{
                background-color: {c['input_bg']};
                border: 1px solid {c['input_border']};
                border-radius: {_px(12)}px;
            }}
        """)
        lc_l = QtWidgets.QVBoxLayout(list_container)
        lc_l.setContentsMargins(0, 0, 0, 0)
        lc_l.setSpacing(0)
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setItemDelegate(PluginItemDelegate(self.theme_manager, self.list_widget))
        self.list_header = _PluginListHeader(self.theme_manager, list_widget=self.list_widget,
                                             parent=self)
        lc_l.addWidget(self.list_header)
        self.list_widget.setStyleSheet(self._build_list_qss(c))
        lc_l.addWidget(self.list_widget)

        self.list_widget.itemChanged.connect(lambda _item: self._refresh_action_bar())
        layout.addWidget(list_container, 1)
        self._list_container = list_container
        self._root_layout = layout

        # 记住全量 plugins 原始数据，Tab/搜索过滤时不用从 controller 重新拉
        self._all_plugins_cache = []

        # DPI 尺寸清单
        self._dpi_sized_widgets = [
            (self.refresh_btn, "min_text", "刷新列表"),
            (self.search_install_btn, "min_text", "搜索安装"),
            (self.install_btn, "min_text", "URL安装插件"),
            (self.check_updates_btn, "min_text", "检查更新"),
            (self.update_all_btn, "min_text", "更新全部"),
            (self.update_selected_btn, "min_text", "更新选中"),
            (self.enable_btn, "min_text", "启用选中"),
            (self.disable_btn, "min_text", "禁用选中"),
            (self.uninstall_btn, "min_text", "卸载选中"),
        ]
        self._reapply_dpi_sizes()
        # Tab 首次样式初始化
        self._refresh_tab_styles()
        # 首次统计数字归 0
        self._refresh_stats([])


    # ---- 主题 QSS 构造（与 P0-2 update_theme 共享）----
    def _build_title_qss(self, c):
        return (f"font: bold {self._pt(18)}pt 'Microsoft YaHei UI';"
                f" color: {c['label']};"
                f" letter-spacing: 0.2px;")

    def _build_subtitle_qss(self, c):
        return (f"color: {c['label_muted']};"
                f" font: {self._pt(9)}pt 'Microsoft YaHei UI';")

    def _build_actionbar_qss(self, c):
        return (f"QWidget#PluginActionBar {{"
                f" background-color: {c['group_bg']};"
                f" border: 1px solid {c['input_border']};"
                f" border-radius: {self._px(10)}px;"
                f"}}")

    def _build_tab_qss(self, c):
        px, pt = self._px, self._pt
        checked_bg = c.get("btn_primary_bg", "#7F56D9")
        checked_hover = c.get("btn_primary_hover", "#9E77ED")
        normal_text = c.get("label_muted", "#9CA3AF")
        hover_bg = c.get("group_bg", "rgba(0,0,0,0.2)")
        return f"""
            QWidget#PluginFilterTabs {{
                background-color: {c.get('group_bg', 'rgba(0,0,0,0.08)')};
                border: 1px solid {c.get('input_border', '#4B5563')};
                border-radius: {px(10)}px;
            }}
            QWidget#PluginFilterTabs > QPushButton {{
                background-color: transparent;
                color: {normal_text};
                border: none;
                border-radius: {px(7)}px;
                padding: {px(4)}px {px(12)}px;
                font: {pt(9.5)}pt 'Microsoft YaHei UI';
                height: {px(26)}px;
            }}
            QWidget#PluginFilterTabs > QPushButton:hover {{
                background-color: {hover_bg};
                color: {c.get('label', '#E5E7EB')};
            }}
            QWidget#PluginFilterTabs > QPushButton:checked {{
                background-color: {checked_bg};
                color: #FFFFFF;
                font-weight: bold;
            }}
            QWidget#PluginFilterTabs > QPushButton:checked:hover {{
                background-color: {checked_hover};
            }}
        """

    def _build_list_container_qss(self, c):
        return (f"QWidget#PluginListContainer {{"
                f" background-color: {c['input_bg']};"
                f" border: 1px solid {c['input_border']};"
                f" border-radius: {self._px(12)}px; }}")

    def _build_count_badge_qss(self, c):
        return (f"QLabel#PluginCountBadge {{ "
                f" background-color: {c['btn_primary_bg']}; color: #FFFFFF;"
                f" border-radius: {self._px(8)}px;"
                f" font: bold {self._pt(9)}pt 'Microsoft YaHei UI'; }}")

    def _build_search_qss(self, c):
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
        """DPI / UI scale 变化时重算尺寸。"""
        _px = self._px
        # 根 layout 边距 & 间距
        try:
            self._root_layout.setContentsMargins(
                _px(28), _px(24), _px(28), _px(24))
        except Exception:
            pass
        try:
            self._root_layout.setSpacing(_px(16))
        except Exception:
            pass
        # Tab 容器高度 + layout margin/spacing
        try:
            self._tab_container.setFixedHeight(_px(34))
            self._tab_layout.setContentsMargins(_px(4), 0, _px(4), 0)
            self._tab_layout.setSpacing(_px(4))
        except Exception:
            pass
        # ActionBar: 固定高度 + 内部 layout margins/spacing
        try:
            self._action_bar.setFixedHeight(_px(46))
        except Exception:
            pass
        try:
            self._ab_layout.setContentsMargins(
                _px(14), _px(6), _px(14), _px(6))
        except Exception:
            pass
        try:
            self._ab_layout.setSpacing(_px(8))
        except Exception:
            pass
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
        # 统计卡片自身有 theme listener 会 update_theme；这里额外保险重算 4 张卡片的数字字级
        try:
            for card in (getattr(self, "_stat_total", None),
                         getattr(self, "_stat_outdated", None),
                         getattr(self, "_stat_enabled", None),
                         getattr(self, "_stat_disabled", None)):
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
        # 1. BasePage 重应用 content_style
        try:
            super().update_theme(theme_styles)
        except Exception:
            pass
        # 2. 重取颜色 token + 重建 QSS
        try:
            c = self._get_colors()
            # 标题 + 副标题
            try:
                self._title_label.setStyleSheet(self._build_title_qss(c))
            except Exception:
                pass
            try:
                self._subtitle_label.setStyleSheet(self._build_subtitle_qss(c))
            except Exception:
                pass
            # Tab 栏 QSS
            try:
                self._tab_container.setStyleSheet(self._build_tab_qss(c))
            except Exception:
                pass
            # 搜索框 QSS
            try:
                self._search_edit.setStyleSheet(self._build_search_qss(c))
            except Exception:
                pass
            # ActionBar 容器
            try:
                self._action_bar.setStyleSheet(self._build_actionbar_qss(c))
            except Exception:
                pass
            # ActionBar 内标签：hint/已选中/计数 badge
            try:
                self._ab_hint_label.setStyleSheet(
                    f"color: {c['label_dim']};"
                    f" font: {self._pt(9.5)}pt 'Microsoft YaHei UI';")
            except Exception:
                pass
            try:
                self._ab_label.setStyleSheet(
                    f"color: {c['label_muted']};"
                    f" font: {self._pt(9.5)}pt 'Microsoft YaHei UI';")
            except Exception:
                pass
            try:
                self._ab_count_label.setStyleSheet(self._build_count_badge_qss(c))
            except Exception:
                pass
            # List 容器 + list widget QSS
            try:
                self._list_container.setStyleSheet(self._build_list_container_qss(c))
            except Exception:
                pass
            try:
                self.list_widget.setStyleSheet(self._build_list_qss(c))
            except Exception:
                pass
            # 3. DPI 尺寸重算（margin/spacing/高度/按钮 minWidth）
            self._reapply_dpi_sizes()
            # 4. Tab 再刷一次样式（因为颜色 token 变了）
            self._refresh_tab_styles()
            # 5. 通知子 delegate / 子控件各自 update_theme
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

    # ---- Tab/搜索/统计 helper ----
    def _refresh_tab_styles(self):
        """Tab 按钮 QSS 统一由容器级 QWidget#PluginFilterTabs > QPushButton 覆盖，
        这里只做保险：非 focus/hover/checked 状态下确保按钮无边框与统一高度。
        _build_tab_qss 已在 update_theme/init 期应用。"""
        try:
            c = self._get_colors()
            self._tab_container.setStyleSheet(self._build_tab_qss(c))
        except Exception:
            pass

    def _refresh_stats(self, plugins=None):
        """刷新 4 张状态卡数字：总数/可更新/已启用/已禁用。
        plugins 不传则从 self._all_plugins_cache 取（兼容 populate 前后）。"""
        ps = list(plugins) if plugins is not None else list(
            getattr(self, "_all_plugins_cache", []))
        total = len(ps)
        outdated = sum(1 for p in ps if p.get("_outdated", False))
        enabled = sum(1 for p in ps if p.get("enabled", True))
        disabled = total - enabled
        # 若 mark_outdated 已经给 list 打过标记，优先用那边的 _outdated_dir_names（
        # populate 之后 mark_outdated 之前，plugins._outdated 会是 False；
        # mark_outdated 后会再次调用 _refresh_stats 同步）
        if getattr(self, "_outdated_dir_names", None):
            try:
                dir_names = {p.get("dir_name", p.get("name", "")) for p in ps}
                outdated = len(self._outdated_dir_names & dir_names)
            except Exception:
                pass
        try:
            self._stat_total.set_value(total)
            self._stat_outdated.set_value(outdated)
            self._stat_enabled.set_value(enabled)
            self._stat_disabled.set_value(disabled)
        except Exception:
            pass

    def _set_filter(self, key: str):
        """点击 Tab → 切换当前过滤器，取消其它 Tab 的 checked 状态，重跑过滤。"""
        self._current_filter = key
        # 单选项互斥：当前项 checked=True，其余 False（避免点"已检查"项自己把自己取消）
        for k, btn in getattr(self, "_filter_tabs", {}).items():
            try:
                btn.setChecked(k == key)
            except Exception:
                pass
        self._apply_filters()

    def _apply_filters(self):
        """综合当前 Tab + 搜索框关键字，从 _all_plugins_cache 过滤出最终列表并渲染。
        populate() 把全量数据塞进 _all_plugins_cache，之后所有过滤都走本地。"""
        try:
            cache = list(getattr(self, "_all_plugins_cache", []))
        except Exception:
            cache = []
        kw = ""
        try:
            kw = (getattr(self, "_search_edit", None).text()
                  if getattr(self, "_search_edit", None) else "").strip().lower()
        except Exception:
            kw = ""
        flt = getattr(self, "_current_filter", "all")

        # 1) Tab 过滤
        if flt != "all":
            if flt in ("git", "cnr", "local"):
                cache = [p for p in cache if (p.get("kind") or "").lower() == flt]
            elif flt == "outdated":
                # _outdated_dir_names 是 mark_outdated 设置的；若无 mark_outdated，
                # 则 fallback 到 plugin dict 里的 _outdated 字段（populate 时回填）
                od = getattr(self, "_outdated_dir_names", None) or set()
                cache = [
                    p for p in cache
                    if p.get("dir_name", p.get("name", "")) in od
                    or p.get("_outdated", False)
                ]
            elif flt == "disabled":
                cache = [p for p in cache if not p.get("enabled", True)]
        # 2) 关键字过滤（name/author/version/description/id/git url 四个维度）
        if kw:
            def _hit(p):
                if kw in (p.get("name") or "").lower():
                    return True
                if kw in (p.get("author") or "").lower():
                    return True
                if kw in (p.get("version") or "").lower():
                    return True
                if kw in (p.get("description") or "").lower():
                    return True
                if kw in (p.get("id") or "").lower():
                    return True
                if kw in (p.get("remote_url") or "").lower():
                    return True
                return False
            cache = [p for p in cache if _hit(p)]
        # 3) 渲染。注意：list_widget 要的是 item + UserRole，
        # 这就是 populate 的后半段，直接抽成 _render_items 共用，但为了不引入太多结构改动，
        # 这里内联逻辑与 populate 保持等价（除了不清空 outdated 标记，因为是过滤不是刷新）
        self._render_from_list(cache, preserve_outdated=True)

    def _render_from_list(self, plugins, preserve_outdated=False):
        """把 plugins 画进 list_widget。
        - preserve_outdated=False（populate 路径）：清空列表 + 清 old item 的 _OUTDATED_ROLE
        - preserve_outdated=True（_apply_filters 路径）：保留 _outdated_dir_names 与每个 item
          插回后根据 dir_name 是否在里面还原 mark_outdated 标志。
        """
        lw = self.list_widget
        if not preserve_outdated:
            lw.clear()
        else:
            # 先摘出所有 item，再按新 filtered 顺序插回，保留原 item 对象上的 _OUTDATED_ROLE / CheckState
            n_total = lw.count()
            existing = {}
            for _i in range(n_total):
                it = lw.takeItem(0)
                try:
                    dn = it.data(QtCore.Qt.UserRole + 1)
                    if dn:
                        existing[str(dn)] = it
                except Exception:
                    pass

        for p in plugins:
            name = p.get("name", "?")
            dir_name = p.get("dir_name", name)
            enabled = p.get("enabled", True)
            is_git = p.get("is_git", False)
            # 保留原 item（若存在）的勾选/过时状态
            item = None
            if preserve_outdated:
                item = existing.get(str(dir_name))
            if item is None:
                display = name if enabled else f"{name}（已禁用）"
                item = QtWidgets.QListWidgetItem(display)
                item.setData(QtCore.Qt.UserRole, p)
                item.setData(QtCore.Qt.UserRole + 1, dir_name)
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
                if not enabled:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(
                        self.theme_manager.colors.get("label_dim", "#9CA3AF"))))
                # mark_outdated 写的三个 role：若 plugin dict 里有 _outdated/_remote_date/_checked，
                # 回填到 item（过滤场景，mark_outdated 已经给老 item 写过但现在是新的 item）
                if p.get("_outdated"):
                    item.setData(_OUTDATED_ROLE, True)
                if p.get("_checked") is not None:
                    item.setData(_CHECKED_ROLE, bool(p["_checked"]))
                if p.get("_remote_date"):
                    item.setData(_REMOTE_DATE_ROLE, p["_remote_date"])
            lw.addItem(item)

        # 如果是 filter 场景且全局 mark_outdated 过，同步插回的 item 的三个 role 标记
        # （上面只从 plugin dict 回填，对 mark_outdated 后再 filter 的情况需要从
        #  _outdated_dir_names 比对再写一次 item.data，因为 delegate 只看 item.data）
        if preserve_outdated:
            try:
                od = getattr(self, "_outdated_dir_names", None) or set()
                for i in range(lw.count()):
                    it = lw.item(i)
                    dn = it.data(QtCore.Qt.UserRole + 1)
                    if str(dn) in od:
                        it.setData(_OUTDATED_ROLE, True)
                        it.setData(_CHECKED_ROLE, True)
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

        显示规则与原版保持一致（兼容旧测试）：
        - item 文本 = 纯 name（禁用项加「（已禁用）」）
        - git 插件 tooltip 显示版本/来源
        - 全量重填后，把 plugins 缓存到 self._all_plugins_cache（便于 Tab/搜索过滤）
        - mark_outdated 标记清空（和旧行为一致）
        """
        plugins = list(plugins)
        self._outdated_dir_names = set()
        self._all_plugins_cache = list(plugins)
        # 清掉上次 filter 塞进去的 _outdated/_checked/_remote_date 残留，重新 populate 就是干净新列表
        for p in self._all_plugins_cache:
            for k in ("_outdated", "_checked", "_remote_date"):
                if k in p:
                    try:
                        del p[k]
                    except Exception:
                        p[k] = False if k == "_outdated" else ""
        self._render_from_list(plugins, preserve_outdated=False)
        # 首次 populate 后重刷统计 & 重置 Tab/搜索
        self._refresh_stats(plugins)
        try:
            if getattr(self, "_current_filter", None) != "all":
                self._set_filter("all")
        except Exception:
            pass
        try:
            if getattr(self, "_search_edit", None):
                self._search_edit.blockSignals(True)
                self._search_edit.setText("")
                self._search_edit.blockSignals(False)
        except Exception:
            pass

    def mark_outdated(self, dir_names, remote_dates=None):
        """controller 通过 outdated_reported 推回 → 标记对应项并重排（可更新置顶）。

        新增：同步把 _outdated/_checked/_remote_date 写回 self._all_plugins_cache，
        这样 filter 切换 Tab 时，item 上的过时标志不会丢（_render_from_list 在 filter 模式下会
        从 plugin dict 回填 UserRole）。
        """
        self._outdated_dir_names = {str(d) for d in dir_names}
        remote_dates = remote_dates or {}
        # 先同步回 _all_plugins_cache
        dn_to_plugin = {}
        for p in getattr(self, "_all_plugins_cache", []):
            dn = str(p.get("dir_name") or p.get("name") or "")
            if dn:
                dn_to_plugin[dn] = p
        for dn, p in dn_to_plugin.items():
            is_od = dn in self._outdated_dir_names
            p["_outdated"] = is_od
            p["_checked"] = True
            p["_remote_date"] = remote_dates.get(dn, "") if is_od else ""
        # 再更新 list widget 上每个 item 的三个 role + text
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            dir_name = item.data(QtCore.Qt.UserRole + 1)
            is_outdated = str(dir_name) in self._outdated_dir_names
            item.setData(_OUTDATED_ROLE, is_outdated)
            item.setData(_CHECKED_ROLE, True)
            item.setData(_REMOTE_DATE_ROLE,
                         remote_dates.get(dir_name, "") if is_outdated else "")
            if is_outdated:
                accent = self.theme_manager.colors.get("btn_primary_bg", "#6366F1")
                base = item.data(QtCore.Qt.UserRole) or {}
                name = base.get("name", item.text())
                enabled = base.get("enabled", True)
                display = name if enabled else f"{name}（已禁用）"
                item.setText(f"🔄 {display}  [可更新]")
                item.setForeground(QtGui.QBrush(QtGui.QColor(accent)))
        # 刷新状态卡「可更新」数字
        self._refresh_stats()
        # 重排：outdated 项移到顶部
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
                msg = "插件更新全部完成，重启 ComfyUI 后生效" + (f"（{len(failed)} 个建议强制更新）" if failed else "")
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
            msg = f"选中插件更新完成 ({len(names)} 个)，重启 ComfyUI 后生效"
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
                        msg = f"插件安装完成：{spec}\n重启 ComfyUI 后生效"
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
                        msg = f"已{op_label} {len(dir_names)} 个插件，重启 ComfyUI 后生效"
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
