"""插件搜索安装对话框。

从 ComfyUI-Manager 的本地 CNR 缓存（+ 刷新的 legacy custom-node-list）搜索插件，
选中后交给 qt_app 走标准安装链（_do_plugin_install）。

数据源：PluginService.search_plugins（CNR 缓存 5117+ 插件 + 刷新补充）。
设计：打开时后台加载全量索引到内存，搜索框输入 → 300ms 防抖 → 纯内存过滤（不重读 JSON）。
"""
from PyQt5 import QtWidgets, QtCore

from ui_qt.widgets.frameless_draggable_dialog import FramelessDraggableDialog

_SEARCH_DEBOUNCE_MS = 300
_RENDER_LIMIT = 60          # 列表最多渲染条数（避免 5117 条卡顿）
_LOAD_LIMIT = 10000         # 加载到内存的全量上限（实际 ~5117）
_DESC_MAX_LINES = 3         # 描述最多显示行数，超出末尾 …
_RENDER_REWIDTH_THRESHOLD = 40  # resizeEvent 宽度变化超过多少像素才重换行（避免拖边框抖动）


class PluginSearchDialog(FramelessDraggableDialog):
    """插件搜索弹窗：搜索框 + 结果列表 + 刷新索引 + 安装/取消。"""

    def __init__(self, parent=None, theme_manager=None, svc=None,
                 run_in_background=None, post_to_ui=None):
        super().__init__(parent=parent)
        self.theme_manager = theme_manager
        self._svc = svc
        self._run_in_background = run_in_background
        self._post_to_ui = post_to_ui
        self._all_plugins = []          # 全量索引（内存，过滤用）
        self._index_loaded = False
        self._selected_spec = None      # 选中插件的安装 spec（id 优先，否则 repository）
        self._last_rendered_width = None  # 上次渲染的列表宽度，resizeEvent 判断要不要重换行

        self._setup_ui()

        # 注册主题监听（切主题 / 切 scale → update_theme 重建 QSS + 重算尺寸）
        if self.theme_manager:
            self.theme_manager.register_listener(self._on_theme_changed)

    # DPI 缩放 helper —— 每次调用读 theme_manager.styles 的【当前】实例。
    # set_scale 会新建 ThemeStyles 替换 self.styles（theme_manager.py）；
    # 若在 __init__ 把 _px/_pt 绑定到当时实例的方法，DPI 变化后永远停在首次 scale
    # （与 qt_app._sp 及三个 launch section 的旧代码同族 bug）。
    def _px(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._px(base) if styles else base

    def _pt(self, base):
        styles = getattr(self.theme_manager, "styles", None) if self.theme_manager else None
        return styles._pt(base) if styles else base

    def _get_colors(self):
        """按当前 theme_manager.colors 取色（兜底默认值）。每次 update_theme 重走。"""
        bg = "#1F2937"; border = "#374151"; text = "#E5E7EB"
        title_color = "#F3F4F6"; input_bg = "#111827"; muted = "#9CA3AF"
        accent = "#6366F1"; accent_hover = "#818CF8"; btn_bg = "#374151"
        if self.theme_manager:
            c = self.theme_manager.colors
            bg = c.get('content_bg', bg)
            border = c.get('group_border', border)
            text = c.get('text', text)
            title_color = c.get('label', title_color)
            input_bg = c.get('input_bg', input_bg)
            muted = c.get('label_muted', muted)
            accent = c.get('btn_primary_bg', accent)
            accent_hover = c.get('btn_primary_hover', accent_hover)
            btn_bg = c.get('btn_secondary_bg', btn_bg)
        return dict(bg=bg, border=border, text=text, title_color=title_color,
                    input_bg=input_bg, muted=muted, accent=accent,
                    accent_hover=accent_hover, btn_bg=btn_bg)

    def _build_stylesheet(self, c):
        px, pt = self._px, self._pt
        return f"""
            QFrame#PluginSearchContainer {{
                background-color: {c['bg']};
                border: 1px solid {c['border']};
                border-radius: {px(16)}px;
            }}
            QLabel {{ background: transparent; color: {c['text']}; }}
            QLineEdit {{
                background-color: {c['input_bg']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: {px(8)}px;
                padding: {px(10)}px {px(12)}px;
                font: {pt(10)}pt "Microsoft YaHei UI";
            }}
            QLineEdit:focus {{ border: 1px solid {c['accent']}; }}
            QListWidget {{
                background-color: {c['input_bg']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: {px(8)}px;
                padding: {px(6)}px;
                font: {pt(10)}pt "Microsoft YaHei UI";
            }}
            QListWidget::item {{ padding: {px(4)}px; border-radius: {px(6)}px; }}
            QListWidget::item:selected {{ background-color: {c['accent']}; }}
            /* 自定义 item widget（QVBoxLayout + 3*QLabel）自身不要画背景，
               让底下 QListWidget::item 的选中色透上来；也不要拦截事件 */
            QWidget#PluginItem {{ background: transparent; }}
            QWidget#PluginItem > QLabel {{ background: transparent; }}
            QPushButton {{
                background-color: {c['btn_bg']}; color: {c['text']};
                border: none; border-radius: {px(8)}px;
                padding: {px(9)}px {px(20)}px;
                font: {pt(10)}pt "Microsoft YaHei UI";
            }}
            QPushButton:hover {{ background-color: {c['accent_hover']}; }}
            QPushButton#PrimaryBtn {{ background-color: {c['accent']}; color: #FFFFFF; }}
            QPushButton#PrimaryBtn:hover {{ background-color: {c['accent_hover']}; }}
            QPushButton:disabled {{ color: {c['muted']}; background-color: {c['btn_bg']}; }}
        """

    def _setup_ui(self):
        _pt = self._pt
        c = self._get_colors()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.container = QtWidgets.QFrame()
        self.container.setObjectName("PluginSearchContainer")
        self.container.setStyleSheet(self._build_stylesheet(c))

        inner = QtWidgets.QVBoxLayout(self.container)
        inner.setContentsMargins(self._px(24), self._px(24), self._px(24), self._px(24))
        inner.setSpacing(self._px(12))
        self._inner_layout = inner

        # 标题
        self.lbl_title = QtWidgets.QLabel("搜索安装插件")
        self.lbl_title.setStyleSheet(
            f"font: bold {_pt(14)}pt 'Microsoft YaHei UI'; color: {c['title_color']};")
        inner.addWidget(self.lbl_title)

        # 搜索框 + 刷新按钮
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(self._px(8))
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("搜索插件名 / 描述 / 作者")
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        top_row.addWidget(self.search_edit, 1)
        self.btn_refresh = QtWidgets.QPushButton("刷新索引")
        self.btn_refresh.clicked.connect(self._on_refresh)
        top_row.addWidget(self.btn_refresh)
        inner.addLayout(top_row)

        # 结果列表
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # 关键：关闭「统一 item 尺寸」，每个 item 可以有自己多行对应的高度
        self.list_widget.setUniformItemSizes(False)
        # 选中时背景色由 QSS 管，不需要选中框
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._on_install_clicked)
        inner.addWidget(self.list_widget, 1)

        # 提示行
        self.lbl_hint = QtWidgets.QLabel("正在加载插件索引…")
        self.lbl_hint.setStyleSheet(
            f"color: {c['muted']}; font: {_pt(9)}pt 'Microsoft YaHei UI';")
        self.lbl_hint.setWordWrap(True)
        inner.addWidget(self.lbl_hint)

        # 底部按钮
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QtWidgets.QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        self.btn_install = QtWidgets.QPushButton("安装")
        self.btn_install.setObjectName("PrimaryBtn")
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self._on_install_clicked)
        btn_row.addWidget(self.btn_install)
        inner.addLayout(btn_row)

        layout.addWidget(self.container)

        # 防抖 timer
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._do_filter)

        # DPI 相关尺寸：DPI 变化时需重算（见 _reapply_dpi_sizes / update_theme）。
        self._dpi_sized_widgets = [
            (self.btn_refresh, "min_text", "刷新中…"),
            (self.btn_install, "min_text", "安装"),
            (self.btn_cancel, "min_text", "取消"),
        ]
        # 900 宽够放长插件名 + ⭐/⬇ meta + 完整描述（多数描述 100~140 字）。
        # 640 高默认能看 ~12 行结果，扫热门插件不用滚。
        self._initial_size = (900, 640)
        # 最小尺寸兜底：用户拖太小会破坏布局，最低给个能看的下限。
        self._minimum_size = (760, 500)
        self._reapply_dpi_sizes()
        # 布局全部建好后，用 adjustSize 验证最终尺寸至少覆盖 layout 的需求，
        # 避免某些字体/缩放下 initial 刚好压在 minimumSizeHint 上被裁。
        try:
            self.adjustSize()
        except Exception:
            pass

    # ---- 索引加载（后台，读 CNR 缓存 + legacy）----
    def showEvent(self, event):
        super().showEvent(event)
        if not self._index_loaded and self._svc is not None:
            self._start_load_index()
        # 首帧后重渲染一次：__init__ 时列表 viewport 宽为 0，尺寸按兜底值；
        # showEvent 后 viewport 宽度真实，借此把换行、item 高校准一遍。
        QtCore.QTimer.singleShot(0, self._re_render_if_needed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 宽度变化超过阈值才重换行（用户拖边框频繁触发，避免抖动）
        self._re_render_if_needed()

    def _re_render_if_needed(self):
        if not self._index_loaded:
            return
        try:
            lw = self.list_widget
            cur_w = max(lw.viewport().width(), lw.width() - 40)
            if cur_w <= 80:
                return
            last = self._last_rendered_width
            if last is None or abs(cur_w - last) >= _RENDER_REWIDTH_THRESHOLD:
                kw = (self.search_edit.text() or "").strip().lower()
                if kw:
                    data = [p for p in self._all_plugins if self._match(p, kw)]
                else:
                    data = self._all_plugins
                self._render_list(data[:_RENDER_LIMIT])
        except Exception:
            pass

    def _start_load_index(self):
        """后台加载全量索引到 _all_plugins，加载完渲染前 N 个热门。"""
        if self._run_in_background is None or self._svc is None:
            self.lbl_hint.setText("索引不可用（服务未就绪），可用「安装插件」按钮贴 URL 安装")
            return

        def work():
            try:
                plugins = self._svc.search_plugins("", limit=_LOAD_LIMIT)
            except Exception:
                plugins = []

            def fill():
                self._all_plugins = plugins
                self._index_loaded = True
                self._render_list(plugins[:_RENDER_LIMIT])
                if plugins:
                    self.lbl_hint.setText(
                        f"共 {len(plugins)} 个插件，输入关键字筛选；"
                        "搜不到的可用「取消」后点「安装插件」贴 URL")
                else:
                    self.lbl_hint.setText(
                        "本地索引为空，点「刷新索引」拉取，或用「安装插件」贴 URL")

            (self._post_to_ui or (lambda f: f()))(fill)

        self._run_in_background(work)

    # ---- 搜索过滤（防抖 → 内存过滤）----
    def _on_search_text_changed(self, _text):
        if not self._index_loaded:
            return
        self._search_timer.start()

    def _do_filter(self):
        if not self._index_loaded:
            return
        kw = self.search_edit.text().strip().lower()
        if not kw:
            self._render_list(self._all_plugins[:_RENDER_LIMIT])
            self.lbl_hint.setText(f"共 {len(self._all_plugins)} 个插件")
            return
        # 纯内存过滤（数据已在 _all_plugins，快）
        result = [p for p in self._all_plugins if self._match(p, kw)]
        self._render_list(result[:_RENDER_LIMIT])
        self.lbl_hint.setText(
            f"找到 {len(result)} 个结果" if result else "无匹配结果，换个关键字或用 URL 安装")

    @staticmethod
    def _repo_author(repo_url: str) -> str:
        """从 GitHub 仓库 url 中抽取用户名；失败返回 ''。
        例如 https://github.com/ltdrdata/ComfyUI-Impact-Pack → ltdrdata
        git@github.com:ltdrdata/ComfyUI-Impact-Pack.git → ltdrdata"""
        if not repo_url:
            return ""
        try:
            parts = [seg for seg in str(repo_url).replace("\\", "/").split("/") if seg]
            if len(parts) >= 2:
                second_last = parts[-2]
                candidate = (second_last.rsplit(":", 1)[-1] if ":" in second_last
                             else second_last)
                if candidate and not candidate.endswith(".git") and "." not in candidate:
                    return candidate
        except Exception:
            pass
        return ""

    @classmethod
    def _match(cls, p: dict, kw: str) -> bool:
        """本地过滤（在 _all_plugins 上跑，_start_load_index 已经拉全量）。
        按 name/id/author/tags/description + 兜底 repo_author 匹配，对齐 PluginService
        的 search_plugins 字段，避免两边字段集不一致导致本地过滤命中比远端少。"""
        name = (p.get("name") or "").lower()
        if kw in name:
            return True
        pid = (p.get("id") or "").lower()
        if kw in pid:
            return True
        author = (p.get("author") or "").lower()
        if kw in author:
            return True
        # 兜底：部分老 CNR 缓存 author 字段空，即使 PluginService 修了，
        # 再从 repository 取一次用户名，确保搜作者名/组织名肯定命得中
        repo_author = cls._repo_author(p.get("repository") or "").lower()
        if repo_author and kw in repo_author:
            return True
        tags = " ".join(p.get("tags") or []).lower()
        if tags and kw in tags:
            return True
        desc = (p.get("description") or "").lower()
        if kw in desc:
            return True
        return False

    def _render_list(self, plugins):
        self.list_widget.clear()
        self.btn_install.setEnabled(False)
        self._selected_spec = None

        # 记录此次渲染的列表宽度，resizeEvent 根据宽度差决定是否重渲染
        try:
            lw = self.list_widget
            vw = lw.viewport().width()
            # viewport 宽为 0/1 的情况（窗口未真正显示）用 lw.width()-padding 兜底
            cur_w = vw if vw > 80 else max(lw.width() - 40, self._px(760))
            if cur_w > 80:
                self._last_rendered_width = cur_w
        except Exception:
            cur_w = self._px(760)

        c = self._get_colors()
        _pt = self._pt
        _px = self._px
        fm = self.list_widget.fontMetrics()
        line_h = fm.height()
        ellipsis_char = "\u2026"

        # 描述可用最大高度：行高 × 行数，用于给 QLabel setMaximumHeight 强制显示 _DESC_MAX_LINES 行
        desc_max_h = line_h * _DESC_MAX_LINES + _px(2)  # 给点抗走样余量

        # 给 item 内部 label 的可用宽度（扣除 item widget 左右 padding 10+10）
        avail_w_item = max(cur_w - _px(24), _px(600))

        for p in plugins:
            name = p.get("name") or p.get("repository") or "?"
            author = (p.get("author") or "").strip()
            # 显示端双重兜底：即使 PluginService 修了数据源（list_registry_plugins），
            # 历史上 _reg_cache 可能缓存了空 author 的数据，再抽一次保证 UI 始终有作者名
            if not author:
                author = self._repo_author(p.get("repository") or "")
            desc = (p.get("description") or "").strip().replace("\n", " ")
            meta_bits = []
            if author:
                meta_bits.append(author)
            if p.get("stars"):
                meta_bits.append(f"⭐{p['stars']}")
            if p.get("downloads"):
                meta_bits.append(f"⬇{p['downloads']}")
            meta_str = " \u00b7 ".join(meta_bits)

            # --- 自定义 item widget：3 个 label ---
            widget = QtWidgets.QWidget()
            widget.setObjectName("PluginItem")
            wl = QtWidgets.QVBoxLayout(widget)
            wl.setContentsMargins(_px(10), _px(8), _px(10), _px(8))
            wl.setSpacing(_px(3))

            # 行 1：插件名（末尾省略号）
            lbl_name = QtWidgets.QLabel(name)
            lbl_name.setStyleSheet(
                f"color: {c['text']};"
                f" font: bold {_pt(11)}pt 'Microsoft YaHei UI';"
                " background: transparent;")
            lbl_name.setTextFormat(QtCore.Qt.PlainText)
            lbl_name.setWordWrap(False)
            # QLabel 自身做末尾省略（比 fm.elidedText 更稳，它按实际宽度算）
            lbl_name_name = "PluginItemName"
            # 注：Qt 没有原生"单行+末尾省略"的 QLabel flag，我们用 resizeEvent 套一层最简单：
            # 这里先把完整文本塞进去，下面给 widget 挂个 resizeEvent override 在宽度变化时
            # 重新 fm.elidedText。但对我们场景 —— 列表重渲染时就已经知道宽度了 —— 直接先塞
            # 完整字符串，让 QLabel 在 minimumSizeHint 阶段就知道最长行是多少。
            lbl_name.setText(name)
            wl.addWidget(lbl_name)

            # 行 2：meta（作者 · ⭐ · ⬇）—— 灰色小字，单行省略
            if meta_str:
                lbl_meta = QtWidgets.QLabel(meta_str)
                lbl_meta.setStyleSheet(
                    f"color: {c['muted']};"
                    f" font: {_pt(9)}pt 'Microsoft YaHei UI';"
                    " background: transparent;")
                lbl_meta.setWordWrap(False)
                wl.addWidget(lbl_meta)
            else:
                lbl_meta = None

            # 行 3+：描述（最多 3 行，自动 word wrap，末行末尾省略）
            if desc:
                # 描述过长先按字符软限 220 字（CNR 里有 changelog 当描述的奇葩）
                desc_clipped = desc if len(desc) <= 220 else desc[:220] + ellipsis_char
                lbl_desc = QtWidgets.QLabel(desc_clipped)
                lbl_desc.setStyleSheet(
                    f"color: {c['text']};"
                    f" font: {_pt(9.5)}pt 'Microsoft YaHei UI';"
                    " background: transparent;")
                lbl_desc.setWordWrap(True)
                # 关键：QLabel 的 QSS 不支持 max-height 控制行数；用 setMaximumHeight + 对齐
                # 方式截断（第 4+ 行被 clip，视觉上就是"3 行满了没显示全"，配合 Tooltip 看全量）
                lbl_desc.setMinimumHeight(0)
                lbl_desc.setMaximumHeight(desc_max_h)
                lbl_desc.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
                wl.addWidget(lbl_desc)
            else:
                lbl_desc = None

            # Tooltip：完整信息（文字被省略的行靠 Tooltip 看全）
            tip_parts = [f"{name}"]
            if author:
                tip_parts.append(f"作者: {author}")
            if p.get("stars") or p.get("downloads"):
                tip_parts.append(
                    f"⭐ {p.get('stars') or 0}   ⬇ {p.get('downloads') or 0}")
            tip_parts.append("")
            tip_parts.append(desc or "(无描述)")
            widget.setToolTip("\n".join(tip_parts))

            # --- 把 widget 塞进 QListWidgetItem，并且让 item 的 sizeHint 等于 widget 的 sizeHint ---
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, p)
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

            # --- 单行过长 → ElideRight 末尾省略号（QLabel 没有原生单行省略，用 fm 手动截一次）---
            # 注意：这里只是首帧兜底，resize 导致宽度变化时会整个重渲染，所以不用实时更新
            if avail_w_item > 0:
                try:
                    name_w = max(avail_w_item, 200)
                    # name label 用的是 bold 11pt，和 fm（list_widget 10pt）不是同一字号，按 label 自己测
                    fm_name = lbl_name.fontMetrics()
                    lbl_name.setText(
                        fm_name.elidedText(name, QtCore.Qt.ElideRight, name_w))
                    if lbl_meta is not None:
                        fm_meta = lbl_meta.fontMetrics()
                        lbl_meta.setText(
                            fm_meta.elidedText(meta_str, QtCore.Qt.ElideRight, avail_w_item))
                except Exception:
                    pass

            widget.adjustSize()
            # 取 widget 的实际 sizeHint 作为 item 的 size（比估算更准，sizeHint 是布局实际算出来的）
            sz = widget.sizeHint()
            if sz.isValid() and sz.height() > 0:
                item_hint_h = sz.height() + _px(6)
            else:
                # 兜底：行数 × line_h + padding（10+8+8+10=36 上下余裕）
                rows_est = 1
                if lbl_meta is not None:
                    rows_est += 1
                if lbl_desc is not None:
                    rows_est += _DESC_MAX_LINES
                item_hint_h = max(_px(52), rows_est * line_h + _px(22))
            item.setSizeHint(QtCore.QSize(0, item_hint_h))

            # 保存引用，便于 resize 时重新调整（只改 label 文本，不重建整个 widget）
            widget._lbl_name = lbl_name
            widget._lbl_meta = lbl_meta
            widget._lbl_desc = lbl_desc
            widget._raw_name = name
            widget._raw_meta = meta_str
            widget._raw_desc = desc_clipped if desc else ""

    def _on_selection_changed(self):
        has = self.list_widget.currentItem() is not None
        self.btn_install.setEnabled(has)
        # 手动更新所有 item widget 内 label 的选中态颜色（QSS 子控件不穿透自定义 widget）
        self._apply_selection_colors()

    def _apply_selection_colors(self):
        """遍历列表，对选中/未选中的 item widget 内 label 改前景色。
        QListWidget::item:selected 的 QSS 对自定义 setItemWidget 的 label 不生效（label
        自己有样式表）；所以手动切换。"""
        c = self._get_colors()
        _pt = self._pt
        sel_text = "#FFFFFF"  # 选中背景是 accent 紫，白色文字对比高
        sel_muted = "#F3F4F6"  # 选中态下的 meta 灰也浅一点但要可见
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item is None:
                continue
            widget = self.list_widget.itemWidget(item)
            if widget is None:
                continue
            selected = self.list_widget.itemIsSelected(item)
            try:
                # name 行
                if getattr(widget, "_lbl_name", None) is not None:
                    widget._lbl_name.setStyleSheet(
                        f"color: {sel_text if selected else c['text']};"
                        f" font: bold {_pt(11)}pt 'Microsoft YaHei UI';"
                        " background: transparent;")
                # meta 行
                if getattr(widget, "_lbl_meta", None) is not None:
                    widget._lbl_meta.setStyleSheet(
                        f"color: {sel_muted if selected else c['muted']};"
                        f" font: {_pt(9)}pt 'Microsoft YaHei UI';"
                        " background: transparent;")
                # desc 行
                if getattr(widget, "_lbl_desc", None) is not None:
                    widget._lbl_desc.setStyleSheet(
                        f"color: {sel_text if selected else c['text']};"
                        f" font: {_pt(9.5)}pt 'Microsoft YaHei UI';"
                        " background: transparent;")
            except Exception:
                pass

    def _on_install_clicked(self, *_):
        item = self.list_widget.currentItem()
        if item is None:
            return
        p = item.data(QtCore.Qt.UserRole) or {}
        spec = p.get("id") or p.get("repository")
        if spec:
            self._selected_spec = spec
            self.accept()

    def get_selected_spec(self):
        """qt_app 在 exec_()==Accepted 后取选中插件的安装 spec。"""
        return self._selected_spec

    # ---- 刷新索引（远程拉 custom-node-list.json）----
    def _on_refresh(self):
        if self._svc is None or self._run_in_background is None:
            return
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("刷新中…")
        self.list_widget.clear()
        self.lbl_hint.setText("正在从远程拉取插件索引（国内网络可能需要几十秒）…")
        self._index_loaded = False

        def work():
            try:
                res = self._svc.refresh_registry_index()
            except Exception as e:
                res = {"ok": False, "error": str(e), "count": 0}

            def done():
                self.btn_refresh.setEnabled(True)
                self.btn_refresh.setText("刷新索引")
                if res.get("ok"):
                    self.lbl_hint.setText(
                        f"索引已刷新（+{res.get('count', 0)} 个），正在重新加载…")
                    self._start_load_index()
                else:
                    self._index_loaded = True  # 允许继续用旧的 _all_plugins 过滤
                    self._render_list(self._all_plugins[:_RENDER_LIMIT])
                    self.lbl_hint.setText("刷新失败，仍使用本地索引搜索")
                    from ui_qt.widgets.dialog_helper import DialogHelper
                    DialogHelper.show_warning(
                        self, "刷新失败",
                        f"远程拉取插件索引失败：{res.get('error', '未知错误')}\n\n"
                        "国内访问 GitHub 常超时，可稍后重试，或开一次 ComfyUI 让 "
                        "ComfyUI-Manager 自己更新索引。\n\n搜索仍可使用本地缓存。")

            (self._post_to_ui or (lambda f: f()))(done)

        self._run_in_background(work)

    # ---- 主题 / DPI 缩放 ----
    def _on_theme_changed(self, theme_styles):
        self.update_theme(theme_styles)

    def _reapply_dpi_sizes(self):
        """重算所有 DPI 相关尺寸（DPI / 主题变化时调用）。"""
        # inner layout 间距 & 边距
        inner = getattr(self, "_inner_layout", None)
        if inner is not None:
            try:
                inner.setContentsMargins(
                    self._px(24), self._px(24), self._px(24), self._px(24))
            except Exception:
                pass
            try:
                inner.setSpacing(self._px(12))
            except Exception:
                pass
        # 按钮 minWidth：按「临时文本 → sizeHint.width()」的最大值设置
        for w, kind, aux in getattr(self, "_dpi_sized_widgets", []):
            try:
                if kind == "min_text":
                    # 临时文本（aux）和当前文本都测一遍，取宽的
                    cur = w.text()
                    w1 = w.sizeHint().width()
                    w.setText(aux)
                    w2 = w.sizeHint().width()
                    w.setText(cur)
                    w.setMinimumWidth(max(w1, w2))
            except Exception:
                pass
        # 最小尺寸保护：先设 minimum，再 resize 到 initial
        mins = getattr(self, "_minimum_size", None)
        if mins is not None:
            try:
                self.setMinimumSize(self._px(mins[0]), self._px(mins[1]))
            except Exception:
                pass
        init = getattr(self, "_initial_size", None)
        if init is not None:
            try:
                self.resize(self._px(init[0]), self._px(init[1]))
            except Exception:
                pass

    def update_theme(self, theme_styles=None):
        """主题 / 缩放变化：重取颜色 + 重建 QSS + 重算尺寸 + 重渲染列表（字号/色 token 都变了）。"""
        try:
            c = self._get_colors()
            self.container.setStyleSheet(self._build_stylesheet(c))
            # 重设标签样式（颜色 token + _pt 字号都可能变了）
            try:
                self.lbl_title.setStyleSheet(
                    f"font: bold {self._pt(14)}pt 'Microsoft YaHei UI';"
                    f" color: {c['title_color']};")
            except Exception:
                pass
            try:
                self.lbl_hint.setStyleSheet(
                    f"color: {c['muted']}; font: {self._pt(9)}pt 'Microsoft YaHei UI';")
            except Exception:
                pass
            # 重算 DPI 尺寸
            self._reapply_dpi_sizes()
        except Exception:
            pass
        # 主题/DPI 变 → 字号、行高、颜色 token 都变，列表需要重渲一遍
        if getattr(self, "_index_loaded", False):
            try:
                kw = (getattr(self, "search_edit", None).text()
                      if getattr(self, "search_edit", None) else "").strip().lower()
                data = (
                    [p for p in self._all_plugins if self._match(p, kw)]
                    if kw else list(self._all_plugins)
                )
                self._render_list(data[:_RENDER_LIMIT])
                self._apply_selection_colors()
            except Exception:
                pass
